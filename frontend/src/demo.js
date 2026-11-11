/**
 * Fuente de eventos simulada para el modo demo (`?demo=1`).
 *
 * Mantiene la misma interfaz que un `EventSource` (`onopen`, `onmessage`,
 * `onerror`, `close`), de modo que el resto de la app no necesita saber si
 * hay un backend detras o no.
 *
 * Los eventos simulados son los cuatro del backend: `tia`, `progress`,
 * `job` y `log`.
 */

/** Escenario del demo: un trabajo de sincronizacion de tres pasos. */
const ESCENARIO = [
  {
    espera: 300,
    evento: {
      type: "tia",
      conectado: true,
      trabajo_actual: null,
      ultimo_error: null,
      version_tia: "V21.0",
    },
  },
  {
    espera: 300,
    evento: {
      type: "log",
      nivel: "info",
      mensaje: "Demo: la consola de trazabilidad recibe los eventos del backend.",
      detalle: null,
    },
  },
  {
    espera: 300,
    evento: {
      type: "progress",
      active: true,
      operation: "sincronizar",
      label: "Sincronizar dispositivos",
      current: 0,
      total: 3,
      percent: 0,
      stages: [
        { id: "exportar", label: "Exportar bloques", status: "running", detail: null },
        { id: "comparar", label: "Comparar con el libro maestro", status: "pending", detail: null },
        { id: "aplicar", label: "Aplicar los cambios", status: "pending", detail: null },
      ],
      started_at: null,
      finished_at: null,
      error: null,
    },
  },
  {
    espera: 900,
    evento: {
      type: "progress",
      active: true,
      operation: "sincronizar",
      label: "Sincronizar dispositivos",
      current: 1,
      total: 3,
      percent: 33,
      stages: [
        { id: "exportar", label: "Exportar bloques", status: "done", detail: "12 bloques" },
        { id: "comparar", label: "Comparar con el libro maestro", status: "running", detail: null },
        { id: "aplicar", label: "Aplicar los cambios", status: "pending", detail: null },
      ],
      started_at: null,
      finished_at: null,
      error: null,
    },
  },
  {
    espera: 300,
    evento: {
      type: "log",
      nivel: "warning",
      mensaje: "Demo: un aviso sin traceback.",
      detalle: null,
    },
  },
  {
    espera: 300,
    evento: {
      type: "log",
      nivel: "error",
      mensaje: "Demo: un fallo con traceback, para ver el desplegable.",
      detalle:
        "Traceback (most recent call last):\n" +
        '  File "demo.py", line 1, in <module>\n' +
        "    fallar()\n" +
        "DemoError: esto es un traceback de mentira\n",
    },
  },
  {
    espera: 600,
    evento: {
      type: "progress",
      active: true,
      operation: "sincronizar",
      label: "Sincronizar dispositivos",
      current: 2,
      total: 3,
      percent: 66,
      stages: [
        { id: "exportar", label: "Exportar bloques", status: "done", detail: "12 bloques" },
        { id: "comparar", label: "Comparar con el libro maestro", status: "done", detail: "3 cambios" },
        { id: "aplicar", label: "Aplicar los cambios", status: "running", detail: null },
      ],
      started_at: null,
      finished_at: null,
      error: null,
    },
  },
  {
    espera: 700,
    evento: {
      type: "job",
      job: "demo0001",
      estado: "ok",
      resultado: { cambios: 3 },
      error: null,
    },
  },
  {
    espera: 100,
    evento: {
      type: "progress",
      active: false,
      operation: "sincronizar",
      label: "Sincronizar dispositivos",
      current: 3,
      total: 3,
      percent: 100,
      stages: [
        { id: "exportar", label: "Exportar bloques", status: "done", detail: "12 bloques" },
        { id: "comparar", label: "Comparar con el libro maestro", status: "done", detail: "3 cambios" },
        { id: "aplicar", label: "Aplicar los cambios", status: "done", detail: "3 cambios aplicados" },
      ],
      started_at: null,
      finished_at: null,
      error: null,
    },
  },
];

/** Pausa entrecenario y el siguiente. */
const PAUSA = 6000;

/**
 * Crea una fuente de eventos simulada.
 *
 * @param {object} opciones opciones.
 * @param {number} opciones.factor multiplicador de los tiempos. Con 0 el
 *   escenario sale de inmediato.
 * @returns {object} la fuente, con la interfaz de `EventSource`.
 */
export function crearFuenteDemo({ factor = 1 } = {}) {
  let temporizadores = [];
  let cerrado = false;

  const fuente = {
    onopen: null,
    onmessage: null,
    onerror: null,
    close() {
      cerrado = true;
      temporizadores.forEach((temporizador) => clearTimeout(temporizador));
      temporizadores = [];
    },
  };

  function programar(espera, accion) {
    const temporizador = setTimeout(() => {
      if (cerrado) return;
      accion();
    }, Math.max(0, Math.round(espera * factor)));
    temporizadores.push(temporizador);
  }

  function emitir(evento) {
    if (cerrado || typeof fuente.onmessage !== "function") return;
    fuente.onmessage({ data: JSON.stringify(evento) });
  }

  function reproducir() {
    if (cerrado) return;
    let acumulado = 0;
    ESCENARIO.forEach(({ espera, evento }) => {
      acumulado += espera;
      programar(acumulado, () => emitir(evento));
    });
    programar(acumulado + PAUSA, reproducir);
  }

  programar(50, () => {
    if (typeof fuente.onopen === "function") fuente.onopen();
  });
  reproducir();

  return fuente;
}
