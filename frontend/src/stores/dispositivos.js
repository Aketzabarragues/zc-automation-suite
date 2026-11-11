/**
 * Store de la prevision de dispositivos.
 *
 * La prevision la calcula el backend en un trabajo: el POST responde 202 con
 * el `job_id` y el resultado llega por el stream de eventos. Cuando el
 * trabajo termina, la prevision queda aqui y la vista la pinta.
 */
import { defineStore } from "pinia";
import { pedir } from "../api.js";
import { useTrabajosStore } from "./trabajos.js";

/** Ruta del endpoint de la prevision. */
export const RUTA_PREVIEW = "/api/v1/areas/alimentacion/dispositivos/preview";

export const useDispositivosStore = defineStore("dispositivos", {
  state: () => ({
    /** La prevision en curso, con su shape del backend. */
    preview: null,
    /** `true` mientras se genera la prevision. */
    generando: false,
    /** Ultimo error de la vista. */
    error: null,
  }),

  getters: {
    /** `true` si hay prevision. */
    hayPreview: (state) => Boolean(state.preview),

    /** El resumen de la prevision: cuantos hay de cada. */
    resumen: (state) => (state.preview && state.preview.summary) || {},

    /** Los N_MAX de la prevision, uno por cada. */
    nMax: (state) => (state.preview && state.preview.nmax && state.preview.nmax.todos) || [],

    /** Las filas del diff, agrupadas por tipo de dispositivo. */
    filasPorTipo: (state) => {
      const grupos = new Map();
      const filas = (state.preview && state.preview.todos) || [];
      for (const fila of filas) {
        if (!grupos.has(fila.type)) grupos.set(fila.type, []);
        grupos.get(fila.type).push(fila);
      }
      return grupos;
    },

    /** Los tipos de dispositivo, con su contador de filas. */
    tipos: (state) => {
      const grupos = new Map();
      const filas = (state.preview && state.preview.todos) || [];
      for (const fila of filas) {
        grupos.set(fila.type, (grupos.get(fila.type) || 0) + 1);
      }
      return [...grupos.entries()].map(([tipo, total]) => ({ tipo, total }));
    },

    /** Los cambios que se aplicarian en TIA (agregar + renombrar). */
    totalCambios: (state) => {
      const resumen = (state.preview && state.preview.summary) || {};
      return (resumen.agregar || 0) + (resumen.renombrados || 0);
    },
  },

  actions: {
    /**
     * Genera la prevision de los dispositivos del PLC.
     *
     * @param {string} plc el PLC elegido.
     * @returns {Promise<boolean>} si se lanzo el trabajo.
     */
    async generar(plc) {
      if (!plc) {
        this.error = "Elige un PLC antes de generar la prevision.";
        return false;
      }
      this.error = null;
      this.generando = true;
      try {
        const datos = await pedir(RUTA_PREVIEW, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ plc }),
        });
        const job = await useTrabajosStore().esperar(datos.job_id);
        if (job.estado === "ok") {
          this.preview = job.resultado;
          return true;
        }
        this.error = job.error || "No se pudo generar la prevision.";
        return false;
      } catch (error) {
        this.error = error.message;
        return false;
      } finally {
        this.generando = false;
      }
    },

    /** Limpia la prevision y el error. */
    limpiar() {
      this.preview = null;
      this.error = null;
    },
  },
});
