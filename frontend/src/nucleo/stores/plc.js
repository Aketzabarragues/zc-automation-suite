/**
 * Store del PLC: los PLCs del proyecto, el que esta seleccionado y su
 * contenido (bloques, tablas de tags y tipos de usuario).
 *
 * El estado vive en el backend (la sesion). Este store solo lo refleja: la
 * seleccion y el escaneo se piden al servidor, no se guardan aqui.
 *
 * Todas las operaciones contra TIA son trabajos: el backend responde 202 con
 * el `job_id` y el resultado llega por el stream, en el evento `job`.
 */
import { defineStore } from "pinia";
import {
  buscarPlcs as apiBuscarPlcs,
  escanearPlc,
  seleccionarPlc,
} from "../api.js";
import { datosDemo } from "../demo.js";
import { useTiaStore } from "./tia.js";
import { useTrabajosStore } from "./trabajos.js";

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
  }),

  getters: {
    /** `true` si ya hay un escaneo del PLC seleccionado. */
    escaneado: (state) =>
      state.bloques.length > 0 || state.tablas.length > 0 || state.tipos.length > 0,

    /** El PLC seleccionado, con su designacion. */
    plcActual(state) {
      return state.plcs.find((plc) => plc.nombre === state.seleccionado) || null;
    },
  },

  actions: {
    /**
     * Refleja el estado de la sesion que sirve el backend.
     *
     * @param {object} estado el estado de la sesion.
     */
    aplicarSesion(estado) {
      this.plcs = (estado && estado.plcs) || [];
      this.proyecto = (estado && estado.proyecto) || null;
      this.seleccionado = (estado && estado.plc_seleccionado) || "";
      this.aplicarEscaneo(estado && estado.escaneo);
    },

    /**
     * Refleja un escaneo del backend.
     *
     * @param {object|null} escaneo el escaneo, con sus bloques, tablas y
     *   tipos. `null` deja el PLC vacio.
     */
    aplicarEscaneo(escaneo) {
      if (!escaneo) {
        this.bloques = [];
        this.tablas = [];
        this.tipos = [];
        return;
      }
      this.bloques = escaneo.bloques || [];
      this.tablas = escaneo.tablas || [];
      this.tipos = escaneo.tipos || [];
    },

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
        const respuesta = await apiBuscarPlcs();
        const job = await useTrabajosStore().esperar(respuesta.job_id);
        if (job.estado !== "ok") {
          this.error = job.error || "No se pudieron buscar los PLCs.";
          return;
        }
        const resultado = job.resultado || {};
        this.plcs = resultado.plcs || [];
        this.proyecto = resultado.proyecto || null;
      } catch (error) {
        this.error = error.message;
      }
    },

    /**
     * Selecciona un PLC.
     *
     * La seleccion se guarda en el servidor. Si el PLC tiene un escaneo que
     * sigue valiendo, se enseña; si no, el servidor escanea (una sola vez).
     */
    async seleccionar(nombre) {
      if (!nombre) return;
      this.error = null;
      const tia = useTiaStore();
      if (tia.demo) {
        this.seleccionado = nombre;
        const datos = datosDemo();
        this.bloques = datos.bloques;
        this.tablas = datos.tablas;
        this.tipos = datos.tipos;
        return;
      }
      try {
        const { job_id, escaneo } = await seleccionarPlc(nombre);
        this.seleccionado = nombre;
        if (escaneo) {
          this.aplicarEscaneo(escaneo);
          return;
        }
        this.ocupado = true;
        const job = await useTrabajosStore().esperar(job_id);
        this.ocupado = false;
        if (job.estado !== "ok") {
          this.error = job.error || "No se pudo seleccionar el PLC.";
          return;
        }
        this.aplicarEscaneo(job.resultado || {});
      } catch (error) {
        this.error = error.message;
      }
    },

    /**
     * Escanea el PLC seleccionado. Esto es el "Actualizar": fuerza el
     * escaneo, aunque el de la sesion siga en vigor.
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
        const job = await useTrabajosStore().esperar(respuesta.job_id);
        this.ocupado = false;
        if (job.estado !== "ok") {
          this.error = job.error || "No se pudo escanear el PLC.";
          return;
        }
        this.aplicarEscaneo(job.resultado || {});
      } catch (error) {
        this.error = error.message;
        this.ocupado = false;
      }
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
