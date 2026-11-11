import { flushPromises, mount } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";
import { beforeEach, describe, expect, it, vi } from "vitest";
import Dispositivos from "../areas/alimentacion/vistas/Dispositivos.vue";
import { useDispositivosStore } from "../stores/dispositivos.js";
import { useExcelStore } from "../stores/excel.js";
import { usePlcStore } from "../stores/plc.js";
import { useTiaStore } from "../stores/tia.js";

/** La prevision que devuelve el backend. */
const PREVISION = {
  agregados: [{ uid: "9", table: "2000_Disp_ED", plc_tag: "ED_009" }],
  eliminados: [],
  renombrados: [{ uid: "1", table: "2000_Disp_ED", actual: "ED_001", nuevo: "V_ED_001" }],
  todos: [
    {
      table: "2000_Disp_ED",
      type: "ed",
      uid: "1",
      numero: 1,
      actual: "ED_001",
      nuevo: "V_ED_001",
      status: "renombrar",
      comentario_actual: "",
    },
    {
      table: "2000_Disp_ED",
      type: "ed",
      uid: "2",
      numero: 2,
      actual: "ED_002",
      nuevo: "ED_002",
      status: "sin_cambios",
      comentario_actual: "",
    },
    {
      table: "2000_Disp_ED",
      type: "ed",
      uid: "9",
      numero: 9,
      actual: null,
      nuevo: "ED_009",
      status: "agregar",
      comentario_actual: "",
    },
  ],
  nmax: {
    current: { N_MAX_DISP_ED: 10 },
    desired: { N_MAX_DISP_ED: 20 },
    todos: [{ name: "N_MAX_DISP_ED", actual: 10, nuevo: 20, status: "actualizar" }],
    summary: { actualizar: 1, sin_cambios: 0, total: 1 },
  },
  summary: { agregar: 1, eliminar: 0, renombrados: 1, sin_cambios: 1, total: 3 },
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

describe("Dispositivos", () => {
  beforeEach(() => {
    global.fetch = vi.fn().mockResolvedValue({ ok: true, json: async () => ({}) });
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

    const boton = wrapper.find('[data-testid="dispositivos-generar"]');
    expect(boton.attributes("disabled")).toBeDefined();

    tia.conectado = true;
    excel.cargado = true;
    plc.seleccionado = "ZC_PLC_STD";
    await flushPromises();

    expect(wrapper.find('[data-testid="dispositivos-generar"]').attributes("disabled")).toBeUndefined();
  });

  it("con prevision enseña el resumen, las pestañas y el diff", async () => {
    const { wrapper, dispositivos } = montar();
    dispositivos.preview = PREVISION;
    await flushPromises();

    expect(wrapper.find('[data-testid="dispositivos-resumen"]').text()).toContain(
      "3 dispositivos analizados",
    );
    expect(wrapper.find('[data-testid="dispositivos-resumen"]').text()).toContain("1 a agregar");
    expect(wrapper.find('[data-testid="dispositivos-resumen"]').text()).toContain("1 a renombrar");

    const pestana = wrapper.find('[data-testid="dispositivos-tipo-ed"]');
    expect(pestana.exists()).toBe(true);
    expect(pestana.text()).toContain("(3)");

    const tabla = wrapper.find('[data-testid="dispositivos-tabla"]');
    expect(tabla.text()).toContain("RENOMBRAR");
    expect(tabla.text()).toContain("AGREGAR");
    expect(tabla.text()).toContain("OK");
    expect(tabla.text()).toContain("V_ED_001");
  });

  it("las tarjetas de N_MAX muestran el valor nuevo en naranja", async () => {
    const { wrapper, dispositivos } = montar();
    dispositivos.preview = PREVISION;
    await flushPromises();

    const tarjetas = wrapper.find('[data-testid="dispositivos-nmax"]');
    expect(tarjetas.exists()).toBe(true);
    expect(tarjetas.text()).toContain("N_MAX_DISP_ED");
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
