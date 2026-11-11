/**
 * Store de la conexion con TIA Portal.
 *
 * La fuente de verdad es el evento `tia` del backend. Las acciones solo
 * encolan el trabajo: el resultado llega por el stream.
 */
import { defineStore } from "pinia";
import { conectar as conectarTia, desconectar as desconectarTia } from "../api.js";
import { usePlcStore } from "./plc.js";
import { useTrabajosStore } from "./trabajos.js";

export const useTiaStore = defineStore("tia", {
  state: () => ({
    /** `true` si hay portal abierto y el hilo de TIA sigue vivo. */
    conectado: false,
    /** Version del TIA Portal conectado. Vacia si no se sabe. */
    version_tia: "",
    /** Ultimo error de la conexion. */
    ultimo_error: null,
    /** Identificador del trabajo en curso, si lo hay. */
    trabajo_actual: null,
    /** Estado del stream de eventos. */
    estadoStream: "cerrado",
    /** `true` en el modo demo (`?demo=1`): no hay backend detras. */
    demo: false,
    /** Aviso de la ultima accion. */
    aviso: null,
  }),

  getters: {
    /** Texto del estado de la conexion. */
    etiqueta: (state) => (state.conectado ? "connected" : "idle"),
    /** `true` si el stream de eventos no esta vivo. */
    streamCaido: (state) => state.estadoStream !== "conectado",
  },

  actions: {
    /**
     * Aplica un evento `tia` del backend.
     *
     * @param {object} evento el evento.
     */
    aplicar(evento) {
      this.conectado = Boolean(evento.conectado);
      this.version_tia = evento.version_tia || "";
      this.ultimo_error = evento.ultimo_error || null;
      this.trabajo_actual = evento.trabajo_actual || null;
      if (this.demo && this.conectado) {
        // En el demo, conectar es buscar los PLCs: los datos simulados.
        usePlcStore().buscarPlcs();
      }
    },

    /** Encola la conexion con TIA Portal. */
    async conectar() {
      this.aviso = null;
      if (this.demo) {
        this.conectado = true;
        this.version_tia = this.version_tia || "V21.0";
        usePlcStore().buscarPlcs();
        return;
      }
      try {
        const respuesta = await conectarTia();
        const job = await useTrabajosStore().esperar(respuesta.job_id);
        if (job.estado !== "ok") {
          this.aviso = job.error || "No se pudo conectar con TIA Portal.";
          return;
        }
        // Conectar bien es buscar los PLCs: es lo que ve el operario en la
        // lista de "PLC disponibles".
        usePlcStore().buscarPlcs();
      } catch (error) {
        this.aviso = error.message;
      }
    },

    /** Encola la desconexion de TIA Portal. */
    async desconectar() {
      this.aviso = null;
      if (this.demo) {
        this.conectado = false;
        usePlcStore().vaciar();
        return;
      }
      try {
        const respuesta = await desconectarTia();
        const job = await useTrabajosStore().esperar(respuesta.job_id);
        if (job.estado !== "ok") {
          this.aviso = job.error || "No se pudo desconectar de TIA Portal.";
          return;
        }
        usePlcStore().vaciar();
      } catch (error) {
        this.aviso = error.message;
      }
    },
  },
});
