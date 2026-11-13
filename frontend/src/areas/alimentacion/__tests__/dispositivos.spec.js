import { flushPromises, mount } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";
import { beforeEach, describe, expect, it, vi } from "vitest";
import Dispositivos from "../vistas/Dispositivos.vue";
import { useDispositivosStore } from "../stores/dispositivos.js";
import { useExcelStore } from "../stores/excel.js";
import { usePlcStore } from "../../../nucleo/stores/plc.js";
import { useSesionStore } from "../../../nucleo/stores/sesion.js";
import { useTiaStore } from "../../../nucleo/stores/tia.js";
import { useTrabajosStore } from "../../../nucleo/stores/trabajos.js";

/** El Excel maestro que tiene el backend. */
const EXCEL_CARGADO = { cargado: true, archivo: "Maestro.xlsm" };

/** El catalogo del area, como lo sirve el backend. */
const CATALOGO = {
  alimentacion: {
    device_tabs: [
      { hw_type: "ed", label: "ED" },
      { hw_type: "ea", label: "EA" },
    ],
    nmax: [{ name: "N_MAX_DISP_ED", label: "num_disp_ed" }],
  },
};

/**
 * La prevision que devuelve el backend.
 *
 * Las filas van desordenadas a proposito: la vista las ordena por numero.
 */
const PREVISION = {
  agregados: [{ uid: "9", table: "2000_Disp_ED", plc_tag: "ED_009" }],
  eliminados: [{ uid: "3", table: "2000_Disp_ED", plc_tag: "ED_003" }],
  renombrados: [{ uid: "1", table: "2000_Disp_ED", actual: "ED_001", nuevo: "V_ED_001" }],
  todos: [
    {
      table: "2000_Disp_ED",
      type: "ed",
      uid: "3",
      numero: 3,
      actual: "ED_003",
      nuevo: null,
      status: "eliminar",
    },
    {
      table: "2000_Disp_ED",
      type: "ed",
      uid: "9",
      numero: 9,
      actual: null,
      nuevo: "ED_009",
      status: "agregar",
    },
    {
      table: "2000_Disp_ED",
      type: "ed",
      uid: "1",
      numero: 1,
      actual: "ED_001",
      nuevo: "V_ED_001",
      status: "renombrar",
    },
    {
      table: "2000_Disp_ED",
      type: "ed",
      uid: "2",
      numero: 2,
      actual: "ED_002",
      nuevo: "ED_002",
      status: "sin_cambios",
    },
  ],
  nmax: {
    current: { N_MAX_DISP_ED: 10 },
    desired: { N_MAX_DISP_ED: 20 },
    todos: [
      { name: "N_MAX_DISP_ED", actual: 10, nuevo: 20, status: "actualizar" },
      { name: "N_MAX_DISP_EA", actual: 20, nuevo: 20, status: "sin_cambios" },
    ],
    summary: { actualizar: 1, sin_cambios: 1, total: 2 },
    nmax_error: null,
  },
  summary: { agregados: 1, eliminados: 1, renombrados: 1, sin_cambios: 1, total: 4 },
};

/**
 * La prevision que devuelve el backend tras el sync: los cambios ya estan
 * aplicados y solo quedan los dispositivos sin cambios.
 */
const PREVISION_POST = {
  agregados: [],
  eliminados: [],
  renombrados: [],
  todos: [
    {
      table: "2000_Disp_ED",
      type: "ed",
      uid: "1",
      numero: 1,
      actual: "V_ED_001",
      nuevo: "V_ED_001",
      status: "sin_cambios",
    },
    {
      table: "2000_Disp_ED",
      type: "ed",
      uid: "2",
      numero: 2,
      actual: "ED_002",
      nuevo: "ED_002",
      status: "sin_cambios",
    },
  ],
  nmax: {
    current: { N_MAX_DISP_ED: 20 },
    desired: { N_MAX_DISP_ED: 20 },
    todos: [{ name: "N_MAX_DISP_ED", actual: 20, nuevo: 20, status: "sin_cambios" }],
    summary: { actualizar: 0, sin_cambios: 1, total: 1 },
    nmax_error: null,
  },
  summary: { agregados: 0, eliminados: 0, renombrados: 0, sin_cambios: 2, total: 2 },
};

