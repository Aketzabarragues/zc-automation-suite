"""Tests del shell MCP (``core.interfaces.mcp_server``).

Cubre PR 6:
  - El shell registra las tools genéricas del gateway.
  - El shell agrega las tools aportadas por las áreas vía
    ``AreaRegistry.discover().for_each("contributes_mcp_tools", ...)``.
  - ``get_mcp_deps()`` devuelve el dict poblado por ``create_mcp_server``.

Nota: en este repo el shell registra 22 tools genéricas (el plan PR 6
mencionaba 28; el conteo real tras auditoría es 22). Los tests se
ciñen al conteo real.
"""
from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import MagicMock

import pytest

from core.infrastructure.gateway import TIAProcessGateway
from core.interfaces import mcp_server
from core.interfaces.mcp_server import (
    create_mcp_server,
    get_mcp_deps,
)


# ── Fixtures ───────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _reset_mcp_deps() -> None:
    """Resetea el dict módulo-level ``_deps`` antes de cada test.

    El shell mantiene ``_deps`` como Singleton a nivel de módulo
    (es la forma de pasarlo a las tools del área sin DI explícita).
    Como los tests pueden ejecutarse en cualquier orden, forzamos
    estado limpio antes de cada uno para no contaminar aserciones.
    """
    mcp_server._deps = {}


# ── Helpers ────────────────────────────────────────────────────────────


def _list_tool_names(mcp: Any) -> list[str]:
    """Devuelve los nombres de las tools registradas en el FastMCP.

    FastMCP expone ``list_tools()`` como coroutine que devuelve una
    secuencia de objetos ``Tool`` con atributo ``.name``. Lo
    ejecutamos aquí con ``asyncio.run`` para mantener la API del
    test síncrona.
    """
    tools = asyncio.run(mcp.list_tools())
    return sorted(t.name for t in tools)


# ── Tests ──────────────────────────────────────────────────────────────


def test_mcp_shell_registers_generic_tools() -> None:
    """El shell registra las 22 tools genéricas del gateway."""
    mcp = create_mcp_server(MagicMock(spec=TIAProcessGateway))

    names = _list_tool_names(mcp)
    generic_tools = [
        "tia_attach_portal",
        "tia_open_new_portal",
        "tia_open_project",
        "tia_save_project",
        "tia_close_project",
        "tia_list_plcs",
        "tia_list_blocks",
        "tia_compile_plc",
        "tia_export_blocks_sd",
        "tia_export_udts_sd",
        "tia_export_plc_tags_xml",
        "tia_import_blocks_sd",
        "tia_import_plc_tags_xml",
        "tia_export_block",
        "tia_import_block",
        "tia_export_tag_table",
        "tia_import_tag_table",
        "tia_get_user_constants",
        "tia_update_user_constant_value",
        "tia_update_user_constant_name",
        "tia_delete_user_constant",
        "tia_execute_transactional_batch",
    ]
    assert len(generic_tools) == 22, (
        "Si añades/eliminas tools genéricas del shell, actualiza este assert."
    )
    for expected in generic_tools:
        assert expected in names, (
            f"Tool genérica esperada no registrada: {expected!r}"
        )


def test_mcp_shell_with_area_registers_4_area_tools() -> None:
    """Con el AreaRegistry discover'd (alimentación), se registran 22 + 4 = 26 tools."""
    mcp = create_mcp_server(MagicMock(spec=TIAProcessGateway))

    names = _list_tool_names(mcp)
    # El área de alimentación aporta exactamente 4 tools MCP.
    area_tools = {
        "tia_sync_disp_preview",
        "tia_sync_disp_commit",
        "tia_apply_disp_comentarios",
        "tia_upload_excel",
    }
    for expected in area_tools:
        assert expected in names, (
            f"Tool del área esperada no registrada: {expected!r}"
        )
    # Total: 22 genéricas + 4 del área = 26.
    assert len(names) == 26, (
        f"Esperaba 26 tools (22 genéricas + 4 del área), obtuve {len(names)}: "
        f"{names}"
    )


def test_mcp_get_mcp_deps_returns_expected_dict() -> None:
    """``get_mcp_deps()`` devuelve un dict con las 4 claves tras arrancar el shell.

    Antes de ``create_mcp_server``, el dict está vacío (modo lazy).
    Tras ``create_mcp_server``, contiene las 4 deps inyectadas.
    """
    # Antes: vacío.
    assert get_mcp_deps() == {}

    create_mcp_server(MagicMock(spec=TIAProcessGateway))

    # Tras: 4 claves garantizadas por el shell.
    deps = get_mcp_deps()
    assert "gateway" in deps
    assert "config_manager" in deps
    assert "app_state" in deps
    assert "logger" in deps
    # El gateway inyectado es el mock que pasamos.
    assert isinstance(deps["gateway"], MagicMock)


def test_mcp_get_mcp_deps_module_dict_is_singleton() -> None:
    """``get_mcp_deps()`` devuelve siempre el mismo dict (módulo-level)."""
    create_mcp_server(MagicMock(spec=TIAProcessGateway))
    first = mcp_server._deps
    second = get_mcp_deps()
    assert first is second
    assert first is mcp_server._deps
