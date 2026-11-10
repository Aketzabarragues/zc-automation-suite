"""Tests de la configuracion: rutas, copia de la plantilla y validacion."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import pytest

from zc_suite.config import (
    Config,
    ConfigError,
    cargar_config,
    resolve_config_path,
    ruta_plantilla,
)

RAIZ = Path(__file__).resolve().parents[2]


@pytest.fixture
def congelado(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Any:
    """Simula una app empaquetada: ``_MEIPASS`` y ejecutable de mentira."""
    exe_dir = tmp_path / "instalacion"
    exe_dir.mkdir()
    ejecutable = exe_dir / "zc_automation_suite.exe"
    ejecutable.write_bytes(b"MZ")

    meipass = tmp_path / "meipass"
    (meipass / "config").mkdir(parents=True)
    plantilla = meipass / "config" / "config.json"
    plantilla.write_text(
        json.dumps({"tia": {"plc": "PLANTILLA"}, "areas": {}}),
        encoding="utf-8",
    )

    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(meipass), raising=False)
    monkeypatch.setattr(sys, "executable", str(ejecutable))
    return plantilla


# ── rutas ──────────────────────────────────────────────────────────────────


def test_en_desarrollo_la_plantilla_es_la_del_repo() -> None:
    assert ruta_plantilla() == RAIZ / "config" / "config.json"


def test_en_desarrollo_se_usa_el_config_del_repo(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ZC_CONFIG_DIR", raising=False)

    assert resolve_config_path() == RAIZ / "config" / "config.json"


def test_la_variable_de_entorno_manda(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ZC_CONFIG_DIR", str(tmp_path))

    assert resolve_config_path() == tmp_path / "config.json"


# ── copia de la plantilla ──────────────────────────────────────────────────


def test_en_empaquetado_se_copia_la_plantilla_junto_al_exe(congelado: Path) -> None:
    destino = resolve_config_path()

    assert destino.parent.name == "config"
    assert destino.parent.parent.name == "instalacion"
    assert destino.is_file()
    assert json.loads(destino.read_text(encoding="utf-8"))["tia"]["plc"] == "PLANTILLA"


def test_el_config_del_usuario_manda_siempre(congelado: Path) -> None:
    destino = resolve_config_path()
    destino.write_text(
        json.dumps({"tia": {"plc": "EL_MIO"}, "areas": {}}),
        encoding="utf-8",
    )

    assert resolve_config_path() == destino
    assert json.loads(destino.read_text(encoding="utf-8"))["tia"]["plc"] == "EL_MIO"


def test_un_config_invalido_no_se_pisa(congelado: Path) -> None:
    destino = resolve_config_path()
    destino.write_text("{esto no es json", encoding="utf-8")

    assert resolve_config_path() == destino
    assert destino.read_text(encoding="utf-8") == "{esto no es json"


def test_sin_permisos_se_usa_la_plantilla_en_solo_lectura(
    congelado: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _falla(*args: Any, **kwargs: Any) -> None:
        raise OSError("sin permisos")

    monkeypatch.setattr("zc_suite.config.shutil.copy2", _falla)

    assert resolve_config_path() == congelado


def test_sin_plantilla_ni_config_falla(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path / "vacio"), raising=False)
    monkeypatch.setattr(sys, "executable", str(tmp_path / "app.exe"))
    monkeypatch.delenv("ZC_CONFIG_DIR", raising=False)

    with pytest.raises(FileNotFoundError):
        resolve_config_path()


# ── validacion ─────────────────────────────────────────────────────────────


def test_la_plantilla_del_repo_es_valida() -> None:
    config = cargar_config(RAIZ / "config" / "config.json")

    assert isinstance(config, Config)
    assert config.tia.plc
    assert "alimentacion" in config.areas


def test_un_config_valido_se_carga(tmp_path: Path) -> None:
    ruta = tmp_path / "config.json"
    ruta.write_text(
        json.dumps(
            {
                "tia": {"plc": "PLC_1", "proyecto": ""},
                "paths": {"excel": "D:\\datos\\maestro.xlsm"},
                "areas": {"alimentacion": {"global_config_table_name": "0_Config"}},
            }
        ),
        encoding="utf-8",
    )

    config = cargar_config(ruta)

    assert config.tia.plc == "PLC_1"
    assert config.paths.excel == "D:\\datos\\maestro.xlsm"
    assert config.areas["alimentacion"]["global_config_table_name"] == "0_Config"


def test_un_config_que_no_es_json_falla(tmp_path: Path) -> None:
    ruta = tmp_path / "config.json"
    ruta.write_text("{no es json", encoding="utf-8")

    with pytest.raises(ConfigError, match="JSON valido"):
        cargar_config(ruta)


def test_un_config_inexistente_falla(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="No se encontro"):
        cargar_config(tmp_path / "no-existe.json")


def test_un_config_con_el_tipo_mal_falla(tmp_path: Path) -> None:
    ruta = tmp_path / "config.json"
    ruta.write_text(json.dumps({"tia": {"plc": 42}}), encoding="utf-8")

    with pytest.raises(ConfigError, match="esquema"):
        cargar_config(ruta)


def test_una_config_vacia_usa_los_valores_por_defecto(tmp_path: Path) -> None:
    ruta = tmp_path / "config.json"
    ruta.write_text("{}", encoding="utf-8")

    config = cargar_config(ruta)

    assert config.tia.plc == ""
    assert config.paths.excel == ""
    assert config.areas == {}


# ── secciones de area ──────────────────────────────────────────────────────


def test_la_seccion_del_area_mezcla_defaults_y_usuario() -> None:
    config = Config.model_validate(
        {"areas": {"alimentacion": {"plc": "el mio", "extra": 1}}}
    )

    seccion = config.seccion_area(
        "alimentacion",
        {"plc": "por defecto", "tia_folders": {"disp": "2000"}},
    )

    assert seccion["plc"] == "el mio"
    assert seccion["extra"] == 1
    assert seccion["tia_folders"] == {"disp": "2000"}


def test_un_area_sin_configuracion_usa_los_defaults() -> None:
    config = Config.model_validate({})

    seccion = config.seccion_area("alimentacion", {"tia_folders": {"disp": "2000"}})

    assert seccion == {"tia_folders": {"disp": "2000"}}


def test_la_seccion_devuelta_no_altera_la_configuracion() -> None:
    config = Config.model_validate({"areas": {"a": {"x": 1}}})

    seccion = config.seccion_area("a", {"y": 2})
    seccion["x"] = 99

    assert config.areas["a"]["x"] == 1
