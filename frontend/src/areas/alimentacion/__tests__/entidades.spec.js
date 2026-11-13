import { flushPromises, mount } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";
import { beforeEach, describe, expect, it, vi } from "vitest";
import Entidades from "../vistas/Entidades.vue";
import { useEntidadesStore } from "../stores/entidades.js";
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
    nmax: [{ name: "N_MAX_ENTIDAD", label: "num_entidades" }],
  },
};

/**
 * La prevision que devuelve el backend.
 *
 * Las ops van desordenadas a proposito: la vista las ordena por tag.
 */
const PREVISION = {
  precondiciones_ok: true,
  ops: [
    { kind: "delete", plc_tag: "ENT_050", value_tia: 50 },
    { kind: "rename", plc_tag_tia: "ENT_002", plc_tag_new: "ENT_002_NUEVO", value_tia: 2 },
    { kind: "add", plc_tag: "ENT_004", value_excel: 4, comment_excel: null },
    { kind: "update_comment", plc_tag: "ENT_001", value_tia: 1, comment_tia: null, comment_excel: "Comentario uno" },
    { kind: "sin_cambios", plc_tag: "ENT_099", value_tia: 99 },
  ],
  entities_block: {
    desired: { ENT_001: 1, ENT_002_NUEVO: 2, ENT_004: 4, ENT_099: 99 },
  },
  nmax: {
    current: { N_MAX_ENTIDAD: 3 },
    desired: { N_MAX_ENTIDAD: 6 },
    todos: [{ name: "N_MAX_ENTIDAD", actual: 3, nuevo: 6, status: "actualizar" }],
    summary: { actualizar: 1, sin_cambios: 0, total: 1 },
    nmax_error: null,
  },
  summary: {
    constants_agregados: 1,
    constants_eliminados: 1,
    constants_renombrados: 0,
    constants_sin_cambios: 1,
    comments_added: 0,
    comments_updated: 1,
    comments_unchanged: 0,
    total: 4,
  },
};

/**
 * La prevision que devuelve el backend tras el sync: los cambios ya estan
 * aplicados y solo quedan las entidades sin cambios.
 */
const PREVISION_POST = {
  ...PREVISION,
  ops: [{ kind: "sin_cambios", plc_tag: "ENT_099", value_tia: 99 }],
  entities_block: { desired: { ENT_099: 99 } },
  nmax: {
    current: { N_MAX_ENTIDAD: 6 },
    desired: { N_MAX_ENTIDAD: 6 },
    todos: [{ name: "N_MAX_ENTIDAD", actual: 6, nuevo: 6, status: "sin_cambios" }],
    summary: { actualizar: 0, sin_cambios: 1, total: 1 },
    nmax_error: null,
  },
};

/** Las transacciones que devuelve el trabajo de sincronizacion. */
const TRANSACCIONES = [
  { nombre: "N_MAX", estado: "confirmada", detalle: "1 N_MAX" },
  { nombre: "Constantes", estado: "confirmada", detalle: "1 tablas" },
  { nombre: "Comentarios", estado: "no ejecutada", detalle: "TIA Portal anterior a V21" },
];

/**
 * Monta la vista con un pinia limpio.
 *
 * @returns {object} `{wrapper, entidades, excel, plc, tia, trabajos}`.
 */
