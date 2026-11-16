/**
 * Store de la sincronizacion de los comentarios de un proceso.
 *
 * La prevision la calcula el backend en un trabajo: el POST responde 202 con
 * el `job_id` y el resultado llega por el stream de eventos. Cuando el
 * trabajo termina, la prevision queda aqui y la vista la pinta.
 *
 * A diferencia de dispositivos y entidades, la prevision es por proceso: el
 * POST lleva el `proc_uid` del proceso elegido en la vista. Cambiar de
 * proceso limpia la prevision anterior para no ver el diff del proceso
 * equivocado.
 */
import { defineStore } from "pinia";
import { pedir } from "../../../nucleo/api.js";
import { usePlcStore } from "../../../nucleo/stores/plc.js";
import { useSesionStore } from "../../../nucleo/stores/sesion.js";
import { useTiaStore } from "../../../nucleo/stores/tia.js";
import { useTrabajosStore } from "../../../nucleo/stores/trabajos.js";

/** Identificador del area y clave de la prevision en la sesion del backend. */
const ID_AREA = "alimentacion";
const CLAVE_PREVISION = "prevision_procesos";

/** Ruta del endpoint de la prevision. */
export const RUTA_PREVIEW = "/api/v1/areas/alimentacion/procesos/preview";

/** Ruta del endpoint que aplica los cambios en TIA Portal. */
export const RUTA_SINCRONIZAR = "/api/v1/areas/alimentacion/procesos/sincronizar";

/**
 * Los estados de un slot y como se pintan.
 *
 * Mismos labels y colores que las vistas de dispositivos y entidades: la
 * fuente unica de verdad para las acciones del diff.
 */
export const PROC_STATUS = Object.freeze({
  agregar: { label: "➕ AGREGAR", clase: "text-accent font-semibold" },
  renombrar: { label: "✏️ RENOMBRAR", clase: "text-amber-700 font-semibold" },
  eliminar: { label: "🗑️ ELIMINAR", clase: "text-red-700 font-semibold" },
  sin_cambios: { label: "✓ OK", clase: "text-ink-muted" },
});

/** Los arrays del proceso, en el orden de las pestanas. */
export const ARRAYS = Object.freeze(["PReal", "PInt", "ALM"]);

/**
 * Las etiquetas legibles de los N_MAX, por kind.
 *
 * La constante de TIA se llama `100_N_MAX_PREAL` (kind + uid): al operario
 * le interesa el sufijo humano. Un kind que no esta aqui usa el `name` de
 * la constante.
 */
export const ETIQUETAS_NMAX = Object.freeze({
  preal: "N_MAX PReal",
  pint: "N_MAX PInt",
  alm: "N_MAX Alarmas",
});