/** Las transacciones que devuelve el trabajo de sincronizacion. */
const TRANSACCIONES = [
  { nombre: "N_MAX y renombres", estado: "confirmada", detalle: "1 N_MAX y 1 renombres" },
  { nombre: "Dispositivos", estado: "confirmada", detalle: "1 tablas" },
  { nombre: "Comentarios", estado: "no ejecutada", detalle: "TIA Portal anterior a V21" },
];

/**
 * Monta la vista con un pinia limpio.
 *
 * @returns {object} `{wrapper, dispositivos, excel, plc, tia, trabajos}`.
 */
function montar() {
  const pinia = createPinia();
  setActivePinia(pinia);
  const wrapper = mount(Dispositivos, { global: { plugins: [pinia] } });
  return {
    wrapper,
    dispositivos: useDispositivosStore(),
    excel: useExcelStore(),
    plc: usePlcStore(),
    tia: useTiaStore(),
    trabajos: useTrabajosStore(),
  };
}

/**
 * Monta la vista con una prevision vigente: la del PLC seleccionado y con
 * TIA conectado.
 */
function montarConPrevision() {
  const montado = montar();
  montado.tia.conectado = true;
  montado.plc.seleccionado = "ZC_PLC_STD";
  montado.dispositivos.preview = PREVISION;
  montado.dispositivos.previewPlc = "ZC_PLC_STD";
  return montado;
}

/**
 * Los numeros de la primera columna de la tabla.
 *
 * @param {object} wrapper la vista montada.
 * @returns {Array<string>} los numeros, en el orden que se ven.
 */
function numeros(wrapper) {
  return wrapper.findAll('[data-testid="dispositivos-tabla"] tbody tr td:first-child').map(
    (celda) => celda.text(),
  );
}

/**
 * Abre el dialogo de confirmacion y lo confirma.
 *
 * @param {object} wrapper la vista montada.
 */
async function confirmarAplicacion(wrapper) {
  await wrapper.find('[data-testid="dispositivos-aplicar"]').trigger("click");
  await wrapper.find('[data-testid="dispositivos-confirmar-si"]').trigger("click");
  await flushPromises();
}

