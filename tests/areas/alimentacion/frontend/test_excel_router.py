"""Tests del router Flask ``POST /api/v1/excel/upload``.

El router ya no bloquea: escribe el fichero subido a un temporal,
encola el trabajo en el OB1 y responde 202 con el ``job_id``. El
resultado llega al HMI por push (SSE ``fb_state`` y el slot
``excel_full`` del AppCache que publica el FB al terminar).

Cubre:
  - sin fichero subido           -> 400
  - extension no soportada       -> 400
  - sin engine inyectado         -> 500
  - FB no registrado en el engine -> 500
  - FB con trabajo en curso       -> 409
  - fallo al encolar              -> 500
  - happy path                    -> 202 con job_id
  - la respuesta NO lleva el result del FB
  - el temporal sobrevive al 202  -> lo borra el FB
  - el temporal no queda colgando en 409/500
  - el FB borra el temporal al terminar
"""
from __future__ import annotations

import io
import tempfile
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from flask import Flask

from areas.alimentacion.frontend.excel_router import bp
from areas.alimentacion.functions.function_excel_cargar import (
    FunctionExcelCargar,
)
from core.composition.plc_engine import FBBusyError
from core.infrastructure.config.config_manager import ConfigManager
from core.runtime.app_cache import AppCache
from core.runtime.progress_buffer import ProgressTracker


def _make_app(engine: MagicMock | None = None) -> Flask:
    app = Flask(__name__)
    app.register_blueprint(bp)
    if engine is not None:
        app.config["ENGINE"] = engine
    return app


def _make_engine(*, fb: object = "fb", submit: object = None) -> MagicMock:
    engine = MagicMock()
    engine.get_fb.return_value = fb if fb != "fb" else MagicMock()
    engine.submit.return_value = submit if submit is not None else "job-abc123"
    return engine


def _subir(client, filename: str = "excel.xlsx") -> object:
    """POST multipart con un fichero ``.xlsx``."""
    return client.post(
        "/api/v1/excel/upload",
        data={"file": (io.BytesIO(b"PK-fake-xlsx"), filename)},
        content_type="multipart/form-data",
    )


@pytest.fixture
def temporales(monkeypatch) -> list[Path]:
    """Registra los temporales que crea el router (sin cambiar su comportamiento).

    Spy sobre ``tempfile.NamedTemporaryFile``: permite afirmar si el
    temporal sigue en disco tras la respuesta (lo borra el FB) o si el
    router lo limpio (el trabajo no llego a encolarse).
    """
    rutas: list[Path] = []
    original = tempfile.NamedTemporaryFile

    def _spy(*args, **kwargs):
        handle = original(*args, **kwargs)
        rutas.append(Path(handle.name))
        return handle

    monkeypatch.setattr(tempfile, "NamedTemporaryFile", _spy)
    return rutas


# ---------------------------------------------------------------------------
# 400
# ---------------------------------------------------------------------------


def test_post_sin_fichero_devuelve_400() -> None:
    app = _make_app(_make_engine())
    with app.test_client() as client:
        resp = client.post(
            "/api/v1/excel/upload",
            data={},
            content_type="multipart/form-data",
        )
    assert resp.status_code == 400
    body = resp.get_json()
    assert body["ok"] is False
    assert "file" in body["error"]


def test_post_con_extension_no_soportada_devuelve_400() -> None:
    app = _make_app(_make_engine())
    with app.test_client() as client:
        resp = _subir(client, filename="excel.txt")
    assert resp.status_code == 400
    body = resp.get_json()
    assert body["ok"] is False
    assert ".xlsx" in body["error"]


# ---------------------------------------------------------------------------
# 500
# ---------------------------------------------------------------------------


def test_post_sin_engine_devuelve_500(temporales: list[Path]) -> None:
    """Sin ENGINE en el config -> KeyError -> 500 (y nada de temporales)."""
    app = Flask(__name__)
    app.register_blueprint(bp)
    with app.test_client() as client:
        resp = _subir(client)
    assert resp.status_code == 500
    # El trabajo no llego a encolarse: el temporal no puede quedar
    # colgando en el %TEMP% de Windows.
    assert temporales and not temporales[0].exists()


def test_post_con_engine_none_devuelve_500(temporales: list[Path]) -> None:
    """ENGINE presente pero ``None`` -> 500 con mensaje accionable."""
    app = _make_app(_make_engine())
    app.config["ENGINE"] = None
    with app.test_client() as client:
        resp = _subir(client)
    assert resp.status_code == 500
    body = resp.get_json()
    assert body["ok"] is False
    assert "Engine no disponible" in body["error"]
    assert temporales and not temporales[0].exists()


def test_post_fb_no_registrado_devuelve_500(temporales: list[Path]) -> None:
    app = _make_app(_make_engine(fb=None))
    with app.test_client() as client:
        resp = _subir(client)
    assert resp.status_code == 500
    body = resp.get_json()
    assert "no registrado" in body["error"]
    assert temporales and not temporales[0].exists()


def test_post_si_submit_falla_devuelve_500(temporales: list[Path]) -> None:
    engine = _make_engine()
    engine.submit.side_effect = RuntimeError("boom")
    app = _make_app(engine)
    with app.test_client() as client:
        resp = _subir(client)
    assert resp.status_code == 500
    body = resp.get_json()
    assert body["ok"] is False
    assert "boom" in body["error"]
    assert temporales and not temporales[0].exists()


