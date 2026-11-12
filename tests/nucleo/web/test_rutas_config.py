"""Tests de la ruta del estado de la configuracion.

El ``config.json`` del operario manda siempre: si no vale (le falta la seccion
de un area registrada), la app lo dice y no lo sustituye.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from flask import Flask

from zc_suite.nucleo.app.config import Config, cargar_config
from zc_suite.nucleo.app.main import AREAS, montar_app
from zc_suite.nucleo.tia.eventos import BusEventos
from zc_suite.nucleo.tia.servicio import ServicioTIA

RAIZ = Path(__file__).resolve().parents[3]


class TsFalso:
    """Doble minimo del modulo ``siemens_tia_scripting``."""

    class Enums:
        class PortalMode:
            AnyUserInterface = "cualquier_interfaz"
            WithGraphicalUserInterface = "con_gui"
            WithoutGraphicalUserInterface = "sin_gui"

    def set_logging(self, path: str, console: bool) -> None:
        pass


def _app(config: Config) -> Flask:
    """La app montada con el config dado."""
    bus_eventos = BusEventos()
    servicio = ServicioTIA(publicador=bus_eventos.publicar, cargador=lambda: TsFalso())
    return montar_app(servicio, bus_eventos, config=config)


@pytest.fixture
def app() -> Flask:
    """La app con un config que vale: el del repo."""
    config = cargar_config(RAIZ / "config" / "config.json")
    return _app(config)


def _estado(cliente: Any) -> dict[str, Any]:
    """El estado de la configuracion que sirve la app."""
    respuesta = cliente.get("/api/v1/config", base_url="http://localhost:9484")
    assert respuesta.status_code == 200
    return respuesta.get_json()


def test_la_ruta_del_estado_de_la_config_esta_montada(app: Flask) -> None:
    reglas = {regla.rule for regla in app.url_map.iter_rules()}

    assert "/api/v1/config" in reglas


def test_un_config_que_sirve_no_avisa(app: Flask) -> None:
    """Con el area registrada en su sitio, no hay nada que avisar."""
    estado = _estado(app.test_client())

    assert estado["incompatible"] is False
    assert estado["motivo"] is None
    assert estado["areas_faltantes"] == []


def test_un_config_sin_la_seccion_areas_avisa() -> None:
    """Un config sin la seccion 'areas' es de otra version de la app."""
    config = Config.model_validate({})
    app = _app(config)

    estado = _estado(app.test_client())

    assert estado["incompatible"] is True
    assert "areas" in estado["motivo"]


def test_un_config_sin_el_area_registrada_avisa() -> None:
    """Le falta la seccion de un area registrada: el config no vale."""
    config = Config.model_validate({"areas": {"otro_area": {}}})
    app = _app(config)

    estado = _estado(app.test_client())

    assert estado["incompatible"] is True
    assert "alimentacion" in estado["motivo"]
    assert estado["areas_faltantes"] == ["alimentacion"]


def test_un_config_del_area_invalido_avisa() -> None:
    """El area dice que su seccion del config no vale: el banner lo enseña."""
    config = Config.model_validate({"areas": {"alimentacion": {"tabla_nmax": "0_Config"}}})
    app = _app(config)

    estado = _estado(app.test_client())

    assert estado["incompatible"] is True
    assert "no cumple el formato" in estado["motivo"]


def test_un_config_del_area_invalido_no_se_sustituye() -> None:
    """El config del operario manda: aunque su area no valga, no se toca."""
    config = Config.model_validate({"areas": {"alimentacion": {"tabla_nmax": "0_Config"}}})
    app = _app(config)

    estado = _estado(app.test_client())

    assert estado["ruta"]
    assert estado["areas_faltantes"] == []


def test_el_estado_dice_de_donde_sale_el_config(app: Flask) -> None:
    """El operario tiene que saber que fichero esta en uso."""
    estado = _estado(app.test_client())

    assert estado["ruta"]
    assert estado["origen"] in {"usuario", "copia", "plantilla", "entorno"}


def test_el_estado_avisa_de_todas_las_areas_registradas() -> None:
    """Cada area registrada tiene que estar en el config."""
    config = cargar_config(RAIZ / "config" / "config.json")
    app = _app(config)

    estado = _estado(app.test_client())

    assert len(AREAS) == 1
    assert estado["areas_faltantes"] == []


def test_el_config_incompatible_no_se_sustituye(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """El config del operario manda: aunque no valga, no se toca."""
    import json
    import sys

    exe_dir = tmp_path / "instalacion"
    (exe_dir / "config").mkdir(parents=True)
    ejecutable = exe_dir / "zc_automation_suite.exe"
    ejecutable.write_bytes(b"MZ")

    meipass = tmp_path / "meipass"
    (meipass / "config").mkdir(parents=True)
    (meipass / "config" / "config.json").write_text(
        json.dumps({"areas": {"alimentacion": {"tabla_nmax": "PLANTILLA"}}}),
        encoding="utf-8",
    )

    destino = exe_dir / "config" / "config.json"
    contenido = json.dumps({"areas": {"alimentacion": {"tabla_nmax": "DEL_OPERARIO"}}})
    destino.write_text(contenido, encoding="utf-8")

    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(meipass), raising=False)
    monkeypatch.setattr(sys, "executable", str(ejecutable))

    from zc_suite.nucleo.app.config import resolver_config

    config_en_uso = resolver_config()

    assert config_en_uso.ruta == destino
    assert config_en_uso.origen == "usuario"
    assert destino.read_text(encoding="utf-8") == contenido
