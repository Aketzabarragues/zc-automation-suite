"""Tests del router Flask ``proc_process_crear_router``.

El Excel del operario es la fuente de verdad para los datos del
proceso nuevo. La SPA solo envia ``dir_plantilla_nombre + proc_uid``
y el router los resuelve desde
``app_cache.area("alimentacion").excel_full.procesos``.

El router ya no bloquea: encola el trabajo en el OB1 (dispatcher con
cola) y responde ``202`` con el ``job_id``. El resultado del FB
llega al HMI por push (evento SSE ``fb_state``), no en el cuerpo de
la respuesta HTTP.

Tests:
  - ``test_crear_preview_ok_con_plantilla``:
    Body valido (minimal) + Excel con proc_uid=300 + plantillas_path OK
    -> 202 con ``job_id`` y ``engine.submit`` con los params resueltos.
  - ``test_crear_preview_expone_descripcion_y_dependencias``:
    El ``result`` del preview ya no viaja en la respuesta (llega por SSE).
  - ``test_crear_preview_sin_excel``:
    app_cache sin excel_full -> 400 (accionable: "Cargue el Excel").
  - ``test_crear_preview_proc_uid_inexistente``:
    proc_uid=999 que no esta en el Excel -> 400 con mensaje accionable.
  - ``test_crear_preview_body_incompleto``:
    Body sin campos obligatorios -> 400.
  - ``test_crear_aplicar_fb_no_registrado``:
    engine.get_fb(None) -> 500.
  - ``test_crear_aplicar_fb_ocupado_409``:
    ``engine.submit`` lanza ``FBBusyError`` -> 409.
  - ``test_crear_aplicar_sincroniza_selected_plc``:
    ``with_plc`` + 202 con ``job_id``.
  - ``test_crear_preview_plc_blocks_cache_acepta_strings_y_dicts``:
    ``plc_blocks_cache`` normalizado en los params del ``submit``.
  - ``test_crear_aplicar_plc_no_esta_en_el_excel_devuelve_400``:
    ``plc_name`` fuera de la Tabla_PLC del Excel -> 400 (validacion de
    entrada, no 500).
  - Suite parametrizada de los 2 endpoints: sin engine -> 500, FB no
    registrado -> 500, FB ocupado -> 409, submit falla -> 500, happy
    path -> 202 con ``job_id`` y respuesta sin el ``result`` del FB.
  - Suite parametrizada de los 2 endpoints: el router no lee
    ``fb.result`` y no emite el log de cierre (lo emite el FB al
    terminar el trabajo).
"""
from __future__ import annotations

import json
import logging
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from flask import Flask

from core.composition.plc_engine import FBBusyError


# Logger del router: sirve para comprobar que NO es quien emite el log
# de cierre del trabajo (eso lo hace el FB, al terminar).
ROUTER_LOGGER = "areas.alimentacion.frontend.proc_process_crear_router"


# ── Helpers ──────────────────────────────────────────────────────────


def _make_app(
    engine: MagicMock | None = None,
    app_cache: MagicMock | None = None,
    config_manager: MagicMock | None = None,
) -> Flask:
    """Crea una app Flask minima con el ``Engine`` y ``APP_CACHE`` mockeados.

    ``APP_CACHE`` es la convencion actual del shell Flask
    (``core/web_server/app_flask.py``): el contenedor del proceso
    se inyecta como un mock directo.
    """
    app = Flask(__name__)
    app.config["TESTING"] = True
    if engine is not None:
        app.config["ENGINE"] = engine
    if app_cache is not None:
        app.config["APP_CACHE"] = app_cache
    if config_manager is not None:
        app.config["CONFIG_MANAGER"] = config_manager
    else:
        # Default: ConfigManager con plantillas_path = tmp_path del test
        cm = MagicMock()
        cm.get_plantillas_path.return_value = ""
        app.config["CONFIG_MANAGER"] = cm
    return app


def _make_mock_proc_excel(uid: int = 300) -> MagicMock:
    """Crea un mock de ``DataProcesoPLC`` para inyectar en excel_cache."""
    proc = MagicMock()
    proc.uid = uid
    proc.nombre = "ProcesoTest300"
    proc.codigo = "EXP"
    proc.preal = 30
    proc.pint = 30
    proc.alarmas = 30
    proc.alm_hmi = 5
    return proc


def _make_mock_excel_cache(proc_uid: int = 300) -> MagicMock:
    """Crea un mock del ``excel_cache_full`` con un proceso del Excel."""
    cache = MagicMock()
    cache.procesos = [_make_mock_proc_excel(proc_uid)]
    return cache


