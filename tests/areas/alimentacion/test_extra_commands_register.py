"""Smoke test del register() del area alimentacion (Fase 4 / paso 4.1.3).

El area aporta handlers ``(portal, ts, args) -> result`` que internamente
operan sobre el .NET wrapper y el modulo siemens. Para OB1 (DA-014)
solo necesitamos:
  1. Que register() acepte un tia_client (no un dict).
  2. Que registre TODOS los comandos esperados (incluyendo los 6 hw_types
     y los 3 proc_kinds).
  3. Que los handlers registrados tengan firma ``(args, tia_client) -> dict``.

No testeamos la logica interna de los handlers (export/import SD,
modificadores de comentarios) — eso ya esta cubierto por tests
existentes del area en ``tests/areas/alimentacion/``. Aqui solo
verificamos el wiring OB1.
"""
from __future__ import annotations

from unittest.mock import MagicMock

from areas.alimentacion.infrastructure.tia.extra_commands import (
    EXTRA_HW_TYPES,
    EXTRA_PROC_KINDS,
    register,
    register_ob1,
)
from core.infrastructure.tia_client import SyncTIAClient


def _fresh_client():
    return SyncTIAClient()


def test_register_ob1_accepts_tia_client():
    """register_ob1(tia_client) funciona; no requiere dict."""
    client = _fresh_client()
    register_ob1(client)
    assert len(client.registered_commands()) > 0


def test_register_ob1_registers_all_disp_commands_per_hw_type():
    """6 comandos update_disp_comments_db_<hw> (uno por hw_type)."""
    client = _fresh_client()
    register_ob1(client)
    for hw in EXTRA_HW_TYPES:
        cmd = f"update_disp_comments_db_{hw}"
        assert client.has_command(cmd), f"missing: {cmd}"


def test_register_ob1_registers_all_proc_commands_per_kind():
    """3 comandos update_proc_comments_db_<kind> (uno por kind)."""
    client = _fresh_client()
    register_ob1(client)
    for kind in EXTRA_PROC_KINDS:
        cmd = f"update_proc_comments_db_{kind}"
        assert client.has_command(cmd), f"missing: {cmd}"


def test_register_ob1_registers_proc_param_combined_handler():
    client = _fresh_client()
    register_ob1(client)
    assert client.has_command("update_proc_comments_db_param")


def test_register_ob1_registers_online_and_offline_commit_handlers():
    client = _fresh_client()
    register_ob1(client)
    assert client.has_command("commit_disp_nmax_renames_online")
    assert client.has_command("commit_disp_devices_offline")


def test_register_ob1_keeps_deprecated_commit_devices_sync_for_compat():
    """El handler deprecated se mantiene por compat con callers legacy."""
    client = _fresh_client()
    register_ob1(client)
    assert client.has_command("commit_devices_sync")


def test_register_ob1_total_count_is_consistent():
    """Suma verificada: 6 disp + 3 proc + 1 param + 3 commit = 13."""
    client = _fresh_client()
    register_ob1(client)
    expected = (
        len(EXTRA_HW_TYPES)  # 6
        + len(EXTRA_PROC_KINDS)  # 3
        + 1  # param
        + 3  # 3 commits (online, offline, deprecated)
    )
    assert len(client.registered_commands()) == expected


def test_registered_handlers_have_ob1_signature():
    """Handlers registrados aceptan (args, tia_client) -> dict.

    Verificamos mediante introspection: el wrapper generado por
    _wrap_handler es invocable con 2 args.
    """
    client = _fresh_client()
    register_ob1(client)

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

    worker_tia.py sigue vivo hasta 4.6.1; su COMMAND_REGISTRY es un dict
    plano. register(registry) muta ese dict.
    """
    from unittest.mock import MagicMock

    registry: dict = {}
    register(registry)
    # Comprobamos que al menos los disp_commands estan en el dict.
    for hw in EXTRA_HW_TYPES:
        cmd = f"update_disp_comments_db_{hw}"
        assert cmd in registry, f"missing legacy: {cmd}"
        # El valor es un callable (handler con firma (portal, ts, args)).
        assert callable(registry[cmd])
