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
import { pedir } from "../../../nucleo/api.js";
import { usePlcStore } from "../../../nucleo/stores/plc.js";
import { useSesionStore } from "../../../nucleo/stores/sesion.js";
import { useTiaStore } from "../../../nucleo/stores/tia.js";
import { useTrabajosStore } from "../../../nucleo/stores/trabajos.js";

/** Identificador del area y clave de la prevision en la sesion del backend. */
const ID_AREA = "alimentacion";
const CLAVE_PREVISION = "prevision_dispositivos";

/** Ruta del endpoint de la prevision. */
export const RUTA_PREVIEW = "/api/v1/areas/alimentacion/dispositivos/preview";

/** Ruta del endpoint que aplica los cambios en TIA Portal. */
export const RUTA_SINCRONIZAR = "/api/v1/areas/alimentacion/dispositivos/sincronizar";

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
    /** La ultima prevision, con su shape del backend. */
    preview: null,
    /** El PLC de la prevision: solo vale mientras siga seleccionado. */
    previewPlc: "",
    /** `true` cuando ya se aplico la prevision de la sesion (una vez). */
    hidratado: false,
    /** `true` mientras se genera la prevision. */
    generando: false,
    /** `true` mientras se sincroniza el PLC con el Excel. */
    aplicando: false,
    /** El estado de cada transaccion del ultimo sync. */
    transacciones: [],
    /** Ultimo error de la vista. */
    error: null,
  }),

  getters: {
    /**
     * La prevision que vale ahora: la del PLC seleccionado y con TIA
     * conectado. Si cambia el PLC o se pierde TIA, deja de verse (como main:
     * `area_clear_disp_preview`).
     */
    vigente(state) {
      if (!state.preview) return null;
      if (!useTiaStore().conectado) return null;
      if (state.previewPlc !== usePlcStore().seleccionado) return null;
      return state.preview;
    },

    /** `true` si hay prevision. */
    hayPreview() {
      return Boolean(this.vigente && Array.isArray(this.vigente.todos));
    },

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
    resumen() {
      const prevision = this.vigente;
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
    tarjetasNMax() {
      const prevision = this.vigente;
      if (!prevision) return [];
      return (prevision.nmax && prevision.nmax.todos) || [];
    },

    /** El resumen de los N_MAX. */
    resumenNMax() {
      const prevision = this.vigente;
      if (!prevision || !prevision.nmax) {
        return { actualizar: 0, sin_cambios: 0, total: 0 };
      }
      return prevision.nmax.summary || { actualizar: 0, sin_cambios: 0, total: 0 };
    },

    /**
     * Cuantos cambios van a aplicarse: los dispositivos que se agregan, se
     * renombran o se eliminan, mas los N_MAX que hay que actualizar.
     */
    numeroDeCambios() {
      if (!this.hayPreview) return 0;
      const resumen = this.resumen;
      const nmax = this.resumenNMax;
      return (
        (resumen.agregados || 0) +
        (resumen.renombrados || 0) +
        (resumen.eliminados || 0) +
        (nmax.actualizar || 0)
      );
    },

    /** Cuantas filas del diff hay de cada tipo. */
    contadorPorTipo() {
      const contadores = {};
      for (const pestana of (this.catalog && this.catalog.device_tabs) || []) {
        contadores[pestana.hw_type] = 0;
      }
      const filas = (this.vigente && this.vigente.todos) || [];
      for (const fila of filas) {
        if (contadores[fila.type] !== undefined) contadores[fila.type] += 1;
      }
      return contadores;
    },
  },

  actions: {
    /**
     * Aplica la prevision guardada en la sesion del backend, una sola vez
     * (la foto de la sesion es la de cuando se cargo la pagina).
     */
    hidratar() {
      if (this.hidratado) return;
      this.hidratado = true;
      const estado = useSesionStore().area(ID_AREA);
      const guardada = estado && estado[CLAVE_PREVISION];
      if (guardada && guardada.resultado) {
        this.preview = guardada.resultado;
        this.previewPlc = guardada.plc || "";
      }
    },

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
          this.previewPlc = plc;
          this.hidratado = true;
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

    /**
     * Aplica en TIA Portal los cambios de la prevision.
     *
     * El trabajo devuelve la prevision recalculada y el estado de cada
     * transaccion: lo que se confirmo, lo que se revirtio y lo que no llego
     * a ejecutarse.
     *
     * @param {string} plc el PLC elegido.
     * @returns {Promise<boolean>} si el sync se completo.
     */
    async aplicar(plc) {
      if (!plc) {
        this.error = "Elige un PLC antes de aplicar los cambios.";
        return false;
      }
      this.error = null;
      this.aplicando = true;
      try {
        const datos = await pedir(RUTA_SINCRONIZAR, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ plc }),
        });
        const job = await useTrabajosStore().esperar(datos.job_id);
        if (job.estado === "ok") {
          const resultado = job.resultado || {};
          // Si el backend no pudo recalcular la prevision, esta viene vacia:
          // la vista se queda sin ella.
          this.preview = resultado.prevision || null;
          this.previewPlc = plc;
          this.transacciones = resultado.transacciones || [];
          this.hidratado = true;
          return true;
        }
        this.error = job.error || "No se pudo sincronizar.";
        return false;
      } catch (error) {
        this.error = error.message;
        return false;
      } finally {
        this.aplicando = false;
      }
    },

    /** Limpia la prevision, las transacciones y el error. */
    limpiar() {
      this.preview = null;
      this.previewPlc = "";
      this.transacciones = [];
      this.error = null;
    },
  },
});