def _make_mock_app_cache(
    proc_uid: int = 300,
    plc_names: tuple[str, ...] = ("S7-1500",),
) -> MagicMock:
    """Crea un ``AppCache`` mockeado con un Excel cacheado.

    Multi-PLC: el endpoint ``crear_aplicar`` ahora valida
    ``plc_name in excel_cache_full.plcs`` antes de encolar el FB.
    Por defecto mockeamos un cache con PLCs ``["S7-1500"]``.

    El router lee del ``app_cache`` via ``excel_get_full`` (area
    ``"alimentacion"``). La API vive en
    ``app_cache.area("alimentacion").excel_full``.
    """
    app_cache = MagicMock()
    cache = _make_mock_excel_cache_with_plcs(
        proc_uid=proc_uid, plc_names=plc_names
    )
    # Mockeamos el area cache: ``app_cache.area("alimentacion")``
    # devuelve un objeto con atributo ``excel_full``.
    area_mock = MagicMock()
    area_mock.excel_full = cache
    area_mock.excel_active = cache
    app_cache.area.return_value = area_mock
    return app_cache


def _make_mock_excel_cache_with_plcs(
    proc_uid: int, plc_names: tuple[str, ...]
) -> MagicMock:
    """Cache fake con un set concreto de PLCs en ``Tabla_PLC`` y un
    proceso para que ``_resolve_excel_proc`` lo encuentre.

    Usado para que ``validate_plc_in_excel`` acepte el plc_name del body
    Y para que el lookup por proc_uid no lance ``ValueError``.
    """
    cache = MagicMock()
    cache.plcs = [MagicMock(plc=p, uid=i) for i, p in enumerate(plc_names)]
    cache.procesos = [_make_mock_proc_excel(proc_uid)]
    return cache


def _make_mock_fb(
    *,
    result: dict | None = None,
    is_terminal_return: bool = True,
) -> MagicMock:
    """Crea un mock del FB que el router consume.

    El router solo mira que el FB este registrado
    (``engine.get_fb``): no lo arranca, no lo sondea y no lee su
    ``result`` (el trabajo aun no se ha ejecutado al responder 202).
    ``result`` se conserva para los tests que comprueban que el result
    del FB no se filtra en el body de la respuesta.
    ``is_terminal`` se fija a True porque un ``MagicMock`` sin
    configurar es truthy y falsearia cualquier comprobacion de estado.
    """
    fb = MagicMock()
    fb.is_terminal = MagicMock(return_value=is_terminal_return)
    fb.result = result
    return fb


class _FakeFBQueRegistraElResult:
    """FB fake que anota si alguien lee su atributo ``result``.

    El router no debe leer ``fb.result``: al responder 202 el FB todavia
    no ha ejecutado, asi que cualquier lectura daria un valor vacio.
    """

    def __init__(self) -> None:
        self.result_leido = False

    @property
    def result(self) -> dict:
        self.result_leido = True
        return {
            "success": True,
            "archivos_previstos": [{"nombre_nuevo": "FC60010_EXP_INTERFAZ"}],
            "archivos_generados": ["Bloques de programa/FC60010_EXP_INTERFAZ.s7dcl"],
            "colisiones": [],
            "compile_result": {"ok": True},
        }


@pytest.fixture
def plantilla_dummy(tmp_path: Path) -> Path:
    """Crea una plantilla minima en tmp_path."""
    p = tmp_path / "TestPlantilla"
    p.mkdir()
    bloques = p / "Bloques de programa"
    bloques.mkdir()
    (bloques / "FC50010_TEST_INTERFAZ.s7dcl").write_text(
        "FUNCTION_BLOCK FC50010_TEST_INTERFAZ\n", encoding="utf-8",
    )
    (bloques / "50010_TEST_COMENTARIOS.s7res").write_text(
        "BOM content", encoding="utf-8-sig",
    )
    (p / "manifest.json").write_text(
        json.dumps({
            "base": 50010, "codigo": "TEST", "nombre": "ProcesoTest",
            "minimos": {
                "N_MAX_PREAL": 3, "N_MAX_PINT": 15,
                "N_MAX_ALM": 16, "N_MAX_ALM_HMI": 3,
            },
        }),
        encoding="utf-8",
    )
    return p


# ── Tests ────────────────────────────────────────────────────────────


