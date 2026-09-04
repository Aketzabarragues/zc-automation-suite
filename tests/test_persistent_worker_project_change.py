"""Tests de la deteccion de cambio de proyecto del worker OT persistente (PR 7).

Cubre el mecanismo definido en
``_plan/12_worker_persistent_design.md`` §2.8 y §3.5: si el operario
abre un proyecto distinto en TIA Portal sin pasar por la app, el
worker persistente lo detecta comparando el ``path`` del proyecto
activo con el ultimo conocido (``self._project_path``). Si difiere,
invalida ``_cache`` y ``_bloques_cache`` y marca
``self._project_changed = True`` para que el snapshot de
``/tia/connection`` lo exponga al frontend.

API publica anadida en este PR:

  - ``gateway._detect_project_change()``: metodo async que consulta
    ``get_project_info`` al worker, compara el path y, si difiere,
    invalida caches y marca el flag. Retorna ``True`` si hubo
    cambio, ``False`` en caso contrario (incluyendo modo 1-shot y
    errores de comunicacion con el worker).
  - ``gateway.consume_project_changed()``: helper sincrono que lee
    el flag y lo resetea (semantica one-shot para el frontend).

Estrategia de testing:

  - **Mocking ligero**: ``_send_to_persistent_worker`` se sustituye
    por un ``AsyncMock`` que retorna el ``get_project_info`` que
    queramos (con o sin path). Asi los tests no necesitan un
    subproceso real ni TIA Portal.
  - **Lock**: el metodo adquiere ``self._worker_lock`` internamente.
    En los tests creamos un gateway persistente con un ``asyncio.Lock``
    ya inicializado, asi ``async with self._worker_lock`` no crashea.
  - **Caches**: verificamos via ``call_count`` de mocks sobre
    ``clear_cache`` y ``_clear_bloques_cache`` que se invocan solo
    cuando hay cambio real.

Tests:

  1. ``test_cambio_de_proyecto_invalida_caches_y_marca_flag``: path
     distinto al cacheado → ``clear_cache`` y ``_clear_bloques_cache``
     se llaman, ``_project_path`` se actualiza, ``_project_changed``
     queda a ``True``, retorno ``True``.
  2. ``test_mismo_proyecto_no_invalida_caches``: path igual al
     cacheado → caches NO se tocan, flag NO se setea, retorno ``False``.
  3. ``test_worker_falla_retorna_false_sin_crashear``: el
     ``_send_to_persistent_worker`` lanza → retorno ``False``, sin
     tocar caches, sin setear flag.
  4. ``test_consume_project_changed_lectura_y_reset``: el flag se lee
     y se resetea a ``False`` (one-shot); segunda llamada retorna
     ``False``.
  5. ``test_modo_1shot_no_detecta_ni_invalida``: gateway
     ``persistent=False`` → ``_detect_project_change`` retorna
     ``False`` y no consulta al worker (modo MCP intacto).
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from core.infrastructure.gateway import TIAProcessGateway


# ────────────────────────────────────────────────────────────────────────
# Test 1: cambio de proyecto invalida caches y marca el flag
# ────────────────────────────────────────────────────────────────────────


class TestDetectProjectChangeInvalidatesCaches:
    """Si el path del proyecto difiere del cacheado, se invalidan las caches."""

    @pytest.mark.asyncio
    async def test_cambio_de_proyecto_invalida_caches_y_marca_flag(self) -> None:
        """Path nuevo distinto al cacheado → ``clear_cache`` +
        ``_clear_bloques_cache`` se invocan, ``_project_path`` se
        actualiza, ``_project_changed`` queda a ``True``, el metodo
        retorna ``True``.

        Caso real: el operario tiene TIA abierto con el proyecto A
        (path ``A/ap17``), la app arranca, se cachea. Despues abre
        el proyecto B (path ``B/ap17``) desde TIA. La siguiente
        operacion del operario dispara ``_detect_project_change``,
        que invalida caches (los bloques y los tags del proyecto A
        ya no son validos para B) y marca el flag para que el
        frontend muestre una notificacion.
        """
        gateway = TIAProcessGateway(persistent=True)
        gateway._project_path = r"C:\ws\proyectoA\proyectoA.ap17"

        # El worker reporta que el proyecto activo ahora es B.
        async def fake_send(command, args, timeout_override):  # noqa: ARG001
            assert command == "get_project_info"
            return {
                "name": "ProyectoB",
                "path": r"C:\ws\proyectoB\proyectoB.ap17",
                "version": "18.0",
            }

        gateway._send_to_persistent_worker = fake_send
        # Mockeamos los helpers de limpieza para verificar que se llaman.
        # Usamos ``MagicMock`` (no ``AsyncMock``) porque son sync.
        gateway.clear_cache = MagicMock(name="clear_cache")
        gateway._clear_bloques_cache = MagicMock(name="_clear_bloques_cache")

        changed = await gateway._detect_project_change()

        # Se detecto cambio.
        assert changed is True, (
            f"se esperaba True tras cambio de proyecto, got {changed!r}"
        )
        # ``_project_path`` se actualizo al nuevo path.
        assert gateway._project_path == r"C:\ws\proyectoB\proyectoB.ap17"
        # ``_project_changed`` esta a True (frontend lo consumira via
        # ``consume_project_changed``).
        assert gateway._project_changed is True
        # Ambas caches se invalidaron.
        gateway.clear_cache.assert_called_once()
        gateway._clear_bloques_cache.assert_called_once()
        # ``_send_to_persistent_worker`` se llamo UNA vez con
        # ``get_project_info``.
        # (el fake_send no tiene assert_call_count, pero verificamos
        # el path actualizado que solo puede venir de su retorno)


# ────────────────────────────────────────────────────────────────────────
# Test 2: mismo proyecto no invalida caches
# ────────────────────────────────────────────────────────────────────────


class TestDetectProjectChangeSamePath:
    """Si el path del proyecto coincide con el cacheado, no se invalidan caches."""

    @pytest.mark.asyncio
    async def test_mismo_proyecto_no_invalida_caches(self) -> None:
        """Path identico al cacheado → caches NO se tocan, flag NO
        se setea, retorno ``False``.

        Caso normal: el operario no cambio de proyecto, el operario
        simplemente lanzo otra operacion. La deteccion debe ser un
        no-op que no penalice con invalidadciones innecesarias
        (cada ``clear_cache`` es O(1) pero psicologicamente "se
        invalido la cache" podria disparar relecturas si el
        frontend lo interpretara como cambio).
        """
        gateway = TIAProcessGateway(persistent=True)
        gateway._project_path = r"C:\ws\proyectoA\proyectoA.ap17"

        # El worker reporta el MISMO path que tenemos cacheado.
        async def fake_send(command, args, timeout_override):  # noqa: ARG001
            return {
                "name": "ProyectoA",
                "path": r"C:\ws\proyectoA\proyectoA.ap17",
                "version": "18.0",
            }

        gateway._send_to_persistent_worker = fake_send
        gateway.clear_cache = MagicMock(name="clear_cache")
        gateway._clear_bloques_cache = MagicMock(name="_clear_bloques_cache")

        changed = await gateway._detect_project_change()

        # No hay cambio.
        assert changed is False, (
            f"se esperaba False cuando el path coincide, got {changed!r}"
        )
        # ``_project_path`` no se toco.
        assert gateway._project_path == r"C:\ws\proyectoA\proyectoA.ap17"
        # ``_project_changed`` sigue a False (o lo que estuviera antes).
        assert gateway._project_changed is False
        # Caches NO se invalidaron.
        gateway.clear_cache.assert_not_called()
        gateway._clear_bloques_cache.assert_not_called()


# ────────────────────────────────────────────────────────────────────────
# Test 3: el worker falla → retorno False sin crashear
# ────────────────────────────────────────────────────────────────────────


class TestDetectProjectChangeWorkerError:
    """Si ``_send_to_persistent_worker`` falla, no se invalida nada y se retorna ``False``."""

    @pytest.mark.asyncio
    async def test_worker_falla_retorna_false_sin_crashear(self) -> None:
        """Excepcion en ``_send_to_persistent_worker`` → ``False``, caches intactas.

        Caso real: TIA Portal cerrado entre el attach y la consulta,
        timeout, excepcion COM/RPC, BrokenPipeError si el worker
        murio durante el write. La deteccion NO debe tumbar el
        comando del operario; el heartbeat marcara ``disconnected``
        si persiste. Aqui solo nos ocupa el cambio de proyecto.
        """
        gateway = TIAProcessGateway(persistent=True)
        gateway._project_path = r"C:\ws\proyectoA\proyectoA.ap17"
        # NO se debe tocar el flag ni el path.
        original_path = gateway._project_path

        async def fake_send_raises(command, args, timeout_override):  # noqa: ARG001
            raise RuntimeError("Worker no respondio: BrokenPipeError")

        gateway._send_to_persistent_worker = fake_send_raises
        gateway.clear_cache = MagicMock(name="clear_cache")
        gateway._clear_bloques_cache = MagicMock(name="_clear_bloques_cache")

        # No debe lanzar; retorna ``False`` y degrada limpio.
        changed = await gateway._detect_project_change()

        assert changed is False
        # El path NO se toco.
        assert gateway._project_path == original_path
        # El flag NO se seteo.
        assert gateway._project_changed is False
        # Las caches NO se invalidaron.
        gateway.clear_cache.assert_not_called()
        gateway._clear_bloques_cache.assert_not_called()


# ────────────────────────────────────────────────────────────────────────
# Test 4: ``consume_project_changed`` es one-shot
# ────────────────────────────────────────────────────────────────────────


class TestConsumeProjectChanged:
    """``consume_project_changed()`` lee el flag y lo resetea (one-shot)."""

    def test_consume_project_changed_lectura_y_reset(self) -> None:
        """Primera llamada con flag ``True`` → retorna ``True`` y resetea.

        Segunda llamada → retorna ``False`` (el flag ya fue consumido).
        Esto modela el patron de uso del frontend: el indicador
        recibe ``project_changed=true`` UNA sola vez tras un cambio
        real; el siguiente polling ya no ve el flag.
        """
        gateway = TIAProcessGateway(persistent=True)
        gateway._project_changed = True  # simulado por ``_detect_project_change``

        # Primera lectura: True, y se resetea.
        assert gateway.consume_project_changed() is True
        assert gateway._project_changed is False
        # Segunda lectura: ya no hay nada pendiente.
        assert gateway.consume_project_changed() is False
        # Estado estable tras lecturas repetidas.
        assert gateway.consume_project_changed() is False

    def test_consume_project_changed_sin_flag_es_false(self) -> None:
        """``consume_project_changed()`` con flag a ``False`` retorna ``False``.

        Caso normal: el operario nunca cambio de proyecto (o el
        cambio ya fue notificado). El endpoint no debe mostrar el
        flag a ``True`` nunca.
        """
        gateway = TIAProcessGateway(persistent=True)
        # Estado por defecto tras construir el gateway.
        assert gateway._project_changed is False
        assert gateway.consume_project_changed() is False


# ────────────────────────────────────────────────────────────────────────
# Test 5 (defensivo): en modo 1-shot no se detecta ni invalida nada
# ────────────────────────────────────────────────────────────────────────


class TestDetectProjectChangeEphemeral:
    """En modo ``persistent=False`` la deteccion es no-op (MCP intacto)."""

    @pytest.mark.asyncio
    async def test_modo_1shot_no_detecta_ni_invalida(self) -> None:
        """Gateway MCP (``persistent=False``) + ``_detect_project_change``
        → ``False`` sin tocar nada.

        El modo 1-shot (MCP) sigue siendo process-per-call: cada
        invocacion del LLM levanta un worker nuevo que abre proyecto
        desde cero, asi que la deteccion de cambio entre invocaciones
        no tiene sentido (no hay estado persistente que invalidar).
        El metodo retorna ``False`` inmediatamente.
        """
        gateway = TIAProcessGateway(persistent=False)
        # Aunque pongamos un path cacheado (no deberia pasar en MCP,
        # pero defensivo), el metodo debe retornar ``False`` sin
        # intentar comunicarse con un worker.
        gateway._project_path = r"C:\ws\fantasma\fantasma.ap17"

        # Si el metodo intentara enviar algo al worker, fallaria
        # porque ``_send_to_persistent_worker`` no existe en modo 1-shot.
        # Usamos ``AsyncMock`` para que, en el improbable caso de que
        # el codigo lo invocara, NO lance ``AttributeError`` que es
        # un fallo de test confuso.
        gateway._send_to_persistent_worker = AsyncMock(
            return_value={"name": "X", "path": "Y"}
        )
        gateway.clear_cache = MagicMock()
        gateway._clear_bloques_cache = MagicMock()

        changed = await gateway._detect_project_change()

        assert changed is False
        # Nada se toco.
        gateway._send_to_persistent_worker.assert_not_called()
        gateway.clear_cache.assert_not_called()
        gateway._clear_bloques_cache.assert_not_called()
