"""core.runtime.sse.sse_publishers - cablea publishers al EventBusSync.

5 publishers se conectan al bus al arrancar la app (ver ``wire_all()``
en ``main_supervisor._build_components``):

  1. LogBuffer          -> {type: "log", level, message, timestamp}
  2. ProgressTracker    -> {type: "progress", **snapshot.to_dict()}
  3. SyncTIAClient      -> {type: "tia_state", state, project, plcs}
  4. FunctionBase       -> {type: "fb_state", name, nStep, is_terminal, result}
  5. TIA-loop lifecycle -> {type: "tia_loop_status", running, thread_name}

Cualquier cambio se retransmite como evento SSE a todos los suscriptores
del bus.

Para anadir un publisher nuevo:
  1. Crear una factory ``make_X_publisher(bus, ...) -> callable``.
  2. Anadir el cableado en ``wire_all()``.
  3. (Si hace falta) Anadir el hook en la clase origen.
"""
from __future__ import annotations

import logging
from typing import Any, Callable

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────
# 1. LogBuffer -> {type: "log", ...entry}
# ─────────────────────────────────────────────────────────────────────

def make_log_publisher(bus: Any) -> Callable[[dict[str, Any]], None]:
    """Devuelve un callback que publica cada entry como evento ``log``.

    Hook: LogBuffer._on_publish (ya existe en LogBuffer).
    """
    def publish(entry: dict[str, Any]) -> None:
        bus.publish({"type": "log", **entry})
    return publish


# ─────────────────────────────────────────────────────────────────────
# 2. ProgressTracker -> {type: "progress", **snapshot.to_dict()}
# ─────────────────────────────────────────────────────────────────────

def make_progress_publisher(bus: Any) -> Callable[..., None]:
    """Devuelve un callback que publica cada snapshot como evento ``progress``.

    Hook: ProgressTracker._on_publish (ya existe en ProgressTracker).
    """
    def publish(snapshot: Any) -> None:
        bus.publish({"type": "progress", **snapshot.to_dict()})
    return publish


# ─────────────────────────────────────────────────────────────────────
# 3. SyncTIAClient state machine -> {type: "tia_state", state, ...}
# ─────────────────────────────────────────────────────────────────────

def make_tia_state_publisher(bus: Any, tia_client: Any) -> Callable[[], None]:
    """Devuelve un callback que publica el state + project + plcs.

    Hook: tia_client.on_state_change (se anade en tia_loop.py).

    Payload:
        {"type": "tia_state", "state": <str>, "project": <dict|None>, "plcs": <list>}
    """
    def publish() -> None:
        wrapper = tia_client.wrapper
        project: dict[str, Any] | None = None
        plcs: list[dict[str, Any]] = []
        if wrapper is not None:
            try:
                proj_obj = wrapper.get_project()
                if proj_obj is not None:
                    project = {
                        "name": getattr(proj_obj, "Name", None),
                        "path": getattr(proj_obj, "Path", None),
                        "version": getattr(proj_obj, "Version", None),
                    }
            except Exception as exc:  # noqa: BLE001
                logger.debug("tia_state_publisher: get_project fallo: %s", exc)
        event: dict[str, Any] = {
            "type": "tia_state",
            "state": tia_client.state,
            "project": project,
            "plcs": plcs,
        }
        bus.publish(event)
    return publish


# ─────────────────────────────────────────────────────────────────────
# 4. FunctionBase / Engine -> {type: "fb_state", name, nStep, ...}
# ─────────────────────────────────────────────────────────────────────

def make_fb_state_publisher(bus: Any, engine: Any) -> Callable[[str, Any], None]:
    """Devuelve un callback que publica el estado de un FB concreto.

    Hook: engine.on_fb_change (se anade en engine.py). El engine
    lo invoca con (nombre, fb) tras cada tick que cambie nStep.

    Payload:
        {"type": "fb_state",
         "name": <str>,
         "nStep": <int>,
         "is_terminal": <bool>,
         "result": <Any>,
         "error_msg": <str|None>}
    """
    def publish(name: str, fb: Any) -> None:
        bus.publish({
            "type": "fb_state",
            "name": name,
            "nStep": fb.nStep,
            "is_terminal": fb.is_terminal(),
            "result": fb.result,
            "error_msg": fb.error_msg,
        })
    return publish


# ─────────────────────────────────────────────────────────────────────
# 5. TIA-loop lifecycle -> {type: "tia_loop_status", running, ...}
# ─────────────────────────────────────────────────────────────────────

