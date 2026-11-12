import { mount } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";
import { beforeEach, describe, expect, it } from "vitest";
import App from "../../App.vue";
import { useAreasStore } from "../stores/areas.js";

describe("App", () => {
  let pinia;

  beforeEach(() => {
    pinia = createPinia();
    setActivePinia(pinia);
  });

  it("arranca en la pantalla de inicio, sin barra lateral", () => {
    const wrapper = mount(App, { global: { plugins: [pinia] } });

    expect(wrapper.find('[data-testid="bienvenida"]').exists()).toBe(true);
    expect(wrapper.find('[data-testid="sidebar"]').exists()).toBe(false);
  });

  it("dentro del area, muestra la barra lateral, la superior y la consola", () => {
    const areas = useAreasStore();
    areas.entrar("alimentacion");
    const wrapper = mount(App, { global: { plugins: [pinia] } });

    expect(wrapper.find('[data-testid="sidebar"]').exists()).toBe(true);
    expect(wrapper.find('[data-testid="topbar-plc"]').exists()).toBe(true);
    expect(wrapper.find('[data-testid="consola-limpiar"]').exists()).toBe(true);
  });

  it("la vista PLC se abre desde el menu lateral", () => {
    const areas = useAreasStore();
    areas.entrar("alimentacion");
    const wrapper = mount(App, { global: { plugins: [pinia] } });

    expect(wrapper.find('[data-testid="vista-plc"]').exists()).toBe(false);
  });

  it("el editor de bloques se abre desde el menu lateral", () => {
    const areas = useAreasStore();
    areas.entrar("alimentacion");
    areas.irA("block-editor");
    const wrapper = mount(App, { global: { plugins: [pinia] } });

    expect(wrapper.find('[data-testid="editor-bloques"]').exists()).toBe(true);
  });

  it("el inicio del area es su propia vista", () => {
    const areas = useAreasStore();
    areas.entrar("alimentacion");
    const wrapper = mount(App, { global: { plugins: [pinia] } });

    expect(wrapper.find('[data-testid="area-inicio"]').exists()).toBe(true);
  });
});