def test_crear_preview_ok_con_plantilla(plantilla_dummy: Path) -> None:
    """Body minimal valido (dir_plantilla_nombre + proc_uid) ->
    202 con el ``job_id`` (el result llega por SSE ``fb_state``)."""
    from areas.alimentacion.frontend.proc_process_crear_router import bp

    engine = MagicMock()
    fb_mock = _make_mock_fb(result={
        "success": True,
        "manifest_plantilla": {"base": 300, "codigo": "EXP"},
        "archivos_previstos": [
            {
                "nombre_original": "FC50010_TEST_INTERFAZ",
                "nombre_nuevo": "FC60010_EXP_INTERFAZ",
                "estado": "OK",
            },
        ],
        "colisiones": [],
        "preview_dir": str(plantilla_dummy.parent / "preview"),
    })
    engine.get_fb.return_value = fb_mock
    engine.submit.return_value = "job-preview-1"

    cm = MagicMock()
    cm.get_plantillas_path.return_value = str(plantilla_dummy.parent)

    app_cache = _make_mock_app_cache(proc_uid=300)

    app = _make_app(engine=engine, app_cache=app_cache, config_manager=cm)
    app.register_blueprint(bp)
    client = app.test_client()

    resp = client.post("/api/v1/procesos/crear/preview", json={
        "dir_plantilla_nombre": "TestPlantilla",
        "proc_uid": 300,
    })
    assert resp.status_code == 202
    data = resp.get_json()
    assert data["ok"] is True
    assert data["job_id"] == "job-preview-1"
    # El mock FB fue consultado por nombre correcto.
    engine.get_fb.assert_called_with("proc_process_crear_preview")
    # El trabajo se encola para el FB correcto con los kwargs resueltos
    # (uid=300 -> base=300, codigo=EXP, minimos_usuario={...} del Excel).
    engine.submit.assert_called_once()
    args, kwargs = engine.submit.call_args
    assert args[0] == "proc_process_crear_preview"
    assert kwargs["base_nueva"] == 300
    assert kwargs["codigo_nuevo"] == "EXP"
    assert kwargs["minimos_usuario"]["N_MAX_PREAL"] == 30


def test_crear_preview_expone_descripcion_y_dependencias(plantilla_dummy: Path) -> None:
    """El ``result`` del preview (``descripcion``,
    ``dependencias_ok`` y ``dependencias_faltantes``) ya NO viaja en
    la respuesta HTTP: el router responde 202 con el ``job_id`` y el
    result llega al HMI por el evento SSE ``fb_state``.

    Test historique adaptado al contrato OB1: fija que el router no
    filtre el result del FB en el body de la respuesta.
    """
    from areas.alimentacion.frontend.proc_process_crear_router import bp

    engine = MagicMock()
    fb_mock = _make_mock_fb(result={
        "success": True,
        "manifest_plantilla": {"base": 300, "codigo": "EXP"},
        "descripcion": "Proceso estandar de expedicion",
        "dependencias_ok": ["DB1_SYS"],
        "dependencias_faltantes": ["FC15151_ZC_MARCHA_PARO_SEC"],
        "archivos_previstos": [],
        "colisiones": [],
        "preview_dir": str(plantilla_dummy.parent / "preview"),
    })
    engine.get_fb.return_value = fb_mock
    engine.submit.return_value = "job-preview-2"

    cm = MagicMock()
    cm.get_plantillas_path.return_value = str(plantilla_dummy.parent)
    app_cache = _make_mock_app_cache(proc_uid=300)

    app = _make_app(engine=engine, app_cache=app_cache, config_manager=cm)
    app.register_blueprint(bp)
    client = app.test_client()

    resp = client.post("/api/v1/procesos/crear/preview", json={
        "dir_plantilla_nombre": "TestPlantilla",
        "proc_uid": 300,
    })
    assert resp.status_code == 202
    data = resp.get_json()
    assert data == {"ok": True, "job_id": "job-preview-2"}
    # El result del FB no se filtra en la respuesta (llega por SSE).
    assert "descripcion" not in data
    assert "dependencias_ok" not in data
    assert "dependencias_faltantes" not in data
    assert "archivos_previstos" not in data


def test_crear_preview_sin_excel() -> None:
    """Excel no cargado en app_cache -> 400 accionable."""
    from areas.alimentacion.frontend.proc_process_crear_router import bp

    engine = MagicMock()
    app_cache = MagicMock()
    # Mock del ``AreaCache`` con ``excel_full=None``.
    area_mock = MagicMock()
    area_mock.excel_full = None
    area_mock.excel_active = None
    app_cache.area.return_value = area_mock
    cm = MagicMock()
    cm.get_plantillas_path.return_value = "C:/plantillas"

    app = _make_app(engine=engine, app_cache=app_cache, config_manager=cm)
    app.register_blueprint(bp)
    client = app.test_client()

    resp = client.post("/api/v1/procesos/crear/preview", json={
        "dir_plantilla_nombre": "P",
        "proc_uid": 300,
    })
    assert resp.status_code == 400
    data = resp.get_json()
    assert "Excel" in data["error"] or "excel" in data["error"]


