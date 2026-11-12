import { mount } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";
import { beforeEach, describe, expect, it } from "vitest";
import Bienvenida from "../componentes/Bienvenida.vue";
import { useAreasStore } from "../stores/areas.js";

describe("Bienvenida", () => {
  let pinia;

  beforeEach(() => {
    pinia = createPinia();
    setActivePinia(pinia);
  });

  it("enseña el logo y el titulo", () => {
    const wrapper = mount(Bienvenida, { global: { plugins: [pinia] } });

    expect(wrapper.find('img[src="/logo-zeus-control.png"]').exists()).toBe(true);
    expect(wrapper.text()).toContain("Zeus Control");
    expect(wrapper.text()).toContain("Selecciona un área para comenzar");
  });

  it("enseña una tarjeta por area", () => {
    const wrapper = mount(Bienvenida, { global: { plugins: [pinia] } });

    expect(wrapper.find('[data-area-key="alimentacion"]').exists()).toBe(true);
    expect(wrapper.text()).toContain("Área de alimentación");
  });

  it("pulsar un area entra en ella", async () => {
    const areas = useAreasStore();
    const wrapper = mount(Bienvenida, { global: { plugins: [pinia] } });

    await wrapper.find('[data-area-key="alimentacion"]').trigger("click");
    expect(areas.areaId).toBe("alimentacion");
    expect(areas.vista).toBe("inicio");
  });
});
