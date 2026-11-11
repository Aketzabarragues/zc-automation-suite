import { mount } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";
import { beforeEach, describe, expect, it, vi } from "vitest";
import ShellTopbar from "../componentes/ShellTopbar.vue";
import { useTiaStore } from "../stores/tia.js";

describe("ShellTopbar", () => {
  let pinia;

  beforeEach(() => {
    pinia = createPinia();
    setActivePinia(pinia);
    global.fetch = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ job_id: "abc" }),
    });
  });

  it("empieza desconectada", () => {
    const wrapper = mount(ShellTopbar, { global: { plugins: [pinia] } });
    expect(wrapper.find('[data-testid="topbar-estado"]').text()).toContain("Desconectado");
    expect(wrapper.find('[data-testid="topbar-boton"]').text()).toContain("Conectar");
  });

  it("el boton encola la conexion", async () => {
    const wrapper = mount(ShellTopbar, { global: { plugins: [pinia] } });
    await wrapper.find('[data-testid="topbar-boton"]').trigger("click");
    expect(global.fetch).toHaveBeenCalledWith(
      "/api/v1/tia/conectar",
      expect.objectContaining({ method: "POST" }),
    );
  });

  it("con la conexion viva el boton desconecta", async () => {
    const tia = useTiaStore();
    tia.aplicar({ conectado: true, version_tia: "V21.0", ultimo_error: null });
    const wrapper = mount(ShellTopbar, { global: { plugins: [pinia] } });

    expect(wrapper.find('[data-testid="topbar-estado"]').text()).toContain("Conectado");
    expect(wrapper.find('[data-testid="topbar-version"]').text()).toContain("V21.0");
    expect(wrapper.find('[data-testid="topbar-boton"]').text()).toContain("Desconectar");

    await wrapper.find('[data-testid="topbar-boton"]').trigger("click");
    expect(global.fetch).toHaveBeenCalledWith(
      "/api/v1/tia/desconectar",
      expect.objectContaining({ method: "POST" }),
    );
  });

  it("enseña el ultimo error", () => {
    const tia = useTiaStore();
    tia.aplicar({ conectado: false, ultimo_error: "No hay ningún TIA Portal abierto" });
    const wrapper = mount(ShellTopbar, { global: { plugins: [pinia] } });

    expect(wrapper.find('[data-testid="topbar-error"]').text()).toContain("TIA Portal");
  });

  it("avisa cuando el stream de eventos se ha caido", () => {
    const tia = useTiaStore();
    tia.estadoStream = "reconectando";
    const wrapper = mount(ShellTopbar, { global: { plugins: [pinia] } });

    expect(wrapper.find('[data-testid="topbar-stream"]').exists()).toBe(true);
  });

  it("en modo demo no hay stream que se haya caido", () => {
    const tia = useTiaStore();
    tia.demo = true;
    tia.estadoStream = "cerrado";
    const wrapper = mount(ShellTopbar, { global: { plugins: [pinia] } });

    expect(wrapper.find('[data-testid="topbar-stream"]').exists()).toBe(false);
    expect(wrapper.find('[data-testid="topbar-demo"]').exists()).toBe(true);
  });
});