def test_crear_preview_proc_uid_inexistente() -> None:
    """proc_uid no esta en el Excel -> 400 accionable."""
    from areas.alimentacion.frontend.proc_process_crear_router import bp

    engine = MagicMock()
    cm = MagicMock()
    cm.get_plantillas_path.return_value = "C:/plantillas"
    app_cache = _make_mock_app_cache(proc_uid=300)  # El Excel solo tiene uid=300

    app = _make_app(engine=engine, app_cache=app_cache, config_manager=cm)
    app.register_blueprint(bp)
    client = app.test_client()

    resp = client.post("/api/v1/procesos/crear/preview", json={
        "dir_plantilla_nombre": "P",
        "proc_uid": 999,  # No existe en el Excel
    })
    assert resp.status_code == 400
    assert "999" in resp.get_json()["error"]


def test_crear_preview_body_incompleto() -> None:
    """Body sin dir_plantilla_nombre o sin proc_uid -> 400."""
    from areas.alimentacion.frontend.proc_process_crear_router import bp

    app = _make_app(engine=MagicMock())
    app.register_blueprint(bp)
    client = app.test_client()

    # Body vacio: faltan los 2 campos obligatorios.
    resp = client.post("/api/v1/procesos/crear/preview", json={})
    assert resp.status_code == 400
    assert "falta" in resp.get_json()["error"]

    # Falta solo proc_uid.
    resp = client.post("/api/v1/procesos/crear/preview", json={
        "dir_plantilla_nombre": "P",
    })
    assert resp.status_code == 400
    assert "proc_uid" in resp.get_json()["error"]

    # proc_uid no es int.
    resp = client.post("/api/v1/procesos/crear/preview", json={
        "dir_plantilla_nombre": "P",
        "proc_uid": "300",
    })
    assert resp.status_code == 400
    assert "int" in resp.get_json()["error"]


def test_crear_aplicar_fb_no_registrado() -> None:
    """Si el FB NO esta en el engine -> 500."""
    from areas.alimentacion.frontend.proc_process_crear_router import bp

    engine = MagicMock()
    engine.get_fb.return_value = None
    cm = MagicMock()
    cm.get_plantillas_path.return_value = "C:/plantillas"
    app_cache = _make_mock_app_cache(proc_uid=300)

    app = _make_app(engine=engine, app_cache=app_cache, config_manager=cm)
    app.register_blueprint(bp)
    client = app.test_client()

    resp = client.post("/api/v1/procesos/crear/aplicar", json={
        "dir_plantilla_nombre": "P",
        "proc_uid": 300,
        "plc_name": "S7-1500",
    })
    assert resp.status_code == 500
    data = resp.get_json()
    assert data["ok"] is False
    assert "proc_process_crear_aplicar" in data["error"]


def test_crear_aplicar_fb_ocupado_409(plantilla_dummy: Path) -> None:
    """Si ``engine.submit`` lanza ``FBBusyError`` (el FB ya tiene un
    trabajo en curso) -> 409."""
    from unittest.mock import patch
    from areas.alimentacion.frontend.proc_process_crear_router import bp

    engine = MagicMock()
    engine.get_fb.return_value = _make_mock_fb()
    engine.submit.side_effect = FBBusyError("FB ocupado: ya tiene trabajo")
    cm = MagicMock()
    cm.get_plantillas_path.return_value = str(plantilla_dummy.parent)
    app_cache = _make_mock_app_cache(proc_uid=300)

    app = _make_app(engine=engine, app_cache=app_cache, config_manager=cm)
    app.register_blueprint(bp)
    client = app.test_client()

    # ``with_plc`` opera sobre ``excel_cache_full`` (dataclass frozen).
    # En este test mockeamos el cache entero (MagicMock), asi que
    # parchamos el helper para que sea no-op.
    with patch(
        "areas.alimentacion.frontend.proc_process_crear_router.with_plc"
    ):
        resp = client.post("/api/v1/procesos/crear/aplicar", json={
            "dir_plantilla_nombre": "TestPlantilla",
            "proc_uid": 300,
            "plc_name": "S7-1500",
        })
    assert resp.status_code == 409
    data = resp.get_json()
    assert data["ok"] is False
    assert "trabajo en curso" in data["error"]


