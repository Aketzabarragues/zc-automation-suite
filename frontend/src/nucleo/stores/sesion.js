/**
 * Store de la sesion: el estado que tiene el backend.
 *
 * La sesion vive en la memoria del backend. La SPA la pide al hidratarse
 * (un `GET /api/v1/sesion`) y sus stores solo la reflejan: no guardan nada
 * propio que se pierda con un F5.
 */
import { defineStore } from "pinia";
import { estadoSesion } from "../api.js";
import { usePlcStore } from "./plc.js";
import { useTiaStore } from "./tia.js";

export const useSesionStore = defineStore("sesion", {
  state: () => ({
    /** El estado de la sesion, tal y como lo sirve el backend. */
    estado: null,
    /** `true` cuando ya se ha hidratado (o se ha intentado). */
    hidratada: false,
    /** `true` mientras se pide el estado. */
    cargando: false,
    /** Ultimo error de la hidratacion. */
    error: null,
  }),

  getters: {
    /**
     * Lo que tiene un area en la sesion.
     *
     * @param {string} id identificador del area.
     * @returns {object|null} el estado del area, o `null` si no lo tiene.
     */
    area: (state) => (id) => {
      const areas = (state.estado && state.estado.areas) || {};
      return areas[id] || null;
    },
  },

  actions: {
    /**
     * Pide el estado de la sesion al backend y lo refleja en los stores.
     *
     * Es lo que hace la SPA al cargar: un F5 no pierde nada de lo que hay
     * en el servidor.
     */
    async hidratar() {
      const tia = useTiaStore();
      if (tia.demo) {
        // En el demo no hay backend detras: la sesion la inventamos.
        this.hidratada = true;
        return;
      }
      this.cargando = true;
      this.error = null;
      try {
        const datos = await estadoSesion();
        this.estado = datos;
        this.hidratada = true;
        tia.aplicarSesion(datos.tia || {});
        usePlcStore().aplicarSesion(datos);
      } catch (error) {
        this.error = error.message;
      } finally {
        this.cargando = false;
      }
    },
  },
});