def make_tia_loop_status_publisher(
    bus: Any, tia_client: Any,
) -> Callable[[], None]:
    """Devuelve un callback que publica running/stopped del tia-loop.

    Hook: tia_client.on_loop_status (se anade en tia_loop.py).
    El tia-loop lo invoca tras start_tia_loop() y al salir
    del bucle principal.

    Payload:
        {"type": "tia_loop_status", "running": <bool>, "thread_name": <str|None>}
    """
    def publish() -> None:
        thread = tia_client._tia_thread
        running = tia_client._loop_running
        bus.publish({
            "type": "tia_loop_status",
            "running": running,
            "thread_name": thread.name if thread else None,
        })
    return publish


# ─────────────────────────────────────────────────────────────────────
# wire_all — cablea los 5 publishers en una sola llamada
# ─────────────────────────────────────────────────────────────────────

def wire_all(
    log_buffer: Any,
    progress_tracker: Any,
    tia_client: Any,
    engine: Any,
    bus: Any,
) -> None:
    """Conecta los 5 publishers al bus. Se llama una vez al arrancar.

    Si algun publisher no esta disponible (p. ej. tia_client sin
    on_state_change todavia), se loggea warning y sigue con los
    demas. Asi wire_all() puede correr desde el paso 1 sin esperar
    a los hooks de los pasos 2/3.
    """
    # 1. LogBuffer
    if log_buffer is not None and hasattr(log_buffer, "_on_publish"):
        log_buffer._on_publish = make_log_publisher(bus)
        logger.debug("publishers: LogBuffer cableado.")
    else:
        logger.warning("publishers: LogBuffer sin _on_publish; log publisher no cableado.")

    # 2. ProgressTracker
    if progress_tracker is not None and hasattr(progress_tracker, "_on_publish"):
        progress_tracker._on_publish = make_progress_publisher(bus)
        logger.debug("publishers: ProgressTracker cableado.")
    else:
        logger.warning("publishers: ProgressTracker sin _on_publish; progress publisher no cableado.")

    # 3. SyncTIAClient state
    if hasattr(tia_client, "on_state_change"):
        tia_client.on_state_change = make_tia_state_publisher(bus, tia_client)
        logger.debug("publishers: SyncTIAClient.on_state_change cableado.")
    else:
        logger.debug("publishers: SyncTIAClient.on_state_change aun no existe; saltando.")

    # 4. Engine FB state
    if hasattr(engine, "on_fb_change"):
        engine.on_fb_change = make_fb_state_publisher(bus, engine)
        # Cablear retroactivamente los FBs YA registrados: el hook
        # _on_nstep_change de cada FB se conecta para que cualquier
        # cambio de nStep publique al bus. (register_fb() cablea esto
        # para FBs nuevos; aqui nos encargamos de los registrados
        # antes de wire_all.)
        if engine is not None:
            for fb_name, fb in list(engine._fbs.items()):  # noqa: SLF001
                fb._on_nstep_change = (
                    lambda old, new, _n=fb_name, _fb=fb: (
                        engine.on_fb_change(_n, _fb)
                    )
                )
        logger.debug("publishers: engine.on_fb_change cableado.")
    else:
        logger.debug("publishers: engine.on_fb_change aun no existe; saltando.")

    # 5. TIA-loop lifecycle
    if hasattr(tia_client, "on_loop_status"):
        publisher_5 = make_tia_loop_status_publisher(bus, tia_client)
        tia_client.on_loop_status = publisher_5
        # Publica retroactivamente el estado actual: el hook se conecta
        # DESPUES de que el tia-loop arranca, asi que el evento
        # "running=true" inicial se pierde si no lo forzamos aqui.
        try:
            publisher_5()
        except Exception as exc:  # noqa: BLE001
            logger.debug("publishers: retroactiva tia_loop_status fallo: %s", exc)
        logger.debug("publishers: SyncTIAClient.on_loop_status cableado.")
    else:
        logger.debug("publishers: SyncTIAClient.on_loop_status aun no existe; saltando.")

    # 4b. Publica retroactivamente cada FB registrado en el engine.
    if engine is not None and hasattr(engine, "on_fb_change"):
        for fb_name, fb in list(engine._fbs.items()):  # noqa: SLF001
            try:
                engine.on_fb_change(fb_name, fb)
            except Exception as exc:  # noqa: BLE001
                logger.debug(
                    "publishers: retroactiva fb_state(%s) fallo: %s",
                    fb_name, exc,
                )

    logger.info("publishers: wire_all() completado (5 publishers).")


__all__ = [
    "make_log_publisher",
    "make_progress_publisher",
    "make_tia_state_publisher",
    "make_fb_state_publisher",
    "make_tia_loop_status_publisher",
    "wire_all",
]