def test_crear_aplicar_sincroniza_selected_plc(plantilla_dummy: Path) -> None:
    """El endpoint invoca ``with_plc`` con (app_cache, plc_name, area_id)
    antes de encolar el FB (D6 stateless: el FB
    ``function_proc_crear_sincronizar`` no recibe ``app_cache`` por
    constructor, asi que el endpoint propaga ``selected_plc``).
    """
    from unittest.mock import patch
    from areas.alimentacion.frontend.proc_process_crear_router import bp
    from areas.alimentacion._area_id import AREA_ID

    engine = MagicMock()
    fb_mock = _make_mock_fb(result={
        "success": True, "archivos_generados": [],
        "colisiones": [], "manifest_plantilla": {},
        "import_result": {"success": True},
        "compile_result": {"ok": True},
    })
    engine.get_fb.return_value = fb_mock
    engine.submit.return_value = "job-aplicar-1"
    cm = MagicMock()
    cm.get_plantillas_path.return_value = str(plantilla_dummy.parent)
    app_cache = _make_mock_app_cache(proc_uid=300)

    app = _make_app(engine=engine, app_cache=app_cache, config_manager=cm)
    app.register_blueprint(bp)
    client = app.test_client()

    with patch(
        "areas.alimentacion.frontend.proc_process_crear_router.with_plc"
    ) as with_plc_mock:
        resp = client.post("/api/v1/procesos/crear/aplicar", json={
            "dir_plantilla_nombre": "TestPlantilla",
            "proc_uid": 300,
            "plc_name": "S7-1500",
        })

    assert resp.status_code == 202
    assert resp.get_json()["job_id"] == "job-aplicar-1"
    with_plc_mock.assert_called_once_with(
        app_cache, "S7-1500", AREA_ID,
    )
    # El trabajo se encola para el FB correcto.
    engine.submit.assert_called_once()
    args, kwargs = engine.submit.call_args
    assert args[0] == "proc_process_crear_aplicar"
    assert kwargs["plc_name"] == "S7-1500"


def test_crear_preview_plc_blocks_cache_acepta_strings_y_dicts(
    plantilla_dummy: Path,
) -> None:
    """``plc_blocks_cache`` acepta ``list[str]`` (recomendado) o
    ``list[dict{ nombre }]``. El router extrae el campo ``nombre``
    de los dicts defensivamente (descarta items sin nombre) y
    popula ``plc_blocks_cache`` como ``list[dict{nombre, numero}]``
    (match por nombre O por numero, consistente con la logica
    del helper v2). Strings legacy se envuelven en ``{nombre}``.
    Items sin nombre se descartan defensivo.
    """
    from areas.alimentacion.frontend.proc_process_crear_router import bp

    engine = MagicMock()
    fb_mock = _make_mock_fb(result={
        "success": True, "archivos_previstos": [],
        "colisiones": [], "manifest_plantilla": {},
    })
    engine.get_fb.return_value = fb_mock
    engine.submit.return_value = "job-preview-3"
    cm = MagicMock()
    cm.get_plantillas_path.return_value = str(plantilla_dummy.parent)
    app_cache = _make_mock_app_cache(proc_uid=300)

    app = _make_app(engine=engine, app_cache=app_cache, config_manager=cm)
    app.register_blueprint(bp)
    client = app.test_client()

    resp = client.post("/api/v1/procesos/crear/preview", json={
        "dir_plantilla_nombre": "TestPlantilla",
        "proc_uid": 300,
        "plc_blocks_cache": [
            "DB60010_OTRA",
            "FB60010",
            {"nombre": "DB70001"},
            # Item sin nombre -> el router lo descarta defensivo.
            {"tipo": "DB", "numero": 60010},
            # Item con numero como string -> se coerce a int.
            {"nombre": "DB80001", "numero": "80001"},
        ],
    })
    assert resp.status_code == 202

    _, kwargs = engine.submit.call_args
    # Lista dicts ``{nombre, numero}`` normalizada. Strings se
    # envuelven en ``{nombre, numero: None}``. Items sin nombre y
    # dicts mal formados se descartan.
    assert kwargs["plc_blocks_cache"] == [
        {"nombre": "DB60010_OTRA", "numero": None},
        {"nombre": "FB60010", "numero": None},
        {"nombre": "DB70001", "numero": None},
        {"nombre": "DB80001", "numero": 80001},
    ], f"plc_blocks_cache={kwargs['plc_blocks_cache']}"
    # Sin campos avanzados: el router NO emite plc_blocks_por_tipo
    # ni plc_blocks_detalle.
    assert "plc_blocks_por_tipo" not in kwargs
    assert "plc_blocks_detalle" not in kwargs


