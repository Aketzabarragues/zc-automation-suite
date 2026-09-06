# Refactor state machine del worker persistente (sept-2026)

> Complemento del design doc original `_plan/12_worker_persistent_design.md`.
> _plan/ está en .gitignore, así que este resumen ejecutivo del refactor
> vive aquí, en `docs/`, para que el equipo pueda consultarlo sin abrir
> el plan local.

---

## §11. Refactor state machine (sept-2026)

Aketza decidió (sept-2026) un refactor mayor del modelo de conexión con TIA
Portal: el worker ahora arranca SIEMPRE en estado idle (sin attach), y el
operario decide cuándo conectar vía botón en el topbar. Este cambio elimina
el race condition entre el lazy start del worker y el primer comando del
frontend (auditoría `_plan/14_post_worker_persistent_audit.md`, fix X1+ready).

### §11.1. Worker: idle por defecto

El worker (`worker_tia.py::main_persistent_loop`) ya NO intenta hacer
`ts.attach_portal` al inicio. Después de cargar el wrapper nativo, emite:

    {"id": 0, "ok": true, "result": "ready_idle"}

y entra al loop esperando comandos del IT process. Comandos nuevos:

- `attach_portal` (args: `{"mode": "WithGraphicalUserInterface" | "WithoutGraphicalUserInterface"}`): llama `ts.attach_portal`, devuelve `{"pid": <int>}` o `{"error": "..."}`.
- `detach_portal`: llama `portal.detach()` si `portal is not None`, devuelve `{"detached": true}`.

El resto de comandos requieren `portal is not None`. Si llega uno sin attach,
devuelve `{"error": "Portal no attached. Conectar primero."}`.

Cleanup final: si `portal is not None` al exit (exit o stdin cerrado),
detach best-effort.

### §11.2. Gateway: state machine

El gateway (`gateway.py`) maneja una máquina de estados:

    idle -> connecting -> connected -> idle
                      \-> error -> idle (retry)

Valores del atributo `_connection_state`: `"idle" | "connecting" | "connected" | "error"`. Estado inicial: `"idle"`.

Métodos públicos:

- `start()`: arranca el subproceso worker y espera al `"ready_idle"` signal con timeout 60s. Si OK, `state="idle"`. Si falla, `TIAConnectionError`.
- `connect()`: envía `"attach_portal"` al worker. State: `idle -> connecting -> connected`. Si falla: `error`. Adquiere `self._worker_lock`.
- `disconnect()`: envía `"detach_portal"` al worker. State: `connected -> idle`. Limpia caches (`_cache`, `_bloques_cache`, `_project_path`). Adquiere `self._worker_lock`. NO mata el subproceso.
- `reconnect()`: `disconnect` + `connect` (compatibilidad con tests legacy).

Validación de comandos en `_send_to_persistent_worker`:

- `attach_portal`, `detach_portal`, `ping`, `get_project_info`: siempre permitidos.
- Resto: solo si `state == "connected"`. Si no, `TIAConnectionError`.

El heartbeat (`_heartbeat_loop`) solo corre si `state == "connected"`. El
cambio de proyecto (`_detect_project_change`) se llama en `connect()`, no
automáticamente en cada dispatch.

### §11.3. Endpoints REST

`GET /api/v1/tia/connection`:

    {state, project, plcs, last_ping_ok_unix, last_error, project_changed,
     worker_alive, pid (si state=="connected")}

`POST /api/v1/tia/connect`:

- Llama `gateway.connect()`.
- Devuelve `{ok: true, state: "connecting"|"connected"|"error", pid: <int>|null}` o `{ok: false, state: "error", error: "..."}`.

`POST /api/v1/tia/disconnect`:

- Llama `gateway.disconnect()`.
- Devuelve `{ok: true, state: "idle"}` o error.

### §11.4. Frontend: topbar reorganizado

El `ShellTopbar` reorganiza el control de conexión:

    [ breadcrumb ] [ Worker ] [ TIA Portal ] [ Conectar | Desconectar ] [ PLC: list ] [ Buscar PLCs ]

- `WorkerStatusIndicator`: círculo `w-3 h-3`, "subproceso vivo" (verde/gris). Independiente del attach a TIA.
- `TiaConnectionIndicator`: círculo `w-3 h-3` (mismo tamaño), state del gateway (gris `idle`, ámbar `connecting`, verde `connected`, rojo `error`).
- Botón "Conectar" visible si `state in {idle, error}`.
- Botón "Desconectar" visible si `state in {connecting, connected}`.
- Botón "Buscar PLCs" visible si `state == "connected"`.
- Lista de PLCs visible si `state == "connected"` Y hay PLCs.

Al desconectar: vaciar `store.plcs`, `store.selectedPlc`, `store.plcBlocksCache`, `store.projectInfo`.

### §11.5. Compatibilidad

- Modo MCP (1-shot, `persistent=False`): sin cambios. Los tests del MCP siguen pasando.
- Commits previos compatibles: X1 (`store.js` propaga `worker_alive`), X2 (lifespan al shutdown), X3 (lock en connect/disconnect), chore (`styles.css`).

---

## Referencias cruzadas

- Design doc original (gitignored, local): `_plan/12_worker_persistent_design.md`.
- Auditoría que motivó el refactor (gitignored, local): `_plan/14_post_worker_persistent_audit.md`.
- Rama de los 5 commits mergeados: `fix/audit-x1-x2-x3-post-impl-worker-persistent`.

---

*Documento de referencia rápido, generado como commit 6 (docs) del refactor
del worker persistente. Para el detalle completo del diseño, ver
`_plan/12_worker_persistent_design.md` en local.*
