"""core.runtime.sse.sse_publishers - cablea publishers al EventBusSync.

5 publishers se conectan al bus al arrancar la app (ver ``wire_all()``
en ``main_supervisor._build_components``):

  1. LogBuffer          -> {type: "log", level, message, timestamp}
  2. ProgressTracker    -> {type: "progress", **snapshot.to_dict()}
  3. SyncTIAClient      -> {type: "tia_state", state, project, plcs}
  4. FunctionBase       -> {type: "fb_state", name, nStep, is_terminal, result}
  5. TIA-loop lifecycle -> {type: "tia_loop_status", running, thread_name}

Adicionalmente el AppCache aporta 2 publishers:

  6. AppCache snapshot  -> {type: "cache_snapshot", data: <to_api_dict()>}
                           (se envia 1 vez a cada suscriptor nuevo).
  7. AppCache delta     -> {type: "cache_changed", slot, area_id, plc_name, data}
                           (broadcast tras cada ``mutate/mutate_area``).

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

from core.runtime.sse._serialize import to_jsonable

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

def make_tia_state_publisher(
    bus: Any,
    tia_client: Any,
    app_cache: Any | None = None,
) -> Callable[[], None]:
    """Devuelve un callback que publica el state + project + plcs.

    Hook: tia_client.on_state_change (se anade en tia_loop.py).

    Payload:
        {"type": "tia_state", "state": <str>, "project": <dict|None>, "plcs": <list>}
    """
    def publish() -> None:
        # Local imports: evita import cycle sse_publishers -> tia_loop
        # en boot si el caller no necesita project.
        from core.infrastructure.tia.tia_state_cache import (
            plc_list_get,
            plc_project_get,
        )
        from core.runtime.app_cache import get_app_cache

        cache = app_cache if app_cache is not None else get_app_cache()
        plc_info_list = plc_list_get(cache)
        plcs = [
            {"name": p.name, "type": p.type, "ip": p.ip}
            for p in plc_info_list
        ]
        # ``project`` se elige desde el primer PLC conocido. Si el
        # operario aun no ha hecho scan, queda a ``None``. Los datos
        # vienen del AppCache (cacheados por el gateway en su scan),
        # no del wrapper .NET directo.
        project: dict[str, Any] | None = None
        if plc_info_list:
            plc_name_activo = plc_info_list[0].name
            proj = plc_project_get(cache, plc_name_activo)
            if proj is not None:
                project = {
                    "name": proj.name,
                    "path": proj.path,
                    "version": proj.version,
                }
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
            "result": to_jsonable(fb.result),
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
# 6. AppCache snapshot -> {type: "cache_snapshot", data: ...}
# ─────────────────────────────────────────────────────────────────────

def make_cache_snapshot_publisher(
    bus: Any,
    app_cache: Any,
) -> Callable[[Any], None]:
    """Registra el callback de snapshot en el bus al suscribirse.

    Usa ``EventBusSync.set_on_subscribe`` para inyectar el snapshot
    del AppCache DIRECTAMENTE en la cola del suscriptor que se acaba
    de conectar (no via ``publish`` broadcast, que iria a todos).

    Payload:
        {"type": "cache_snapshot", "data": app_cache.to_api_dict()}

    Devuelve un callable ``no_op`` (no hay cleanup; el hook vive en
    el bus mientras este viva).
    """
    def on_subscribe(q: Any) -> None:
        try:
            q.put_nowait({
                "type": "cache_snapshot",
                "data": app_cache.to_api_dict(),
            })
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "cache_snapshot_publisher: no se pudo encolar snapshot: %s",
                exc,
            )
    bus.set_on_subscribe(on_subscribe)
    return lambda: None


# ─────────────────────────────────────────────────────────────────────
# 7. AppCache delta -> {type: "cache_changed", slot, ...}
# ─────────────────────────────────────────────────────────────────────

def make_cache_change_publisher(
    bus: Any,
    app_cache: Any,
) -> Callable[[], None]:
    """Cablea ``app_cache.on_change`` para emitir deltas ``cache_changed``.

    Tras cada ``mutate/mutate_area`` el AppCache invoca el callback
    con ``(slot, area_id, plc_name, value)``. Esta factory envuelve
    esa llamada en un ``bus.publish`` broadcast, de modo que todos
    los suscriptores del SSE reciben el delta y pueden parchear su
    copia local del cache sin re-suscribirse.

    Payload:
        {"type": "cache_changed",
         "slot":      <str>,
         "area_id":   <str|None>,
         "plc_name":  <str|None>,
         "data":      <Any>}

    Devuelve un callable ``no_op`` (no hay cleanup; el hook vive
    en el AppCache mientras este viva).
    """
    def on_change(
        slot: str,
        area_id: str | None,
        plc_name: str | None,
        value: Any,
    ) -> None:
        bus.publish({
            "type": "cache_changed",
            "slot": slot,
            "area_id": area_id,
            "plc_name": plc_name,
            "data": to_jsonable(value),
        })

    app_cache.on_change(on_change)
    return lambda: None


# ─────────────────────────────────────────────────────────────────────
# wire_all — cablea los publishers en una sola llamada
# ─────────────────────────────────────────────────────────────────────

def wire_all(
    log_buffer: Any,
    progress_tracker: Any,
    tia_client: Any,
    engine: Any,
    bus: Any,
    app_cache: Any | None = None,
) -> None:
    """Conecta los 5+2 publishers al bus. Se llama una vez al arrancar.

    Si algun publisher no esta disponible (p. ej. tia_client sin
    on_state_change todavia), se loggea warning y sigue con los
    demas. Asi wire_all() puede correr desde el paso 1 sin esperar
    a los hooks de los pasos 2/3.

    ``app_cache`` se inyecta al publisher de ``tia_state`` para que
    lea la lista de PLCs y el proyecto del cache IT; el wrapper .NET
    no se expone directamente al SSE. Tambien cablea los 2 publishers
    del AppCache (``cache_snapshot`` + ``cache_changed``) si
    ``bus.set_on_subscribe`` y ``app_cache.on_change`` estan
    disponibles.
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
        tia_client.on_state_change = make_tia_state_publisher(
            bus, tia_client, app_cache,
        )
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

    # 6. AppCache snapshot: enqueue el snapshot del AppCache en la
    # cola del nuevo suscriptor al hacer subscribe(). Asi el frontend
    # recibe el estado completo en cuanto abre el EventSource, sin
    # esperar al primer delta.
    if app_cache is not None and hasattr(bus, "set_on_subscribe"):
        make_cache_snapshot_publisher(bus, app_cache)
        logger.debug("publishers: cache_snapshot cableado.")
    else:
        logger.debug("publishers: bus sin set_on_subscribe o app_cache ausente; saltando cache_snapshot.")

    # 7. AppCache delta: hookea app_cache.on_change de modo que cada
    # mutate/mutate_area con ``slot=`` emita un evento cache_changed
    # broadcast. Asi el frontend aplica parches incrementales sin
    # re-suscribirse.
    if app_cache is not None and hasattr(app_cache, "on_change"):
        make_cache_change_publisher(bus, app_cache)
        logger.debug("publishers: cache_changed cableado.")
    else:
        logger.debug("publishers: app_cache sin on_change; saltando cache_changed.")

    logger.info("publishers: wire_all() completado.")


__all__ = [
    "make_log_publisher",
    "make_progress_publisher",
    "make_tia_state_publisher",
    "make_fb_state_publisher",
    "make_tia_loop_status_publisher",
    "make_cache_snapshot_publisher",
    "make_cache_change_publisher",
    "wire_all",
]