# ── Suite parametrizada: los 2 endpoints ─────────────────────────────

# (url, nombre del FB encolado, body valido)
ENDPOINTS = [
    ("/api/v1/procesos/crear/preview", "proc_process_crear_preview",
     {"dir_plantilla_nombre": "TestPlantilla", "proc_uid": 300}),
    ("/api/v1/procesos/crear/aplicar", "proc_process_crear_aplicar",
     {"dir_plantilla_nombre": "TestPlantilla", "proc_uid": 300,
      "plc_name": "S7-1500"}),
]
IDS = ["preview", "aplicar"]


def _make_app_para_endpoint(engine: MagicMock | None = None) -> Flask:
    """App con Excel cacheado y ``plantillas_path`` valido.

    Los endpoints validan el body ANTES de mirar el engine, asi que
    para probar los 500/409 hace falta un body valido + Excel. Sin
    ``engine`` el config se queda sin la clave ``ENGINE`` (el router
    la lee con ``current_app.config["ENGINE"]``).
    """
    app = Flask(__name__)
    if engine is not None:
        app.config["ENGINE"] = engine
    app.config["APP_CACHE"] = _make_mock_app_cache(proc_uid=300)
    cm = MagicMock()
    cm.get_plantillas_path.return_value = "C:/plantillas"
    app.config["CONFIG_MANAGER"] = cm
    return app


@contextmanager
def _with_plc_noop():
    """``with_plc`` no-op: el ``app_cache`` de los tests es un mock."""
    with patch(
        "areas.alimentacion.frontend.proc_process_crear_router.with_plc"
    ):
        yield


@pytest.mark.parametrize("url,_fb_name,body", ENDPOINTS, ids=IDS)
def test_endpoint_body_invalido_devuelve_400(url, _fb_name, body) -> None:
    """Body incompleto -> 400 (mismo codigo que antes de migrar)."""
    from areas.alimentacion.frontend.proc_process_crear_router import bp

    engine = MagicMock()
    engine.get_fb.return_value = _make_mock_fb()
    app = _make_app_para_endpoint(engine=engine)
    app.register_blueprint(bp)
    client = app.test_client()

    resp = client.post(url, json={})
    assert resp.status_code == 400
    payload = resp.get_json()
    assert payload["ok"] is False
    assert "falta" in payload["error"]


def test_crear_aplicar_sin_plc_name_devuelve_400(plantilla_dummy: Path) -> None:
    """El ``plc_name`` sigue siendo obligatorio en ``/aplicar`` -> 400."""
    from areas.alimentacion.frontend.proc_process_crear_router import bp

    engine = MagicMock()
    engine.get_fb.return_value = _make_mock_fb()
    cm = MagicMock()
    cm.get_plantillas_path.return_value = str(plantilla_dummy.parent)
    app_cache = _make_mock_app_cache(proc_uid=300)

    app = _make_app(engine=engine, app_cache=app_cache, config_manager=cm)
    app.register_blueprint(bp)
    client = app.test_client()

    resp = client.post("/api/v1/procesos/crear/aplicar", json={
        "dir_plantilla_nombre": "TestPlantilla",
        "proc_uid": 300,
    })
    assert resp.status_code == 400
    payload = resp.get_json()
    assert payload["ok"] is False
    assert "plc_name" in payload["error"]


@pytest.mark.parametrize("url,_fb_name,body", ENDPOINTS, ids=IDS)
def test_endpoint_sin_engine_devuelve_500(url, _fb_name, body) -> None:
    """Sin ``ENGINE`` en el config -> KeyError -> 500."""
    from areas.alimentacion.frontend.proc_process_crear_router import bp

    app = _make_app_para_endpoint(engine=None)
    app.register_blueprint(bp)
    with app.test_client() as client:
        resp = client.post(url, json=body)
    assert resp.status_code == 500


@pytest.mark.parametrize("url,fb_name,body", ENDPOINTS, ids=IDS)
def test_endpoint_fb_no_registrado_devuelve_500(url, fb_name, body) -> None:
    """FB no registrado en el engine -> 500."""
    from areas.alimentacion.frontend.proc_process_crear_router import bp

    engine = MagicMock()
    engine.get_fb.return_value = None
    app = _make_app_para_endpoint(engine=engine)
    app.register_blueprint(bp)
    with app.test_client() as client:
        resp = client.post(url, json=body)
    assert resp.status_code == 500
    payload = resp.get_json()
    assert payload["ok"] is False
    assert "no registrado" in payload["error"]
    assert fb_name in payload["error"]


