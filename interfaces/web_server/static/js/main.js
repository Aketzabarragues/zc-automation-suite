// =========================================================================
//  main.js — HMI pasivo (Fase 0.5 spike)
//
//  Objetivo: validar que SSE funciona dentro de un .exe de PyInstaller
//  contra el Windows real del operario. Vanilla JS a propósito — Vue 3
//  sin build step se introduce en Fase 3 (clonación de los 11 componentes
//  legacy, no rediseño). Por ahora, lo único que se valida es:
//
//    1. El browser abre 1 EventSource a /api/v1/events.
//    2. El backend emite {"ping": "pong"} por SSE.
//    3. El DOM se actualiza con el último evento recibido.
//    4. F5 → el EventSource se reestablece solo (auto-reconnect nativo).
//    5. Tras 30s, la conexión sigue abierta (heartbeat del backend).
//
//  Convenciones del greenfield (no violar):
//    - PROHIBIDO setInterval / polling. El EventSource es push.
//    - PROHIBIDO fetch directo desde un componente (Fase 3 usará usePlc()).
//    - Sin CDN, sin import externo, sin TypeScript.
// =========================================================================

const app = document.getElementById("app");
app.innerHTML = `
    <main class="p-4 font-mono text-sm">
        <h1 class="text-lg font-semibold text-accent mb-2">
            zc-automation-suite — Fase 0.5
        </h1>
        <p class="text-ink-muted mb-4">
            Spike SSE dentro de PyInstaller. El backend emite
            <code>{"tick": N}</code> cada 500ms; el contador se resetea a 0
            al llegar a 500. Mira la consola del navegador (F12) para ver
            los timestamps exactos.
        </p>
        <div class="grid grid-cols-2 gap-3 max-w-md">
            <div class="bg-surface-raised border border-line rounded p-3">
                <div class="text-[10px] uppercase text-ink-muted">tick actual</div>
                <div id="tick-value" class="text-3xl font-bold text-accent">—</div>
            </div>
            <div class="bg-surface-raised border border-line rounded p-3">
                <div class="text-[10px] uppercase text-ink-muted">ultimo evento</div>
                <div id="tick-time" class="text-3xl font-bold text-ink">—</div>
            </div>
        </div>
        <pre id="sse-output"
             class="mt-3 bg-surface-raised border border-line rounded p-3 whitespace-pre-wrap break-words text-xs">esperando evento…</pre>
    </main>
`;

const tickValueEl = document.getElementById("tick-value");
const tickTimeEl = document.getElementById("tick-time");
const outputEl = document.getElementById("sse-output");
let eventSource = null;

function connect() {
    // El path /api/v1/events es el contrato del backend en Fase 0.5.
    // El FastAPI sirve esta SPA desde /static/ y monta los routers en /api/v1/*.
    eventSource = new EventSource("/api/v1/events");

    eventSource.onopen = () => {
        outputEl.textContent = "[conectado] esperando primer evento…";
    };

    eventSource.onmessage = (e) => {
        // Parseamos el JSON {"tick": N} y pintamos el tick + timestamp.
        // En la consola del navegador (F12) se ve la fecha/hora exacta
        // de cada push, lo que permite medir la frecuencia visualmente.
        let tick = null;
        try {
            const parsed = JSON.parse(e.data);
            tick = parsed.tick;
        } catch {
            tick = e.data;
        }
        tickValueEl.textContent = String(tick);
        const now = new Date();
        tickTimeEl.textContent =
            String(now.getHours()).padStart(2, "0") + ":" +
            String(now.getMinutes()).padStart(2, "0") + ":" +
            String(now.getSeconds()).padStart(2, "0") + "." +
            String(now.getMilliseconds()).padStart(3, "0");
        console.log(`[SSE] ${now.toISOString()} tick=${tick}`);
        outputEl.textContent = e.data;
    };

    eventSource.onerror = (e) => {
        // EventSource nativo reconecta solo; sólo pintamos el estado.
        // Cuando el backend está caído, readyState === 2 (CLOSED) y el
        // browser reintenta cada ~3s. No cerramos manualmente.
        if (eventSource.readyState === EventSource.CLOSED) {
            outputEl.textContent = "[desconectado] el browser reintentará…";
        }
    };
}

function disconnect() {
    if (eventSource) {
        eventSource.close();
        eventSource = null;
    }
}

connect();

// Hook de limpieza: si el operario cierra la pestaña, cerramos limpio.
window.addEventListener("beforeunload", disconnect);
