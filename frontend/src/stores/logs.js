/**
 * Store de la consola de trazabilidad.
 *
 * Cada linea de log del backend llega por el evento `log`. Si el registro
 * traia excepcion, el traceback viaja en `detalle` y se muestra desplegado
 * bajo el mensaje.
 */
import { defineStore } from "pinia";

/** Cuantas lineas se guardan antes de empezar a descartar las antiguas. */
export const MAXIMO_MENSAJES = 500;

export const useLogsStore = defineStore("logs", {
  state: () => ({
    /** Las lineas de log, en orden de llegada. */
    mensajes: [],
    /** Contador de lineas, para poder distinguir unas de otras. */
    contador: 0,
  }),

  getters: {
    /** Las lineas invertidas: la mas reciente arriba. */
    invertidos: (state) => [...state.mensajes].reverse(),
  },

  actions: {
    /**
     * Aplica un evento `log` del backend.
     *
     * @param {object} evento el evento.
     */
    aplicar(evento) {
      this.contador += 1;
      this.mensajes.push({
        id: this.contador,
        nivel: evento.nivel || "info",
        mensaje: evento.mensaje || "",
        detalle: evento.detalle || null,
        hora: new Date().toLocaleTimeString("es-ES", { hour12: false }),
      });
      if (this.mensajes.length > MAXIMO_MENSAJES) {
        this.mensajes.shift();
      }
    },

    /** Vacia la consola. */
    limpiar() {
      this.mensajes = [];
    },
  },
});
