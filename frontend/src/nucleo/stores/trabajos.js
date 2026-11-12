/**
 * Store de los trabajos: el avance de la operacion en curso y el resultado
 * de los trabajos terminados.
 *
 * Un trabajo se lanza con un POST que responde 202 y el ``job_id``. Su
 * resultado llega por el stream, en el evento ``job``. Las dos cosas pueden
 * llegar **en cualquier orden**: si el trabajo es rapido, el evento sale
 * antes de que la respuesta del POST llegue al navegador.
 *
 * Por eso el store guarda los trabajos terminados por id: ``esperar()``
 * devuelve el resultado tanto si el evento ya llego como si llega después.
 */
import { defineStore } from "pinia";

/** Estado de progreso vacio. */
export const PROGRESO_VACIO = {
  active: false,
  operation: null,
  label: null,
  current: 0,
  total: 0,
  percent: 0,
  stages: [],
  started_at: null,
  finished_at: null,
  error: null,
};

/** Cuantos trabajos terminados se guardan. */
export const MAXIMO_TERMINADOS = 50;

/**
 * Los resolutores de las esperas, fuera del store: son funciones y no
 * tienen por que ser reactivas.
 */
const ESPERAS = new Map();

export const useTrabajosStore = defineStore("trabajos", {
  state: () => ({
    /** Espejo del avance del trabajo en curso. */
    progreso: { ...PROGRESO_VACIO },
    /** Ultimo trabajo terminado. */
    ultimoJob: null,
    /** Historial de trabajos terminados, del mas reciente al mas antiguo. */
    historial: [],
    /** Los ultimos trabajos terminados, indexados por ``job_id``. */
    terminados: {},
  }),

  actions: {
    /**
     * Aplica un evento ``progress`` o ``job`` del backend.
     *
     * @param {object} evento el evento.
     */
    aplicar(evento) {
      if (evento.type === "progress") {
        const instantanea = { ...evento };
        delete instantanea.type;
        this.progreso = { ...PROGRESO_VACIO, ...instantanea };
        return;
      }
      if (evento.type !== "job") return;

      const registro = {
        job: evento.job,
        estado: evento.estado,
        resultado: evento.resultado ?? null,
        error: evento.error || null,
      };
      this.ultimoJob = registro;
      this.historial.unshift(registro);
      if (this.historial.length > MAXIMO_TERMINADOS) {
        this.historial.pop();
      }

      this.terminados[evento.job] = registro;
      const ids = Object.keys(this.terminados);
      if (ids.length > MAXIMO_TERMINADOS) {
        for (const id of ids.slice(0, ids.length - MAXIMO_TERMINADOS)) {
          delete this.terminados[id];
        }
      }

      // Despertar a quien esperaba este trabajo.
      const esperas = ESPERAS.get(evento.job);
      if (esperas) {
        ESPERAS.delete(evento.job);
        for (const resolver of esperas) resolver(registro);
      }
    },

    /**
     * Espera a que termine un trabajo.
     *
     * @param {string} job_id identificador del trabajo.
     * @returns {Promise<object>} ``{job, estado, resultado, error}``. Se
     *   resuelve en el momento si el trabajo ya termino.
     */
    esperar(job_id) {
      const terminado = this.terminados[job_id];
      if (terminado) return Promise.resolve(terminado);
      return new Promise((resolve) => {
        const esperas = ESPERAS.get(job_id) || [];
        esperas.push(resolve);
        ESPERAS.set(job_id, esperas);
      });
    },

    /** Limpia el faceplate de progreso. */
    limpiarProgreso() {
      this.progreso = { ...PROGRESO_VACIO };
    },
  },
});
