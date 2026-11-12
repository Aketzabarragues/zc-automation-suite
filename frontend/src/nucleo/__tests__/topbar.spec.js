import { mount } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";
import { beforeEach, describe, expect, it } from "vitest";
import ShellTopbar from "../componentes/ShellTopbar.vue";
import { useAreasStore } from "../stores/areas.js";
import { usePlcStore } from "../stores/plc.js";

describe("ShellTopbar", () => {
  let pinia;

  beforeEach(() => {
    pinia = createPinia();
    setActivePinia(pinia);
  });

  it("enseña las migas del area y de la vista", () => {
    const areas = useAreasStore();
    areas.entrar("alimentacion");
    areas.irA("plc");
    const wrapper = mount(ShellTopbar, { global: { plugins: [pinia] } });

    expect(wrapper.text()).toContain("ÁREA DE ALIMENTACIÓN");
    expect(wrapper.text()).toContain("PLC");
  });

  it("la vista de la miga cambia con la vista activa", () => {
    const areas = useAreasStore();
    areas.entrar("alimentacion");
    areas.irA("block-editor");
    const wrapper = mount(ShellTopbar, { global: { plugins: [pinia] } });

    expect(wrapper.text()).toContain("EDITOR DE BLOQUES");
  });

  it("la pastilla de PLC va vacia si no hay PLC seleccionado", () => {
    const wrapper = mount(ShellTopbar, { global: { plugins: [pinia] } });
    expect(wrapper.find('[data-testid="topbar-plc"]').text()).toContain("PLC:");
    expect(wrapper.find('[data-testid="topbar-plc"]').text()).toContain("—");
  });

  it("la pastilla de PLC muestra el PLC seleccionado", () => {
    const plc = usePlcStore();
    plc.seleccionado = "ZC_PLC_STD";
    const wrapper = mount(ShellTopbar, { global: { plugins: [pinia] } });

    expect(wrapper.find('[data-testid="topbar-plc"]').text()).toContain("ZC_PLC_STD");
  });

  it("no hay boton de conectar en la barra superior", () => {
    // La conexion se hace en la vista PLC.
    const wrapper = mount(ShellTopbar, { global: { plugins: [pinia] } });
    expect(wrapper.find('[data-testid="topbar-boton"]').exists()).toBe(false);
  });
});
