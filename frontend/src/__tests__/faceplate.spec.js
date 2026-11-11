import { mount } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";
import { beforeEach, describe, expect, it } from "vitest";
import FaceplateProgreso from "../components/FaceplateProgreso.vue";
import { useTrabajosStore } from "../stores/trabajos.js";

const PROGRESO = {
  type: "progress",
  active: true,
  operation: "sincronizar",
  label: "Sincronizar dispositivos",
  current: 1,
  total: 3,
  percent: 33,
  stages: [
    { id: "exportar", label: "Exportar bloques", status: "done", detail: "12 bloques" },
    { id: "comparar", label: "Comparar", status: "running", detail: null },
    { id: "aplicar", label: "Aplicar los cambios", status: "pending", detail: null },
  ],
  started_at: null,
  finished_at: null,
  error: null,
};

describe("FaceplateProgreso", () => {
  let pinia;

  beforeEach(() => {
    pinia = createPinia();
    setActivePinia(pinia);
  });

  it("no se ve cuando no hay nada que reportar", () => {
    const wrapper = mount(FaceplateProgreso, { global: { plugins: [pinia] } });
    expect(wrapper.find('[data-testid="faceplate-progreso"]').exists()).toBe(false);
  });

  it("enseña los pasos del trabajo en curso", () => {
    const trabajos = useTrabajosStore();
    trabajos.aplicar(PROGRESO);
    const wrapper = mount(FaceplateProgreso, { global: { plugins: [pinia] } });

    expect(wrapper.find('[data-testid="faceplate-progreso"]').attributes("data-mode")).toBe(
      "running",
    );
    expect(wrapper.text()).toContain("Exportar bloques");
    expect(wrapper.text()).toContain("Aplicar los cambios");
    expect(wrapper.text()).toContain("12 bloques");
  });

  it("enseña el error cuando el trabajo falla", () => {
    const trabajos = useTrabajosStore();
    trabajos.aplicar({ ...PROGRESO, active: false, error: "La compilación tiene errores" });
    const wrapper = mount(FaceplateProgreso, { global: { plugins: [pinia] } });

    expect(wrapper.find('[data-testid="faceplate-progreso"]').attributes("data-mode")).toBe(
      "error",
    );
    expect(wrapper.text()).toContain("La compilación tiene errores");
  });

  it("el boton de cerrar limpia el progreso", async () => {
    const trabajos = useTrabajosStore();
    trabajos.aplicar(PROGRESO);
    const wrapper = mount(FaceplateProgreso, { global: { plugins: [pinia] } });

    await wrapper.find('[data-testid="faceplate-cerrar"]').trigger("click");
    expect(wrapper.find('[data-testid="faceplate-progreso"]').exists()).toBe(false);
  });
});
