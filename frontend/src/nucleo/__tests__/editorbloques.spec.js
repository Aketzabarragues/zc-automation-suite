import { flushPromises, mount } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";
import { beforeEach, describe, expect, it, vi } from "vitest";
import EditorBloques from "../vistas/EditorBloques.vue";
import { usePlcStore } from "../stores/plc.js";
import { useTiaStore } from "../stores/tia.js";
import { useTrabajosStore } from "../stores/trabajos.js";

const BLOQUES = [
  {
    nombre: "OB1_MAIN",
    numero: 1,
    tipo: "OB",
    ruta: "",
    extended: {
      title: "Principal",
      author: "Aketza",
      version: "1.0",
      programming_language: null,
      memory_layout: null,
    },
  },
];

function montar() {
  const pinia = createPinia();
  setActivePinia(pinia);
  const tia = useTiaStore();
  tia.aplicar({ conectado: true });
  const plc = usePlcStore();
  plc.seleccionar("ZC_PLC_STD");
  plc.bloques = BLOQUES;
  const wrapper = mount(EditorBloques, { global: { plugins: [pinia] } });
  return { wrapper, trabajos: useTrabajosStore() };
}

describe("EditorBloques", () => {
  beforeEach(() => {
    global.fetch = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ job_id: "j1" }),
    });
  });

  it("sin conexion pide conectar", () => {
    const pinia = createPinia();
    setActivePinia(pinia);
    const wrapper = mount(EditorBloques, { global: { plugins: [pinia] } });

    expect(wrapper.find('[data-testid="editor-sin-conexion"]').exists()).toBe(true);
  });

  it("con bloque escaneado enseña el arbol", () => {
    const { wrapper } = montar();

    expect(wrapper.find('[data-testid="editor-arbol-lista"]').text()).toContain("OB1_MAIN");
  });

  it("un evento que llega antes del POST tambien se aplica", async () => {
    // La carrera: el trabajo termina antes de que llegue la respuesta.
    let responder;
    global.fetch = vi.fn(
      () =>
        new Promise((resolver) => {
          responder = resolver;
        }),
    );
    const { wrapper, trabajos } = montar();

    await wrapper.find('[data-testid="editor-arbol"] input[type="checkbox"]').trigger("change");
    await wrapper.find('[data-testid="editor-editar"]').trigger("click");

    // El evento sale antes de que el POST conteste.
    trabajos.aplicar({
      type: "job",
      job: "j1",
      estado: "ok",
      resultado: { bloques: BLOQUES },
      error: null,
    });
    responder({ ok: true, json: async () => ({ job_id: "j1" }) });
    await flushPromises();

    expect(wrapper.find('[data-testid="editor-tabla"]').exists()).toBe(true);
    expect(wrapper.find('[data-testid="editor-nombre-OB1_MAIN"]').exists()).toBe(true);
  });

  it("el resultado del trabajo llega a la vista", async () => {
    // El resultado del trabajo es lo que rellena la tabla de propiedades.
    const { wrapper, trabajos } = montar();

    await wrapper.find('[data-testid="editor-arbol"] input[type="checkbox"]').trigger("change");
    await wrapper.find('[data-testid="editor-editar"]').trigger("click");
    await flushPromises();

    trabajos.aplicar({
      type: "job",
      job: "j1",
      estado: "ok",
      resultado: { bloques: BLOQUES },
      error: null,
    });
    await flushPromises();

    expect(wrapper.find('[data-testid="editor-tabla"]').exists()).toBe(true);
    expect(wrapper.find('[data-testid="editor-nombre-OB1_MAIN"]').element.value).toBe("OB1_MAIN");
    expect(wrapper.find('[data-testid="editor-numero-OB1_MAIN"]').element.value).toBe("1");
  });

  it("un trabajo que falla enseña el error en la vista", async () => {
    const { wrapper, trabajos } = montar();

    await wrapper.find('[data-testid="editor-arbol"] input[type="checkbox"]').trigger("change");
    await wrapper.find('[data-testid="editor-editar"]').trigger("click");
    await flushPromises();

    trabajos.aplicar({
      type: "job",
      job: "j1",
      estado: "error",
      resultado: null,
      error: "No se pudo exportar el bloque",
    });
    await flushPromises();

    expect(wrapper.find('[data-testid="editor-error"]').text()).toContain("No se pudo exportar");
    expect(wrapper.find('[data-testid="editor-tabla"]').exists()).toBe(false);
  });

  it("con la tabla abierta el arbol queda deshabilitado", async () => {
    const { wrapper, trabajos } = montar();

    expect(wrapper.find('[data-testid="editor-arbol"]').classes()).not.toContain("opacity-50");

    await wrapper.find('[data-testid="editor-arbol"] input[type="checkbox"]').trigger("change");
    await wrapper.find('[data-testid="editor-editar"]').trigger("click");
    await flushPromises();

    trabajos.aplicar({
      type: "job",
      job: "j1",
      estado: "ok",
      resultado: { bloques: BLOQUES },
      error: null,
    });
    await flushPromises();

    expect(wrapper.find('[data-testid="editor-arbol"]').classes()).toContain("opacity-50");
    expect(wrapper.find('[data-testid="editor-arbol"]').classes()).toContain(
      "pointer-events-none",
    );
  });
});