@pytest.mark.parametrize("url,_fb_name,body", ENDPOINTS, ids=IDS)
def test_endpoint_fb_ocupado_devuelve_409(url, _fb_name, body) -> None:
    """``engine.submit`` lanza ``FBBusyError`` -> 409."""
    from areas.alimentacion.frontend.proc_process_crear_router import bp

    engine = MagicMock()
    engine.get_fb.return_value = _make_mock_fb()
    engine.submit.side_effect = FBBusyError("FB ocupado: ya tiene trabajo")
    app = _make_app_para_endpoint(engine=engine)
    app.register_blueprint(bp)
    with app.test_client() as client:
        with _with_plc_noop():
            resp = client.post(url, json=body)
    assert resp.status_code == 409
    payload = resp.get_json()
    assert payload["ok"] is False
    assert "trabajo en curso" in payload["error"]


@pytest.mark.parametrize("url,_fb_name,body", ENDPOINTS, ids=IDS)
def test_endpoint_submit_falla_devuelve_500(url, _fb_name, body) -> None:
    """``engine.submit`` lanza otra excepcion -> 500."""
    from areas.alimentacion.frontend.proc_process_crear_router import bp

    engine = MagicMock()
    engine.get_fb.return_value = _make_mock_fb()
    engine.submit.side_effect = RuntimeError("boom")
    app = _make_app_para_endpoint(engine=engine)
    app.register_blueprint(bp)
    with app.test_client() as client:
        with _with_plc_noop():
            resp = client.post(url, json=body)
    assert resp.status_code == 500
    payload = resp.get_json()
    assert payload["ok"] is False
    assert "boom" in payload["error"]


@pytest.mark.parametrize("url,fb_name,body", ENDPOINTS, ids=IDS)
def test_endpoint_happy_path_devuelve_202_con_job_id(
    url, fb_name, body,
) -> None:
    """Happy path -> 202 con ``job_id`` y ``submit`` con los params."""
    from areas.alimentacion.frontend.proc_process_crear_router import bp

    engine = MagicMock()
    fb_mock = _make_mock_fb()
    engine.get_fb.return_value = fb_mock
    engine.submit.return_value = "job-abc123"
    app = _make_app_para_endpoint(engine=engine)
    app.register_blueprint(bp)
    with app.test_client() as client:
        with _with_plc_noop():
            resp = client.post(url, json=body)
    assert resp.status_code == 202
    payload = resp.get_json()
    assert payload["ok"] is True
    assert payload["job_id"] == "job-abc123"
    # El trabajo se encola para el FB correcto con los params resueltos.
    engine.submit.assert_called_once()
    args, kwargs = engine.submit.call_args
    assert args[0] == fb_name
    assert kwargs["dir_plantilla_nombre"] == "TestPlantilla"
    assert kwargs["base_nueva"] == 300
    assert kwargs["codigo_nuevo"] == "EXP"
    assert kwargs["minimos_usuario"]["N_MAX_PREAL"] == 30
    if fb_name == "proc_process_crear_aplicar":
        assert kwargs["plc_name"] == "S7-1500"
    # El router no arranca ni sondea el FB (no hay poll bloqueante).
    fb_mock.start.assert_not_called()
    fb_mock.is_terminal.assert_not_called()


@pytest.mark.parametrize("url,_fb_name,body", ENDPOINTS, ids=IDS)
def test_endpoint_no_devuelve_el_result_del_fb(url, _fb_name, body) -> None:
    """El router no bloquea: la respuesta lleva solo ok + job_id."""
    from areas.alimentacion.frontend.proc_process_crear_router import bp

    engine = MagicMock()
    engine.get_fb.return_value = _make_mock_fb(result={
        "success": True,
        "archivos_previstos": [{"nombre": "FC60010_EXP_INTERFAZ"}],
        "archivos_generados": [{"nombre": "FC60010_EXP_INTERFAZ"}],
        "colisiones": [],
        "import_result": {"success": True},
        "compile_result": {"ok": True},
    })
    engine.submit.return_value = "job-abc123"
    app = _make_app_para_endpoint(engine=engine)
    app.register_blueprint(bp)
    with app.test_client() as client:
        with _with_plc_noop():
            resp = client.post(url, json=body)
    assert resp.status_code == 202
    payload = resp.get_json()
    assert payload == {"ok": True, "job_id": "job-abc123"}
    for key in (
        "result", "success", "archivos_previstos", "archivos_generados",
        "colisiones", "import_result", "compile_result",
    ):
        assert key not in payload


