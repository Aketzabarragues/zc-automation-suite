"""Tests de ``FB_Base`` y ``FB_ConexionTIA``.

Verifica el contrato de los Function Blocks:
  - ``start()`` es idempotente: doble ``start()`` no rearranca.
  - ``tick()`` no se llama en estado terminal (idle, done, error).

Estos son parte de los 6 tests obligatorios de ``.clinerules`` §12.
"""
from __future__ import annotations

import asyncio
from typing import Any

import pytest

from core.plc.plc import (
    DB_ESTADO,
    DB_EstadoConexion,
    FB_Base,
    FB_ConexionTIA,
    MockWorkerBridge,
)

# ─────────────────────────────────────────────────────────────────────
#  Tests de FB_Base
# ─────────────────────────────────────────────────────────────────────


def test_fb_idempotent_start() -> None:
    """``start()`` es idempotente: la 2ª llamada no rearranca.

    Verifica que ``start()`` ignora la llamada si el FB ya esta en
    una etapa activa (no idle, no done, no error). Esto evita que
    doble-clics del operario en "Conectar" arranquen el FB dos
    veces (leccion X3 de ``PLC_IE_61131_GREENFIELD.md`` §0.4).

    Estrategia:
      1. ``start()`` pone ``nStep=10``.
      2. ``start()`` de nuevo NO cambia ``nStep`` (sigue en 10).
      3. ``start()`` tampoco reinicia ``progress`` (sigue en 0
         porque el FB no avanzo etapas entre las dos llamadas).
    """
    fb = FB_ConexionTIA(bridge=MockWorkerBridge(), db=DB_EstadoConexion())
    assert fb.nStep == 0  # idle por defecto
    fb.start()
    assert fb.nStep == 10  # arranco
    # 2ª llamada: idempotente. El ``progress`` no se resetea a 0
    # porque la base solo resetea al RE-ENTRAR a idle.
    fb.start()
    assert fb.nStep == 10  # sigue en 10, no se re-arranco


@pytest.mark.asyncio
async def test_fb_does_not_tick_in_terminal_state() -> None:
    """``tick()`` en estado terminal (done=30) NO avanza el FB.

    El Engine skipea FBs en ``nStep in (0, n_done, n_error)``. Si
    por algun bug un tick se invocara manualmente, el FB no debe
    avanzar (el ``tick()`` de ``FB_ConexionTIA`` no tiene caso
    para ``nStep=30``; simplemente cae por el ``if/elif`` sin
    hacer nada).

    Estrategia:
      1. Crear un FB y llevarlo manualmente a ``nStep=30`` (done).
      2. Llamar ``await tick()``.
      3. Verificar que ``nStep`` sigue en 30 y que el bridge no
         fue llamado (no hay ``list_plcs()`` extra).
    """
    bridge = MockWorkerBridge()
    fb = FB_ConexionTIA(bridge=bridge, db=DB_EstadoConexion())
    # Forzamos el estado terminal OK manualmente (sin pasar por
    # ``start()`` para no ejercitar el flujo completo; aqui solo
    # nos importa el caso terminal).
    fb.nStep = fb.n_done  # 30
    nStep_before = fb.nStep
    await fb.tick()
    # nStep no cambia; el ``tick()`` de ``FB_ConexionTIA`` no
    # tiene rama para ``nStep=30``.
    assert fb.nStep == nStep_before == 30
    # El bridge no se llamo: ``attached`` sigue ``False``.
    assert bridge.attached is False


@pytest.mark.asyncio
async def test_fb_does_not_tick_in_error_state() -> None:
    """``tick()`` en estado de error (``n_error=99``) NO avanza.

    Igual que el test anterior pero para el estado de error. Esto
    es importante: si un FB falla, no debe ``resucitar`` con un
    tick posterior. Solo un nuevo ``start()`` lo rearma.
    """
    bridge = MockWorkerBridge()
    fb = FB_ConexionTIA(bridge=bridge, db=DB_EstadoConexion())
    fb.nStep = fb.n_error  # 99
    fb.nError = 1
    fb.error_msg = "fallo previo"
    await fb.tick()
    assert fb.nStep == fb.n_error == 99
    assert fb.error_msg == "fallo previo"  # no se sobreescribe
    assert bridge.attached is False


# ─────────────────────────────────────────────────────────────────────
#  Tests de FB_ConexionTIA (flujo completo, sin TIA real)
# ─────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_fb_conexion_tia_full_happy_path() -> None:
    """El FB avanza ``10 -> 20 -> 30`` y popula la DB con PLCs.

    Verifica el flujo principal end-to-end con un ``MockWorkerBridge``
    que devuelve datos falsos:
      - Tras ``start()``: ``nStep=10`` (la base resetea el state
        machine; la DB sigue en ``idle`` hasta el primer tick).
      - Tras 1er tick: ``nStep=20``, ``db.tia_state="connecting"``
        -> ``"connecting"`` (se setea en ``tick()``, no en
        ``start()``), ``progress=50``, ``bridge.attach()`` OK.
      - Tras 2do tick: ``nStep=30`` (done), ``progress=100``,
        ``db.tia_state="connected"``, ``db.plcs`` populado,
        ``db.project_name`` y ``db.project_path``.

    La DB se modifica in-place; al final tiene los PLCs y el nombre
    del proyecto. Esto es lo que el HMI recibe via SSE.
    """
    db = DB_EstadoConexion()
    bridge = MockWorkerBridge()
    bridge.fake_plcs = [{"name": "PLC1"}, {"name": "PLC2"}]
    bridge.fake_project_info = {
        "name": "ProyectoTest",
        "path": "C:/test/proj.ap17",
    }
    fb = FB_ConexionTIA(bridge=bridge, db=db)

    fb.start()
    assert fb.nStep == 10
    # ``start()`` solo resetea el state machine del FB; el estado
    # ``connecting`` de la DB se aplica en el primer tick. Antes
    # del tick, la DB sigue en su valor inicial (``idle``).
    assert db.tia_state == "idle"

    # Tick 1: nStep=10 -> 20. Aqui la DB pasa a "connecting".
    await fb.tick()
    assert fb.nStep == 20
    assert fb.progress == 50
    assert db.tia_state == "connecting"
    assert bridge.attached is True

    # Tick 2: nStep=20 -> 30 (done). La DB se popula y pasa a
    # "connected".
    await fb.tick()
    assert fb.nStep == 30
    assert fb.progress == 100
    assert db.tia_state == "connected"
    assert db.plcs == [{"name": "PLC1"}, {"name": "PLC2"}]
    assert db.project_name == "ProyectoTest"
    assert db.project_path == "C:/test/proj.ap17"