describe("Dispositivos", () => {
  beforeEach(() => {
    global.fetch = vi.fn((ruta) => {
      const url = String(ruta);
      if (url.includes("/api/v1/catalog")) {
        return Promise.resolve({ ok: true, json: async () => CATALOGO });
      }
      if (url.includes("/api/v1/areas/alimentacion/excel")) {
        return Promise.resolve({ ok: true, json: async () => EXCEL_CARGADO });
      }
      if (url.includes("/dispositivos/sincronizar")) {
        return Promise.resolve({ ok: true, json: async () => ({ job_id: "j1" }) });
      }
      return Promise.resolve({ ok: true, json: async () => ({}) });
    });
  });

  it("sin prevision enseña el estado vacio", async () => {
    const { wrapper } = montar();
    await flushPromises();

    expect(wrapper.find('[data-testid="dispositivos-vacio"]').exists()).toBe(true);
    expect(wrapper.find('[data-testid="dispositivos-vacio"]').text()).toContain(
      "Sin prevision generada.",
    );
    expect(wrapper.find('[data-testid="dispositivos-tabla"]').exists()).toBe(false);
  });

  it("el boton de generar esta deshabilitado sin TIA o sin Excel", async () => {
    const { wrapper, tia, excel, plc } = montar();
    await flushPromises();

    expect(wrapper.find('[data-testid="dispositivos-generar"]').attributes("disabled")).toBeDefined();

    tia.conectado = true;
    excel.cargado = true;
    plc.seleccionado = "ZC_PLC_STD";
    await flushPromises();

    expect(
      wrapper.find('[data-testid="dispositivos-generar"]').attributes("disabled"),
    ).toBeUndefined();
  });

  it("con prevision enseña el resumen, las pestañas y el diff", async () => {
    const { wrapper, dispositivos } = montarConPrevision();
    await flushPromises();

    const resumen = wrapper.find('[data-testid="dispositivos-resumen"]');
    expect(resumen.text()).toContain("4 dispositivos analizados");
    expect(resumen.text()).toContain("1 a agregar");
    expect(resumen.text()).toContain("1 a renombrar");
    expect(resumen.text()).toContain("1 a eliminar");
    expect(resumen.text()).toContain("1 sin cambios");
  });

  it("las pestañas salen del catalogo, con su etiqueta y su contador", async () => {
    const { wrapper, dispositivos } = montarConPrevision();
    await flushPromises();

    const pestana = wrapper.find('[data-testid="dispositivos-tipo-ed"]');
    expect(pestana.exists()).toBe(true);
    expect(pestana.text()).toContain("ED");
    expect(pestana.text()).toContain("(4)");
    expect(wrapper.find('[data-testid="dispositivos-tipo-ea"]').text()).toContain("(0)");
  });

  it("las filas salen con el estado y el color de cada caso", async () => {
    const { wrapper, dispositivos } = montarConPrevision();
    await flushPromises();

    const tabla = wrapper.find('[data-testid="dispositivos-tabla"]');
    expect(tabla.text()).toContain("RENOMBRAR");
    expect(tabla.text()).toContain("AGREGAR");
    expect(tabla.text()).toContain("ELIMINAR");
    expect(tabla.text()).toContain("OK");
    expect(tabla.text()).toContain("V_ED_001");
  });

  it("las filas salen ordenadas por numero", async () => {
    const { wrapper, dispositivos } = montarConPrevision();
    await flushPromises();

    expect(numeros(wrapper)).toEqual(["1", "2", "3", "9"]);
  });

  it("la fila a eliminar enseña el valor actual tachado y en rojo", async () => {
    const { wrapper, dispositivos } = montarConPrevision();
    await flushPromises();

    const fila = wrapper.findAll('[data-testid="dispositivos-tabla"] tbody tr')[2];
    const actual = fila.findAll("td")[1];
    expect(actual.text()).toBe("ED_003");
    expect(actual.classes()).toContain("line-through");
    expect(actual.classes()).toContain("text-red-700");
  });

  it("una pestaña sin dispositivos avisa", async () => {
    const { wrapper, dispositivos } = montarConPrevision();
    await flushPromises();

    await wrapper.find('[data-testid="dispositivos-tipo-ea"]').trigger("click");
    await flushPromises();

    expect(wrapper.find('[data-testid="dispositivos-tabla"]').text()).toContain(
      '⚠️ Sin dispositivos para "ea".',
    );
  });

  it("las tarjetas de N_MAX salen todas, con la etiqueta del catalogo", async () => {
    const { wrapper, dispositivos } = montarConPrevision();
    await flushPromises();

    const tarjetas = wrapper.find('[data-testid="dispositivos-nmax"]');
    expect(tarjetas.exists()).toBe(true);
    expect(tarjetas.text()).toContain("num_disp_ed");
    expect(tarjetas.text()).toContain("10");
    expect(tarjetas.text()).toContain("20");
  });

  it("el boton de aplicar esta deshabilitado sin prevision", async () => {
    const { wrapper } = montar();
    await flushPromises();

    const boton = wrapper.find('[data-testid="dispositivos-aplicar"]');
    expect(boton.text()).toContain("Aplicar Cambios en TIA Portal");
    expect(boton.attributes("disabled")).toBeDefined();
    expect(wrapper.find('[data-testid="dispositivos-transacciones"]').exists()).toBe(false);
  });

  it("el boton de aplicar enseña cuantos cambios van a aplicarse", async () => {
    const { wrapper } = montarConPrevision();
    await flushPromises();

    const boton = wrapper.find('[data-testid="dispositivos-aplicar"]');
    expect(boton.text()).toContain("Aplicar Cambios en TIA Portal");
    expect(boton.text()).toContain("(4 cambios)");
    expect(boton.attributes("disabled")).toBeUndefined();
  });

  it("el boton de aplicar se habilita con Excel, TIA y PLC", async () => {
    const { wrapper, excel, tia, plc } = montarConPrevision();
    await flushPromises();

    expect(
      wrapper.find('[data-testid="dispositivos-aplicar"]').attributes("disabled"),
    ).toBeUndefined();

    excel.cargado = false;
    await flushPromises();
    expect(
      wrapper.find('[data-testid="dispositivos-aplicar"]').attributes("disabled"),
    ).toBeDefined();

    excel.cargado = true;
    tia.conectado = false;
    await flushPromises();
    expect(
      wrapper.find('[data-testid="dispositivos-aplicar"]').attributes("disabled"),
    ).toBeDefined();

    tia.conectado = true;
    plc.seleccionado = "";
    await flushPromises();
    expect(
      wrapper.find('[data-testid="dispositivos-aplicar"]').attributes("disabled"),
    ).toBeDefined();
  });

  it("mientras se aplica, los botones de generar y de aplicar estan deshabilitados", async () => {
    const { wrapper, dispositivos } = montarConPrevision();
    await flushPromises();

    dispositivos.aplicando = true;
    await flushPromises();

    expect(
      wrapper.find('[data-testid="dispositivos-aplicar"]').attributes("disabled"),
    ).toBeDefined();
    expect(
      wrapper.find('[data-testid="dispositivos-generar"]').attributes("disabled"),
    ).toBeDefined();
  });

  it("el dialogo de confirmacion se abre al pulsar y se cierra al cancelar", async () => {
    const { wrapper } = montarConPrevision();
    await flushPromises();

    expect(wrapper.find('[data-testid="dispositivos-confirmar-dialogo"]').exists()).toBe(false);

    await wrapper.find('[data-testid="dispositivos-aplicar"]').trigger("click");

    const dialogo = wrapper.find('[data-testid="dispositivos-confirmar-dialogo"]');
    expect(dialogo.exists()).toBe(true);
    expect(dialogo.attributes("role")).toBe("dialog");
    expect(dialogo.attributes("aria-modal")).toBe("true");
    expect(dialogo.text()).toContain("¿Aplicar 4 cambios en TIA Portal?");
    expect(dialogo.text()).toContain("Devices:");
    expect(dialogo.text()).toContain("Agregar: 1");
    expect(dialogo.text()).toContain("Renombrar: 1");
    expect(dialogo.text()).toContain("Eliminar: 1");
    expect(dialogo.text()).toContain("N_MAX (dimensiones):");
    expect(dialogo.text()).toContain("Actualizar: 1");

    await wrapper.find('[data-testid="dispositivos-confirmar-no"]').trigger("click");

    expect(wrapper.find('[data-testid="dispositivos-confirmar-dialogo"]').exists()).toBe(false);
  });

  it("el dialogo de confirmacion se cierra con Escape", async () => {
    const { wrapper } = montarConPrevision();
    await flushPromises();

    await wrapper.find('[data-testid="dispositivos-aplicar"]').trigger("click");
    expect(wrapper.find('[data-testid="dispositivos-confirmar-dialogo"]').exists()).toBe(true);

    window.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape" }));
    await flushPromises();

    expect(wrapper.find('[data-testid="dispositivos-confirmar-dialogo"]').exists()).toBe(false);
  });

  it("al confirmar se encola la sincronizacion y queda la prevision posterior", async () => {
    const { wrapper, trabajos } = montarConPrevision();
    await flushPromises();

    await confirmarAplicacion(wrapper);

    const post = global.fetch.mock.calls.find(
      ([ruta, opciones]) =>
        opciones && opciones.method === "POST" && String(ruta).includes("sincronizar"),
    );
    expect(post).toBeTruthy();
    expect(String(post[0])).toBe("/api/v1/areas/alimentacion/dispositivos/sincronizar");
    expect(JSON.parse(post[1].body)).toEqual({ plc: "ZC_PLC_STD" });
    expect(wrapper.find('[data-testid="dispositivos-confirmar-dialogo"]').exists()).toBe(false);

    // El trabajo termina: la vista se queda con la prevision posterior.
    trabajos.aplicar({
      type: "job",
      job: "j1",
      estado: "ok",
      resultado: { prevision: PREVISION_POST, transacciones: TRANSACCIONES },
      error: null,
    });
    await flushPromises();

    expect(wrapper.find('[data-testid="dispositivos-resumen"]').text()).toContain("0 a agregar");
    expect(wrapper.find('[data-testid="dispositivos-resumen"]').text()).toContain("2 sin cambios");
  });

  it("el estado de cada transaccion se ve al terminar la sincronizacion", async () => {
    const { wrapper, trabajos } = montarConPrevision();
    await flushPromises();

    await confirmarAplicacion(wrapper);

    trabajos.aplicar({
      type: "job",
      job: "j1",
      estado: "ok",
      resultado: { prevision: PREVISION_POST, transacciones: TRANSACCIONES },
      error: null,
    });
    await flushPromises();

    const bloque = wrapper.find('[data-testid="dispositivos-transacciones"]');
    expect(bloque.exists()).toBe(true);
    expect(bloque.text()).toContain("N_MAX y renombres: confirmada");
    expect(bloque.text()).toContain("Dispositivos: confirmada");
    expect(bloque.text()).toContain("Comentarios: no ejecutada");
  });

  it("el error de la sincronizacion se ve en la vista", async () => {
    const { wrapper, trabajos } = montarConPrevision();
    await flushPromises();

    await confirmarAplicacion(wrapper);

    trabajos.aplicar({
      type: "job",
      job: "j1",
      estado: "error",
      resultado: null,
      error: "La transaccion de dispositivos se revirtio",
    });
    await flushPromises();

    expect(wrapper.find('[data-testid="dispositivos-error"]').text()).toContain(
      "La transaccion de dispositivos se revirtio",
    );
    expect(wrapper.find('[data-testid="dispositivos-transacciones"]').exists()).toBe(false);
  });

  it("subir el Excel y entrar en Dispositivos no pisa el Excel con la foto de la sesion", async () => {
    const pinia = createPinia();
    setActivePinia(pinia);
    // La foto de la sesion es de cuando se cargo la pagina: sin Excel.
    useSesionStore().estado = { areas: { alimentacion: { excel: { cargado: false } } } };
    const excel = useExcelStore();
    excel.aplicar({ cargado: true, archivo: "Maestro.xlsm" });
    const tia = useTiaStore();
    tia.conectado = true;
    usePlcStore().seleccionado = "ZC_PLC_STD";

    const wrapper = mount(Dispositivos, { global: { plugins: [pinia] } });
    await flushPromises();

    expect(excel.cargado).toBe(true);
    expect(
      wrapper.find('[data-testid="dispositivos-generar"]').attributes("disabled"),
    ).toBeUndefined();
  });

  it("la prevision guardada en la sesion se ve tras un F5", async () => {
    const pinia = createPinia();
    setActivePinia(pinia);
    useSesionStore().estado = {
      areas: {
        alimentacion: { prevision_dispositivos: { plc: "ZC_PLC_STD", resultado: PREVISION } },
      },
    };
    useTiaStore().conectado = true;
    usePlcStore().seleccionado = "ZC_PLC_STD";

    const wrapper = mount(Dispositivos, { global: { plugins: [pinia] } });
    await flushPromises();

    expect(wrapper.find('[data-testid="dispositivos-tabla"]').exists()).toBe(true);
  });

  it("la prevision de otro PLC no se ve", async () => {
    const { wrapper, plc } = montarConPrevision();
    plc.seleccionado = "OTRO_PLC";
    await flushPromises();

    expect(wrapper.find('[data-testid="dispositivos-tabla"]').exists()).toBe(false);
    expect(wrapper.find('[data-testid="dispositivos-vacio"]').exists()).toBe(true);
  });

  it("sin TIA la prevision no se ve", async () => {
    const { wrapper, tia } = montarConPrevision();
    tia.conectado = false;
    await flushPromises();

    expect(wrapper.find('[data-testid="dispositivos-tabla"]').exists()).toBe(false);
  });
});
