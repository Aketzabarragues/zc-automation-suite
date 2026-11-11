/**
 * Store de los trabajos: el avance de la operacion en curso y el resultado
 * del ultimo trabajo terminado.
 *
 * Los dos vienen del backend por el stream de eventos: `progress` cambia el
 * avance y `job` cierra el trabajo.
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
export const MAXIMO_HISTORIAL = 50;

export const useTrabajosStore = defineStore("trabajos", {
  state: () => ({
    /** Espejo del avance del trabajo en curso. */
    progreso: { ...PROGRESO_VACIO },
    /** Ultimo trabajo terminado. */
    ultimoJob: null,
    /** Historial de trabajos terminados, del mas reciente al mas antiguo. */
    historial: [],
  }),

  actions: {
    /**
     * Aplica un evento `progress` o `job` del backend.
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
      if (evento.type === "job") {
        this.ultimoJob = {
          job: evento.job,
          estado: evento.estado,
          error: evento.error || null,
        };
        this.historial.unshift(this.ultimoJob);
        if (this.historial.length > MAXIMO_HISTORIAL) {
          this.historial.pop();
        }
      }
    },

    /** Limpia el faceplate de progreso. */
    limpiarProgreso() {
      this.progreso = { ...PROGRESO_VACIO };
    },
  },
});
