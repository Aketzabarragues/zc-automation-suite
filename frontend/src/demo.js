/**
 * Fuente de eventos simulada para el modo demo (`?demo=1`).
 *
 * Mantiene la misma interfaz que un `EventSource` (`onopen`, `onmessage`,
 * `onerror`, `close`), de modo que el resto de la app no necesita saber si
 * hay un backend detras o no.
 *
 * Los eventos simulados son los cuatro del backend: `tia`, `progress`,
 * `job` y `log`.
 */

/** Escenario del demo: un trabajo de sincronizacion de tres pasos. */
const ESCENARIO = [
  {
    espera: 300,
    evento: {
      type: "tia",
      conectado: true,
      trabajo_actual: null,
      ultimo_error: null,
      version_tia: "V21.0",
    },
  },
  {
    espera: 300,
    evento: {
      type: "log",
      nivel: "info",
      mensaje: "Demo: la consola de trazabilidad recibe los eventos del backend.",
      detalle: null,
    },
  },
  {
    espera: 300,
    evento: {
      type: "progress",
      active: true,
      operation: "sincronizar",
      label: "Sincronizar dispositivos",
      current: 0,
      total: 3,
      percent: 0,
      stages: [
        { id: "exportar", label: "Exportar bloques", status: "running", detail: null },
        { id: "comparar", label: "Comparar con el libro maestro", status: "pending", detail: null },
        { id: "aplicar", label: "Aplicar los cambios", status: "pending", detail: null },
      ],
      started_at: null,
      finished_at: null,
      error: null,
    },
  },
  {
    espera: 900,
    evento: {
      type: "progress",
      active: true,
      operation: "sincronizar",
      label: "Sincronizar dispositivos",
      current: 1,
      total: 3,
      percent: 33,
      stages: [
        { id: "exportar", label: "Exportar bloques", status: "done", detail: "12 bloques" },
        { id: "comparar", label: "Comparar con el libro maestro", status: "running", detail: null },
        { id: "aplicar", label: "Aplicar los cambios", status: "pending", detail: null },
      ],
      started_at: null,
      finished_at: null,
      error: null,
    },
  },
  {
    espera: 300,
    evento: {
      type: "log",
      nivel: "warning",
      mensaje: "Demo: un aviso sin traceback.",
      detalle: null,
    },
  },
  {
    espera: 300,
    evento: {
      type: "log",
      nivel: "error",
      mensaje: "Demo: un fallo con traceback, para ver el desplegable.",
      detalle:
        "Traceback (most recent call last):\n" +
        '  File "demo.py", line 1, in <module>\n' +
        "    fallar()\n" +
        "DemoError: esto es un traceback de mentira\n",
    },
  },
  {
    espera: 600,
    evento: {
      type: "progress",
      active: true,
      operation: "sincronizar",
      label: "Sincronizar dispositivos",
      current: 2,
      total: 3,
      percent: 66,
      stages: [
        { id: "exportar", label: "Exportar bloques", status: "done", detail: "12 bloques" },
        { id: "comparar", label: "Comparar con el libro maestro", status: "done", detail: "3 cambios" },
        { id: "aplicar", label: "Aplicar los cambios", status: "running", detail: null },
      ],
      started_at: null,
      finished_at: null,
      error: null,
    },
  },
  {
    espera: 700,
    evento: {
      type: "job",
      job: "demo0001",
      estado: "ok",
      resultado: { cambios: 3 },
      error: null,
    },
  },
  {
    espera: 100,
    evento: {
      type: "progress",
      active: false,
      operation: "sincronizar",
      label: "Sincronizar dispositivos",
      current: 3,
      total: 3,
      percent: 100,
      stages: [
        { id: "exportar", label: "Exportar bloques", status: "done", detail: "12 bloques" },
        { id: "comparar", label: "Comparar con el libro maestro", status: "done", detail: "3 cambios" },
        { id: "aplicar", label: "Aplicar los cambios", status: "done", detail: "3 cambios aplicados" },
      ],
      started_at: null,
      finished_at: null,
      error: null,
    },
  },
];

/** Pausa entrecenario y el siguiente. */
const PAUSA = 6000;

/**
 * Los datos que ve el operario en el modo demo.
 *
 * Reproducen el proyecto de prueba: los mismos nombres de bloques, las
 * mismas carpetas y la misma jerarquia que el smoke del PLC real.
 */
export function datosDemo() {
  return {
    plcs: [{ nombre: "ZC_PLC_STD", designacion: "CPU 1516-3 PN/DP" }],
    proyecto: {
      nombre: "ZC_PLC_STD",
      ruta: "D:\\Proyectos\\ZC_PLC_STD\\ZC_PLC_STD.ap21",
    },
    bloques: BLOQUES_DEMO,
    tablas: TABLAS_DEMO,
    tipos: TIPOS_DEMO,
  };
}