# ── El log de cierre lo emite el FB, no el router ────────────────────


@pytest.mark.parametrize("url,_fb_name,body", ENDPOINTS, ids=IDS)
def test_router_no_lee_el_result_del_fb(url, _fb_name, body) -> None:
    """El router no lee ``fb.result``.

    Al responder 202 el FB todavia no ha ejecutado: su ``result`` esta
    vacio. Si el router lo leyera, el log de cierre reportaria siempre
    "0 archivos, 0 colisiones". El cierre lo emite el FB, que ya tiene
    el dato real.
    """
    from areas.alimentacion.frontend.proc_process_crear_router import bp

    engine = MagicMock()
    fb_falso = _FakeFBQueRegistraElResult()
    engine.get_fb.return_value = fb_falso
    engine.submit.return_value = "job-abc123"
    app = _make_app_para_endpoint(engine=engine)
    app.register_blueprint(bp)
    with app.test_client() as client:
        with _with_plc_noop():
            resp = client.post(url, json=body)
    assert resp.status_code == 202
    assert fb_falso.result_leido is False


@pytest.mark.parametrize("url,_fb_name,body", ENDPOINTS, ids=IDS)
def test_router_no_emite_el_log_de_cierre(
    url, _fb_name, body, caplog: pytest.LogCaptureFixture,
) -> None:
    """El router no emite el log de cierre del trabajo.

    Ese log lo emite el FB al terminar (``on_finish``), cuando ya
    dispone del resultado real. Si el router lo emitiera al encolar,
    los contadores saldrian siempre a cero.
    """
    from areas.alimentacion.frontend.proc_process_crear_router import bp

    engine = MagicMock()
    engine.get_fb.return_value = _make_mock_fb(result={
        "success": True,
        "archivos_previstos": [{"nombre_nuevo": "FC60010_EXP_INTERFAZ"}],
        "archivos_generados": ["Bloques de programa/FC60010_EXP_INTERFAZ.s7dcl"],
        "colisiones": [],
        "compile_result": {"ok": True},
    })
    engine.submit.return_value = "job-abc123"
    app = _make_app_para_endpoint(engine=engine)
    app.register_blueprint(bp)
    with app.test_client() as client:
        with caplog.at_level(logging.DEBUG, logger=ROUTER_LOGGER):
            with _with_plc_noop():
                resp = client.post(url, json=body)
    assert resp.status_code == 202
    cierres = [
        record.getMessage()
        for record in caplog.records
        if record.name == ROUTER_LOGGER
        and (
            "archivos previstos" in record.getMessage()
            or "archivos generados" in record.getMessage()
        )
    ]
    assert cierres == [], (
        f"el router no debe emitir el log de cierre: {cierres}"
    )


# ── Validacion de entrada -> 400 ─────────────────────────────────────


def test_crear_aplicar_plc_no_esta_en_el_excel_devuelve_400() -> None:
    """El ``plc_name`` no esta en la Tabla_PLC del Excel -> 400.

    Es validacion de entrada, no un fallo del servidor. El mensaje lo
    da ``validate_plc_in_excel`` e incluye la lista de PLCs disponibles
    en el Excel para que el operario sepa que corregir.
    """
    from areas.alimentacion.frontend.proc_process_crear_router import bp

    engine = MagicMock()
    engine.get_fb.return_value = _make_mock_fb()
    cm = MagicMock()
    cm.get_plantillas_path.return_value = "C:/plantillas"
    app_cache = _make_mock_app_cache(proc_uid=300, plc_names=("S7-1500",))

    app = _make_app(engine=engine, app_cache=app_cache, config_manager=cm)
    app.register_blueprint(bp)
    client = app.test_client()

    with _with_plc_noop():
        resp = client.post("/api/v1/procesos/crear/aplicar", json={
            "dir_plantilla_nombre": "TestPlantilla",
            "proc_uid": 300,
            "plc_name": "PLC_INEXISTENTE",
        })
    assert resp.status_code == 400
    payload = resp.get_json()
    assert payload["ok"] is False
    assert "no esta en el Excel" in payload["error"]
    # El mensaje reutiliza el del helper: lista los PLCs del Excel.
    assert "S7-1500" in payload["error"]
    # No se encolo ningun trabajo.
    engine.submit.assert_not_called()
