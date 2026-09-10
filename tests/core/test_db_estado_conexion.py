"""Tests de la Data Block trasversal ``DB_EstadoConexion``.

Verifica que el estado por defecto es el esperado: ``tia_state="idle"``,
``worker_alive=False``, ``plcs=[]`` (lista vacia, no ``None``), etc.

Este test es uno de los 6 obligatorios de ``.clinerules`` §12 (test 3:
el engine expone el estado al HMI sin campos faltantes, leccion X1).
"""
from __future__ import annotations

from core.plc.plc import DB_ESTADO, DB_EstadoConexion


def test_default_state() -> None:
    """El estado inicial de la DB tiene los defaults esperados.

    Cubre el contrato:
      - ``tia_state == "idle"`` (no ``None``, no ``""``).
      - ``worker_alive == False``.
      - ``plcs == []`` (lista vacia, no ``None``; importante para que
        el HMI pueda hacer ``.length`` sin chequeos adicionales).
      - ``project_name == ""`` y ``project_path == ""``.
      - ``last_error == ""``.
      - ``last_ping_ok_unix == 0.0``.
    """
    db = DB_EstadoConexion()
    assert db.tia_state == "idle"
    assert db.worker_alive is False
    assert db.plcs == []
    assert db.project_name == ""
    assert db.project_path == ""
    assert db.last_error == ""
    assert db.last_ping_ok_unix == 0.0


def test_singleton_db_uses_defaults() -> None:
    """El singleton ``DB_ESTADO`` arrancado al importar ``core.plc.plc``
    tiene los defaults esperados. Esto es importante porque el lifespan
    de FastAPI reusa este singleton (no crea uno nuevo por instancia).
    """
    assert DB_ESTADO.tia_state == "idle"
    assert DB_ESTADO.worker_alive is False
    assert DB_ESTADO.plcs == []


def test_db_instances_are_independent() -> None:
    """Dos instancias de ``DB_EstadoConexion`` no comparten estado.

    Si modificas una, la otra no se ve afectada. Esto evita
    acoplamientos sutiles en tests que crean DBs temporales.
    """
    a = DB_EstadoConexion()
    b = DB_EstadoConexion()
    a.tia_state = "connected"
    a.plcs = [{"name": "PLC1"}]
    a.last_error = "boom"
    # ``b`` no se ve afectada.
    assert b.tia_state == "idle"
    assert b.plcs == []
    assert b.last_error == ""
