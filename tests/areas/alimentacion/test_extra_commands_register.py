"""Smoke test del register() del area alimentacion.

El area aporta handlers ``(portal, ts, args) -> result`` que internamente
operan sobre el .NET wrapper y el modulo siemens. Solo verificamos:
  1. Que register_main() acepte un tia_client (no un dict).
  2. Que registre TODOS los comandos esperados (6 hw_types + 3 proc_kinds).
  3. Que los handlers registrados tengan firma ``(args, tia_client) -> dict``.

No testeamos la logica interna (export/import SD, modificadores de
comentarios) â€” eso esta cubierto por tests del area.
"""
from __future__ import annotations

from unittest.mock import MagicMock

from areas.alimentacion.helpers.tia.tia_extra_commands import (
    EXTRA_HW_TYPES,
    EXTRA_PROC_KINDS,
    register,
    register_main,
)
from core.infrastructure.tia_client import SyncTIAClient


def _fresh_client():
    return SyncTIAClient()


def test_register_main_accepts_tia_client():
    """register_main(tia_client) funciona; no requiere dict."""
    client = _fresh_client()
    register_main(client)
    assert len(client.registered_commands()) > 0


def test_register_main_registers_all_disp_commands_per_hw_type():
    """6 comandos update_disp_comments_db_<hw> (uno por hw_type)."""
    client = _fresh_client()
    register_main(client)
    for hw in EXTRA_HW_TYPES:
        cmd = f"update_disp_comments_db_{hw}"
        assert client.has_command(cmd), f"missing: {cmd}"


def test_register_main_registers_all_proc_commands_per_kind():
    """3 comandos update_proc_comments_db_<kind> (uno por kind)."""
    client = _fresh_client()
    register_main(client)
    for kind in EXTRA_PROC_KINDS:
        cmd = f"update_proc_comments_db_{kind}"
        assert client.has_command(cmd), f"missing: {cmd}"


def test_register_main_registers_proc_param_combined_handler():
    client = _fresh_client()
    register_main(client)
    assert client.has_command("update_proc_comments_db_param")


def test_register_main_registers_online_and_offline_commit_handlers():
    client = _fresh_client()
    register_main(client)
    assert client.has_command("commit_user_constants_online")
    assert client.has_command("commit_disp_devices_offline")


def test_register_main_keeps_deprecated_commit_devices_sync_for_compat():
    """El handler deprecated se mantiene por compat con callers legacy."""
    client = _fresh_client()
    register_main(client)
    assert client.has_command("commit_devices_sync")


def test_register_main_total_count_is_consistent():
    """Suma verificada: 6 disp + 3 proc + 1 param + 3 commit = 13."""
    client = _fresh_client()
    register_main(client)
    expected = (
        len(EXTRA_HW_TYPES)
        + len(EXTRA_PROC_KINDS)
        + 1
        + 3
    )
    assert len(client.registered_commands()) == expected


def test_registered_handlers_have_main_signature():
    """Handlers registrados aceptan (args, tia_client) -> dict."""
    client = _fresh_client()
    register_main(client)

    cmd = "update_disp_comments_db_ed"
    assert client.has_command(cmd)

    import inspect
    handler = client._handlers[cmd]
    sig = inspect.signature(handler)
    params = list(sig.parameters.keys())
    assert params == ["args", "tia_client"], (
        f"handler signature deberia ser (args, tia_client); got {params}"
    )


def test_legacy_register_dict_still_works_for_worker_tia():
    """register(registry) legacy (worker_tia) sigue funcionando.

    worker_tia.py sigue vivo hasta Fase 4.6.1; su COMMAND_REGISTRY es
    un dict plano. register(registry) muta ese dict.
    """
    registry: dict = {}
    register(registry)
    for hw in EXTRA_HW_TYPES:
        cmd = f"update_disp_comments_db_{hw}"
        assert cmd in registry, f"missing legacy: {cmd}"
        assert callable(registry[cmd])
