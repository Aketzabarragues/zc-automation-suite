"""Tests para ``ConfigManager`` y ``DispositivoTIAConfig``.

Tests OFFLINE (no requieren TIA Portal). Crean un config.json de
fixture en un directorio temporal y verifican que el ConfigManager:
  - Carga correctamente el archivo JSON con la nueva estructura
    multi-departamento ``departments.<dept>.{...}``.
  - Resuelve correctamente el departamento activo.
  - Expone getters tipados para cada tipo de dispositivo.
  - Retorna None silencioso + warning cuando un tipo no existe.
  - Mantiene fallbacks defensivos si faltan claves.
  - Lista correctamente los keys configurados.
  - Mantiene los aliases deprecados (``get_hardware_config``,
    ``list_hw_types``, ``HardwareTIAConfig``) por una release.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

import pytest

from infrastructure.config_manager import (
    ConfigManager,
    DispositivoTIAConfig,
)


# ────────────────────────────────────────────────────────────────────────
# Fixture: config.json completo (6 tipos) en tmp_path
# ────────────────────────────────────────────────────────────────────────

_FULL_CONFIG = {
    "_comment": "Test fixture",
    "departments": {
        "alimentacion": {
            "global_config_table_name": "000_Config_Dispositivos",
            "tia_folders": {
                "proceso":      "003_Procesos",
                "dispositivos": "2000_Dispositivos",
                "nmax":         "000_Sistema",
            },
            "Dispositivos": {
                "ed": {
                    "db_name":       "DB2000_ED",
                    "db_array_name": "ED",
                    "tag_table":     "2000_Disp_ED",
                    "config_table":  "000_Config_Dispositivos",
                },
                "ea": {
                    "db_name":       "DB2001_EA",
                    "db_array_name": "EA",
                    "tag_table":     "2000_Disp_EA",
                    "config_table":  "000_Config_Dispositivos",
                },
                "sa": {
                    "db_name":       "DB2006_SA",
                    "db_array_name": "SA",
                    "tag_table":     "2000_Disp_SA",
                    "config_table":  "000_Config_Dispositivos",
                },
                "v": {
                    "db_name":       "DB2010_V",
                    "db_array_name": "V",
                    "tag_table":     "2000_Disp_V",
                    "config_table":  "000_Config_Dispositivos",
                },
                "m": {
                    "db_name":       "DB2015_M",
                    "db_array_name": "M",
                    "tag_table":     "2000_Disp_M",
                    "config_table":  "000_Config_Dispositivos",
                },
                "m_vf": {
                    "db_name":       "DB2016_M_VF",
                    "db_array_name": "M_VF",
                    "tag_table":     "2000_Disp_M_VF",
                    "config_table":  "000_Config_Dispositivos",
                },
            },
        },
    },
}


@pytest.fixture
def cm(tmp_path: Path) -> ConfigManager:
    """Crea un config.json completo en tmp_path y devuelve el ConfigManager."""
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps(_FULL_CONFIG), encoding="utf-8")
    return ConfigManager(config_path=config_path)


# ────────────────────────────────────────────────────────────────────────
# Tests de carga
# ────────────────────────────────────────────────────────────────────────


def test_load_full_config(cm: ConfigManager) -> None:
    """Carga correctamente el archivo JSON completo."""
    assert cm.department == "alimentacion"
    assert cm.get_global_config_table_name() == "000_Config_Dispositivos"


def test_load_raises_when_file_missing(tmp_path: Path) -> None:
    """Si el archivo no existe, lanza FileNotFoundError."""
    with pytest.raises(FileNotFoundError, match="No se encontr"):
        ConfigManager(config_path=tmp_path / "nope.json")


# ────────────────────────────────────────────────────────────────────────
# Tests de departamento
# ────────────────────────────────────────────────────────────────────────


def test_default_department_is_alimentacion(tmp_path: Path) -> None:
    """El departamento por defecto es ``alimentacion``."""
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps(_FULL_CONFIG), encoding="utf-8")
    cm_default = ConfigManager(config_path=config_path)
    assert cm_default.department == "alimentacion"


def test_explicit_department(tmp_path: Path) -> None:
    """Se puede instanciar apuntando a un departamento explícito."""
    multi = {
        "departments": {
            "alimentacion": _FULL_CONFIG["departments"]["alimentacion"],
            "envasado": {
                "global_config_table_name": "000_Config_Envasado",
                "tia_folders": {"dispositivos": "3000_Envasado"},
                "Dispositivos": {
                    "ev1": {
                        "db_name": "DB3000_EV1",
                        "db_array_name": "EV1",
                        "tag_table": "3000_Disp_EV1",
                        "config_table": "000_Config_Envasado",
                    },
                },
            },
        },
    }
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps(multi), encoding="utf-8")
    cm_env = ConfigManager(config_path=config_path, department="envasado")
    assert cm_env.department == "envasado"
    assert cm_env.get_global_config_table_name() == "000_Config_Envasado"
    assert cm_env.get_tag_table_name("ev1") == "3000_Disp_EV1"
    # El alimentacion sigue accesible solo con su propio ConfigManager.
    assert cm_env.get_tag_table_name("ed") is None


def test_unknown_department_falls_back_to_first(tmp_path: Path) -> None:
    """Si el departamento pedido no existe, se usa el primero disponible."""
    multi = {
        "departments": {
            "envasado": _FULL_CONFIG["departments"]["alimentacion"],
            "alimentacion": _FULL_CONFIG["departments"]["alimentacion"],
        },
    }
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps(multi), encoding="utf-8")
    cm = ConfigManager(config_path=config_path, department="no_existe")
    # Fallback: primer departamento disponible.
    assert cm.department == "envasado"


# ────────────────────────────────────────────────────────────────────────
# Tests de la tabla global N_MAX
# ────────────────────────────────────────────────────────────────────────


def test_get_global_config_table_name(cm: ConfigManager) -> None:
    assert cm.get_global_config_table_name() == "000_Config_Dispositivos"


# ────────────────────────────────────────────────────────────────────────
# Tests de configuración por tipo de dispositivo
# ────────────────────────────────────────────────────────────────────────


def test_get_dispositivo_config_ed(cm: ConfigManager) -> None:
    """``get_dispositivo_config('ed')`` retorna el dataclass correcto."""
    cfg = cm.get_dispositivo_config("ed")
    assert cfg is not None
    assert isinstance(cfg, DispositivoTIAConfig)
    assert cfg.key == "ed"
    assert cfg.db_name == "DB2000_ED"
    assert cfg.db_array_name == "ED"
    assert cfg.tag_table == "2000_Disp_ED"
    assert cfg.config_table == "000_Config_Dispositivos"


def test_get_dispositivo_config_all_types(cm: ConfigManager) -> None:
    """Los 6 tipos se resuelven correctamente."""
    for hw_type in ["ed", "ea", "sa", "v", "m", "m_vf"]:
        cfg = cm.get_dispositivo_config(hw_type)
        assert cfg is not None, f"Falla para {hw_type}"
        assert cfg.tag_table.startswith("2000_Disp_")


def test_get_dispositivo_config_unknown_returns_none(cm: ConfigManager) -> None:
    """Tipos no configurados retornan ``None`` (no raise)."""
    assert cm.get_dispositivo_config("sd") is None
    assert cm.get_dispositivo_config("m_sina") is None
    assert cm.get_dispositivo_config("tipo_imaginario") is None


def test_get_dispositivo_config_unknown_logs_warning(
    cm: ConfigManager, caplog: pytest.LogCaptureFixture
) -> None:
    """Los tipos desconocidos se loggean como warning (no raise)."""
    with caplog.at_level(logging.WARNING, logger="infrastructure.config_manager"):
        cfg = cm.get_dispositivo_config("inexistente")
    assert cfg is None
    assert any(
        "inexistente" in record.message for record in caplog.records
    )


def test_alias_get_hardware_config(cm: ConfigManager) -> None:
    """El alias deprecado ``get_hardware_config`` sigue funcionando."""
    cfg = cm.get_hardware_config("ed")
    assert cfg is not None
    assert cfg.tag_table == "2000_Disp_ED"


def test_alias_hardware_tia_config_class(cm: ConfigManager) -> None:
    """El alias de clase ``HardwareTIAConfig`` apunta a ``DispositivoTIAConfig``."""
    assert ConfigManager.HardwareTIAConfig is DispositivoTIAConfig


# ────────────────────────────────────────────────────────────────────────
# Tests de getters específicos
# ────────────────────────────────────────────────────────────────────────


def test_get_tag_table_name(cm: ConfigManager) -> None:
    assert cm.get_tag_table_name("ed") == "2000_Disp_ED"
    assert cm.get_tag_table_name("v") == "2000_Disp_V"
    assert cm.get_tag_table_name("m_vf") == "2000_Disp_M_VF"
    assert cm.get_tag_table_name("no_existe") is None


def test_get_db_name(cm: ConfigManager) -> None:
    assert cm.get_db_name("ed") == "DB2000_ED"
    assert cm.get_db_name("v") == "DB2010_V"
    assert cm.get_db_name("m_vf") == "DB2016_M_VF"
    assert cm.get_db_name("no_existe") is None


def test_get_db_array_name(cm: ConfigManager) -> None:
    assert cm.get_db_array_name("ed") == "ED"
    assert cm.get_db_array_name("v") == "V"
    assert cm.get_db_array_name("m_vf") == "M_VF"
    assert cm.get_db_array_name("no_existe") is None


def test_list_keys(cm: ConfigManager) -> None:
    """``list_keys`` retorna los 6 tipos configurados."""
    keys = cm.list_keys()
    assert sorted(keys) == ["ea", "ed", "m", "m_vf", "sa", "v"]


def test_alias_list_hw_types(cm: ConfigManager) -> None:
    """El alias deprecado ``list_hw_types`` sigue funcionando."""
    assert sorted(cm.list_hw_types()) == ["ea", "ed", "m", "m_vf", "sa", "v"]


# ────────────────────────────────────────────────────────────────────────
# Tests de carpetas TIA
# ────────────────────────────────────────────────────────────────────────


def test_get_tia_folder_proceso(cm: ConfigManager) -> None:
    assert cm.get_tia_folder_proceso() == "003_Procesos"


def test_get_tia_folder_dispositivos(cm: ConfigManager) -> None:
    """``get_tia_folder_dispositivos`` retorna la carpeta del config."""
    assert cm.get_tia_folder_dispositivos() == "2000_Dispositivos"


def test_get_tia_folder_nmax(cm: ConfigManager) -> None:
    """``get_tia_folder_nmax`` retorna la carpeta N_MAX del config."""
    assert cm.get_tia_folder_nmax() == "000_Sistema"


def test_get_tia_folder_nmax_explicit(tmp_path: Path) -> None:
    """Si ``tia_folders.nmax`` está explícito en el config, se respeta."""
    cfg = {
        "departments": {
            "alimentacion": {
                "tia_folders": {"nmax": "999_Custom_NMAX"},
                "Dispositivos": {},
            },
        },
    }
    path = tmp_path / "explicit.json"
    path.write_text(json.dumps(cfg), encoding="utf-8")
    cm = ConfigManager(config_path=path)
    assert cm.get_tia_folder_nmax() == "999_Custom_NMAX"


def test_get_tia_folder_dispositivos_canonical_key(tmp_path: Path) -> None:
    """Si el config solo usa ``tia_folders.dispositivos``, funciona."""
    cfg = {
        "departments": {
            "alimentacion": {
                "tia_folders": {"dispositivos": "8888_Nuevo_Nombre"},
                "Dispositivos": {},
            },
        },
    }
    path = tmp_path / "canonical.json"
    path.write_text(json.dumps(cfg), encoding="utf-8")
    cm = ConfigManager(config_path=path)
    assert cm.get_tia_folder_dispositivos() == "8888_Nuevo_Nombre"


# ────────────────────────────────────────────────────────────────────────
# Tests de fallbacks defensivos
# ────────────────────────────────────────────────────────────────────────


def test_fallback_when_global_config_table_missing(tmp_path: Path) -> None:
    """Si falta ``global_config_table_name``, retorna default."""
    minimal = {
        "departments": {
            "alimentacion": {"Dispositivos": {}},
        },
    }
    minimal_path = tmp_path / "minimal.json"
    minimal_path.write_text(json.dumps(minimal), encoding="utf-8")
    cm_minimal = ConfigManager(config_path=minimal_path)
    assert (
        cm_minimal.get_global_config_table_name()
        == "000_Config_Dispositivos"
    )


def test_fallback_when_dispositivos_section_missing(tmp_path: Path) -> None:
    """Si falta la sección ``Dispositivos``, ``list_keys`` retorna []."""
    minimal = {"departments": {"alimentacion": {}}}
    minimal_path = tmp_path / "minimal.json"
    minimal_path.write_text(json.dumps(minimal), encoding="utf-8")
    cm_minimal = ConfigManager(config_path=minimal_path)
    assert cm_minimal.list_keys() == []


def test_fallback_when_tia_folders_missing(tmp_path: Path) -> None:
    """Si falta ``tia_folders``, retorna defaults."""
    minimal = {"departments": {"alimentacion": {"Dispositivos": {}}}}
    minimal_path = tmp_path / "minimal.json"
    minimal_path.write_text(json.dumps(minimal), encoding="utf-8")
    cm_minimal = ConfigManager(config_path=minimal_path)
    assert cm_minimal.get_tia_folder_proceso() == "003_Procesos"
    assert cm_minimal.get_tia_folder_dispositivos() == "2000_Dispositivos"
    assert cm_minimal.get_tia_folder_nmax() == "000_Sistema"


def test_fallback_when_departments_block_missing(tmp_path: Path) -> None:
    """Si falta el bloque ``departments``, los getters usan defaults."""
    minimal_path = tmp_path / "no_depts.json"
    minimal_path.write_text("{}", encoding="utf-8")
    cm_minimal = ConfigManager(config_path=minimal_path)
    assert cm_minimal.get_global_config_table_name() == "000_Config_Dispositivos"
    assert cm_minimal.get_tia_folder_dispositivos() == "2000_Dispositivos"
    assert cm_minimal.list_keys() == []


def test_dispositivo_config_partial_fields(tmp_path: Path) -> None:
    """Si una entrada de Dispositivos tiene campos parciales, retorna los presentes."""
    partial = {
        "departments": {
            "alimentacion": {
                "Dispositivos": {
                    "ed": {
                        "db_name": "DB_ED",
                        # db_array_name, tag_table, config_table faltan
                    },
                },
            },
        },
    }
    partial_path = tmp_path / "partial.json"
    partial_path.write_text(json.dumps(partial), encoding="utf-8")
    cm_partial = ConfigManager(config_path=partial_path)
    cfg = cm_partial.get_dispositivo_config("ed")
    assert cfg is not None
    assert cfg.db_name == "DB_ED"
    assert cfg.db_array_name == ""  # default a string vacío
    assert cfg.tag_table == ""
    assert cfg.config_table == ""
