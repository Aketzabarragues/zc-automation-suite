import { flushPromises, mount } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";
import { beforeEach, describe, expect, it, vi } from "vitest";
import Procesos from "../vistas/Procesos.vue";
import { useProcesosStore } from "../stores/procesos.js";
import { useExcelStore } from "../stores/excel.js";
import { usePlcStore } from "../../../nucleo/stores/plc.js";
import { useSesionStore } from "../../../nucleo/stores/sesion.js";
import { useTiaStore } from "../../../nucleo/stores/tia.js";
import { useTrabajosStore } from "../../../nucleo/stores/trabajos.js";

/**
 * El volcado del Excel maestro que tiene el backend, en el mismo shape que
 * devuelve `GET /api/v1/areas/alimentacion/excel`: un dict plano con la
 * meta (``cargado``, ``archivo``, ...) y los dominios.
 */
const EXCEL_CARGADO = {
  cargado: true,
  archivo: "Maestro.xlsm",
  procesos: {
    Procesos: {
      columnas: [],
      filas: [
        { uid: 100, nombre: "CPR", codigo: "CPR", preal: 2, pint: 1, alarmas: 2, alm_hmi: 2, plc_name: "ZC_PLC_STD" },
        { uid: 200, nombre: "PUM", codigo: "PUM", preal: 1, pint: 1, alarmas: 1, alm_hmi: 1, plc_name: "ZC_PLC_STD" },
      ],
    },
  },
};

/**
 * La prevision que devuelve el backend para el proceso 100.
 *
 * Los slots van desordenados a proposito: la vista los ordena por slot.
 */
const PREVISION = {
  proc_uid: 100,
  proc_codigo: "CPR",
  precondiciones_ok: true,
  missing_blocks: [],
  db_param_name: "DB53100_CPR_PARAM",
  db_alm_name: "DB55100_CPR_ALM",
  table_name: "100_CPR",
  db_present: { param: true, alm: true },
  table_present: true,
  arrays: {
    PReal: {
      db_name: "DB53100_CPR_PARAM",
      array_name: "PReal",
      satellite_arrays: ["PReal_Vis", "Aux.PReal_ValorAnterior"],
      current_count: 2,
      desired_count: 3,
      slot_map: {
        "2": { current: "Parametro dos", desired: "Parametro dos", action: "sin_cambios" },
        "1": { current: "Parametro uno (viejo)", desired: "Parametro uno", action: "renombrar" },
        "3": { current: null, desired: "Parametro tres", action: "agregar" },
      },
      summary: { total: 3, agregados: 1, renombrados: 1, eliminados: 0, sin_cambios: 1 },
    },
    PInt: {
      db_name: "DB53100_CPR_PARAM",
      array_name: "PInt",
      satellite_arrays: ["PInt_Vis", "Aux.PInt_ValorAnterior"],
      current_count: 1,
      desired_count: 1,
      slot_map: {
        "1": { current: "Entero uno", desired: "Entero uno", action: "sin_cambios" },
      },
      summary: { total: 1, agregados: 0, renombrados: 0, eliminados: 0, sin_cambios: 1 },
    },
    ALM: {
      db_name: "DB55100_CPR_ALM",
      array_name: "ALM",
      satellite_arrays: [],
      current_count: 3,
      desired_count: 2,
      slot_map: {
        "1": { current: "Alarma uno", desired: "Alarma uno", action: "sin_cambios" },
        "2": { current: "Alarma dos", desired: "Alarma dos (ren)", action: "renombrar" },
        "3": { current: "Alarma tres", desired: null, action: "eliminar" },
      },
      summary: { total: 3, agregados: 0, renombrados: 1, eliminados: 1, sin_cambios: 1 },
    },
  },
  summary: { total: 7, agregados: 1, renombrados: 2, eliminados: 1, sin_cambios: 3 },
  nmax: {
    current: { "100_N_MAX_PREAL": 3, "100_N_MAX_ALM": 2 },
    desired: { "100_N_MAX_PREAL": 2, "100_N_MAX_ALM": 2 },
    todos: [
      { name: "100_N_MAX_PREAL", kind: "preal", actual: 3, nuevo: 2, status: "actualizar" },
      { name: "100_N_MAX_ALM", kind: "alm", actual: 2, nuevo: 2, status: "sin_cambios" },
      { name: "100_N_MAX_ALM_HMI", kind: "alm_hmi", actual: null, nuevo: 4, status: "actualizar" },
    ],
    summary: { actualizar: 2, sin_cambios: 1, total: 3 },
    nmax_error: null,
  },
  warnings: [],
};

/**
 * La prevision tras el sync: los cambios ya aplicados, solo quedan los
 * sin cambios.
 */
