"""Tests de la configuracion: rutas, copia de la plantilla y validacion."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import pytest

from zc_suite.nucleo.app.config import (
    Config,
    ConfigEnUso,
    ConfigError,
    areas_registradas_faltantes,
    cargar_config,
    config_incompatible,
    escribir_config,
    estado_config,
    resolve_config_path,
    ruta_plantilla,
)

RAIZ = Path(__file__).resolve().parents[3]


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
        json.dumps({"areas": {"alimentacion": {"tabla_nmax": "PLANTILLA"}}}),
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
    copia = json.loads(destino.read_text(encoding="utf-8"))
    assert copia["areas"]["alimentacion"]["tabla_nmax"] == "PLANTILLA"


def test_el_config_del_usuario_manda_siempre(congelado: Path) -> None:
    destino = resolve_config_path()
    destino.write_text(
        json.dumps({"areas": {"alimentacion": {"tabla_nmax": "EL_MIO"}}}),
        encoding="utf-8",
    )

    assert resolve_config_path() == destino
    copia = json.loads(destino.read_text(encoding="utf-8"))
    assert copia["areas"]["alimentacion"]["tabla_nmax"] == "EL_MIO"


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

    monkeypatch.setattr("zc_suite.nucleo.app.config.shutil.copy2", _falla)

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
    assert "alimentacion" in config.areas


def test_la_plantilla_no_lleva_rutas_de_la_maquina_del_operario() -> None:
    """La plantilla es portable: no lleva rutas absolutas ni el Excel."""
    config = cargar_config(RAIZ / "config" / "config.json")
    seccion = config.areas["alimentacion"]

    assert "excel" not in seccion
    assert "plantillas_path" not in seccion
    assert seccion["plantillas_procesos"] == ""


def test_un_config_valido_se_carga(tmp_path: Path) -> None:
    ruta = tmp_path / "config.json"
    ruta.write_text(
        json.dumps(
            {
                "areas": {
                    "alimentacion": {
                        "tabla_nmax": "0_Config",
                        "plantillas_procesos": "plantillas",
                    }
                },
            }
        ),
        encoding="utf-8",
    )

    config = cargar_config(ruta)

    assert config.areas["alimentacion"]["tabla_nmax"] == "0_Config"
    assert config.areas["alimentacion"]["plantillas_procesos"] == "plantillas"


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
    ruta.write_text(json.dumps({"areas": {"alimentacion": "no es una seccion"}}), encoding="utf-8")

    with pytest.raises(ConfigError, match="esquema"):
        cargar_config(ruta)


def test_una_config_vacia_usa_los_valores_por_defecto(tmp_path: Path) -> None:
    ruta = tmp_path / "config.json"
    ruta.write_text("{}", encoding="utf-8")

    config = cargar_config(ruta)

    assert config.areas == {}
    assert config.paths.model_dump() == {}


def test_un_config_con_bom_no_tumba_la_app(tmp_path: Path) -> None:
    """Hay editores que guardan con BOM: el config se lee igual."""
    ruta = tmp_path / "config.json"
    ruta.write_bytes(
        b"\xef\xbb\xbf"
        + json.dumps({"areas": {"alimentacion": {"tabla_nmax": "0_Config"}}}).encode()
    )

    config = cargar_config(ruta)

    assert config.areas["alimentacion"]["tabla_nmax"] == "0_Config"


# ── escritura atomica ──────────────────────────────────────────────────────


def test_escribir_config_guarda_los_datos_sin_bom(tmp_path: Path) -> None:
    """El fichero resulta un JSON valido, sin BOM, terminado en salto de linea."""
    ruta = tmp_path / "config.json"
    datos = {"areas": {"alimentacion": {"plantillas_procesos": "C:\\plantillas"}}}

    escribir_config(ruta, datos)

    assert ruta.read_bytes()[:3] != b"\xef\xbb\xbf"
    assert json.loads(ruta.read_text(encoding="utf-8")) == datos
    assert not (tmp_path / "config.json.tmp").exists()


def test_escribir_config_sobre_fichero_existente_lo_sustituye(tmp_path: Path) -> None:
    """El ``os.replace`` sustituye el fichero: no queda nada suelto."""
    ruta = tmp_path / "config.json"
    ruta.write_text(json.dumps({"areas": {}}), encoding="utf-8")

    escribir_config(ruta, {"areas": {"alimentacion": {"a": 1}}})

    assert json.loads(ruta.read_text(encoding="utf-8")) == {
        "areas": {"alimentacion": {"a": 1}}
    }
    assert not (tmp_path / "config.json.tmp").exists()


def test_escribir_config_con_carpeta_inexistente_lanza_config_error(
    tmp_path: Path,
) -> None:
    """La carpeta no existe (no escribible): ``ConfigError`` con la ruta,
    y el ``.tmp`` no queda suelto."""
    ruta = tmp_path / "no_existe" / "config.json"

    with pytest.raises(ConfigError, match="No se pudo escribir"):
        escribir_config(ruta, {"areas": {}})

    assert not (tmp_path / "no_existe" / "config.json.tmp").exists()


def test_escribir_config_con_error_de_sistema_lanza_config_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Un fallo de escritura (permisos, disco lleno): ``ConfigError`` con
    la causa y el ``.tmp`` se limpia."""
    ruta = tmp_path / "config.json"

    def _falla(*args: Any, **kwargs: Any) -> None:
        raise OSError(28, "No space left on device")

    monkeypatch.setattr("zc_suite.nucleo.app.config.os.replace", _falla)

    with pytest.raises(ConfigError, match="No se pudo escribir"):
        escribir_config(ruta, {"areas": {}})

    assert not (tmp_path / "config.json.tmp").exists()
    assert not ruta.exists()


