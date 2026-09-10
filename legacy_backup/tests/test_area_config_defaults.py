"""Tests del extension point ``contributes_config_defaults`` (PR 2).

Cubre los defaults defensivos que el área de alimentación aporta
vía su ``AreaSpec.contributes_config_defaults``. Estos defaults
rellenan claves ausentes en el bloque ``departments["alimentacion"]``
del ``config.json`` (back-compat con configs mínimos que aún no
migraron a la versión con ``n_max_catalog``, carpetas TIA explícitas
y ``global_config_table_name``).

Política (ver ``areas/alimentacion/infrastructure/config_defaults.py``):
  - El callable ``install(dept_cfg, dept_id)`` solo muta el dict
    si ``dept_id == "alimentacion"``.
  - No sobrescribe claves ya presentes (defensa).
  - El área ``ConfigManager.apply_defaults`` invoca el callable
    pasándole ``(dept_cfg, dept_id)`` (PR 2). Antes de PR 2, la
    firma era solo ``(dept_cfg)``; para back-compat el core detecta
    la firma con ``inspect.signature``.
"""
from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest

from core.application.area_registry import AreaRegistry
from core.infrastructure.config_manager import ConfigManager


# ── Filtro por dept_id: la función es no-op para otros departamentos ──


def test_install_is_noop_for_other_departments() -> None:
    """``install`` ignora departamentos distintos de ``alimentacion``."""
    from areas.alimentacion.infrastructure.config_defaults import (
        install as alim_install,
    )

    dept_cfg: dict[str, Any] = {}  # vacío: nada que preservar.
    alim_install(dept_cfg, dept_id="envasado")
    # No añade nada: el dict sigue vacío.
    assert dept_cfg == {}


def test_install_pads_alimentacion_dept_with_nmax_catalog() -> None:
    """``install`` añade los 6 N_MAX legacy al bloque de alimentación."""
    from areas.alimentacion.infrastructure.config_defaults import (
        install as alim_install,
    )

    dept_cfg: dict[str, Any] = {}
    alim_install(dept_cfg, dept_id="alimentacion")
    assert "n_max_catalog" in dept_cfg
    names = {e["name"] for e in dept_cfg["n_max_catalog"]}
    assert names == {
        "N_MAX_DISP_ED", "N_MAX_DISP_EA", "N_MAX_DISP_SA",
        "N_MAX_DISP_V", "N_MAX_DISP_M", "N_MAX_DISP_M_VF",
    }


def test_install_pads_alimentacion_dept_with_tia_folders() -> None:
    """``install`` añade las 3 carpetas TIA por defecto."""
    from areas.alimentacion.infrastructure.config_defaults import (
        install as alim_install,
    )

    dept_cfg: dict[str, Any] = {}
    alim_install(dept_cfg, dept_id="alimentacion")
    folders = dept_cfg["tia_folders"]
    assert folders["proceso"] == "003_Procesos"
    assert folders["dispositivos"] == "2000_Dispositivos"
    assert folders["nmax"] == "000_Sistema"


def test_install_pads_alimentacion_dept_with_global_config_table() -> None:
    """``install`` añade el ``global_config_table_name`` por defecto."""
    from areas.alimentacion.infrastructure.config_defaults import (
        install as alim_install,
    )

    dept_cfg: dict[str, Any] = {}
    alim_install(dept_cfg, dept_id="alimentacion")
    assert dept_cfg["global_config_table_name"] == "000_Config_Dispositivos"


def test_install_does_not_overwrite_existing_keys() -> None:
    """``install`` no sobrescribe claves ya presentes en el JSON."""
    from areas.alimentacion.infrastructure.config_defaults import (
        install as alim_install,
    )

    dept_cfg: dict[str, Any] = {
        "global_config_table_name": "Tabla_Custom",
        "tia_folders": {
            "proceso": "999_Custom_Proceso",
        },
        "n_max_catalog": [{"name": "N_MAX_CUSTOM", "hw_type": "x"}],
    }
    alim_install(dept_cfg, dept_id="alimentacion")
    # Los valores pre-existentes se respetan (no se pisan).
    assert dept_cfg["global_config_table_name"] == "Tabla_Custom"
    assert dept_cfg["tia_folders"]["proceso"] == "999_Custom_Proceso"
    assert dept_cfg["n_max_catalog"] == [
        {"name": "N_MAX_CUSTOM", "hw_type": "x"}
    ]
    # Las carpetas que NO estaban se rellenan con defaults.
    assert dept_cfg["tia_folders"]["dispositivos"] == "2000_Dispositivos"
    assert dept_cfg["tia_folders"]["nmax"] == "000_Sistema"


# ── ConfigManager.apply_defaults invoca al área con (dept_cfg, dept_id) ──


def test_apply_defaults_invokes_area_with_dept_id_kwarg(
    tmp_path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``apply_defaults`` invoca el callable del área con
    ``(dept_cfg=dept_cfg, dept_id=self._department)``.

    Mockeamos el ``AreaRegistry`` para verificar la firma exacta
    de la llamada. Importante: usamos un callable REAL (no
    ``MagicMock``) para que ``inspect.signature`` detecte ``dept_id``
    en sus parámetros.
    """
    cfg = {
        "departments": {
            "alimentacion": {
                "Dispositivos": {"ed": {"db_name": "DB_ED"}},
            },
        },
    }
    import json
    path = tmp_path / "cfg.json"
    path.write_text(json.dumps(cfg), encoding="utf-8")
    cm = ConfigManager(config_path=path)

    received: dict[str, Any] = {}

    def real_callback(dept_cfg: dict[str, Any], dept_id: str) -> None:
        received["dept_cfg"] = dept_cfg
        received["dept_id"] = dept_id

    fake_spec = MagicMock()
    fake_spec.id = "alimentacion"
    fake_spec.contributes_config_defaults = real_callback
    fake_registry = MagicMock()
    fake_registry.all.return_value = [fake_spec]

    import core.application.area_registry as ar_mod
    monkeypatch.setattr(
        ar_mod.AreaRegistry, "discover",
        classmethod(lambda cls: fake_registry),
    )

    cm.apply_defaults()
    assert received == {
        "dept_cfg": cm._department_config,
        "dept_id": "alimentacion",
    }


def test_apply_defaults_legacy_callback_signature_still_works(
    tmp_path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``apply_defaults`` detecta la firma legacy ``(dept_cfg)`` y la
    llama sin ``dept_id`` para back-compat.
    """
    cfg = {
        "departments": {
            "alimentacion": {
                "Dispositivos": {"ed": {"db_name": "DB_ED"}},
            },
        },
    }
    import json
    path = tmp_path / "cfg.json"
    path.write_text(json.dumps(cfg), encoding="utf-8")
    cm = ConfigManager(config_path=path)

    # Callable legacy: solo toma ``dept_cfg``.
    def legacy_callback(dept_cfg: dict[str, Any]) -> None:
        pass

    mock_callback = MagicMock(side_effect=legacy_callback)
    fake_spec = MagicMock()
    fake_spec.id = "alimentacion"
    fake_spec.contributes_config_defaults = mock_callback
    fake_registry = MagicMock()
    fake_registry.all.return_value = [fake_spec]

    import core.application.area_registry as ar_mod
    monkeypatch.setattr(
        ar_mod.AreaRegistry, "discover",
        classmethod(lambda cls: fake_registry),
    )

    cm.apply_defaults()
    mock_callback.assert_called_once()
    kwargs = mock_callback.call_args.kwargs
    # Firma legacy: solo ``dept_cfg``, sin ``dept_id``.
    assert "dept_cfg" in kwargs
    assert "dept_id" not in kwargs