@pytest.mark.asyncio
async def test_fb_conexion_tia_error_on_attach() -> None:
    """Si ``attach()`` lanza excepcion, el FB va a error terminal.

    Verifica la captura de excepciones en ``tick()``:
      - ``nError=1``
      - ``error_msg`` con el mensaje de la excepcion.
      - ``nStep=n_error`` (99).
      - ``db.tia_state="error"`` y ``db.last_error`` con el mensaje.
    """

    class _BrokenBridge(MockWorkerBridge):
        async def attach(self, portal_mode: str = "Primary") -> int:
            raise RuntimeError("TIA no encontrado")

    db = DB_EstadoConexion()
    fb = FB_ConexionTIA(bridge=_BrokenBridge(), db=db)
    fb.start()
    await fb.tick()
    assert fb.nStep == fb.n_error == 99
    assert fb.nError == 1
    assert "TIA no encontrado" in fb.error_msg
    assert db.tia_state == "error"
    assert "TIA no encontrado" in db.last_error


@pytest.mark.asyncio
async def test_fb_conexion_tia_get_project_info_failure_is_tolerated() -> None:
    """Si ``get_project_info()`` falla, el FB sigue con PLCs poblados.

    ``get_project_info`` es best-effort: si el worker no lo
    implementa todavia (es un TODO en Fase 1), el FB no debe
    romperse. Los PLCs se listan; los campos de proyecto
    quedan vacios.
    """

    class _NoProjectInfoBridge(MockWorkerBridge):
        async def get_project_info(self) -> dict:
            raise RuntimeError("TODO: not implemented")

    db = DB_EstadoConexion()
    bridge = _NoProjectInfoBridge()
    bridge.fake_plcs = [{"name": "PLC_A"}]
    fb = FB_ConexionTIA(bridge=bridge, db=db)

    fb.start()
    await fb.tick()  # 10 -> 20
    await fb.tick()  # 20 -> 30
    assert fb.nStep == 30
    assert db.plcs == [{"name": "PLC_A"}]
    # project_name/path vacios porque get_project_info fallo.
    assert db.project_name == ""
    assert db.project_path == ""
    # Pero la DB esta en "connected" (los PLCs vinieron OK).
    assert db.tia_state == "connected"


@pytest.mark.asyncio
async def test_fb_conexion_tia_disconnect_resets_state() -> None:
    """``disconnect()`` desde estado done resetea el FB + la DB.

    Verifica:
      - ``nStep`` vuelve a 0.
      - ``db.tia_state`` vuelve a ``"idle"``.
      - ``db.plcs`` se vacia.
      - El bridge ``detach()`` se llamo.
    """
    bridge = MockWorkerBridge()
    db = DB_EstadoConexion()
    fb = FB_ConexionTIA(bridge=bridge, db=db)

    # Llevamos el FB a done.
    fb.start()
    await fb.tick()  # 10 -> 20
    await fb.tick()  # 20 -> 30
    assert fb.nStep == 30
    assert db.tia_state == "connected"
    assert len(db.plcs) == 0  # mock devuelve []

    # disconnect (async ahora).
    await fb.disconnect()
    assert fb.nStep == 0
    assert fb.progress == 0
    assert db.tia_state == "idle"
    assert db.plcs == []
    assert db.project_name == ""
    assert db.project_path == ""
    assert bridge.detach_count == 1


@pytest.mark.asyncio
async def test_fb_conexion_tia_disconnect_ignored_when_not_done() -> None:
    """``disconnect()`` NO resetea si el FB no esta en estado done.

    Documenta el comportamiento del FB: si estas en idle, en curso,
    o en error, ``disconnect()`` es no-op. Asi no perdemos el
    diagnostico del error al desconectar.
    """
    bridge = MockWorkerBridge()
    db = DB_EstadoConexion()
    fb = FB_ConexionTIA(bridge=bridge, db=db)

    # Estado idle: disconnect es no-op.
    await fb.disconnect()
    assert fb.nStep == 0
    assert bridge.detach_count == 0

    # Estado en error: disconnect NO resetea (mantenemos el
    # diagnostico para que el HMI lo muestre).
    fb.nStep = fb.n_error
    fb.nError = 1
    fb.error_msg = "fallo"
    await fb.disconnect()
    assert fb.nStep == fb.n_error
    assert fb.error_msg == "fallo"
    # ``detach_count`` sigue en 0: el FB decidio no llamar al bridge.
    assert bridge.detach_count == 0