const PREVISION_POST = {
  ...PREVISION,
  arrays: {
    PReal: {
      ...PREVISION.arrays.PReal,
      slot_map: { "1": { current: "Parametro uno", desired: "Parametro uno", action: "sin_cambios" } },
      summary: { total: 1, agregados: 0, renombrados: 0, eliminados: 0, sin_cambios: 1 },
    },
    PInt: { ...PREVISION.arrays.PInt },
    ALM: {
      ...PREVISION.arrays.ALM,
      slot_map: { "1": { current: "Alarma uno", desired: "Alarma uno", action: "sin_cambios" } },
      summary: { total: 1, agregados: 0, renombrados: 0, eliminados: 0, sin_cambios: 1 },
    },
  },
  summary: { total: 3, agregados: 0, renombrados: 0, eliminados: 0, sin_cambios: 3 },
};

/**
 * La prevision de TIA V18: los arrays de comentarios salen vacios (no hay
 * SimaticSD) y lo unico que cambia es el N_MAX.
 */
const PREVISION_V18 = {
  ...PREVISION,
  arrays: {},
  summary: { total: 0, agregados: 0, renombrados: 0, eliminados: 0, sin_cambios: 0 },
  nmax: {
    current: { "100_N_MAX_PREAL": 3 },
    desired: { "100_N_MAX_PREAL": 2 },
    todos: [{ name: "100_N_MAX_PREAL", kind: "preal", actual: 3, nuevo: 2, status: "actualizar" }],
    summary: { actualizar: 1, sin_cambios: 0, total: 1 },
    nmax_error: null,
  },
};

/** Las transacciones que devuelve el trabajo de sincronizacion. */
const TRANSACCIONES = [
  { nombre: "N_MAX", estado: "confirmada", detalle: "1 N_MAX" },
  { nombre: "Comentarios", estado: "confirmada", detalle: "2 arrays" },
];

/**
 * Crea un pinia limpio y pre-hidrata los stores antes de montar, para que la
 * vista no dispare `hidratar()` al montar (que recargaria el Excel).
 *
 * @returns {object} `{pinia, procesos, excel, plc, tia, trabajos}`.
 */
function storesLimpios() {
  const pinia = createPinia();
  setActivePinia(pinia);
  return {
    pinia,
    procesos: useProcesosStore(),
    excel: useExcelStore(),
    plc: usePlcStore(),
    tia: useTiaStore(),
    trabajos: useTrabajosStore(),
  };
}

/** Monta la vista con un pinia limpio. */
function montar() {
  const stores = storesLimpios();
  const wrapper = mount(Procesos, { global: { plugins: [stores.pinia] } });
  return { wrapper, ...stores };
}

/** Monta la vista con Excel, PLC, TIA y proceso 100 elegidos. */
function montarConTodo() {
  const stores = storesLimpios();
  stores.excel.datos = EXCEL_CARGADO;
  stores.excel.cargado = true;
  // El volcado ya esta puesto: la vista no lo recarga al montar.
  stores.excel.hidratado = true;
  stores.tia.conectado = true;
  stores.plc.seleccionado = "ZC_PLC_STD";
  stores.procesos.procUid = 100;
  const wrapper = mount(Procesos, { global: { plugins: [stores.pinia] } });
  return { wrapper, ...stores };
}

/** Monta la vista con una prevision vigente del proceso 100. */
function montarConPrevision(prevision = PREVISION) {
  const montado = montarConTodo();
  montado.procesos.preview = prevision;
  montado.procesos.previewPlc = "ZC_PLC_STD";
  return montado;
}

/**
 * Abre el dialogo de confirmacion y lo confirma.
 *
 * @param {object} wrapper la vista montada.
 */
async function confirmarAplicacion(wrapper) {
  await wrapper.find('[data-testid="procesos-aplicar"]').trigger("click");
  await wrapper.find('[data-testid="procesos-confirmar-si"]').trigger("click");
  await flushPromises();
}

/** Las filas de la tabla, en el orden que se ven. */
function filas(wrapper) {
  return wrapper.findAll('[data-testid="procesos-tabla"] tbody tr').map((fila) =>
    fila.findAll("td").map((celda) => celda.text()),
  );
}

/** Pulsa la tarjeta "comentarios" para activar el modo de la 4.5. */
async function abrirComentarios(wrapper) {
  await wrapper.find('[data-testid="procesos-tarjeta-comentarios"]').trigger("click");
  await flushPromises();
}

