import { mount } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";
import { beforeEach, describe, expect, it } from "vitest";
import ConsolaLogs from "../components/ConsolaLogs.vue";
import { useLogsStore } from "../stores/logs.js";

describe("ConsolaLogs", () => {
  let pinia;

  beforeEach(() => {
    pinia = createPinia();
    setActivePinia(pinia);
  });

  it("espera eventos cuando esta vacia", () => {
    const wrapper = mount(ConsolaLogs, { global: { plugins: [pinia] } });
    expect(wrapper.text()).toContain("Esperando eventos");
  });

  it("enseña los mensajes, el mas reciente arriba", () => {
    const logs = useLogsStore();
    logs.aplicar({ nivel: "info", mensaje: "el primero" });
    logs.aplicar({ nivel: "info", mensaje: "el segundo" });
    const wrapper = mount(ConsolaLogs, { global: { plugins: [pinia] } });

    const texto = wrapper.text();
    expect(texto.indexOf("el segundo")).toBeLessThan(texto.indexOf("el primero"));
  });

  it("el traceback se despliega al pulsar", async () => {
    const logs = useLogsStore();
    logs.aplicar({
      nivel: "error",
      mensaje: "algo fallo",
      detalle: "Traceback (most recent call last):\n  File ...",
    });
    const wrapper = mount(ConsolaLogs, { global: { plugins: [pinia] } });

    expect(wrapper.find('[data-testid="consola-traceback"]').exists()).toBe(false);
    await wrapper.find('[data-testid="consola-detalle"]').trigger("click");
    expect(wrapper.find('[data-testid="consola-traceback"]').text()).toContain("Traceback");
  });

  it("sin traceback no hay boton", () => {
    const logs = useLogsStore();
    logs.aplicar({ nivel: "info", mensaje: "sin traceback" });
    const wrapper = mount(ConsolaLogs, { global: { plugins: [pinia] } });

    expect(wrapper.find('[data-testid="consola-detalle"]').exists()).toBe(false);
  });

  it("el boton de limpiar vacia la consola", async () => {
    const logs = useLogsStore();
    logs.aplicar({ nivel: "info", mensaje: "hola" });
    const wrapper = mount(ConsolaLogs, { global: { plugins: [pinia] } });

    await wrapper.find('[data-testid="consola-limpiar"]').trigger("click");
    expect(wrapper.text()).toContain("Esperando eventos");
  });
});
