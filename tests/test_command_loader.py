"""Tests del command loader del worker OT (PR 3).

Cubre ``core.infrastructure.tia.command_loader.load_extra_commands``:
  - Mockea el ``AreaRegistry`` con 2 specs: uno que aporta
    ``contributes_tia_commands`` y otro que no.
  - Verifica que solo se invoca el callable del spec que aporta.
  - Verifica que el registry vacío + lista de áreas vacía es no-op.
  - Test de integración: el ``AreaRegistry`` real con el área
    ``alimentacion`` registra los 6 ``update_disp_comments_db_*`` en
    el ``COMMAND_REGISTRY`` del worker (vía el import del módulo).

Estos tests sustituyen / complementan a
``test_disp_comment_handlers.py::test_handler_todos_los_hw_types_registrados``
que en PR 3 ya no comprueba entradas hardcoded sino aportadas por
el área al import.
"""
from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from core.application.area_registry import AreaRegistry, AreaSpec
from core.infrastructure.tia.command_loader import load_extra_commands


# ── 1. Registry vacío + lista de áreas vacía = no-op ────────────────────


def test_load_extra_commands_no_areas_no_op() -> None:
    """Con un ``AreaRegistry`` sin specs, ``load_extra_commands`` no falla
    y deja el registry como estaba.
    """
    registry: dict[str, Any] = {}
    with patch.object(AreaRegistry, "discover") as mock_discover:
        mock_discover.return_value.all.return_value = []
        load_extra_commands(registry)
    assert registry == {}, "Registry vacío + 0 áreas debe permanecer vacío"


# ── 2. Specs que aportan ────────────────────────────────────────────────


def test_load_extra_commands_merges_contributing_areas() -> None:
    """Specs con ``contributes_tia_commands`` se invocan con el registry."""
    sentinel = object()
    mock_register = MagicMock()
    spec_a = AreaSpec(
        id="area_a",
        label="Área A",
        contributes_tia_commands=mock_register,
    )
    with patch.object(AreaRegistry, "discover") as mock_discover:
        mock_discover.return_value.all.return_value = [spec_a]
        registry: dict[str, Any] = {"existing": sentinel}
        load_extra_commands(registry)
    # El callable se invoca exactamente una vez con el registry.
    mock_register.assert_called_once_with(registry)
    # Las entradas pre-existentes se preservan (el loader añade, no reemplaza).
    assert registry["existing"] is sentinel


# ── 3. Specs que NO aportan ─────────────────────────────────────────────


def test_load_extra_commands_skips_non_contributing_areas() -> None:
    """Specs con ``contributes_tia_commands=None`` se ignoran en silencio."""
    spec_no_contrib = AreaSpec(
        id="area_sin_tia",
        label="Área Sin TIA",
        contributes_tia_commands=None,
    )
    with patch.object(AreaRegistry, "discover") as mock_discover:
        mock_discover.return_value.all.return_value = [spec_no_contrib]
        registry: dict[str, Any] = {}
        load_extra_commands(registry)
    assert registry == {}, (
        "Specs sin contributes_tia_commands NO deben mutar el registry"
    )


def test_load_extra_commands_mixes_contributing_and_non_contributing() -> None:
    """Mezcla: solo los que aportan se invocan; los otros se ignoran."""
    mock_contrib = MagicMock()
    spec_a = AreaSpec(id="a", label="A", contributes_tia_commands=mock_contrib)
    spec_b = AreaSpec(id="b", label="B", contributes_tia_commands=None)
    spec_c = AreaSpec(id="c", label="C", contributes_tia_commands=mock_contrib)
    with patch.object(AreaRegistry, "discover") as mock_discover:
        mock_discover.return_value.all.return_value = [spec_a, spec_b, spec_c]
        registry: dict[str, Any] = {}
        load_extra_commands(registry)
    assert mock_contrib.call_count == 2, (
        "Las 2 specs contribuyentes deben ser invocadas exactamente una vez"
    )


# ── 4. Test de integración con el área real (alimentación) ──────────────


def test_load_extra_commands_alimentacion_registers_six_handlers() -> None:
    """El ``AreaRegistry`` real con el área de alimentación registra
    los 6 handlers ``update_disp_comments_db_*`` al ``COMMAND_REGISTRY``.

    Este test verifica el cableado completo:
      AreaSpec.contributes_tia_commands → extra_commands.register
        → COMMAND_REGISTRY["update_disp_comments_db_<hw>"]
    """
    from core.infrastructure.tia.worker_tia import COMMAND_REGISTRY

    expected_keys = {
        "update_disp_comments_db_ed",
        "update_disp_comments_db_ea",
        "update_disp_comments_db_sa",
        "update_disp_comments_db_v",
        "update_disp_comments_db_m",
        "update_disp_comments_db_m_vf",
    }
    for name in expected_keys:
        assert name in COMMAND_REGISTRY, (
            f"Falta handler {name!r} en COMMAND_REGISTRY del worker tras "
            f"el import. ¿Está cableado contributes_tia_commands en el "
            f"AREA_SPEC de areas/alimentacion/__init__.py?"
        )
        assert callable(COMMAND_REGISTRY[name]), (
            f"{name!r} debe ser callable (factory + handler)"
        )


def test_alimentacion_area_spec_has_tia_commands_hook() -> None:
    """El ``AREA_SPEC`` del área de alimentación expone un callable no-None
    en ``contributes_tia_commands`` (es lo que el loader busca).
    """
    from areas.alimentacion import AREA_SPEC

    assert isinstance(AREA_SPEC, AreaSpec)
    assert AREA_SPEC.contributes_tia_commands is not None, (
        "El área de alimentación debe cablear contributes_tia_commands "
        "para que el command loader del worker descubra los 6 handlers "
        "de comentarios por instancia."
    )
    assert callable(AREA_SPEC.contributes_tia_commands)
