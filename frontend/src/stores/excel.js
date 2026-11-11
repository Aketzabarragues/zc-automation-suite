/**
 * Store del Excel maestro del area de alimentacion.
 *
 * El backend guarda el Excel parseado en su cache: la vista solo consulta
 * ese volcado. Subir un fichero es un trabajo: el POST responde 202 con el
 * `job_id` y el resultado del parseo llega por el stream, asi que los datos
 * se recargan cuando el trabajo termina.
 */
import { defineStore } from "pinia";
import { pedir } from "../api.js";
import { useTrabajosStore } from "./trabajos.js";

/** Ruta de los endpoints del Excel maestro. */
export const RUTA_EXCEL = "/api/v1/areas/alimentacion/excel";

export const useExcelStore = defineStore("excel", {
  state: () => ({
    /** `true` si el backend tiene un Excel maestro cargado. */
    cargado: false,
    /** Nombre del ultimo archivo cargado. */
    archivo: null,
    /** Momento de la carga, en ISO. */
    cargadoEn: null,
    /** El volcado del Excel, tal y como lo devuelve el backend. */
    datos: null,
    /** Ultimo error de la vista. */
    error: null,
    /** `true` mientras se sube un fichero. */
    subiendo: false,
  }),

  getters: {
    /** Los dispositivos por tipo: una tabla por tipo, en el orden del config. */
    dispositivos: (state) => (state.datos && state.datos.dispositivos) || [],

    /** Los procesos por subdominio: `Procesos`, `Alarmas`, ... */
    procesos: (state) => (state.datos && state.datos.procesos) || {},

    /** La tabla de entidades, o `null` si el Excel no la trae. */
    entidades: (state) => (state.datos && state.datos.entidades) || null,

    /** La tabla de configuracion (N_MAX por PLC), o `null`. */
    configuracion: (state) => (state.datos && state.datos.configuracion) || null,

    /** Cuantas filas hay en cada dominio. */
    contadores() {
      const filas = (tabla) => (tabla && Array.isArray(tabla.filas) ? tabla.filas.length : 0);
      const suma = (grupo) =>
        Object.values(grupo || {}).reduce((total, tabla) => total + filas(tabla), 0);
      return {
        configuracion: filas(this.configuracion),
        dispositivos: (this.dispositivos || []).reduce(
          (total, tabla) => total + filas(tabla),
          0,
        ),
        procesos: suma(this.procesos),
        entidades: filas(this.entidades),
      };
    },
  },

  actions: {
    /**
     * Carga el volcado del Excel que tiene el backend.
     */
    async cargar() {
      try {
        const datos = await pedir(RUTA_EXCEL);
        this.cargado = Boolean(datos.cargado);
        this.archivo = datos.archivo || null;
        this.cargadoEn = datos.cargado_en || null;
        this.datos = datos || null;
        this.error = null;
      } catch (error) {
        this.error = error.message;
      }
    },

    /**
     * Sube un fichero Excel al backend.
     *
     * El backend responde 202 con el `job_id`: el parseo va en un trabajo y
     * su resultado llega por el stream, no en la respuesta.
     *
     * @param {File} fichero el fichero a subir.
     * @returns {Promise<string|null>} el `job_id` del trabajo, o `null` si la
     *   subida fallo.
     */
    async subir(fichero) {
      if (!fichero) return null;
      this.error = null;
      this.subiendo = true;
      const cuerpo = new FormData();
      cuerpo.append("fichero", fichero);
      try {
        // El `Content-Type` no se pone: el navegador pone el del multipart
        // con su frontera.
        const respuesta = await fetch(RUTA_EXCEL, {
          method: "POST",
          body: cuerpo,
          credentials: "same-origin",
        });
        const datos = await respuesta.json().catch(() => ({}));
        if (!respuesta.ok) {
          throw new Error(datos.error || `Error ${respuesta.status}`);
        }
        const jobId = datos.job_id || null;
        if (jobId) this.recargarAlTerminar(jobId);
        return jobId;
      } catch (error) {
        this.error = error.message;
        return null;
      } finally {
        this.subiendo = false;
      }
    },

    /**
     * Recarga los datos cuando termina el trabajo de parseo.
     *
     * @param {string} job_id identificador del trabajo de la subida.
     */
    async recargarAlTerminar(job_id) {
      const trabajos = useTrabajosStore();
      const job = await trabajos.esperar(job_id);
      if (job.estado === "ok") {
        await this.cargar();
        return;
      }
      if (job.estado === "error") {
        this.error = job.error || "No se pudo cargar el Excel.";
      }
    },

    /** Limpia el error de la vista. */
    limpiarError() {
      this.error = null;
    },
  },
});
