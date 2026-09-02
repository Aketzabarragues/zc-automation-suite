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
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from core.infrastructure.config_manager import (
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
            "procesos": {
                "n_max_suffixes": {
                    "preal": "PREAL",
                    "pint":  "PINT",
                    "alm":   "ALM",
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


def test_get_proc_nmax_suffixes(cm: ConfigManager) -> None:
    """``get_proc_nmax_suffixes`` retorna el dict de sufijos del config.

    El nombre completo de la PlcUserConstant se computa en el caller
    como ``f"{proc.uid}_N_MAX_{suffix}"`` con cada sufijo de este dict.
    """
    suffixes = cm.get_proc_nmax_suffixes()
    assert suffixes == {
        "preal": "PREAL",
        "pint":  "PINT",
        "alm":   "ALM",
    }


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
    """Si falta ``global_config_table_name``, retorna ``""`` (genérico, PR 1).

    Antes de PR 1, retornaba ``"000_Config_Dispositivos"`` (default
    hardcoded de alimentación). Ahora es genérico: el área
    "alimentación" aporta su default vía
    ``contributes_config_defaults`` (cableado en PR 2).
    """
    minimal = {
        "departments": {
            "alimentacion": {"Dispositivos": {}},
        },
    }
    minimal_path = tmp_path / "minimal.json"
    minimal_path.write_text(json.dumps(minimal), encoding="utf-8")
    cm_minimal = ConfigManager(config_path=minimal_path)
    assert cm_minimal.get_global_config_table_name() == ""


def test_fallback_when_dispositivos_section_missing(tmp_path: Path) -> None:
    """Si falta la sección ``Dispositivos``, ``list_keys`` retorna []."""
    minimal = {"departments": {"alimentacion": {}}}
    minimal_path = tmp_path / "minimal.json"
    minimal_path.write_text(json.dumps(minimal), encoding="utf-8")
    cm_minimal = ConfigManager(config_path=minimal_path)
    assert cm_minimal.list_keys() == []


def test_fallback_when_tia_folders_missing(tmp_path: Path) -> None:
    """Si falta ``tia_folders``, retorna strings vacíos (genérico, PR 1).

    Antes de PR 1, retornaba ``"003_Procesos"`` / ``"2000_Dispositivos"`` /
    ``"000_Sistema"`` (defaults de alimentación). Ahora retorna ``""``.
    El área "alimentación" aporta los suyos vía
    ``contributes_config_defaults`` (cableado en PR 2).
    """
    minimal = {"departments": {"alimentacion": {"Dispositivos": {}}}}
    minimal_path = tmp_path / "minimal.json"
    minimal_path.write_text(json.dumps(minimal), encoding="utf-8")
    cm_minimal = ConfigManager(config_path=minimal_path)
    assert cm_minimal.get_tia_folder_proceso() == ""
    assert cm_minimal.get_tia_folder_dispositivos() == ""
    assert cm_minimal.get_tia_folder_nmax() == ""


def test_fallback_when_departments_block_missing(tmp_path: Path) -> None:
    """Si falta el bloque ``departments``, los getters usan defaults vacíos.

    Antes de PR 1, los getters usaban defaults de alimentación hardcoded
    (``"000_Config_Dispositivos"``, ``"2000_Dispositivos"``). Ahora son
    genéricos: retornan ``""`` (PR 1).
    """
    minimal_path = tmp_path / "no_depts.json"
    minimal_path.write_text("{}", encoding="utf-8")
    cm_minimal = ConfigManager(config_path=minimal_path)
    assert cm_minimal.get_global_config_table_name() == ""
    assert cm_minimal.get_tia_folder_dispositivos() == ""
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


# ────────────────────────────────────────────────────────────────────────
# Tests del hook apply_defaults y de la genericidad (PR 1)
# ────────────────────────────────────────────────────────────────────────


def test_n_max_catalog_missing_returns_empty(tmp_path: Path) -> None:
    """Sin ``n_max_catalog`` en el JSON, ``list_nmax_active()`` retorna ``[]``.

    Antes de PR 1, retornaba los 6 N_MAX legacy hardcoded
    (``N_MAX_DISP_ED/EA/SA/V/M/M_VF``). PR 1 los quita: ahora es
    genérico (``[]``). El área "alimentación" los aporta vía
    ``contributes_config_defaults`` (cableado en PR 2).
    """
    cfg = {
        "departments": {
            "alimentacion": {
                "global_config_table_name": "000_Config_Dispositivos",
                "tia_folders": {"nmax": "000_Sistema"},
                "Dispositivos": {"ed": {"db_name": "DB2000_ED"}},
            },
        },
    }
    path = tmp_path / "no_nmax.json"
    path.write_text(json.dumps(cfg), encoding="utf-8")
    cm = ConfigManager(config_path=path)
    assert cm.list_nmax_active() == []
    assert cm.get_nmax_for_hw_type("ed") is None


def test_apply_defaults_no_op_when_no_areas_registered(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Si no hay áreas en ``AreaRegistry``, ``apply_defaults`` es no-op.

    El hook delega en las áreas registradas. Mockeamos el ``AreaRegistry``
    para que retorne una lista vacía y verificamos que ``apply_defaults``
    no muta el config. Esto es lo que permite que un config mínimo
    siga funcionando sin warnings nuevos cuando aún no hay áreas
    registradas (p. ej. en un proyecto in-progress).

    Antes de PR 2, el registry estaba vacío por defecto (no había
    áreas). Tras PR 2, el área "alimentación" se autoregistra y aporta
    sus defaults; este test verifica el comportamiento defensivo de
    ``apply_defaults`` cuando se enmascara el registry.
    """
    path = tmp_path / "minimal.json"
    path.write_text(json.dumps(_FULL_CONFIG), encoding="utf-8")
    cm = ConfigManager(config_path=path)

    # Mock del AreaRegistry para que devuelva una lista vacía de specs
    # (simula "no hay áreas registradas" — back-compat con PR 1).
    import core.application.area_registry as ar_mod
    fake_registry = MagicMock()
    fake_registry.all.return_value = []
    monkeypatch.setattr(
        ar_mod.AreaRegistry, "discover",
        classmethod(lambda cls: fake_registry),
    )

    # Snapshot del estado actual (idéntico al JSON).
    pre_keys = sorted(cm.list_nmax_active())
    cm.apply_defaults()  # no-op (registry vacío)
    post_keys = sorted(cm.list_nmax_active())
    assert pre_keys == post_keys


def test_apply_defaults_invokes_area_callback(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``apply_defaults`` invoca ``contributes_config_defaults`` de cada
    ``AreaSpec`` registrada, pasándole el ``dept_cfg`` mutable.

    Mockeamos ``AreaRegistry.discover()`` para devolver una spec con
    un callback espía. Verificamos que el callback se llama con el
    ``dept_cfg`` del departamento activo, y que si el callback muta
    el dict, el cambio se refleja en el ``ConfigManager``.
    """
    path = tmp_path / "minimal.json"
    path.write_text(json.dumps(_FULL_CONFIG), encoding="utf-8")
    cm = ConfigManager(config_path=path)

    # Mock del callback del área.
    mock_callback = MagicMock()
    def fake_defaults(dept_cfg: dict[str, Any]) -> None:
        # Simula que el área "alimentación" añade el catálogo N_MAX
        # legacy si no está presente.
        dept_cfg.setdefault(
            "n_max_catalog",
            [{"name": "N_MAX_DISP_ED", "hw_type": "ed"}],
        )
    mock_callback.side_effect = fake_defaults

    fake_spec = MagicMock()
    fake_spec.id = "alimentacion"
    fake_spec.contributes_config_defaults = mock_callback
    fake_registry = MagicMock()
    fake_registry.all.return_value = [fake_spec]

    # Monkeypatch del AreaRegistry.discover (clase method).
    import core.application.area_registry as ar_mod
    monkeypatch.setattr(ar_mod.AreaRegistry, "discover", classmethod(lambda cls: fake_registry))

    cm.apply_defaults()
    mock_callback.assert_called_once()
    # El kwarg dept_cfg debe ser el department_config mutable.
    call_kwargs = mock_callback.call_args.kwargs
    assert "dept_cfg" in call_kwargs
    assert call_kwargs["dept_cfg"] is cm._department_config  # noqa: SLF001


def test_apply_defaults_adds_missing_keys_via_callback(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Si el callback del área añade claves ausentes, ``list_nmax_active``
    las refleja (data-driven: el área aporta su catálogo por defecto).
    """
    # Config SIN n_max_catalog.
    cfg = {
        "departments": {
            "alimentacion": {
                "Dispositivos": {"ed": {"db_name": "DB_ED"}},
            },
        },
    }
    path = tmp_path / "no_nmax.json"
    path.write_text(json.dumps(cfg), encoding="utf-8")
    cm = ConfigManager(config_path=path)
    assert cm.list_nmax_active() == []

    # Mock que añade los 6 N_MAX legacy (lo que el área alimentación
    # hará realmente en PR 2).
    def fake_defaults(dept_cfg: dict[str, Any]) -> None:
        if "n_max_catalog" not in dept_cfg:
            dept_cfg["n_max_catalog"] = [
                {"name": f"N_MAX_DISP_{hw.upper()}", "hw_type": hw}
                for hw in ("ed", "ea", "sa", "v", "m", "m_vf")
            ]
    fake_spec = MagicMock()
    fake_spec.id = "alimentacion"
    fake_spec.contributes_config_defaults = fake_defaults
    fake_registry = MagicMock()
    fake_registry.all.return_value = [fake_spec]

    import core.application.area_registry as ar_mod
    monkeypatch.setattr(ar_mod.AreaRegistry, "discover", classmethod(lambda cls: fake_registry))

    cm.apply_defaults()
    # Ahora el catálogo se ha poblado (6 entradas como antes de PR 1).
    assert len(cm.list_nmax_active()) == 6
    assert "N_MAX_DISP_ED" in cm.list_nmax_active()
    assert "N_MAX_DISP_M_VF" in cm.list_nmax_active()
