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
export const RUTA_PREVISION = "/api/v1/areas/alimentacion/procesos/crear/preview";

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

/**
 * Si una prevision deja crear el proceso: precondiciones cumplidas, sin
 * colisiones y sin dependencias faltantes.
 *
 * @param {object|null} prevision la prevision, o `null`.
 * @returns {boolean}
 */
function puedeCrearDe(prevision) {
  return Boolean(
    prevision &&
      prevision.precondiciones_ok &&
      prevision.success &&
      ((prevision.colisiones || []).length === 0) &&
      ((prevision.dependencias_faltantes || []).length === 0),
  );
}

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
    prevision: null,
    /** El PLC de la prevision: solo vale para ese PLC. */
    previsionPlc: "",
    /** El uid del proceso de la prevision: solo vale para ese proceso. */
    previsionProcUid: null,
    /** La carpeta de la plantilla con la que se genero la prevision. */
    previsionPlantilla: "",
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
    /** `true` mientras se guarda la ruta de plantillas. */
    guardandoRuta: false,
    /** El error al guardar la ruta de plantillas, o `null`. */
    errorRuta: null,
  }),

  getters: {
    /** `true` si hay una prevision generada. */
    hayPrevision: (state) => Boolean(state.prevision),

    /**
     * Si la prevision vale para la combinacion elegida en la vista: es la
     * del PLC, el proceso y la plantilla indicados. Una prevision vieja no
     * habilita el crear para otra cosa.
     *
     * @param {string} plc el PLC elegido.
     * @param {number} procUid el uid del proceso elegido.
     * @returns {boolean} si la prevision es de ese PLC, proceso y plantilla.
     */
    previsionVale: (state) => (plc, procUid) => {
      return Boolean(
        state.prevision &&
          state.previsionPlc === plc &&
          state.previsionProcUid === procUid &&
          state.previsionPlantilla === state.plantillaSeleccionada,
      );
    },

    /** La plantilla elegida, o `null` si no hay ninguna o no existe. */
    plantilla(state) {
      if (!state.plantillaSeleccionada) return null;
      return state.plantillas.find((p) => p.carpeta === state.plantillaSeleccionada) || null;
    },

    /** Los bloques que se generarian, en el orden del backend. */
    bloquesPrevistos(state) {
      return (state.prevision && state.prevision.archivos_previstos) || [];
    },

    /** Los nombres que colisionan con bloques ya presentes en el PLC. */
    colisiones(state) {
      return (state.prevision && state.prevision.colisiones) || [];
    },

    /** Las dependencias del manifest que faltan en el PLC. */
    dependenciasFaltantes(state) {
      return (state.prevision && state.prevision.dependencias_faltantes) || [];
    },

    /** `true` si la prevision tiene al menos una colision. */
    hayColisiones(state) {
      return (state.prevision && state.prevision.colisiones || []).length > 0;
    },

    /**
     * Si se puede crear el proceso: hay prevision, sus precondiciones estan
     * cumplidas, no colisiona nada y no faltan dependencias.
     */
    puedeCrear: (state) => puedeCrearDe(state.prevision),

    /**
     * Si se puede crear **para la combinacion elegida**: la prevision vale
     * para ese PLC, proceso y plantilla, y ademas deja crear.
     *
     * @param {string} plc el PLC elegido.
     * @param {number} procUid el uid del proceso elegido.
     */
    puedeCrearPara: (state) => (plc, procUid) => {
      const prevision = state.prevision;
      const vale =
        prevision &&
        state.previsionPlc === plc &&
        state.previsionProcUid === procUid &&
        state.previsionPlantilla === state.plantillaSeleccionada;
      return vale && puedeCrearDe(prevision);
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
        this.prevision = guardada.resultado;
        this.previsionPlc = guardada.plc || "";
        this.previsionProcUid = guardada.proc_uid ?? null;
        const plantilla = guardada.dir_plantilla_nombre || "";
        this.previsionPlantilla = plantilla;
        this.plantillaSeleccionada = plantilla;
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
        // La plantilla elegida ya no esta en el listado: es una seleccion
        // fantasma (la ruta cambio) y su prevision tampoco vale.
        if (
          this.plantillaSeleccionada &&
          !this.plantillas.some((p) => p.carpeta === this.plantillaSeleccionada)
        ) {
          this.seleccionarPlantilla("");
        }
        return true;
      } catch (error) {
        this.error = error.message;
        return false;
      } finally {
        this.cargandoPlantillas = false;
      }
    },

    /**
     * Guarda la ruta base de plantillas en el ``config.json`` del usuario.
     *
     * La ruta vacia no se envia: el boton Guardar esta deshabilitado con el
     * input vacio y no hay forma de resetearla desde la UI. Si la escritura
     * falla, el error queda en `errorRuta` (el error de la vista es
     * `error`, que `cargarPlantillas` limpia) y no se recarga el listado.
     *
     * @param {string} ruta la ruta a guardar, con o sin espacios sobrantes.
     * @returns {Promise<boolean>} si se guardo y el listado se recargo.
     */
    async guardarRutaPlantillas(ruta) {
      const nueva = (ruta || "").trim();
      if (!nueva) return false;
      this.guardandoRuta = true;
      this.errorRuta = null;
      try {
        await pedir(RUTA_PLANTILLAS, {
          method: "PUT",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ plantillas_path: nueva }),
        });
        // La ruta que se muestra es la que devuelve el backend, no la
        // escrita a mano: `cargarPlantillas` deja `plantillasPath` tal cual.
        await this.cargarPlantillas();
        return true;
      } catch (error) {
        this.errorRuta = `No se pudo guardar: ${error.message}`;
        return false;
      } finally {
        this.guardandoRuta = false;
      }
    },

    /**
     * Elige la plantilla con la que se creara el proceso.
     *
     * Cambiar de plantilla limpia la prevision y el resultado del aplicar:
     * una prevision vieja no vale para otra plantilla.
     *
     * @param {string} carpeta el nombre de la subcarpeta de la plantilla.
     */
    seleccionarPlantilla(carpeta) {
      if (carpeta === this.plantillaSeleccionada) return;
      this.plantillaSeleccionada = carpeta;
      this.prevision = null;
      this.previsionPlc = "";
      this.previsionProcUid = null;
      this.previsionPlantilla = "";
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
        const datos = await pedir(RUTA_PREVISION, {
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
          this.prevision = job.resultado;
          this.previsionPlc = plc;
          this.previsionProcUid = procUid;
          this.previsionPlantilla = this.plantillaSeleccionada;
          return true;
        }
        // El manifest invalido o los N_MAX insuficientes terminan el trabajo
        // en error: no hay resultado que guardar.
        this.prevision = null;
        this.previsionPlc = "";
        this.previsionProcUid = null;
        this.previsionPlantilla = "";
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
      if (!this.previsionVale(plc, procUid)) {
        this.error =
          "La prevision no corresponde al proceso, PLC o plantilla elegidos: " +
          "genera la prevision otra vez.";
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
          // El proceso ya existe: la prevision deja de valer para este
          // proceso. El resultado del aplicar se conserva.
          this.prevision = null;
          this.previsionPlc = "";
          this.previsionProcUid = null;
          this.previsionPlantilla = "";
          this.resultadoAplicar = job.resultado;
          this.transacciones = (job.resultado && job.resultado.transacciones) || [];
          return true;
        }
        // Si el aplicar fallo, la prevision no se toca: puede reintentarse.
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