/** El orden de las pestanas cuando el operario no ha elegido ninguna. */
export const useProcesosStore = defineStore("procesos", {
  state: () => ({
    /** El uid del proceso seleccionado en la vista. */
    procUid: null,
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
    /** Momento del ultimo apply terminado bien, en ISO. */
    aplicadoEn: null,
  }),

  getters: {
    /**
     * La prevision que vale ahora: la del PLC seleccionado y con TIA
     * conectado. Si cambia el PLC o se pierde TIA, deja de verse.
     */
    vigente(state) {
      if (!state.preview) return null;
      if (!useTiaStore().conectado) return null;
      if (state.previewPlc !== usePlcStore().seleccionado) return null;
      return state.preview;
    },

    /** `true` si hay prevision. */
    hayPreview() {
      const preview = this.vigente;
      return Boolean(preview && preview.precondiciones_ok);
    },

    /** El resumen de la prevision: cuantos hay de cada. */
    resumen() {
      const preview = this.vigente;
      if (!preview) return { agregados: 0, renombrados: 0, eliminados: 0, sin_cambios: 0, total: 0 };
      return preview.summary || { agregados: 0, renombrados: 0, eliminados: 0, sin_cambios: 0, total: 0 };
    },

    /** Las tarjetas de N_MAX: todas las del resultado. */
    tarjetasNMax() {
      const preview = this.vigente;
      if (!preview || !preview.nmax) return [];
      return preview.nmax.todos || [];
    },

    /** El resumen de los N_MAX. */
    resumenNMax() {
      const preview = this.vigente;
      if (!preview || !preview.nmax) return { actualizar: 0, sin_cambios: 0, total: 0 };
      return preview.nmax.summary || { actualizar: 0, sin_cambios: 0, total: 0 };
    },

    /**
     * La etiqueta legible de una tarjeta de N_MAX: la del kind conocido
     * (`preal`, `pint`, `alm`) o, si no, el nombre de la constante.
     *
     * @param {object} tarjeta la tarjeta de N_MAX del backend.
     */
    etiquetaNMax: () => (tarjeta) => {
      if (!tarjeta) return "";
      return ETIQUETAS_NMAX[tarjeta.kind] || tarjeta.name || tarjeta.kind || "";
    },

    /**
     * Cuantos cambios van a aplicarse: los slots que se agregan, se renombran
     * o se eliminan, mas los N_MAX que hay que actualizar.
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

    /**
     * Las filas de un array, ordenadas por slot.
     *
     * @param {string} array uno de `PReal`, `PInt` o `ALM`.
     * @returns {Array<{slot: number, current: string|null, desired: string|null, action: string}>}
     */
    filasDe: (state) => (array) => {
      const preview = state.vigente || state.preview;
      if (!preview || !preview.arrays) return [];
      const arr = preview.arrays[array];
      if (!arr || !arr.slot_map) return [];
      return Object.keys(arr.slot_map)
        .map((clave) => {
          const entrada = arr.slot_map[clave];
          return {
            slot: parseInt(clave, 10),
            current: entrada.current,
            desired: entrada.desired,
            action: entrada.action,
          };
        })
        .sort((a, b) => a.slot - b.slot);
    },

    /**
     * El numero de cambios de un array (renombrar + agregar + eliminar),
     * del `summary` que calcula el backend.
     *
     * @param {string} array uno de `PReal`, `PInt` o `ALM`.
     */
    cambiosDe: (state) => (array) => {
      const preview = state.vigente || state.preview;
      const arr = preview && preview.arrays && preview.arrays[array];
      const summary = (arr && arr.summary) || {};
      return (
        (summary.agregados || 0) + (summary.renombrados || 0) + (summary.eliminados || 0)
      );
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
        this.procUid = guardada.proc_uid ?? null;
      }
    },

    /**
     * Elige el proceso activo. Cambiar de proceso limpia la prevision
     * anterior: no vale para el nuevo proceso.
     *
     * @param {number|null} uid el uid del proceso, o `null` para ninguno.
     */
    elegir(uid) {
      if (uid === this.procUid) return;
      this.procUid = uid;
      if (uid === null) return;
      this.preview = null;
      this.previewPlc = "";
      this.transacciones = [];
      this.aplicadoEn = null;
      this.error = null;
    },

    /**
     * Genera la prevision de los comentarios del proceso elegido.
     *
     * @param {string} plc el PLC elegido.
     * @param {number} procUid el uid del proceso.
     * @returns {Promise<boolean>} si se lanzo el trabajo.
     */
    async generar(plc, procUid) {
      if (!plc) {
        this.error = "Elige un PLC antes de generar la prevision.";
        return false;
      }
      if (procUid == null) {
        this.error = "Elige un proceso antes de generar la prevision.";
        return false;
      }
      this.error = null;
      this.generando = true;
      try {
        const datos = await pedir(RUTA_PREVIEW, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ plc, proc_uid: procUid }),
        });
        const job = await useTrabajosStore().esperar(datos.job_id);
        if (job.estado === "ok") {
          this.preview = job.resultado;
          this.previewPlc = plc;
          this.procUid = procUid;
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
     * @param {number} procUid el uid del proceso.
     * @returns {Promise<boolean>} si el sync se completo.
     */
    async aplicar(plc, procUid) {
      if (!plc) {
        this.error = "Elige un PLC antes de aplicar los cambios.";
        return false;
      }
      if (procUid == null) {
        this.error = "Elige un proceso antes de aplicar los cambios.";
        return false;
      }
      this.error = null;
      this.aplicando = true;
      try {
        const datos = await pedir(RUTA_SINCRONIZAR, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ plc, proc_uid: procUid }),
        });
        const job = await useTrabajosStore().esperar(datos.job_id);
        if (job.estado === "ok") {
          const resultado = job.resultado || {};
          // Si el backend no pudo recalcular la prevision, esta viene vacia:
          // la vista se queda sin ella.
          this.preview = resultado.prevision || null;
          this.previewPlc = plc;
          this.procUid = procUid;
          this.transacciones = resultado.transacciones || [];
          this.aplicadoEn = new Date().toISOString();
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
      this.aplicadoEn = null;
      this.error = null;
    },
  },
});
