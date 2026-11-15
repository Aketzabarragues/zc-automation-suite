/**
 * Store de la creacion de un proceso desde una plantilla TIA.
 *
 * El flujo es el mismo que en el resto del area: los trabajos largos se
 * encolan con un POST (202 + `job_id`) y su resultado llega por el stream
 * de eventos. La vista pide primero el listado de plantillas (un GET plano,
 * sin trabajo) y elige una; con la plantilla elegida genera la prevision y,
 * si esta deja crear, aplica. Cambiar de plantilla limpia la prevision y el
 * resultado del aplicar: no valen para otra plantilla.
 */
import { defineStore } from "pinia";
import { pedir } from "../../../nucleo/api.js";
import { useSesionStore } from "../../../nucleo/stores/sesion.js";
import { useTrabajosStore } from "../../../nucleo/stores/trabajos.js";

/** Identificador del area y clave de la prevision en la sesion del backend. */
const ID_AREA = "alimentacion";
const CLAVE_PREVISION = "prevision_crear_proceso";

/** Ruta del listado de plantillas. */
export const RUTA_PLANTILLAS = "/api/v1/areas/alimentacion/procesos/plantillas";

/** Ruta del endpoint de la prevision de creacion. */
export const RUTA_PREVIEW = "/api/v1/areas/alimentacion/procesos/crear/preview";

/** Ruta del endpoint que crea el proceso en TIA Portal. */
export const RUTA_APLICAR = "/api/v1/areas/alimentacion/procesos/crear/aplicar";

/**
 * Las 4 claves N_MAX de la validacion de minimos, en el orden del backend
 * (``proc_validar_minimos``): el campo del Excel a la izquierda, la clave
 * del manifest a la derecha.
 */
const CLAVES_N_MAX = Object.freeze([
  { clave: "N_MAX_PREAL", excel: "preal" },
  { clave: "N_MAX_PINT", excel: "pint" },
  { clave: "N_MAX_ALM", excel: "alarmas" },
  { clave: "N_MAX_ALM_HMI", excel: "alm_hmi" },
]);

