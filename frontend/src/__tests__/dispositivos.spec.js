import { flushPromises, mount } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";
import { beforeEach, describe, expect, it, vi } from "vitest";
import Dispositivos from "../areas/alimentacion/vistas/Dispositivos.vue";
import { useDispositivosStore } from "../stores/dispositivos.js";
import { useExcelStore } from "../stores/excel.js";
import { usePlcStore } from "../stores/plc.js";
import { useTiaStore } from "../stores/tia.js";

/** El catalogo del area, como lo sirve el backend. */
const CATALOGO = {
  alimentacion: {
    device_tabs: [
      { hw_type: "ed", canonical: "DispED", label: "ED" },
      { hw_type: "ea", canonical: "DispEA", label: "EA" },
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
 * Monta la vista con un pinia limpio.
 *
 * @returns {object} `{wrapper, dispositivos, excel, plc, tia}`.
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
  };
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

describe("Dispositivos", () => {
  beforeEach(() => {
    global.fetch = vi.fn((ruta) => {
      if (String(ruta).includes("/api/v1/catalog")) {
        return Promise.resolve({ ok: true, json: async () => CATALOGO });
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
    const { wrapper, dispositivos } = montar();
    dispositivos.preview = PREVISION;
    await flushPromises();

    const resumen = wrapper.find('[data-testid="dispositivos-resumen"]');
    expect(resumen.text()).toContain("4 dispositivos analizados");
    expect(resumen.text()).toContain("1 a agregar");
    expect(resumen.text()).toContain("1 a renombrar");
    expect(resumen.text()).toContain("1 a eliminar");
    expect(resumen.text()).toContain("1 sin cambios");
  });

  it("las pestañas salen del catalogo, con su etiqueta y su contador", async () => {
    const { wrapper, dispositivos } = montar();
    dispositivos.preview = PREVISION;
    await flushPromises();

    const pestana = wrapper.find('[data-testid="dispositivos-tipo-ed"]');
    expect(pestana.exists()).toBe(true);
    expect(pestana.text()).toContain("ED");
    expect(pestana.text()).toContain("(4)");
    expect(wrapper.find('[data-testid="dispositivos-tipo-ea"]').text()).toContain("(0)");
  });

  it("las filas salen con el estado y el color de cada caso", async () => {
    const { wrapper, dispositivos } = montar();
    dispositivos.preview = PREVISION;
    await flushPromises();

    const tabla = wrapper.find('[data-testid="dispositivos-tabla"]');
    expect(tabla.text()).toContain("RENOMBRAR");
    expect(tabla.text()).toContain("AGREGAR");
    expect(tabla.text()).toContain("ELIMINAR");
    expect(tabla.text()).toContain("OK");
    expect(tabla.text()).toContain("V_ED_001");
  });

  it("las filas salen ordenadas por numero", async () => {
    const { wrapper, dispositivos } = montar();
    dispositivos.preview = PREVISION;
    await flushPromises();

    expect(numeros(wrapper)).toEqual(["1", "2", "3", "9"]);
  });

  it("la fila a eliminar enseña el valor actual tachado y en rojo", async () => {
    const { wrapper, dispositivos } = montar();
    dispositivos.preview = PREVISION;
    await flushPromises();

    const fila = wrapper.findAll('[data-testid="dispositivos-tabla"] tbody tr')[2];
    const actual = fila.findAll("td")[1];
    expect(actual.text()).toBe("ED_003");
    expect(actual.classes()).toContain("line-through");
    expect(actual.classes()).toContain("text-red-700");
  });

  it("una pestaña sin dispositivos avisa", async () => {
    const { wrapper, dispositivos } = montar();
    dispositivos.preview = PREVISION;
    await flushPromises();

    await wrapper.find('[data-testid="dispositivos-tipo-ea"]').trigger("click");
    await flushPromises();

    expect(wrapper.find('[data-testid="dispositivos-tabla"]').text()).toContain(
      '⚠️ Sin dispositivos para "ea".',
    );
  });

  it("las tarjetas de N_MAX salen todas, con la etiqueta del catalogo", async () => {
    const { wrapper, dispositivos } = montar();
    dispositivos.preview = PREVISION;
    await flushPromises();

    const tarjetas = wrapper.find('[data-testid="dispositivos-nmax"]');
    expect(tarjetas.exists()).toBe(true);
    expect(tarjetas.text()).toContain("num_disp_ed");
    expect(tarjetas.text()).toContain("10");
    expect(tarjetas.text()).toContain("20");
  });

  it("el boton de aplicar dice que esta pendiente y no hace nada", async () => {
    const { wrapper, dispositivos } = montar();
    dispositivos.preview = PREVISION;
    await flushPromises();

    const boton = wrapper.find('[data-testid="dispositivos-aplicar"]');
    expect(boton.text()).toContain("Pendiente (fase 4.3)");
    expect(boton.attributes("disabled")).toBeDefined();
  });
});