describe("Procesos", () => {
  beforeEach(() => {
    global.fetch = vi.fn((ruta) => {
      const url = String(ruta);
      if (url.includes("/api/v1/areas/alimentacion/excel")) {
        return Promise.resolve({ ok: true, json: async () => EXCEL_CARGADO });
      }
      if (url.includes("/procesos/sincronizar")) {
        return Promise.resolve({ ok: true, json: async () => ({ job_id: "j1" }) });
      }
      if (url.includes("/procesos/preview")) {
        return Promise.resolve({ ok: true, json: async () => ({ job_id: "j1" }) });
      }
      return Promise.resolve({ ok: true, json: async () => ({}) });
    });
  });

  it("sin Excel enseña el banner de Excel", async () => {
    const { wrapper, excel } = montarConTodo();
    excel.cargado = false;
    await flushPromises();
    const banner = wrapper.find('[data-testid="procesos-banner"]');
    expect(banner.exists()).toBe(true);
    expect(banner.text()).toContain("No hay Excel cargado");
  });

  it("sin PLC enseña el banner de PLC", async () => {
    const { wrapper, plc } = montarConTodo();
    plc.seleccionado = "";
    await flushPromises();

    const banner = wrapper.find('[data-testid="procesos-banner"]');
    expect(banner.exists()).toBe(true);
    expect(banner.text()).toContain("Selecciona un PLC");
  });

  it("el selector lista los procesos del PLC elegido", async () => {
    const { wrapper } = montarConTodo();
    await flushPromises();

    const opciones = wrapper.findAll('[data-testid="procesos-select-opcion"]');
    const textos = opciones.map((o) => o.text());
    expect(textos.some((t) => t.includes("CPR"))).toBe(true);
    expect(textos.some((t) => t.includes("PUM"))).toBe(true);
  });

  it("sin proceso elegido la tarjeta no se habilita y la seccion no se monta", async () => {
    const { wrapper, procesos } = montarConTodo();
    procesos.procUid = null;
    await flushPromises();
    await wrapper.find('[data-testid="procesos-tarjeta-comentarios"]').trigger("click");
    await flushPromises();

    expect(
      wrapper.find('[data-testid="procesos-tarjeta-comentarios"]').attributes("disabled"),
    ).toBeDefined();
    expect(wrapper.find('[data-testid="procesos-contenido"]').exists()).toBe(false);
    expect(wrapper.find('[data-testid="proc-sync-generate-preview"]').exists()).toBe(false);
  });

  it("con proceso elegido el boton de generar se habilita", async () => {
    const { wrapper } = montarConTodo();
    await flushPromises();
    await abrirComentarios(wrapper);

    expect(
      wrapper.find('[data-testid="proc-sync-generate-preview"]').attributes("disabled"),
    ).toBeUndefined();
  });

  it("sin prevision enseña el estado vacio", async () => {
    const { wrapper } = montarConTodo();
    await flushPromises();
    await abrirComentarios(wrapper);

    expect(wrapper.find('[data-testid="procesos-vacio"]').exists()).toBe(true);
    expect(wrapper.find('[data-testid="procesos-vacio"]').text()).toContain(
      "Sin prevision generada.",
    );
    expect(wrapper.find('[data-testid="procesos-vacio"]').text()).toContain(
      'Pulsa "🔍 Generar Previsión" para ver el diff completo.',
    );
    expect(wrapper.find('[data-testid="procesos-tabla"]').exists()).toBe(false);
  });

  it("con prevision enseña el resumen de los slots", async () => {
    const { wrapper } = montarConPrevision();
    await flushPromises();
    await abrirComentarios(wrapper);

    const resumen = wrapper.find('[data-testid="procesos-resumen"]');
    expect(resumen.exists()).toBe(true);
    expect(resumen.text()).toContain("7 slots analizados");
    expect(resumen.text()).toContain("1 a agregar");
    expect(resumen.text()).toContain("2 a renombrar");
    expect(resumen.text()).toContain("1 a eliminar");
    expect(resumen.text()).toContain("3 sin cambios");
  });

  it("el resumen pone renombrar antes que agregar", async () => {
    const { wrapper } = montarConPrevision();
    await flushPromises();
    await abrirComentarios(wrapper);

    const resumen = wrapper.find('[data-testid="procesos-resumen"]').text();
    expect(resumen.indexOf("a renombrar")).toBeLessThan(resumen.indexOf("a agregar"));
    expect(resumen.indexOf("a agregar")).toBeLessThan(resumen.indexOf("a eliminar"));
    expect(resumen.indexOf("a eliminar")).toBeLessThan(resumen.indexOf("sin cambios"));
  });

  it("la cabecera ensena el proceso con su nombre, codigo y uid", async () => {
    const { wrapper } = montarConPrevision();
    await flushPromises();
    await abrirComentarios(wrapper);

    const cabecera = wrapper.find('[data-testid="procesos-comentarios"]');
    expect(cabecera.find("h2").text()).toBe("💬 Actualizar comentarios de DB");
    const texto = cabecera.text();
    expect(texto).toContain("Proceso");
    expect(texto).toContain("CPR");
    expect(texto).toContain("uid 100");
  });

  it("los bloques TIA objetivo se listan con sus nombres", async () => {
    const { wrapper } = montarConPrevision();
    await flushPromises();
    await abrirComentarios(wrapper);

    const bloque = wrapper.find('[data-testid="procesos-bloques-tia"]');
    expect(bloque.exists()).toBe(true);
    expect(bloque.text()).toContain("Bloques TIA objetivo");
    expect(bloque.text()).toContain("DB parámetros: DB53100_CPR_PARAM");
    expect(bloque.text()).toContain("DB alarmas: DB55100_CPR_ALM");
    expect(bloque.text()).toContain("Tabla de variables: 100_CPR");
  });

  it("un bloque que falta en el PLC se marca en rojo", async () => {
    const prevision = {
      ...PREVISION,
      db_present: { param: false, alm: true },
      table_present: false,
    };
    const { wrapper } = montarConPrevision(prevision);
    await flushPromises();
    await abrirComentarios(wrapper);

    const bloque = wrapper.find('[data-testid="procesos-bloques-tia"]');
    expect(bloque.text()).toContain("(no existe en PLC)");
    const filas = bloque.findAll("div.font-mono");
    expect(filas[0].classes()).toContain("text-red-700");
    expect(filas[2].classes()).toContain("text-red-700");
  });

  it("las pestanas muestran los tres arrays con su badge de cambios", async () => {
    const { wrapper } = montarConPrevision();
    await flushPromises();
    await abrirComentarios(wrapper);

    const pestanas = wrapper.findAll('[data-testid="procesos-pestanas"] button');
    expect(pestanas.length).toBe(3);
    expect(pestanas[0].text()).toContain("Parámetros reales");
    expect(pestanas[0].text()).toContain("2"); // renombrar + agregar
    expect(pestanas[1].text()).toContain("Parámetros Enteros");
    expect(pestanas[2].text()).toContain("Alarmas");
    expect(pestanas[2].text()).toContain("2"); // renombrar + eliminar
  });

  it("la tabla se ordena por slot y pinta el estado de cada fila", async () => {
    const { wrapper } = montarConPrevision();
    await flushPromises();
    await abrirComentarios(wrapper);

    // La pestana PReal esta activa por defecto.
    const celdasSlot = filas(wrapper).map((fila) => fila[0]);
    expect(celdasSlot).toEqual(["1", "2", "3"]);

    const tabla = wrapper.find('[data-testid="procesos-tabla"]');
    expect(tabla.text()).toContain("RENOMBRAR");
    expect(tabla.text()).toContain("AGREGAR");
    expect(tabla.text()).toContain("OK");
    // La columna "Actual (TIA)" con un valor nulo se ensena como raya.
    expect(tabla.text()).toContain("—");
  });

  it("cada fila tiene su testid con la pestana y el slot", async () => {
    const { wrapper } = montarConPrevision();
    await flushPromises();
    await abrirComentarios(wrapper);

    expect(wrapper.find('[data-testid="proc-sync-row-PReal-1"]').exists()).toBe(true);
    expect(wrapper.find('[data-testid="proc-sync-row-PReal-3"]').exists()).toBe(true);
  });

  it("cambiar de pestana cambia la tabla", async () => {
    const { wrapper } = montarConPrevision();
    await flushPromises();
    await abrirComentarios(wrapper);

    // PInt por defecto no: la primera pestana es PReal. Cambiamos a ALM.
    await wrapper.findAll('[data-testid="procesos-pestanas"] button')[2].trigger("click");
    await flushPromises();

    const celdas = filas(wrapper).map((fila) => fila[0]);
    expect(celdas).toEqual(["1", "2", "3"]);
    // ALM slot 3 se elimina.
    const tabla = wrapper.find('[data-testid="procesos-tabla"]');
    expect(tabla.text()).toContain("ELIMINAR");
  });

  it("un array sin slots dice que no hay slots", async () => {
    const prevision = {
      ...PREVISION,
      arrays: { ...PREVISION.arrays, PInt: { ...PREVISION.arrays.PInt, slot_map: {} } },
    };
    const { wrapper } = montarConPrevision(prevision);
    await flushPromises();
    await abrirComentarios(wrapper);

    await wrapper.findAll('[data-testid="procesos-pestanas"] button')[1].trigger("click");
    await flushPromises();

    expect(wrapper.find('[data-testid="procesos-tabla"]').text()).toContain(
      "No hay slots en este array.",
    );
  });

  it("la tarjeta de N_MAX sale con el valor actual y el nuevo", async () => {
    const { wrapper } = montarConPrevision();
    await flushPromises();
    await abrirComentarios(wrapper);

    const bloque = wrapper.find('[data-testid="proc-sync-nmax-cards"]');
    expect(bloque.exists()).toBe(true);
    const preal = wrapper.find('[data-testid="proc-sync-nmax-preal"]');
    expect(preal.text()).toContain("N_MAX PReal");
    expect(preal.text()).toContain("3");
    expect(preal.text()).toContain("2");
  });

  it("las etiquetas de N_MAX: las conocidas y el nombre de la constante", async () => {
    const { wrapper } = montarConPrevision();
    await flushPromises();
    await abrirComentarios(wrapper);

    expect(wrapper.find('[data-testid="proc-sync-nmax-preal"]').text()).toContain("N_MAX PReal");
    expect(wrapper.find('[data-testid="proc-sync-nmax-alm"]').text()).toContain("N_MAX Alarmas");
    // Un kind sin etiqueta propia usa el nombre de la constante.
    expect(wrapper.find('[data-testid="proc-sync-nmax-alm_hmi"]').text()).toContain(
      "100_N_MAX_ALM_HMI",
    );
  });

  it("el boton de aplicar esta deshabilitado sin prevision", async () => {
    const { wrapper } = montarConTodo();
    await flushPromises();
    await abrirComentarios(wrapper);

    expect(wrapper.find('[data-testid="procesos-aplicar"]').exists()).toBe(false);
    expect(wrapper.find('[data-testid="proc-sync-generate-preview"]').exists()).toBe(true);
  });

  it("el boton de aplicar se habilita con prevision y esta deshabilitado sin cambios", async () => {
    const { wrapper } = montarConPrevision();
    await flushPromises();
    await abrirComentarios(wrapper);

    const boton = wrapper.find('[data-testid="procesos-aplicar"]');
    expect(boton.text()).toContain("Aplicar al PLC");
    expect(boton.attributes("disabled")).toBeUndefined();
  });

  it("sin cambios que aplicar el boton queda deshabilitado con el motivo", async () => {
    const prevision = {
      ...PREVISION,
      arrays: {},
      summary: { total: 0, agregados: 0, renombrados: 0, eliminados: 0, sin_cambios: 0 },
      nmax: {
        ...PREVISION.nmax,
        todos: [{ name: "100_N_MAX_PREAL", kind: "preal", actual: 2, nuevo: 2, status: "sin_cambios" }],
        summary: { actualizar: 0, sin_cambios: 1, total: 1 },
      },
    };
    const { wrapper } = montarConPrevision(prevision);
    await flushPromises();
    await abrirComentarios(wrapper);

    const boton = wrapper.find('[data-testid="procesos-aplicar"]');
    expect(boton.attributes("disabled")).toBeDefined();
    expect(boton.attributes("title")).toBe("No hay cambios que aplicar");
  });

  it("con solo N_MAX a actualizar (TIA V18) el boton se habilita", async () => {
    const { wrapper } = montarConPrevision(PREVISION_V18);
    await flushPromises();
    await abrirComentarios(wrapper);

    const boton = wrapper.find('[data-testid="procesos-aplicar"]');
    expect(boton.attributes("disabled")).toBeUndefined();
    expect(boton.attributes("title")).toBe("");
  });

  it("sin PLC el boton de aplicar dice que hay que elegir uno", async () => {
    const { wrapper, plc } = montarConPrevision();
    await flushPromises();
    await abrirComentarios(wrapper);
    plc.seleccionado = "";
    await flushPromises();

    const boton = wrapper.find('[data-testid="procesos-aplicar"]');
    expect(boton.attributes("disabled")).toBeDefined();
    expect(boton.attributes("title")).toBe("Selecciona un PLC primero");
  });

  it("el dialogo de confirmacion se abre al pulsar y se cierra al cancelar", async () => {
    const { wrapper } = montarConPrevision();
    await flushPromises();
    await abrirComentarios(wrapper);

    expect(wrapper.find('[data-testid="procesos-confirmar-dialogo"]').exists()).toBe(false);

    await wrapper.find('[data-testid="procesos-aplicar"]').trigger("click");

    const dialogo = wrapper.find('[data-testid="procesos-confirmar-dialogo"]');
    expect(dialogo.exists()).toBe(true);
    expect(dialogo.attributes("role")).toBe("dialog");
    expect(dialogo.attributes("aria-modal")).toBe("true");
    expect(dialogo.text()).toContain("¿Aplicar 6 cambios en TIA Portal?");
    expect(dialogo.text()).toContain("Comentarios de DB:");
    expect(dialogo.text()).toContain("Agregar: 1");
    expect(dialogo.text()).toContain("N_MAX (dimensiones):");
    expect(dialogo.text()).toContain("Actualizar: 2");

    await wrapper.find('[data-testid="procesos-confirmar-no"]').trigger("click");

    expect(wrapper.find('[data-testid="procesos-confirmar-dialogo"]').exists()).toBe(false);
  });

  it("el dialogo de confirmacion se cierra con Escape", async () => {
    const { wrapper } = montarConPrevision();
    await flushPromises();
    await abrirComentarios(wrapper);

    await wrapper.find('[data-testid="procesos-aplicar"]').trigger("click");
    expect(wrapper.find('[data-testid="procesos-confirmar-dialogo"]').exists()).toBe(true);

    window.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape" }));
    await flushPromises();

    expect(wrapper.find('[data-testid="procesos-confirmar-dialogo"]').exists()).toBe(false);
  });

  it("al confirmar se encola la sincronizacion con proc_uid y queda la prevision posterior", async () => {
    const { wrapper, trabajos } = montarConPrevision();
    await flushPromises();
    await abrirComentarios(wrapper);

    await confirmarAplicacion(wrapper);

    const post = global.fetch.mock.calls.find(
      ([ruta, opciones]) =>
        opciones && opciones.method === "POST" && String(ruta).includes("sincronizar"),
    );
    expect(post).toBeTruthy();
    expect(String(post[0])).toBe("/api/v1/areas/alimentacion/procesos/sincronizar");
    expect(JSON.parse(post[1].body)).toEqual({ plc: "ZC_PLC_STD", proc_uid: 100 });
    expect(wrapper.find('[data-testid="procesos-confirmar-dialogo"]').exists()).toBe(false);

    // El trabajo termina: la vista se queda con la prevision posterior.
    trabajos.aplicar({
      type: "job",
      job: "j1",
      estado: "ok",
      resultado: { prevision: PREVISION_POST, transacciones: TRANSACCIONES },
      error: null,
    });
    await flushPromises();

    expect(wrapper.find('[data-testid="procesos-resumen"]').text()).toContain(
      "3 slots analizados",
    );
    expect(wrapper.find('[data-testid="procesos-resumen"]').text()).toContain("3 sin cambios");
  });

  it("tras aplicar se ve la fecha del apply", async () => {
    const { wrapper, trabajos } = montarConPrevision();
    await flushPromises();
    await abrirComentarios(wrapper);

    await confirmarAplicacion(wrapper);

    trabajos.aplicar({
      type: "job",
      job: "j1",
      estado: "ok",
      resultado: { prevision: PREVISION_POST, transacciones: TRANSACCIONES },
      error: null,
    });
    await flushPromises();

    const aplicado = wrapper.find('[data-testid="procesos-aplicado"]');
    expect(aplicado.exists()).toBe(true);
    expect(aplicado.text()).toContain("✓ Aplicado:");
  });

  it("el estado de cada transaccion se ve al terminar la sincronizacion", async () => {
    const { wrapper, trabajos } = montarConPrevision();
    await flushPromises();
    await abrirComentarios(wrapper);

    await confirmarAplicacion(wrapper);

    trabajos.aplicar({
      type: "job",
      job: "j1",
      estado: "ok",
      resultado: { prevision: PREVISION_POST, transacciones: TRANSACCIONES },
      error: null,
    });
    await flushPromises();

    const bloque = wrapper.find('[data-testid="procesos-transacciones"]');
    expect(bloque.exists()).toBe(true);
    expect(bloque.text()).toContain("N_MAX: confirmada");
    expect(bloque.text()).toContain("Comentarios: confirmada");
  });

  it("el error de la sincronizacion se ve en la vista", async () => {
    const { wrapper, trabajos } = montarConPrevision();
    await flushPromises();
    await abrirComentarios(wrapper);

    await confirmarAplicacion(wrapper);

    trabajos.aplicar({
      type: "job",
      job: "j1",
      estado: "error",
      resultado: null,
      error: "La transaccion de N_MAX se revirtio",
    });
    await flushPromises();

    expect(wrapper.find('[data-testid="procesos-error"]').text()).toContain(
      "La transaccion de N_MAX se revirtio",
    );
  });

  it("las precondiciones no cumplidas se avisan", async () => {
    const prevision = {
      ...PREVISION,
      precondiciones_ok: false,
      missing_blocks: ["DB53100_CPR_PARAM", "100_CPR"],
    };
    const { wrapper } = montarConPrevision(prevision);
    await flushPromises();
    await abrirComentarios(wrapper);

    const banner = wrapper.find('[data-testid="procesos-precond"]');
    expect(banner.exists()).toBe(true);
    expect(banner.text()).toContain("Precondiciones no cumplidas");
    expect(banner.text()).toContain("DB53100_CPR_PARAM · 100_CPR");
  });

  it("la prevision guardada en la sesion se ve tras un F5", async () => {
    const pinia = createPinia();
    setActivePinia(pinia);
    useSesionStore().estado = {
      areas: {
        alimentacion: {
          excel: EXCEL_CARGADO,
          prevision_procesos: {
            plc: "ZC_PLC_STD",
            proc_uid: 100,
            resultado: PREVISION,
          },
        },
      },
    };
    useTiaStore().conectado = true;
    usePlcStore().seleccionado = "ZC_PLC_STD";

    const wrapper = mount(Procesos, { global: { plugins: [pinia] } });
    await flushPromises();
    await wrapper.find('[data-testid="procesos-tarjeta-comentarios"]').trigger("click");
    await flushPromises();

    expect(wrapper.find('[data-testid="procesos-tabla"]').exists()).toBe(true);
  });

  it("la prevision de otro PLC no se ve", async () => {
    const { wrapper, plc } = montarConPrevision();
    await wrapper.find('[data-testid="procesos-tarjeta-comentarios"]').trigger("click");
    await flushPromises();
    plc.seleccionado = "OTRO_PLC";
    await flushPromises();

    expect(wrapper.find('[data-testid="procesos-tabla"]').exists()).toBe(false);
    expect(wrapper.find('[data-testid="procesos-vacio"]').exists()).toBe(true);
  });

  it("sin TIA la prevision no se ve", async () => {
    const { wrapper, tia } = montarConPrevision();
    await wrapper.find('[data-testid="procesos-tarjeta-comentarios"]').trigger("click");
    await flushPromises();
    tia.conectado = false;
    await flushPromises();

    expect(wrapper.find('[data-testid="procesos-tabla"]').exists()).toBe(false);
  });

  it("cambiar de proceso limpia la prevision anterior", async () => {
    const { wrapper, procesos } = montarConPrevision();
    await flushPromises();
    await wrapper.find('[data-testid="procesos-tarjeta-comentarios"]').trigger("click");
    await flushPromises();
    expect(wrapper.find('[data-testid="procesos-tabla"]').exists()).toBe(true);

    // Elegir el proceso 200 limpia la prevision del 100.
    procesos.elegir(200);
    await flushPromises();

    expect(procesos.preview).toBe(null);
    expect(wrapper.find('[data-testid="procesos-tabla"]').exists()).toBe(false);
  });

  describe("las tarjetas de modo", () => {
    it("las dos tarjetas estan presentes con los textos de main", async () => {
      const { wrapper } = montarConTodo();
      await flushPromises();

      const crear = wrapper.find('[data-testid="procesos-tarjeta-crear"]');
      expect(crear.exists()).toBe(true);
      expect(crear.text()).toContain("🏗️");
      expect(crear.text()).toContain("Crear proceso completo");
      expect(crear.text()).toContain("Genera el DB + bloques + UDTs del proceso.");

      const comentarios = wrapper.find('[data-testid="procesos-tarjeta-comentarios"]');
      expect(comentarios.exists()).toBe(true);
      expect(comentarios.text()).toContain("💬");
      expect(comentarios.text()).toContain("Actualizar comentarios de DB");
      expect(comentarios.text()).toContain("Sincroniza los comentarios de los DBs existentes.");
    });

    it("sin Excel: deshabilitadas con el motivo en el title", async () => {
      const { wrapper, excel } = montarConTodo();
      excel.cargado = false;
      await flushPromises();

      const crear = wrapper.find('[data-testid="procesos-tarjeta-crear"]');
      expect(crear.attributes("disabled")).toBeDefined();
      expect(crear.attributes("title")).toBe(
        "Carga primero el Excel y pulsa 'Actualizar' en 'Definición programación'.",
      );
      const comentarios = wrapper.find('[data-testid="procesos-tarjeta-comentarios"]');
      expect(comentarios.attributes("disabled")).toBeDefined();
      expect(comentarios.attributes("title")).toBe(
        "Carga primero el Excel y pulsa 'Actualizar' en 'Definición programación'.",
      );
    });

    it("sin PLC: deshabilitadas con el motivo en el title", async () => {
      const { wrapper, plc } = montarConTodo();
      plc.seleccionado = "";
      await flushPromises();

      expect(wrapper.find('[data-testid="procesos-tarjeta-crear"]').attributes("title")).toBe(
        "Selecciona un PLC en el topbar.",
      );
      expect(
        wrapper.find('[data-testid="procesos-tarjeta-comentarios"]').attributes("title"),
      ).toBe("Selecciona un PLC en el topbar.");
      expect(wrapper.find('[data-testid="procesos-tarjeta-crear"]').attributes("disabled")).toBeDefined();
    });

    it("sin TIA conectado: deshabilitadas con el motivo en el title", async () => {
      const { wrapper, tia } = montarConTodo();
      tia.conectado = false;
      await flushPromises();

      expect(wrapper.find('[data-testid="procesos-tarjeta-crear"]').attributes("title")).toBe(
        "Conecta a TIA Portal en el topbar.",
      );
      expect(
        wrapper.find('[data-testid="procesos-tarjeta-comentarios"]').attributes("title"),
      ).toBe("Conecta a TIA Portal en el topbar.");
      expect(wrapper.find('[data-testid="procesos-tarjeta-crear"]').attributes("disabled")).toBeDefined();
    });

    it("sin proceso elegido: deshabilitadas con el motivo en el title", async () => {
      const { wrapper, procesos } = montarConTodo();
      procesos.procUid = null;
      await flushPromises();

      expect(wrapper.find('[data-testid="procesos-tarjeta-crear"]').attributes("title")).toBe(
        "Selecciona un proceso de la lista.",
      );
      expect(
        wrapper.find('[data-testid="procesos-tarjeta-comentarios"]').attributes("title"),
      ).toBe("Selecciona un proceso de la lista.");
      expect(wrapper.find('[data-testid="procesos-tarjeta-comentarios"]').attributes("disabled")).toBeDefined();
    });

    it("con todo: habilitadas y sin motivo", async () => {
      const { wrapper } = montarConTodo();
      await flushPromises();

      const crear = wrapper.find('[data-testid="procesos-tarjeta-crear"]');
      expect(crear.attributes("disabled")).toBeUndefined();
      expect(crear.attributes("title")).toBe("");
      const comentarios = wrapper.find('[data-testid="procesos-tarjeta-comentarios"]');
      expect(comentarios.attributes("disabled")).toBeUndefined();
      expect(comentarios.attributes("title")).toBe("");
    });

    it("estado inicial: sin seccion de comentarios ni CrearProceso", async () => {
      const { wrapper } = montarConTodo();
      await flushPromises();

      expect(wrapper.find('[data-testid="procesos-contenido"]').exists()).toBe(false);
      expect(wrapper.find('[data-testid="proc-sync-generate-preview"]').exists()).toBe(false);
      expect(wrapper.find('[data-testid="crear"]').exists()).toBe(false);
      // Ninguna tarjeta activa.
      expect(wrapper.find('[data-testid="procesos-tarjeta-crear"]').classes()).not.toContain("border-accent");
      expect(wrapper.find('[data-testid="procesos-tarjeta-comentarios"]').classes()).not.toContain("border-accent");
    });

    it("pulsar 'comentarios' muestra la seccion de comentarios y no CrearProceso", async () => {
      const { wrapper } = montarConTodo();
      await flushPromises();
      await abrirComentarios(wrapper);

      expect(wrapper.find('[data-testid="procesos-contenido"]').exists()).toBe(true);
      expect(wrapper.find('[data-testid="proc-sync-generate-preview"]').exists()).toBe(true);
      expect(wrapper.find('[data-testid="crear"]').exists()).toBe(false);
      expect(wrapper.find('[data-testid="procesos-tarjeta-comentarios"]').classes()).toContain("border-accent");
      expect(wrapper.find('[data-testid="procesos-tarjeta-crear"]').classes()).not.toContain("border-accent");
    });

    it("pulsar 'crear' monta CrearProceso y oculta la de comentarios", async () => {
      const { wrapper } = montarConTodo();
      await flushPromises();
      await wrapper.find('[data-testid="procesos-tarjeta-crear"]').trigger("click");
      await flushPromises();

      expect(wrapper.find('[data-testid="crear"]').exists()).toBe(true);
      expect(wrapper.find('[data-testid="crear"]').find("h2").text()).toBe(
        "Crear proceso completo desde plantilla",
      );
      expect(wrapper.find('[data-testid="proc-sync-generate-preview"]').exists()).toBe(false);
      expect(wrapper.find('[data-testid="procesos-tarjeta-crear"]').classes()).toContain("border-accent");
      expect(wrapper.find('[data-testid="procesos-tarjeta-comentarios"]').classes()).not.toContain("border-accent");
    });

    it("el boton Cerrar de los comentarios cierra la vista", async () => {
      const { wrapper } = montarConTodo();
      await flushPromises();
      await abrirComentarios(wrapper);
      expect(wrapper.find('[data-testid="procesos-contenido"]').exists()).toBe(true);

      await wrapper.find('[data-testid="proc-sync-close"]').trigger("click");
      await flushPromises();

      expect(wrapper.find('[data-testid="procesos-contenido"]').exists()).toBe(false);
    });

    it("el evento cerrar de CrearProceso vuelve al modo inicial", async () => {
      const { wrapper } = montarConTodo();
      await flushPromises();
      await wrapper.find('[data-testid="procesos-tarjeta-crear"]').trigger("click");
      await flushPromises();
      expect(wrapper.find('[data-testid="crear"]').exists()).toBe(true);

      await wrapper.find('[data-testid="crear-cerrar"]').trigger("click");
      await flushPromises();

      expect(wrapper.find('[data-testid="crear"]').exists()).toBe(false);
      expect(wrapper.find('[data-testid="procesos-contenido"]').exists()).toBe(false);
    });

    it("cambiar de proceso conserva el modo", async () => {
      const { wrapper, procesos } = montarConTodo();
      await flushPromises();
      await abrirComentarios(wrapper);
      expect(wrapper.find('[data-testid="procesos-contenido"]').exists()).toBe(true);

      // Elegir el proceso 200 no cambia el modo (ni limpia la vista).
      procesos.elegir(200);
      await flushPromises();

      expect(wrapper.find('[data-testid="procesos-contenido"]').exists()).toBe(true);
      expect(wrapper.find('[data-testid="procesos-tarjeta-comentarios"]').classes()).toContain("border-accent");

      // Y al volver al 100 sigue en el mismo modo.
      procesos.elegir(100);
      await flushPromises();
      expect(wrapper.find('[data-testid="procesos-contenido"]').exists()).toBe(true);
    });

    it("pulsar la tarjeta activa no la cierra", async () => {
      const { wrapper } = montarConTodo();
      await flushPromises();
      await abrirComentarios(wrapper);
      await abrirComentarios(wrapper);

      expect(wrapper.find('[data-testid="procesos-contenido"]').exists()).toBe(true);
    });
  });
});
