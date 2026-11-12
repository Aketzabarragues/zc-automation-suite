import { flushPromises, mount } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";
import { beforeEach, describe, expect, it, vi } from "vitest";
import BannerConfig from "../componentes/BannerConfig.vue";
import { useConfigStore } from "../stores/config.js";

/** El estado de la configuracion, como lo sirve el backend. */
const VALIDO = {
  ruta: "C:\\app\\config\\config.json",
  origen: "usuario",
  incompatible: false,
  motivo: null,
  areas_faltantes: [],
};

const INCOMPATIBLE = {
  ruta: "C:\\app\\config\\config.json",
  origen: "usuario",
  incompatible: true,
  motivo: "El config.json no tiene la seccion 'areas'.",
  areas_faltantes: ["alimentacion"],
};

describe("BannerConfig", () => {
  let pinia;

  beforeEach(() => {
    pinia = createPinia();
    setActivePinia(pinia);
    global.fetch = vi.fn(() =>
      Promise.resolve({
        ok: true,
        json: () => Promise.resolve(VALIDO),
      }),
    );
  });

  it("no se ve cuando el config vale", async () => {
    const wrapper = mount(BannerConfig, { global: { plugins: [pinia] } });
    await flushPromises();

    expect(wrapper.find('[data-testid="banner-config"]').exists()).toBe(false);
  });

  it("enseña el banner rojo cuando el config no vale", async () => {
    global.fetch = vi.fn(() =>
      Promise.resolve({
        ok: true,
        json: () => Promise.resolve(INCOMPATIBLE),
      }),
    );
    const wrapper = mount(BannerConfig, { global: { plugins: [pinia] } });
    await flushPromises();

    const banner = wrapper.find('[data-testid="banner-config"]');
    expect(banner.exists()).toBe(true);
    expect(banner.text()).toContain("no tiene la seccion");
  });

  it("el store guarda el estado que dice el backend", async () => {
    global.fetch = vi.fn(() =>
      Promise.resolve({
        ok: true,
        json: () => Promise.resolve(INCOMPATIBLE),
      }),
    );
    const config = useConfigStore();
    await config.cargar();

    expect(config.incompatible).toBe(true);
    expect(config.motivo).toContain("areas");
    expect(config.ruta).toContain("config.json");
  });

  it("sin backend no hay banner", async () => {
    global.fetch = vi.fn(() => Promise.reject(new Error("sin backend")));
    const config = useConfigStore();
    await config.cargar();

    expect(config.cargada).toBe(true);
    expect(config.incompatible).toBe(false);
  });
});
