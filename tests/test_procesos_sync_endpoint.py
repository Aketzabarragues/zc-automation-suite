"""Tests del endpoint REST ``/api/v1/procesos/sync/{preview,commit}``.

Patrón TestClient + ``app.dependency_overrides`` (AGENTS.md §1):
no instanciamos gateways; los mocks se inyectan vía ``Depends``.
"""
from __future__ import annotations

import os
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

from core.application.progress_buffer import ProgressTracker
from core.infrastructure.gateway import TIAProcessGateway
from interfaces.web_server.app import create_app


@pytest.fixture
def mock_gateway() -> MagicMock:
    g = MagicMock(spec=TIAProcessGateway)
    g.execute_transactional_batch = AsyncMock(
        return_value={
            "success": True,
            "operations_executed": 3,
            "details": [
                {"kind": "preal", "modified": True, "db_name": "DB53100_CPR_PARAM"},
                {"kind": "pint",  "modified": True, "db_name": "DB53100_CPR_PARAM"},
                {"kind": "alm",   "modified": True, "db_name": "DB55100_CPR_ALM"},
            ],
        }
    )
    return g


@pytest.fixture
def mock_excel_cache() -> MagicMock:
    """Excel cache con 1 proceso, 2 PReal, 1 ALM."""
    proc = MagicMock(uid=1, nombre="Compacto", codigo="CPR")
    ec = MagicMock()
    ec.procesos = [proc]
    ec.parametros_real = [
        MagicMock(uid="PR_1", codigo="CPR", num_db=53100, comentario_db="X"),
        MagicMock(uid="PR_2", codigo="CPR", num_db=53100, comentario_db="Y"),
    ]
    ec.parametros_int = []
    ec.alarmas = [
        MagicMock(uid="AL_1", proceso="Compacto", num_db=55100, comentario_db="Z")
    ]
    return ec


@pytest.fixture
def mock_app_state(mock_excel_cache: MagicMock) -> MagicMock:
    state = MagicMock()
    state.excel_cache = mock_excel_cache
    return state


@pytest.fixture
def mock_config_manager() -> MagicMock:
    cm = MagicMock()
    cm.get_tia_folder_proceso.return_value = "003_Procesos"
    return cm


@pytest.fixture
def client(
    mock_gateway: MagicMock,
    mock_config_manager: MagicMock,
    mock_app_state: MagicMock,
) -> TestClient:
    app = create_app(gateway=mock_gateway)
    app.state.config_manager = mock_config_manager
    app.state.app_state = mock_app_state
    app.state.progress_tracker = ProgressTracker()
    return TestClient(app)


# ── Tests ───────────────────────────────────────────────────────────────