# ---------------------------------------------------------------------------
# 409
# ---------------------------------------------------------------------------


def test_post_con_fb_ocupado_devuelve_409(temporales: list[Path]) -> None:
    engine = _make_engine()
    engine.submit.side_effect = FBBusyError("FB ocupado: ya tiene trabajo")
    app = _make_app(engine)
    with app.test_client() as client:
        resp = _subir(client)
    assert resp.status_code == 409
    body = resp.get_json()
    assert body["ok"] is False
    assert "trabajo en curso" in body["error"]
    # El FB no va a leer el temporal (el trabajo no se encolo): lo
    # borra el router.
    assert temporales and not temporales[0].exists()


# ---------------------------------------------------------------------------
# 202
# ---------------------------------------------------------------------------


def test_post_happy_path_devuelve_202_con_job_id() -> None:
    engine = _make_engine()
    app = _make_app(engine)
    with app.test_client() as client:
        resp = _subir(client)
    assert resp.status_code == 202
    body = resp.get_json()
    assert body["ok"] is True
    assert body["job_id"] == "job-abc123"
    # El trabajo se encola para el FB correcto, con la ruta del temporal.
    engine.submit.assert_called_once()
    args, kwargs = engine.submit.call_args
    assert args == ("subir_excel",)
    assert kwargs["xlsx_path"].endswith(".xlsx")


def test_post_no_devuelve_el_result_del_fb() -> None:
    """El router no bloquea: no hay result en la respuesta, solo el job_id."""
    engine = _make_engine()
    app = _make_app(engine)
    with app.test_client() as client:
        resp = _subir(client)
    body = resp.get_json()
    assert "result" not in body
    assert "summary" not in body
    assert "total_dispositivos" not in body


def test_temporal_sobrevive_al_202(temporales: list[Path]) -> None:
    """Con 202 el temporal NO se borra: lo borra el FB al terminar.

    Si el router lo borrase aqui, el FB (que corre despues, en el
    hilo del OB1) encontraria el fichero inexistente.
    """
    engine = _make_engine()
    app = _make_app(engine)
    with app.test_client() as client:
        resp = _subir(client)
    assert resp.status_code == 202
    assert len(temporales) == 1
    assert temporales[0].exists()


# ---------------------------------------------------------------------------
# FB: borrado del temporal
# ---------------------------------------------------------------------------


def _app_cache() -> AppCache:
    """AppCache real con el area ``alimentacion`` registrada."""
    import dataclasses

    from areas.alimentacion.state.area_cache import AlimentacionAreaCache

    cache = AppCache()
    cache.register_area("alimentacion", AlimentacionAreaCache())
    # ``selected_plc`` = "" -> filtro by_plc cae en rama "sin filtro".
    cache.mutate(
        lambda s: dataclasses.replace(s, selected_plc=""),
    )
    return cache


def _loader_factory() -> MagicMock:
    """Loader ficticio: ``load()`` devuelve un cache con 2 dispositivos."""
    fake_cache = MagicMock()
    fake_cache.dispositivos = {"disp_ed": (("dev1",), ("dev2",))}
    fake_cache.n_max = MagicMock()
    fake_cache.n_max.to_api_dict.return_value = {"max1": 10}
    fake_cache.procesos = []
    fake_cache.parametros_real = []
    fake_cache.parametros_int = []
    fake_cache.alarmas = []
    fake_cache.excel_path = "/fake/path.xlsx"

    def factory(config_manager: ConfigManager) -> MagicMock:
        loader = MagicMock()
        loader.load = MagicMock(return_value=fake_cache)
        return loader

    return factory


def test_fb_borra_el_temporal_al_terminar(tmp_path) -> None:
    """El FB borra el ``.xlsx`` temporal cuando el parseo termina bien."""
    xlsx = tmp_path / "subida.xlsx"
    xlsx.write_bytes(b"PK-fake-xlsx")

    fb = FunctionExcelCargar(
        nombre="subir_excel_test",
        config_manager=MagicMock(spec=ConfigManager),
        app_cache=_app_cache(),
        tracker=ProgressTracker(),
        excel_loader_factory=_loader_factory(),
    )
    fb.execute(xlsx_path=str(xlsx))

    assert fb.nStep == fb.n_done
    assert not xlsx.exists()


def test_fb_borra_el_temporal_tambien_si_falla(tmp_path) -> None:
    """El FB borra el temporal tambien cuando el parseo falla."""
    xlsx = tmp_path / "subida_corrupta.xlsx"
    xlsx.write_bytes(b"PK-fake-xlsx")

    def bad_factory(config_manager: ConfigManager) -> MagicMock:
        loader = MagicMock()
        loader.load = MagicMock(side_effect=ValueError("xlsx corrupto"))
        return loader

    fb = FunctionExcelCargar(
        nombre="subir_excel_test",
        config_manager=MagicMock(spec=ConfigManager),
        app_cache=_app_cache(),
        tracker=ProgressTracker(),
        excel_loader_factory=bad_factory,
    )
    fb.execute(xlsx_path=str(xlsx))

    assert fb.nStep == fb.n_error
    assert not xlsx.exists()