const VACIO = {
  title: null,
  author: null,
  version: null,
  programming_language: null,
  memory_layout: null,
};

/** Bloque de demo. */
function bloque(nombre, numero, tipo, ruta, extra = {}) {
  return {
    nombre,
    numero,
    tipo,
    ruta,
    extended: { ...VACIO, ...extra },
  };
}

const BLOQUES_DEMO = [
  bloque("OB1_MAIN", 1, "OB", ""),
  bloque("OB30_PID_100MS", 30, "OB", ""),
  bloque("Documentacion", 0, "FC", ""),
  bloque("FC99_test", 99, "FC", ""),
  bloque("_borrar", 59998, "DB", ""),
  bloque("OB40_HardwareInterrupt", 40, "OB", "0_Sistema"),
  bloque("OB80_TimeErrorInterrupt", 80, "OB", "0_Sistema"),
  bloque("OB100_Startup", 100, "OB", "0_Sistema"),
  bloque("DB1_SYS", 1, "DB", "0_Sistema"),
  bloque("DB3_CHECKSUM", 3, "DB", "0_Sistema"),
  bloque("DB100_SYSTEM", 100, "DB", "0_Sistema"),
  bloque("FB100_Cyclic", 100, "FB", "@FAT"),
  bloque("DB2001_EA", 2001, "DB", "2000_Dispositivos"),
  bloque("DB2005_SD", 2005, "DB", "2000_Dispositivos"),
  bloque("DB2006_SA", 2006, "DB", "2000_Dispositivos"),
  bloque("DB2010_V", 2010, "DB", "2000_Dispositivos"),
  bloque("DB2015_M", 2015, "DB", "2000_Dispositivos"),
  bloque("DB2000_ED", 2000, "DB", "2000_Dispositivos"),
  bloque("DB2038_MEDIA_VOL", 9, "DB", "2000_Dispositivos"),
  bloque("DB2037_MEDIA", 10, "DB", "2000_Dispositivos"),
  bloque("DB2041_TQ", 2041, "DB", "2000_Dispositivos"),
  bloque("FC15_ZC_GEST_PREAL", 3, "FC", "ZC_Controles"),
  bloque("FB15049_ZC_AIRE_ESTERIL", 15149, "FB", "ZC_Controles"),
  bloque("DB6001_ENTIDAD", 6001, "DB", "6_Entidades"),
  bloque("DB7001_TERZA", 7001, "DB", "7_Terza"),
  bloque("DB9001_GESTOR", 9001, "DB", "9_Gestor_Dispositivos"),
  bloque("DB11001_INFORME", 11001, "DB", "11_Informes"),
  bloque("DB20001_SCADA", 20001, "DB", "20_Scada"),
];

const TABLAS_DEMO = [
  { nombre: "2000_Disp_ED", ruta: "0_Sistema" },
  { nombre: "2000_Disp_EA", ruta: "0_Sistema" },
  { nombre: "0_Config_Dispositivos", ruta: "" },
  { nombre: "0_Config_Generales", ruta: "" },
];

const TIPOS_DEMO = [
  bloque("MiTipoDeDato", null, "UDT", "1_Documentado"),
  bloque("Estado_Valvula", null, "UDT", "1_Documentado"),
  bloque("Medida", null, "UDT", "0_Sistema"),
  bloque("Historico", null, "UDT", "ZC_Controles"),
];

/**
 * Crea una fuente de eventos simulada.
 *
 * @param {object} opciones opciones.
 * @param {number} opciones.factor multiplicador de los tiempos. Con 0 el
 *   escenario sale de inmediato.
 * @returns {object} la fuente, con la interfaz de `EventSource`.
 */
export function crearFuenteDemo({ factor = 1 } = {}) {
  let temporizadores = [];
  let cerrado = false;

  const fuente = {
    onopen: null,
    onmessage: null,
    onerror: null,
    close() {
      cerrado = true;
      temporizadores.forEach((temporizador) => clearTimeout(temporizador));
      temporizadores = [];
    },
  };

  function programar(espera, accion) {
    const temporizador = setTimeout(() => {
      if (cerrado) return;
      accion();
    }, Math.max(0, Math.round(espera * factor)));
    temporizadores.push(temporizador);
  }

  function emitir(evento) {
    if (cerrado || typeof fuente.onmessage !== "function") return;
    fuente.onmessage({ data: JSON.stringify(evento) });
  }

  function reproducir() {
    if (cerrado) return;
    let acumulado = 0;
    ESCENARIO.forEach(({ espera, evento }) => {
      acumulado += espera;
      programar(acumulado, () => emitir(evento));
    });
    programar(acumulado + PAUSA, reproducir);
  }

  programar(50, () => {
    if (typeof fuente.onopen === "function") fuente.onopen();
  });
  reproducir();

  return fuente;
}
