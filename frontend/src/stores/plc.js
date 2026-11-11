/**
 * Store del PLC: los PLCs del proyecto, el que esta seleccionado y su
 * contenido (bloques, tablas de tags y tipos de usuario).
 *
 * Todas las operaciones contra TIA son trabajos: el backend responde 202
 * con el `job_id` y el resultado llega por el stream, en el evento `job`.
 */
import { defineStore } from "pinia";
import { buscarPlcs, escanearPlc } from "../api.js";
import { datosDemo } from "../demo.js";
import { useTiaStore } from "./tia.js";

export const usePlcStore = defineStore("plc", {
  state: () => ({
    /** Los PLCs del proyecto abierto. */
    plcs: [],
    /** Nombre y ruta del proyecto abierto. */
    proyecto: null,
    /** Nombre del PLC seleccionado. */
    seleccionado: "",
    /** Bloques del PLC escaneado. */
    bloques: [],
    /** Tablas de tags del PLC escaneado. */
    tablas: [],
    /** Tipos de datos de usuario del PLC escaneado. */
    tipos: [],
    /** `true` mientras hay un trabajo en curso sobre este PLC. */
    ocupado: false,
    /** Ultimo error de la vista. */
    error: null,
    /** Trabajos encolados por esta vista, esperando su resultado. */
    pendientes: {},
  }),

  getters: {
    /** `true` si ya hay un escaneo del PLC seleccionado. */
    escaneado: (state) => state.bloques.length > 0 || state.tablas.length > 0 || state.tipos.length > 0,

    /** El PLC seleccionado, con su designacion. */
    plcActual(state) {
      return state.plcs.find((plc) => plc.nombre === state.seleccionado) || null;
    },
  },

  actions: {
    /**
     * Encola la busqueda de los PLCs del proyecto abierto.
     */
    async buscarPlcs() {
      this.error = null;
      const tia = useTiaStore();
      if (tia.demo) {
        const datos = datosDemo();
        this.plcs = datos.plcs;
        this.proyecto = datos.proyecto;
        return;
      }
      try {
        const respuesta = await buscarPlcs();
        this.pendientes[respuesta.job_id] = "buscar";
      } catch (error) {
        this.error = error.message;
      }
    },

    /**
     * Encola el escaneo del PLC seleccionado.
     */
    async escanear() {
      if (!this.seleccionado) return;
      this.error = null;
      this.ocupado = true;
      const tia = useTiaStore();
      if (tia.demo) {
        const datos = datosDemo();
        this.bloques = datos.bloques;
        this.tablas = datos.tablas;
        this.tipos = datos.tipos;
        this.ocupado = false;
        return;
      }
      try {
        const respuesta = await escanearPlc(this.seleccionado);
        this.pendientes[respuesta.job_id] = "escanear";
      } catch (error) {
        this.error = error.message;
        this.ocupado = false;
      }
    },

    /**
     * Aplica el resultado de un trabajo que esta vista encoló.
     *
     * @param {object} evento el evento `job`.
     */
    aplicarJob(evento) {
      const etiqueta = this.pendientes[evento.job];
      if (!etiqueta) return;
      delete this.pendientes[evento.job];
      this.ocupado = false;
      if (evento.estado !== "ok") {
        this.error = evento.error || "El trabajo ha fallado.";
        return;
      }
      const resultado = evento.resultado || {};
      if (etiqueta === "buscar") {
        this.plcs = resultado.plcs || [];
        this.proyecto = resultado.proyecto || null;
        return;
      }
      if (etiqueta === "escanear") {
        this.bloques = resultado.bloques || [];
        this.tablas = resultado.tablas || [];
        this.tipos = resultado.tipos || [];
      }
    },

    /** Selecciona un PLC y vacia su contenido anterior. */
    seleccionar(nombre) {
      if (this.seleccionado === nombre) return;
      this.seleccionado = nombre;
      this.bloques = [];
      this.tablas = [];
      this.tipos = [];
      this.error = null;
    },

    /** Vacia el PLC: se usa al desconectar. */
    vaciar() {
      this.plcs = [];
      this.proyecto = null;
      this.seleccionado = "";
      this.bloques = [];
      this.tablas = [];
      this.tipos = [];
      this.error = null;
    },
  },
});
