/**
 * Store de la prevision de dispositivos.
 *
 * La prevision la calcula el backend en un trabajo: el POST responde 202 con
 * el `job_id` y el resultado llega por el stream de eventos. Cuando el
 * trabajo termina, la prevision queda aqui y la vista la pinta.
 *
 * Las pestañas por tipo y las etiquetas de las tarjetas de N_MAX salen del
 * catalogo del backend (`GET /api/v1/catalog`), igual que en la app original.
 */
import { defineStore } from "pinia";
import { pedir } from "../api.js";
import { useTrabajosStore } from "./trabajos.js";

/** Ruta del endpoint de la prevision. */
export const RUTA_PREVIEW = "/api/v1/areas/alimentacion/dispositivos/preview";

/** Ruta del catalogo de la app. */
export const RUTA_CATALOGO = "/api/v1/catalog";

/** Los estados del diff y como se pintan. */
export const DISP_STATUS = Object.freeze({
  agregar: { label: "➕ AGREGAR", clase: "text-accent font-semibold" },
  renombrar: { label: "✏️ RENOMBRAR", clase: "text-amber-700 font-semibold" },
  eliminar: { label: "🗑️ ELIMINAR", clase: "text-red-700 font-semibold" },
  sin_cambios: { label: "✓ OK", clase: "text-ink-muted" },
});

export const useDispositivosStore = defineStore("dispositivos", {
  state: () => ({
    /** El catalogo del area: las pestañas y las etiquetas de los N_MAX. */
    catalog: null,
    /** La prevision en curso, con su shape del backend. */
    preview: null,
    /** `true` mientras se genera la prevision. */
    generando: false,
    /** Ultimo error de la vista. */
    error: null,
  }),

  getters: {
    /** `true` si hay prevision. */
    hayPreview: (state) => Boolean(state.preview && Array.isArray(state.preview.todos)),

    /** Las pestañas por tipo de dispositivo, en el orden del config. */
    pestanas: (state) => (state.catalog && state.catalog.device_tabs) || [],

    /** El mapa ``nombre del N_MAX -> etiqueta`` de las tarjetas. */
    etiquetaNMax: (state) => {
      const mapa = {};
      for (const entrada of (state.catalog && state.catalog.nmax) || []) {
        mapa[entrada.name] = entrada.label;
      }
      return mapa;
    },

    /** El resumen de la prevision: cuantos hay de cada. */
    resumen: (state) => {
      const prevision = state.preview;
      if (!prevision || !Array.isArray(prevision.todos)) {
        return { agregados: 0, renombrados: 0, eliminados: 0, sin_cambios: 0, total: 0 };
      }
      const resumen = prevision.summary || {};
      return {
        agregados: resumen.agregados ?? (prevision.agregados || []).length,
        renombrados: resumen.renombrados ?? (prevision.renombrados || []).length,
        eliminados: resumen.eliminados ?? (prevision.eliminados || []).length,
        sin_cambios: resumen.sin_cambios ?? 0,
        total: resumen.total ?? (prevision.todos || []).length,
      };
    },

    /** Las tarjetas de N_MAX: todas las del resultado. */
    tarjetasNMax: (state) => {
      const prevision = state.preview;
      if (!prevision) return [];
      return (prevision.nmax && prevision.nmax.todos) || [];
    },

    /** El resumen de los N_MAX. */
    resumenNMax: (state) => {
      const prevision = state.preview;
      if (!prevision || !prevision.nmax) {
        return { actualizar: 0, sin_cambios: 0, total: 0 };
      }
      return prevision.nmax.summary || { actualizar: 0, sin_cambios: 0, total: 0 };
    },

    /** Cuantas filas del diff hay de cada tipo. */
    contadorPorTipo: (state) => {
      const contadores = {};
      for (const pestana of (state.catalog && state.catalog.device_tabs) || []) {
        contadores[pestana.hw_type] = 0;
      }
      const filas = (state.preview && state.preview.todos) || [];
      for (const fila of filas) {
        if (contadores[fila.type] !== undefined) contadores[fila.type] += 1;
      }
      return contadores;
    },
  },

  actions: {
    /**
     * Carga el catalogo del area: las pestañas y las etiquetas.
     */
    async cargarCatalogo() {
      try {
        const datos = await pedir(RUTA_CATALOGO);
        this.catalog = (datos && datos.alimentacion) || null;
      } catch (error) {
        this.error = error.message;
      }
    },

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
