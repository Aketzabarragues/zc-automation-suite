import { mount } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";
import { beforeEach, describe, expect, it } from "vitest";
import ShellSidebar from "../componentes/ShellSidebar.vue";
import { useAreasStore } from "../stores/areas.js";

describe("ShellSidebar", () => {
  let pinia;

  beforeEach(() => {
    pinia = createPinia();
    setActivePinia(pinia);
    useAreasStore().entrar("alimentacion");
  });

  it("enseña la cabecera del area", () => {
    const wrapper = mount(ShellSidebar, { global: { plugins: [pinia] } });
    expect(wrapper.text()).toContain("Área");
    expect(wrapper.text()).toContain("Área de alimentación");
  });

  it("la seccion PLC tiene el PLC y el editor de bloques", () => {
    const wrapper = mount(ShellSidebar, { global: { plugins: [pinia] } });

    expect(wrapper.find('[data-testid="sidebar-plc"]').text()).toContain("PLC");
    expect(wrapper.find('[data-testid="sidebar-plc"]').text()).toContain("Editor de bloques");
  });

  it("la seccion de navegacion trae el menu del area", () => {
    const wrapper = mount(ShellSidebar, { global: { plugins: [pinia] } });
    const menu = wrapper.find('[data-testid="sidebar-menu"]');

    expect(menu.text()).toContain("Navegación");
    expect(menu.text()).toContain("Definición programación");
    expect(menu.text()).toContain("Dispositivos");
    expect(menu.text()).toContain("Procesos");
    expect(menu.text()).toContain("Entidades");
  });

  it("el item activo se marca", () => {
    const areas = useAreasStore();
    areas.irA("disp");
    const wrapper = mount(ShellSidebar, { global: { plugins: [pinia] } });

    expect(wrapper.find('[data-area-key="disp"]').attributes("data-active")).toBe("true");
    expect(wrapper.find('[data-area-key="proc"]').attributes("data-active")).toBe("false");
  });

  it("el boton de volver al inicio sale del area", async () => {
    const areas = useAreasStore();
    const wrapper = mount(ShellSidebar, { global: { plugins: [pinia] } });

    await wrapper.find('[data-testid="sidebar-volver"]').trigger("click");
    expect(areas.areaId).toBe("");
  });

  it("pulsar un item del menu cambia de vista", async () => {
    const areas = useAreasStore();
    const wrapper = mount(ShellSidebar, { global: { plugins: [pinia] } });

    await wrapper.find('[data-area-key="proc"]').trigger("click");
    expect(areas.vista).toBe("proc");
  });
});
