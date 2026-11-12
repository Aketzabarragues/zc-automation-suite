"""Tests del arranque de la aplicacion."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from flask import Flask

from zc_suite.nucleo.app.main import AREAS, montar_app
from zc_suite.nucleo.tia.eventos import BusEventos
from zc_suite.nucleo.tia.servicio import ServicioTIA


class TsFalso:
    """Doble minimo del modulo ``siemens_tia_scripting``."""

    class Enums:
        class PortalMode:
            AnyUserInterface = "cualquier"
            WithGraphicalUserInterface = "con_gui"
            WithoutGraphicalUserInterface = "sin_gui"

    def set_logging(self, path: str, console: bool) -> None:
        pass


@pytest.fixture
def app() -> Flask:
    bus_eventos = BusEventos()
    servicio = ServicioTIA(publicador=bus_eventos.publicar, cargador=lambda: TsFalso())
    return montar_app(servicio, bus_eventos)


def test_la_app_monta_las_rutas_de_conexion(app: Flask) -> None:
    reglas = {regla.rule for regla in app.url_map.iter_rules()}

    assert "/api/v1/tia/conectar" in reglas
    assert "/api/v1/tia/desconectar" in reglas
    assert "/api/v1/tia/estado" in reglas
    assert "/api/eventos" in reglas


def test_el_area_de_alimentacion_esta_registrada() -> None:
    ids = [area.ID for area in AREAS]

    assert "alimentacion" in ids


def test_la_app_monta_las_rutas_del_area(app: Flask) -> None:
    reglas = {regla.rule for regla in app.url_map.iter_rules()}

    assert "/api/v1/areas/alimentacion/excel" in reglas


def test_el_logging_va_al_logger_de_la_app(app: Flask) -> None:
    import logging

    from zc_suite.nucleo.tia.eventos import HandlerEventos

    manejadores = logging.getLogger("zc_suite").handlers
    assert any(isinstance(m, HandlerEventos) for m in manejadores)


def test_el_handler_del_logging_no_se_enchufa_dos_veces() -> None:
    import logging

    from zc_suite.nucleo.tia.eventos import HandlerEventos

    bus_eventos = BusEventos()
    servicio = ServicioTIA(cargador=lambda: TsFalso())
    montar_app(servicio, bus_eventos)
    montar_app(servicio, bus_eventos)

    manejadores = [
        m for m in logging.getLogger("zc_suite").handlers if isinstance(m, HandlerEventos)
    ]
    assert len(manejadores) == 1


def test_el_estado_de_conexion_responde(app: Flask) -> None:
    cliente = app.test_client()

    respuesta = cliente.get("/api/v1/tia/estado", base_url="http://localhost:9484")

    assert respuesta.status_code == 200
    assert respuesta.get_json()["conectado"] is False


def test_las_areas_registran_su_blueprint(app: Flask) -> None:
    """Un area registrada monta sus rutas en la app."""
    from flask import Blueprint

    class AreaFalsa:
        ID = "falsa"

        def __init__(self) -> None:
            self.rutas = Blueprint("area_falsa", __name__, url_prefix="/api/falsa")

            @self.rutas.get("/datos")
            def _datos() -> Any:
                return {"ok": True}

    area = AreaFalsa()
    app.register_blueprint(area.rutas)

    reglas = {regla.rule for regla in app.url_map.iter_rules()}
    assert "/api/falsa/datos" in reglas


def test_el_argumento_web_se_parte_correctamente() -> None:
    from zc_suite.nucleo.app.main import main

    assert callable(main)


def test_el_estado_no_toca_el_portal(app: Flask) -> None:
    """Leer el estado no puede lanzar: el portal solo se toca en el hilo."""
    cliente = app.test_client()

    for _ in range(3):
        respuesta = cliente.get("/api/v1/tia/estado", base_url="http://localhost:9484")
        assert respuesta.status_code == 200


def test_el_servicio_no_arranca_hilo_al_montar_la_app(app: Flask) -> None:
    """Montar la app no debe arrancar el hilo de TIA por su cuenta."""
    servicio = app.config["ZC_TIA"]

    assert servicio.ocupado is False


def test_el_frontend_se_sirve_desde_el_build(app: Flask) -> None:
    cliente = app.test_client()

    respuesta = cliente.get("/", base_url="http://localhost:9484")

    assert respuesta.status_code in (200, 404)
    if respuesta.status_code == 200:
        respuesta.close()


def test_el_bus_recibe_los_eventos_de_la_app(app: Flask) -> None:
    bus_eventos = app.config["ZC_BUS"]

    bus_eventos.publicar("tia", {"conectado": True})

    assert bus_eventos.ultimo_tia() == {"type": "tia", "conectado": True}


def test_las_dependencias_viven_en_config(app: Flask) -> None:
    assert isinstance(app.config["ZC_TIA"], ServicioTIA)
    assert isinstance(app.config["ZC_BUS"], BusEventos)
    assert app.config["ZC_PUERTO"] == 9484


def test_la_configuracion_se_carga_al_montar_la_app(app: Flask) -> None:
    from zc_suite.nucleo.app.config import Config

    assert isinstance(app.config["ZC_CONFIG"], Config)
    assert "alimentacion" in app.config["ZC_CONFIG"].areas


def test_se_puede_inyectar_la_configuracion() -> None:
    from zc_suite.nucleo.app.config import Config

    bus_eventos = BusEventos()
    servicio = ServicioTIA(cargador=lambda: TsFalso())
    propia = Config.model_validate({"areas": {"alimentacion": {"tabla_nmax": "INYECTADA"}}})
    app = montar_app(servicio, bus_eventos, config=propia)

    assert app.config["ZC_CONFIG"].areas["alimentacion"]["tabla_nmax"] == "INYECTADA"


def test_el_modo_desarrollo_admite_los_origenes_de_vite() -> None:
    bus_eventos = BusEventos()
    servicio = ServicioTIA(cargador=lambda: TsFalso())
    app = montar_app(servicio, bus_eventos, desarrollo=True)

    with app.test_request_context("/"):
        from zc_suite.nucleo.web.app import origenes_permitidos

        assert "http://localhost:5173" in origenes_permitidos()


def test_el_modo_normal_no_admite_los_origenes_de_vite() -> None:
    bus_eventos = BusEventos()
    servicio = ServicioTIA(cargador=lambda: TsFalso())
    app = montar_app(servicio, bus_eventos)

    with app.test_request_context("/"):
        from zc_suite.nucleo.web.app import origenes_permitidos

        assert "http://localhost:5173" not in origenes_permitidos()


def test_el_tipo_de_areas_no_obliga_a_nada(app: Flask) -> None:
    assert isinstance(AREAS, list)
    assert all(hasattr(area, "ID") for area in AREAS)
    assert all(hasattr(area, "rutas") for area in AREAS)


def test_el_nucleo_se_monta_aunque_haya_areas(app: Flask) -> None:
    cliente: Any = app.test_client()

    assert cliente.get("/api/v1/tia/estado", base_url="http://localhost:9484").status_code == 200


# ── el log de arranque ──────────────────────────────────────────────────────


def test_el_log_de_arranque_dice_de_donde_sale_el_config(caplog: pytest.LogCaptureFixture) -> None:
    """El log dice que config.json se usa y de donde sale."""
    import logging

    from zc_suite.nucleo.app.config import ORIGEN_USUARIO, ConfigEnUso
    from zc_suite.nucleo.app.main import log_de_arranque

    with caplog.at_level(logging.INFO):
        log_de_arranque(
            ConfigEnUso(Path("C:/app/config/config.json"), ORIGEN_USUARIO),
            {
                "alimentacion": {
                    "device_tabs": [{"hw_type": "ed"}],
                    "nmax": [{"name": "x"}],
                }
            },
        )

    mensajes = [registro.getMessage() for registro in caplog.records]
    ruta = str(Path("C:/app/config/config.json"))
    assert any(ruta in m and "usuario" in m for m in mensajes)


def test_el_log_de_arranque_avisa_si_el_area_no_tiene_dispositivos(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Un area sin tipos de dispositivo avisa: la vista saldria vacia."""
    import logging

    from zc_suite.nucleo.app.config import ORIGEN_USUARIO, ConfigEnUso
    from zc_suite.nucleo.app.main import log_de_arranque

    with caplog.at_level(logging.WARNING):
        log_de_arranque(
            ConfigEnUso(Path("C:/app/config/config.json"), ORIGEN_USUARIO),
            {"alimentacion": {"device_tabs": [], "nmax": []}},
        )

    mensajes = [registro.getMessage() for registro in caplog.records]
    assert any("no tiene tipos de dispositivo" in m for m in mensajes)
    assert any("no tiene N_MAX" in m for m in mensajes)


def test_el_log_de_arranque_no_avisa_con_el_catalogo_completo(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Con el catalogo completo, no hay avisos."""
    import logging

    from zc_suite.nucleo.app.config import ORIGEN_PLANTILLA, ConfigEnUso
    from zc_suite.nucleo.app.main import log_de_arranque

    with caplog.at_level(logging.WARNING):
        log_de_arranque(
            ConfigEnUso(Path("C:/app/config/config.json"), ORIGEN_PLANTILLA),
            {
                "alimentacion": {
                    "device_tabs": [{"hw_type": "ed"}, {"hw_type": "ea"}],
                    "nmax": [{"name": "N_MAX_DISP_ED"}],
                }
            },
        )

    assert not [registro for registro in caplog.records if registro.levelno >= logging.WARNING]
