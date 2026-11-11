import { mount } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";
import { beforeEach, describe, expect, it } from "vitest";
import App from "../App.vue";

describe("App", () => {
  let pinia;

  beforeEach(() => {
    pinia = createPinia();
    setActivePinia(pinia);
  });

  it("monta el shell", () => {
    const wrapper = mount(App, { global: { plugins: [pinia] } });
    expect(wrapper.text()).toContain("ZC Automation Suite");
  });

  it("muestra la barra superior, el menu y la consola", () => {
    const wrapper = mount(App, { global: { plugins: [pinia] } });
    expect(wrapper.find('[data-testid="topbar-boton"]').exists()).toBe(true);
    expect(wrapper.find('[data-testid="sidebar-menu"]').exists()).toBe(true);
    expect(wrapper.find('[data-testid="consola-limpiar"]').exists()).toBe(true);
  });
});