function montar() {
  const pinia = createPinia();
  setActivePinia(pinia);
  const wrapper = mount(Entidades, { global: { plugins: [pinia] } });
  return {
    wrapper,
    entidades: useEntidadesStore(),
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
  montado.entidades.preview = PREVISION;
  montado.entidades.previewPlc = "ZC_PLC_STD";
  return montado;
}

/**
 * Las filas de la tabla, en el orden que se ven.
 *
 * @param {object} wrapper la vista montada.
 * @returns {Array<Array<string>>} las celdas de cada fila.
 */
function filas(wrapper) {
  return wrapper.findAll('[data-testid="entidades-tabla"] tbody tr').map((fila) =>
    fila.findAll("td").map((celda) => celda.text()),
  );
}

/**
 * Abre el dialogo de confirmacion y lo confirma.
 *
 * @param {object} wrapper la vista montada.
 */
async function confirmarAplicacion(wrapper) {
  await wrapper.find('[data-testid="entidades-aplicar"]').trigger("click");
  await wrapper.find('[data-testid="entidades-confirmar-si"]').trigger("click");
  await flushPromises();
}

describe("Entidades", () => {
  beforeEach(() => {
    global.fetch = vi.fn((ruta) => {
      const url = String(ruta);
      if (url.includes("/api/v1/catalog")) {
        return Promise.resolve({ ok: true, json: async () => CATALOGO });
      }
      if (url.includes("/api/v1/areas/alimentacion/excel")) {
        return Promise.resolve({ ok: true, json: async () => EXCEL_CARGADO });
      }
      if (url.includes("/entidades/sincronizar")) {
        return Promise.resolve({ ok: true, json: async () => ({ job_id: "j1" }) });
      }
      return Promise.resolve({ ok: true, json: async () => ({}) });
    });
  });

  it("sin prevision enseña el estado vacio", async () => {
    const { wrapper } = montar();
    await flushPromises();

    expect(wrapper.find('[data-testid="entidades-vacio"]').exists()).toBe(true);
    expect(wrapper.find('[data-testid="entidades-vacio"]').text()).toContain(
      "Sin prevision generada.",
    );
    expect(wrapper.find('[data-testid="entidades-tabla"]').exists()).toBe(false);
  });

  it("el boton de generar esta deshabilitado sin TIA o sin Excel", async () => {
    const { wrapper, tia, excel, plc } = montar();
    await flushPromises();

    expect(wrapper.find('[data-testid="entidades-generar"]').attributes("disabled")).toBeDefined();

    tia.conectado = true;
    excel.cargado = true;
    plc.seleccionado = "ZC_PLC_STD";
    await flushPromises();

    expect(
      wrapper.find('[data-testid="entidades-generar"]').attributes("disabled"),
    ).toBeUndefined();
  });

  it("con prevision enseña el resumen de las entidades", async () => {
    const { wrapper } = montarConPrevision();
    await flushPromises();

    const resumen = wrapper.find('[data-testid="entidades-resumen"]');
    expect(resumen.text()).toContain("4 entidades analizadas");
    expect(resumen.text()).toContain("1 a agregar");
    expect(resumen.text()).toContain("2 a renombrar");
    expect(resumen.text()).toContain("1 a eliminar");
    expect(resumen.text()).toContain("1 sin cambios");
  });

  it("la tabla tiene las seis columnas de main", async () => {
    const { wrapper } = montarConPrevision();
    await flushPromises();

    const cabecera = wrapper.find('[data-testid="entidades-tabla"] thead').text();
    expect(cabecera).toContain("Tag Actual (TIA)");
    expect(cabecera).toContain("Comentario Actual (TIA)");
    expect(cabecera).toContain("Tag Deseado (Excel)");
    expect(cabecera).toContain("Comentario Deseado (Excel)");
    expect(cabecera).toContain("Estado");
  });

  it("las filas salen con el estado de cada operacion", async () => {
    const { wrapper } = montarConPrevision();
    await flushPromises();

    const tabla = wrapper.find('[data-testid="entidades-tabla"]');
    expect(tabla.text()).toContain("AGREGAR");
    expect(tabla.text()).toContain("RENOMBRAR");
    expect(tabla.text()).toContain("ELIMINAR");
    expect(tabla.text()).toContain("OK");
    expect(tabla.text()).toContain("ENT_002 -> ENT_002_NUEVO");
    expect(tabla.text()).toContain("Comentario uno");
  });

  it("las filas salen ordenadas por tag", async () => {
    const { wrapper } = montarConPrevision();
    await flushPromises();

    // La columna 3 es el tag que quiere el Excel; la 2, el que hay en TIA.
    const deseados = filas(wrapper).map((celdas) => celdas[3]);
    expect(deseados).toEqual([
      "ENT_001",
      "ENT_002 -> ENT_002_NUEVO",
      "ENT_004",
      "—",
      "ENT_099",
    ]);

    const actuales = filas(wrapper).map((celdas) => celdas[1]);
    expect(actuales).toEqual([
      "ENT_001",
      "ENT_002 -> ENT_002_NUEVO",
      "—",
      "ENT_050",
      "ENT_099",
    ]);
  });

  it("la fila a eliminar enseña el tag tachado y en rojo", async () => {
    const { wrapper } = montarConPrevision();
    await flushPromises();

    const fila = wrapper.findAll('[data-testid="entidades-tabla"] tbody tr')[3];
    const actual = fila.findAll("td")[1];
    expect(actual.text()).toBe("ENT_050");
    expect(actual.classes()).toContain("line-through");
    expect(actual.classes()).toContain("text-red-700");
  });

  it("la tarjeta de N_MAX sale con la etiqueta del catalogo", async () => {
    const { wrapper } = montarConPrevision();
    await flushPromises();

    const tarjeta = wrapper.find('[data-testid="entidades-nmax"]');
    expect(tarjeta.exists()).toBe(true);
    expect(tarjeta.text()).toContain("num_entidades");
    expect(tarjeta.text()).toContain("3");
    expect(tarjeta.text()).toContain("6");
  });

  it("el boton de aplicar esta deshabilitado sin prevision", async () => {
    const { wrapper } = montar();
    await flushPromises();

    const boton = wrapper.find('[data-testid="entidades-aplicar"]');
    expect(boton.text()).toContain("Aplicar Cambios en TIA Portal");
    expect(boton.attributes("disabled")).toBeDefined();
    expect(wrapper.find('[data-testid="entidades-transacciones"]').exists()).toBe(false);
  });

  it("el boton de aplicar enseña cuantos cambios van a aplicarse", async () => {
    const { wrapper } = montarConPrevision();
    await flushPromises();

    const boton = wrapper.find('[data-testid="entidades-aplicar"]');
    expect(boton.text()).toContain("(5 cambios)");
    expect(boton.attributes("disabled")).toBeUndefined();
  });

  it("el boton de aplicar se habilita con Excel, TIA y PLC", async () => {
    const { wrapper, excel, tia, plc } = montarConPrevision();
    await flushPromises();

    expect(
      wrapper.find('[data-testid="entidades-aplicar"]').attributes("disabled"),
    ).toBeUndefined();

    excel.cargado = false;
    await flushPromises();
    expect(
      wrapper.find('[data-testid="entidades-aplicar"]').attributes("disabled"),
    ).toBeDefined();

    excel.cargado = true;
    tia.conectado = false;
    await flushPromises();
    expect(
      wrapper.find('[data-testid="entidades-aplicar"]').attributes("disabled"),
    ).toBeDefined();

    tia.conectado = true;
    plc.seleccionado = "";
    await flushPromises();
    expect(
      wrapper.find('[data-testid="entidades-aplicar"]').attributes("disabled"),
    ).toBeDefined();
  });

  it("mientras se aplica, los botones de generar y de aplicar estan deshabilitados", async () => {
    const { wrapper, entidades } = montarConPrevision();
    await flushPromises();

    entidades.aplicando = true;
    await flushPromises();

    expect(
      wrapper.find('[data-testid="entidades-aplicar"]').attributes("disabled"),
    ).toBeDefined();
    expect(
      wrapper.find('[data-testid="entidades-generar"]').attributes("disabled"),
    ).toBeDefined();
  });

  it("el dialogo de confirmacion se abre al pulsar y se cierra al cancelar", async () => {
    const { wrapper } = montarConPrevision();
    await flushPromises();

    expect(wrapper.find('[data-testid="entidades-confirmar-dialogo"]').exists()).toBe(false);

    await wrapper.find('[data-testid="entidades-aplicar"]').trigger("click");

    const dialogo = wrapper.find('[data-testid="entidades-confirmar-dialogo"]');
    expect(dialogo.exists()).toBe(true);
    expect(dialogo.attributes("role")).toBe("dialog");
    expect(dialogo.attributes("aria-modal")).toBe("true");
    expect(dialogo.text()).toContain("¿Aplicar 5 cambios en TIA Portal?");
    expect(dialogo.text()).toContain("Entities:");
    expect(dialogo.text()).toContain("Agregar: 1");
    expect(dialogo.text()).toContain("Renombrar: 2");
    expect(dialogo.text()).toContain("Eliminar: 1");
    expect(dialogo.text()).toContain("N_MAX (dimensiones):");
    expect(dialogo.text()).toContain("Actualizar: 1");

    await wrapper.find('[data-testid="entidades-confirmar-no"]').trigger("click");

    expect(wrapper.find('[data-testid="entidades-confirmar-dialogo"]').exists()).toBe(false);
  });

  it("el dialogo de confirmacion se cierra con Escape", async () => {
    const { wrapper } = montarConPrevision();
    await flushPromises();

    await wrapper.find('[data-testid="entidades-aplicar"]').trigger("click");
    expect(wrapper.find('[data-testid="entidades-confirmar-dialogo"]').exists()).toBe(true);

    window.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape" }));
    await flushPromises();

    expect(wrapper.find('[data-testid="entidades-confirmar-dialogo"]').exists()).toBe(false);
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
    expect(String(post[0])).toBe("/api/v1/areas/alimentacion/entidades/sincronizar");
    expect(JSON.parse(post[1].body)).toEqual({ plc: "ZC_PLC_STD" });
    expect(wrapper.find('[data-testid="entidades-confirmar-dialogo"]').exists()).toBe(false);

    // El trabajo termina: la vista se queda con la prevision posterior.
    trabajos.aplicar({
      type: "job",
      job: "j1",
      estado: "ok",
      resultado: { prevision: PREVISION_POST, transacciones: TRANSACCIONES },
      error: null,
    });
    await flushPromises();

    expect(wrapper.find('[data-testid="entidades-resumen"]').text()).toContain("0 a agregar");
    expect(wrapper.find('[data-testid="entidades-resumen"]').text()).toContain("1 sin cambios");
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

    const bloque = wrapper.find('[data-testid="entidades-transacciones"]');
    expect(bloque.exists()).toBe(true);
    expect(bloque.text()).toContain("N_MAX: confirmada");
    expect(bloque.text()).toContain("Constantes: confirmada");
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
      error: "La transaccion de constantes se revirtio",
    });
    await flushPromises();

    expect(wrapper.find('[data-testid="entidades-error"]').text()).toContain(
      "La transaccion de constantes se revirtio",
    );
    expect(wrapper.find('[data-testid="entidades-transacciones"]').exists()).toBe(false);
  });

  it("la prevision guardada en la sesion se ve tras un F5", async () => {
    const pinia = createPinia();
    setActivePinia(pinia);
    useSesionStore().estado = {
      areas: {
        alimentacion: { prevision_entidades: { plc: "ZC_PLC_STD", resultado: PREVISION } },
      },
    };
    useTiaStore().conectado = true;
    usePlcStore().seleccionado = "ZC_PLC_STD";

    const wrapper = mount(Entidades, { global: { plugins: [pinia] } });
    await flushPromises();

    expect(wrapper.find('[data-testid="entidades-tabla"]').exists()).toBe(true);
  });

  it("la prevision de otro PLC no se ve", async () => {
    const { wrapper, plc } = montarConPrevision();
    plc.seleccionado = "OTRO_PLC";
    await flushPromises();

    expect(wrapper.find('[data-testid="entidades-tabla"]').exists()).toBe(false);
    expect(wrapper.find('[data-testid="entidades-vacio"]').exists()).toBe(true);
  });

  it("sin TIA la prevision no se ve", async () => {
    const { wrapper, tia } = montarConPrevision();
    tia.conectado = false;
    await flushPromises();

    expect(wrapper.find('[data-testid="entidades-tabla"]').exists()).toBe(false);
  });
});
