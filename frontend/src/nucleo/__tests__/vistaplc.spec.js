import { mount } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";
import { beforeEach, describe, expect, it, vi } from "vitest";
import VistaPlc from "../vistas/Plc.vue";
import { usePlcStore } from "../stores/plc.js";
import { useTiaStore } from "../stores/tia.js";

describe("VistaPlc", () => {
  let pinia;

  beforeEach(() => {
    pinia = createPinia();
    setActivePinia(pinia);
    global.fetch = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ job_id: "abc" }),
    });
  });

  it("enseña el estado del sistema y los controles", () => {
    const wrapper = mount(VistaPlc, { global: { plugins: [pinia] } });

    expect(wrapper.text()).toContain("Estado del sistema");
    expect(wrapper.text()).toContain("Controles");
    expect(wrapper.find('[data-testid="plc-conectar"]').exists()).toBe(true);
    expect(wrapper.find('[data-testid="plc-desconectar"]').exists()).toBe(true);
  });

  it("sin PLCs muestra el aviso de la lista vacia", () => {
    const wrapper = mount(VistaPlc, { global: { plugins: [pinia] } });

    expect(wrapper.find('[data-testid="plc-lista-vacia"]').text()).toContain(
      "No se han encontrado PLCs disponibles.",
    );
  });

  it("conectado, la lista muestra los PLCs del proyecto", () => {
    const tia = useTiaStore();
    tia.aplicar({ conectado: true, version_tia: "V21.0" });
    const plc = usePlcStore();
    plc.plcs = [{ nombre: "ZC_PLC_STD", designacion: "CPU 1516-3" }];
    plc.proyecto = { nombre: "ZC_PLC_STD", ruta: "D:\\Proyectos\\ZC_PLC_STD.ap21" };

    const wrapper = mount(VistaPlc, { global: { plugins: [pinia] } });

    expect(wrapper.text()).toContain("ZC_PLC_STD");
    expect(wrapper.text()).toContain("CPU 1516-3");
    expect(wrapper.text()).toContain("Seleccionar");
    expect(wrapper.find('[data-testid="plc-ruta"]').text()).toContain("ZC_PLC_STD.ap21");
  });

  it("seleccionar un PLC lo pone en el store y lo marca", async () => {
    const tia = useTiaStore();
    tia.aplicar({ conectado: true });
    const plc = usePlcStore();
    plc.plcs = [{ nombre: "ZC_PLC_STD", designacion: "" }];

    const wrapper = mount(VistaPlc, { global: { plugins: [pinia] } });
    await wrapper.find('[data-testid="plc-card-ZC_PLC_STD"]').trigger("click");

    expect(plc.seleccionado).toBe("ZC_PLC_STD");
    expect(wrapper.find('[data-testid="plc-card-ZC_PLC_STD"]').attributes("data-active")).toBe(
      "true",
    );
  });

  it("sin escaneo pide seleccionar un PLC", () => {
    const wrapper = mount(VistaPlc, { global: { plugins: [pinia] } });

    expect(wrapper.find('[data-testid="plc-vacio"]').text()).toContain("Selecciona un PLC primero.");
  });

  it("el escaneo enseña los bloques agrupados por tipo", () => {
    const tia = useTiaStore();
    tia.aplicar({ conectado: true });
    const plc = usePlcStore();
    plc.seleccionar("ZC_PLC_STD");
    plc.bloques = [
      { nombre: "OB1_MAIN", numero: 1, tipo: "OB", ruta: "" },
      { nombre: "DB10", numero: 10, tipo: "DB", ruta: "0_Sistema" },
    ];

    const wrapper = mount(VistaPlc, { global: { plugins: [pinia] } });

    expect(wrapper.text()).toContain("Bloques");
    expect(wrapper.text()).toContain("OB1_MAIN");
    expect(wrapper.text()).toContain("DB10");
    expect(wrapper.text()).toContain("1 bloque");
  });

  it("el UDT sale con el numero vacio y la ruta completa", async () => {
    const tia = useTiaStore();
    tia.aplicar({ conectado: true });
    const plc = usePlcStore();
    plc.seleccionar("ZC_PLC_STD");
    plc.tipos = [
      {
        nombre: "MiTipo",
        numero: null,
        tipo: "UDT",
        ruta: "ZC_Controles/1_Documentado",
        extended: {},
      },
    ];

    const wrapper = mount(VistaPlc, { global: { plugins: [pinia] } });
    await wrapper.findAll("button").find((boton) => boton.text().includes("UDT")).trigger("click");

    expect(wrapper.text()).toContain("ZC_Controles/1_Documentado");
    expect(wrapper.text()).toContain("MiTipo");
  });
});