# ── secciones de area ──────────────────────────────────────────────────────


def test_la_seccion_del_area_mezcla_defaults_y_usuario() -> None:
    config = Config.model_validate(
        {"areas": {"alimentacion": {"tabla_nmax": "el mio", "extra": 1}}}
    )

    seccion = config.seccion_area(
        "alimentacion",
        {"tabla_nmax": "por defecto", "carpetas_tia": {"dispositivos": "2000"}},
    )

    assert seccion["tabla_nmax"] == "el mio"
    assert seccion["extra"] == 1
    assert seccion["carpetas_tia"] == {"dispositivos": "2000"}


def test_un_area_sin_configuracion_usa_los_defaults() -> None:
    config = Config.model_validate({})

    seccion = config.seccion_area("alimentacion", {"carpetas_tia": {"dispositivos": "2000"}})

    assert seccion == {"carpetas_tia": {"dispositivos": "2000"}}


def test_la_seccion_devuelta_no_altera_la_configuracion() -> None:
    config = Config.model_validate({"areas": {"a": {"x": 1}}})

    seccion = config.seccion_area("a", {"y": 2})
    seccion["x"] = 99

    assert config.areas["a"]["x"] == 1


# ── config incompatible ─────────────────────────────────────────────────────


def test_un_config_sin_areas_es_incompatible() -> None:
    """Sin la seccion 'areas' el config es de otra version: no vale."""
    config = Config.model_validate({})

    motivo = config_incompatible(config, ["alimentacion"])

    assert motivo is not None
    assert "areas" in motivo


def test_un_config_sin_el_area_registrada_es_incompatible() -> None:
    """Le falta la seccion de un area registrada: el config no vale."""
    config = Config.model_validate({"areas": {"otro_area": {}}})

    motivo = config_incompatible(config, ["alimentacion"])

    assert motivo is not None
    assert "alimentacion" in motivo


def test_un_config_con_el_area_registrada_sirve() -> None:
    config = Config.model_validate({"areas": {"alimentacion": {}}})

    assert config_incompatible(config, ["alimentacion"]) is None


def test_el_motivo_dice_que_no_se_sustituye() -> None:
    """El aviso tiene que decir que el config del operario no se toca."""
    config = Config.model_validate({})

    motivo = config_incompatible(config, ["alimentacion"])

    assert motivo is not None
    assert "No se sustituye" in motivo


def test_las_areas_registradas_faltantes_se_listan() -> None:
    config = Config.model_validate({"areas": {"alimentacion": {}}})

    assert areas_registradas_faltantes(config, ["alimentacion", "entidades"]) == ["entidades"]


def test_el_estado_de_la_config_dice_de_donde_sale() -> None:
    config = Config.model_validate({"areas": {"alimentacion": {}}})
    config_en_uso = ConfigEnUso(ruta=Path("C:/app/config/config.json"), origen="usuario")

    estado = estado_config(config, config_en_uso, ["alimentacion"])

    assert estado["ruta"] == str(Path("C:/app/config/config.json"))
    assert estado["origen"] == "usuario"
    assert estado["incompatible"] is False
    assert estado["motivo"] is None
