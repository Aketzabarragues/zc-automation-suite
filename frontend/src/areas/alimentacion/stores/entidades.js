/**
 * Store de la prevision de entidades.
 *
 * La prevision la calcula el backend en un trabajo: el POST responde 202 con
 * el `job_id` y el resultado llega por el stream de eventos. Cuando el
 * trabajo termina, la prevision queda aqui y la vista la pinta.
 *
 * Las entidades son un solo tipo: no hay pestañas ni catalogo. Lo unico que
 * sale del catalogo es la etiqueta del N_MAX.
 */
import { defineStore } from "pinia";
import { pedir } from "../../../nucleo/api.js";
import { usePlcStore } from "../../../nucleo/stores/plc.js";
import { useSesionStore } from "../../../nucleo/stores/sesion.js";
import { useTiaStore } from "../../../nucleo/stores/tia.js";
import { useTrabajosStore } from "../../../nucleo/stores/trabajos.js";

/** Identificador del area y clave de la prevision en la sesion del backend. */
const ID_AREA = "alimentacion";
const CLAVE_PREVISION = "prevision_entidades";

/** Ruta del endpoint de la prevision. */
export const RUTA_PREVIEW = "/api/v1/areas/alimentacion/entidades/preview";

/** Ruta del endpoint que aplica los cambios en TIA Portal. */
export const RUTA_SINCRONIZAR = "/api/v1/areas/alimentacion/entidades/sincronizar";

/** Ruta del catalogo de la app. */
export const RUTA_CATALOGO = "/api/v1/catalog";

/** Los estados del diff y como se pintan. */
export const ENT_STATUS = Object.freeze({
  agregar: { label: "➕ AGREGAR", clase: "text-accent font-semibold" },
  renombrar: { label: "✏️ RENOMBRAR", clase: "text-amber-700 font-semibold" },
  eliminar: { label: "🗑️ ELIMINAR", clase: "text-red-700 font-semibold" },
  sin_cambios: { label: "✓ OK", clase: "text-ink-muted" },
});

/** El orden de los estados cuando dos filas tienen el mismo tag. */
const ORDEN_ESTADOS = Object.freeze({ eliminar: 0, renombrar: 1, agregar: 2, sin_cambios: 3 });

export const useEntidadesStore = defineStore("entidades", {
  state: () => ({
    /** El catalogo del area: solo la etiqueta del N_MAX. */
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
     * conectado. Si cambia el PLC o se pierde TIA, deja de verse.
     */
    vigente(state) {
      if (!state.preview) return null;
      if (!useTiaStore().conectado) return null;
      if (state.previewPlc !== usePlcStore().seleccionado) return null;
      return state.preview;
    },

    /** `true` si hay prevision con las precondiciones cumplidas. */
    hayPreview() {
      const prevision = this.vigente;
      return Boolean(prevision && prevision.precondiciones_ok === true);
    },

    /** Las operaciones de la prevision, en el orden del backend. */
    ops() {
      const prevision = this.vigente;
      return (prevision && prevision.ops) || [];
    },

    /**
     * El resumen de la prevision: cuantas hay de cada.
     *
     * ``total`` es el numero de entidades del Excel: las que el operario ha
     * declarado. ``sin_cambios`` son las que ya estan en TIA con el mismo
     * valor y el mismo comentario.
     */
    resumen() {
      if (!this.hayPreview) {
        return { agregados: 0, renombrados: 0, eliminados: 0, sin_cambios: 0, total: 0 };
      }
      const ops = this.ops;
      const desired = (this.vigente.entities_block && this.vigente.entities_block.desired) || {};
      return {
        agregados: ops.filter((op) => op.kind === "add").length,
        renombrados: ops.filter((op) => op.kind === "rename" || op.kind === "update_comment").length,
        eliminados: ops.filter((op) => op.kind === "delete").length,
        sin_cambios: ops.filter((op) => op.kind === "sin_cambios").length,
        total: Object.keys(desired).length,
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

    /** El mapa ``nombre del N_MAX -> etiqueta`` de las tarjetas. */
    etiquetaNMax: (state) => {
      const mapa = {};
      for (const entrada of (state.catalog && state.catalog.nmax) || []) {
        mapa[entrada.name] = entrada.label;
      }
      return mapa;
    },

    /**
     * Cuantos cambios van a aplicarse: las entidades que se agregan, se
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

    /**
     * Las filas de la tabla, una por operacion, con el estado de cada una.
     *
     * El Excel manda: una fila de alta solo tiene el tag y el comentario del
     * Excel; una de baja solo tiene lo que hay en TIA.
     */
    filas() {
      if (!this.hayPreview) return [];
      const filas = this.ops.map((op) => {
        if (op.kind === "delete") {
          return {
            plc_tag: op.plc_tag,
            status: "eliminar",
            numero_tia: op.value_tia,
            numero_excel: null,
            comment_tia: null,
            comment_excel: null,
          };
        }
        if (op.kind === "add") {
          return {
            plc_tag: op.plc_tag,
            status: "agregar",
            numero_tia: null,
            numero_excel: op.value_excel,
            comment_tia: null,
            comment_excel: op.comment_excel || null,
          };
        }
        if (op.kind === "rename") {
          return {
            plc_tag: `${op.plc_tag_tia} -> ${op.plc_tag_new}`,
            status: "renombrar",
            numero_tia: op.value_tia,
            numero_excel: op.value_tia,
            comment_tia: null,
            comment_excel: null,
          };
        }
        if (op.kind === "update_comment") {
          return {
            plc_tag: op.plc_tag,
            status: "renombrar",
            numero_tia: op.value_tia,
            numero_excel: op.value_tia,
            comment_tia: op.comment_tia || null,
            comment_excel: op.comment_excel || null,
          };
        }
        if (op.kind === "sin_cambios") {
          return {
            plc_tag: op.plc_tag,
            status: "sin_cambios",
            numero_tia: op.value_tia,
            numero_excel: op.value_tia,
            comment_tia: null,
            comment_excel: null,
          };
        }
        return null;
      });
      return filas
        .filter((fila) => fila !== null)
        .sort((a, b) => {
          const at = String(a.plc_tag || "");
          const bt = String(b.plc_tag || "");
          if (at !== bt) return at.localeCompare(bt);
          return (ORDEN_ESTADOS[a.status] ?? 9) - (ORDEN_ESTADOS[b.status] ?? 9);
        });
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
     * Carga el catalogo del area: la etiqueta del N_MAX.
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
     * Genera la prevision de las entidades del PLC.
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