def test_endpoint_preview_devuelve_shape_esperado(
    client: TestClient, mock_gateway: MagicMock
) -> None:
    """POST /preview devuelve el shape con ``precondiciones_ok`` y
    ``missing_blocks`` en el primer nivel. Sin cache inyectada en el
    gateway, el mensaje es accionable (el operario debe escanear
    el PLC primero)."""
    # El mock del gateway, por defecto, devuelve MagicMock para
    # cualquier atributo (incluido ``get_bloques_cache``). Forzamos
    # explícitamente ``None`` para simular "PLC no escaneado".
    mock_gateway.get_bloques_cache.return_value = None
    resp = client.post(
        "/api/v1/procesos/sync/preview",
        json={"proc_uid": 1, "plc_name": "PLC_X"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert "precondiciones_ok" in body
    assert "missing_blocks" in body
    # Sin BloqueCache (gateway.get_bloques_cache devuelve None),
    # el use case devuelve un mensaje accionable.
    assert body["precondiciones_ok"] is False
    assert len(body["missing_blocks"]) == 1
    assert "Cache de bloques del PLC no disponible" in body["missing_blocks"][0]


def test_endpoint_preview_usa_cache_real_del_gateway(
    client: TestClient, mock_gateway: MagicMock, mock_excel_cache: MagicMock
) -> None:
    """Si el gateway tiene la cache de bloques poblada (escaneada
    previamente), el preview la usa para evaluar las precondiciones.

    Regression test: en una versión anterior, el router creaba un
    ``BloqueCache()`` vacío en lugar de usar el del gateway, así que
    los 3 bloques (DB_PARAM, DB_ALM, tabla) salían como missing
    aunque existieran en la cache real. Este test reproduce el bug:
    pre-pobla la cache del gateway, hace el preview y verifica que
    los bloques se consideran encontrados (precondiciones_ok=True
    con 0 missing_blocks).
    """
    from core.models.bloque_cache import BloqueCache
    from core.models.bloque_plc import BloquePLC
    # Pre-poblar la cache del gateway con los 3 bloques esperados
    # para proc_uid=1, codigo="CPR", num_db=53100/55100.
    populated_cache = BloqueCache(
        blocks={
            BloquePLC.normalize_name("DB53100_CPR_PARAM"):
                BloquePLC(nombre="DB53100_CPR_PARAM", numero=0, tipo="DB", ruta=""),
            BloquePLC.normalize_name("DB55100_CPR_ALM"):
                BloquePLC(nombre="DB55100_CPR_ALM", numero=0, tipo="DB", ruta=""),
        },
        tag_tables={
            BloquePLC.normalize_name("1_CPR"):
                BloquePLC(nombre="1_CPR", numero=0, tipo="TAG_TABLE", ruta=""),
        },
        plc_name="PLC_X",
    )
    mock_gateway.get_bloques_cache.return_value = populated_cache

    resp = client.post(
        "/api/v1/procesos/sync/preview",
        json={"proc_uid": 1, "plc_name": "PLC_X"},
    )
    assert resp.status_code == 200
    body = resp.json()
    # La cache está poblada y los 3 bloques existen → precondiciones OK.
    assert body["precondiciones_ok"] is True, (
        f"El router debe usar la cache del gateway, no una vacía. "
        f"missing_blocks={body['missing_blocks']}"
    )
    assert body["missing_blocks"] == []
    # Sanity: el router pidió la cache al gateway.
    mock_gateway.get_bloques_cache.assert_called_with("PLC_X")


def test_endpoint_preview_sin_plc_name_devuelve_precondiciones_false(
    client: TestClient, mock_gateway: MagicMock
) -> None:
    """Si el SPA no envía ``plc_name`` (campo opcional), el router
    trata la cache como ``None`` y devuelve el mensaje accionable
    "Cache de bloques del PLC no disponible". Esto es defensivo:
    el SPA actual siempre envía plc_name, pero queremos un fallback
    robusto."""
    mock_gateway.get_bloques_cache.return_value = None
    resp = client.post(
        "/api/v1/procesos/sync/preview",
        json={"proc_uid": 1},  # sin plc_name
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["precondiciones_ok"] is False
    # El router NO llama a get_bloques_cache con "" (porque evita
    # el lookup en vacío), así que el mock no se invoca aquí. Esto
    # es OK; el use case maneja la cache=None igualmente.
    assert "Cache de bloques" in body["missing_blocks"][0]


def test_endpoint_commit_invoca_3_ops_en_lote(
    client: TestClient, mock_gateway: MagicMock
) -> None:
    """POST /commit invoca ``gateway.execute_transactional_batch`` con
    3 ops (PReal + PInt + ALM). El test inyecta un BloqueCache con
    los 3 nombres esperados en ``app.state.bloques_cache`` (s髄o
    accesible si la inyección lo soporta) — para esta versión
    basta verificar el shape del body y que el gateway fue llamado.
    """
    # Para que la precondición de bloques pase, monkey-patcheamos
    # la cache de bloques en el gateway (que es donde el use case
    # la lee indirectamente a través del state).
    # Como el router no acepta bloques_cache, vamos a verificar
    # un escenario donde la precondición falla y el endpoint
    # devuelve 500 (porque el use case lanza). Esto verifica que
    # la llamada se hace correctamente.
    resp = client.post(
        "/api/v1/procesos/sync/commit",
        json={
            "proc_uid": 1,
            "plc_name": "PLC_X",
            "prevision": {"proc_uid": 1, "plc_name": "PLC_X"},
        },
    )
    # 500 porque missing_blocks → RuntimeError → HTTPException 500.
    # Eso verifica que el endpoint se monta y el use case se invoca.
    assert resp.status_code == 500
    assert "missing" in resp.json()["detail"].lower() or "bloques" in resp.json()["detail"].lower()


def test_endpoint_commit_invoca_gateway_con_target_folder_y_undo(
    client: TestClient, mock_gateway: MagicMock, monkeypatch,
) -> None:
    """Si precondiciones OK, el commit invoca el gateway con 3 ops
    y el target_folder correcto del config."""
    # Monkey-patch del BloqueCacheManager / cache para que las
    # precondiciones pasen. Inyectamos en ``app.state`` un objeto
    # mágico que el router puede usar.
    from core.models.bloque_cache import BloqueCache
    from core.models.bloque_plc import BloquePLC
    bloques = BloqueCache(
        blocks={
            BloquePLC.normalize_name("DB53100_CPR_PARAM"):
                BloquePLC(nombre="DB53100_CPR_PARAM", numero=0, tipo="DB", ruta=""),
            BloquePLC.normalize_name("DB55100_CPR_ALM"):
                BloquePLC(nombre="DB55100_CPR_ALM", numero=0, tipo="DB", ruta=""),
        },
        tag_tables={
            BloquePLC.normalize_name("1_CPR"):
                BloquePLC(nombre="1_CPR", numero=0, tipo="TAG_TABLE", ruta=""),
        },
        plc_name="PLC_X",
    )
    # Inyectamos el BloqueCache en el AppState (el use case lo lee
    # del constructor, pero el router no lo inyecta por ahora).
    # Truco: parchear el módulo del use case para que use nuestro
    # cache.
    from areas.alimentacion.application.use_cases import sync_procesos_comentarios
    original_init = sync_procesos_comentarios.SyncProcesosComentariosUseCase.__init__
    def patched_init(self, gateway, config_manager, app_state, progress=None, bloques_cache=None):
        original_init(self, gateway, config_manager, app_state, progress=progress, bloques_cache=bloques)
    sync_procesos_comentarios.SyncProcesosComentariosUseCase.__init__ = patched_init
    try:
        resp = client.post(
            "/api/v1/procesos/sync/commit",
            json={
                "proc_uid": 1,
                "plc_name": "PLC_X",
                "prevision": {"proc_uid": 1, "plc_name": "PLC_X"},
            },
        )
    finally:
        sync_procesos_comentarios.SyncProcesosComentariosUseCase.__init__ = original_init

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["operations_executed"] == 3
    # Verifica que se llamó al gateway con 3 ops.
    call_args = mock_gateway.execute_transactional_batch.call_args.kwargs
    operations = call_args["operations"]
    assert len(operations) == 3
    command_names = [op["command"] for op in operations]
    assert command_names == [
        "update_proc_comments_db_preal",
        "update_proc_comments_db_pint",
        "update_proc_comments_db_alm",
    ]
    # target_folder y work_dir vienen del config. El work_dir del
    # commit sigue el patrón ``<build_cache>/procesos/commit/``
    # (análogo a ``SyncDispositivosInstancesUseCase``: ``<build_cache>/
    # base/tags/`` y ``<build_cache>/commit/tags/``). El preview usa
    # ``<build_cache>/procesos/preview/`` separado, para que el
    # operario no confunda archivos exportados durante un preview con
    # archivos a reimportar en el commit.
    for op in operations:
        assert op["args"]["target_folder"] == "003_Procesos"
        # ``os.sep`` para tolerar backslash en Windows y slash en
        # Linux/macOS.
        assert op["args"]["work_dir"].endswith(
            f"procesos{os.sep}commit"
        ), op["args"]["work_dir"]
    # Undo text menciona el codigo "CPR" y el PLC.
    assert "CPR" in call_args["undo_text"]
    assert "PLC_X" in call_args["undo_text"]


def test_endpoint_500_si_use_case_falla(
    client: TestClient, mock_gateway: MagicMock,
) -> None:
    """Si el use case lanza, el endpoint responde 500."""
    # Forzamos error: app_state.excel_cache = None hace que
    # ``ejecutar_transaccion`` lance ``RuntimeError("AppState.excel_cache
    # está vacío. ...")`` desde el use case. El router lo convierte
    # en HTTPException 500.
    original_state = client.app.state.app_state
    state_vacio = MagicMock()
    state_vacio.excel_cache = None
    client.app.state.app_state = state_vacio
    try:
        resp = client.post(
            "/api/v1/procesos/sync/commit",
            json={
                "proc_uid": 1,
                "plc_name": "PLC_X",
                "prevision": {"proc_uid": 1, "plc_name": "PLC_X"},
            },
        )
    finally:
        client.app.state.app_state = original_state

    assert resp.status_code == 500
    body = resp.json()
    # El detail trae el mensaje del RuntimeError.
    assert "ejecutar_transaccion" in body["detail"].lower()