export const useCrearProcesoStore = defineStore("crearProceso", {
  state: () => ({
    /** Las plantillas del listado, con su shape del backend. */
    plantillas: [],
    /** La carpeta donde vive la plantilla, tal cual la sirvio el backend. */
    plantillasPath: "",
    /** El aviso del listado (carpeta inexistente o caida), o `null`. */
    aviso: null,
    /** `true` mientras se carga el listado de plantillas. */
    cargandoPlantillas: false,
    /** La carpeta de la plantilla elegida, o `""` si no hay ninguna. */
    plantillaSeleccionada: "",
    /** La ultima prevision, con su shape del backend. */
    preview: null,
    /** `true` mientras se genera la prevision. */
    generando: false,
    /** `true` mientras se crea el proceso en TIA Portal. */
    aplicando: false,
    /** El resultado del ultimo aplicar, o `null` si no hay ninguno. */
    resultadoAplicar: null,
    /** El estado de cada transaccion del ultimo aplicar. */
    transacciones: [],
    /** Ultimo error de la vista. */
    error: null,
    /** `true` cuando ya se aplico la prevision de la sesion (una vez). */
    hidratado: false,
  }),

  getters: {
    /** `true` si hay una prevision generada. */
    hayPreview: (state) => Boolean(state.preview),

    /** La plantilla elegida, o `null` si no hay ninguna o no existe. */
    plantilla(state) {
      if (!state.plantillaSeleccionada) return null;
      return state.plantillas.find((p) => p.carpeta === state.plantillaSeleccionada) || null;
    },

    /** Los bloques que se generarian, en el orden del backend. */
    bloquesPrevistos(state) {
      return (state.preview && state.preview.archivos_previstos) || [];
    },

    /** Los nombres que colisionan con bloques ya presentes en el PLC. */
    colisiones(state) {
      return (state.preview && state.preview.colisiones) || [];
    },

    /** Las dependencias del manifest que faltan en el PLC. */
    dependenciasFaltantes(state) {
      return (state.preview && state.preview.dependencias_faltantes) || [];
    },

    /** `true` si la prevision tiene al menos una colision. */
    hayColisiones(state) {
      return (state.preview && state.preview.colisiones || []).length > 0;
    },

    /**
     * Si se puede crear el proceso: hay prevision, sus precondiciones estan
     * cumplidas, no colisiona nada y no faltan dependencias.
     */
    puedeCrear() {
      const preview = this.preview;
      return Boolean(
        preview &&
          preview.precondiciones_ok &&
          preview.success &&
          this.colisiones.length === 0 &&
          this.dependenciasFaltantes.length === 0,
      );
    },

    /**
     * Los N_MAX donde el proceso del Excel no cubre los minimos de la
     * plantilla, en el orden del backend.
     *
     * El proceso viene en el volcado del Excel maestro (los campos
     * ``preal``, ``pint``, ``alarmas`` y ``alm_hmi``); los ausentes valen
     * 0, igual que en ``proc_minimos_de_proceso`` del backend.
     *
     * @param {object} proceso la fila del proceso del Excel maestro.
     * @returns {Array<{clave: string, usuario: number, plantilla: number}>}
     *   las claves que no cubren, vacio si los minimos se cumplen.
     */
    minimosProblemas: (state) => (proceso) => {
      const planta =
        state.plantillas.find((p) => p.carpeta === state.plantillaSeleccionada) || null;
      if (!planta || !proceso) return [];
      const minimos = planta.minimos || {};
      const problemas = [];
      for (const { clave, excel } of CLAVES_N_MAX) {
        const usuario = Number(proceso[excel] ?? 0) || 0;
        const requerido = Number(minimos[clave] ?? 0) || 0;
        if (usuario < requerido) {
          problemas.push({ clave, usuario, plantilla: requerido });
        }
      }
      return problemas;
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
        this.plantillaSeleccionada = guardada.dir_plantilla_nombre || "";
      }
    },

    /**
     * Carga el listado de plantillas y la carpeta donde viven.
     *
     * @returns {Promise<boolean>} si se cargo el listado.
     */
    async cargarPlantillas() {
      this.cargandoPlantillas = true;
      this.error = null;
      try {
        const datos = await pedir(RUTA_PLANTILLAS);
        this.plantillas = datos.plantillas || [];
        this.plantillasPath = datos.plantillas_path || "";
        this.aviso = datos.aviso || null;
        return true;
      } catch (error) {
        this.error = error.message;
        return false;
      } finally {
        this.cargandoPlantillas = false;
      }
    },

    /**
     * Elige la plantilla con la que se creara el proceso.
     *
     * Cambiar de plantilla limpia la prevision y el resultado del aplicar:
     * un preview viejo no vale para otra plantilla.
     *
     * @param {string} carpeta el nombre de la subcarpeta de la plantilla.
     */
    seleccionarPlantilla(carpeta) {
      if (carpeta === this.plantillaSeleccionada) return;
      this.plantillaSeleccionada = carpeta;
      this.preview = null;
      this.resultadoAplicar = null;
      this.transacciones = [];
      this.error = null;
    },

    /**
     * Genera la prevision de crear el proceso desde la plantilla elegida.
     *
     * @param {string} plc el PLC elegido.
     * @param {number} procUid el uid del proceso del Excel maestro.
     * @returns {Promise<boolean>} si se lanzo el trabajo y termino bien.
     */
    async generarPrevision(plc, procUid) {
      if (!plc) {
        this.error = "Elige un PLC antes de generar la prevision.";
        return false;
      }
      if (procUid == null) {
        this.error = "Elige un proceso antes de generar la prevision.";
        return false;
      }
      if (!this.plantillaSeleccionada) {
        this.error = "Elige una plantilla antes de generar la prevision.";
        return false;
      }
      this.error = null;
      this.generando = true;
      try {
        const datos = await pedir(RUTA_PREVIEW, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            plc,
            proc_uid: procUid,
            dir_plantilla_nombre: this.plantillaSeleccionada,
          }),
        });
        const job = await useTrabajosStore().esperar(datos.job_id);
        if (job.estado === "ok") {
          this.preview = job.resultado;
          return true;
        }
        // El manifest invalido o los N_MAX insuficientes terminan el trabajo
        // en error: no hay resultado que guardar.
        this.preview = null;
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
     * Crea el proceso en TIA Portal desde la plantilla elegida.
     *
     * El trabajo devuelve los archivos generados y el estado de cada
     * transaccion: lo que se confirmo, lo que se revirtio y lo que no llego
     * a ejecutarse.
     *
     * @param {string} plc el PLC elegido.
     * @param {number} procUid el uid del proceso del Excel maestro.
     * @returns {Promise<boolean>} si la creacion se completo.
     */
    async aplicar(plc, procUid) {
      if (!plc) {
        this.error = "Elige un PLC antes de crear el proceso.";
        return false;
      }
      if (procUid == null) {
        this.error = "Elige un proceso antes de crear el proceso.";
        return false;
      }
      if (!this.plantillaSeleccionada) {
        this.error = "Elige una plantilla antes de crear el proceso.";
        return false;
      }
      this.error = null;
      this.aplicando = true;
      try {
        const datos = await pedir(RUTA_APLICAR, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            plc,
            proc_uid: procUid,
            dir_plantilla_nombre: this.plantillaSeleccionada,
          }),
        });
        const job = await useTrabajosStore().esperar(datos.job_id);
        if (job.estado === "ok") {
          this.resultadoAplicar = job.resultado;
          this.transacciones = (job.resultado && job.resultado.transacciones) || [];
          return true;
        }
        this.error = job.error || "No se pudo crear el proceso.";
        return false;
      } catch (error) {
        this.error = error.message;
        return false;
      } finally {
        this.aplicando = false;
      }
    },
  },
});
