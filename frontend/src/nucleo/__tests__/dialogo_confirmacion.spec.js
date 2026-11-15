import { mount } from "@vue/test-utils";
import { describe, expect, it } from "vitest";
import DialogoConfirmacion from "../componentes/DialogoConfirmacion.vue";

/** Monta el dialogo con las props indicadas. */
function montar(props = {}) {
  return mount(DialogoConfirmacion, {
    props: { abierto: true, texto: "Texto de prueba", prefijo: "prueba", ...props },
  });
}

/** Dispara Escape en la ventana. */
function escape() {
  window.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape" }));
}

describe("DialogoConfirmacion", () => {
  it("pinta el texto", () => {
    const wrapper = montar();
    expect(wrapper.find('[data-testid="prueba-confirmar-texto"]').text()).toBe(
      "Texto de prueba",
    );
  });

  it("cerrado no pinta nada", () => {
    const wrapper = montar({ abierto: false });
    expect(wrapper.find('[data-testid="prueba-confirmar-fondo"]').exists()).toBe(false);
    expect(wrapper.find('[data-testid="prueba-confirmar-dialogo"]').exists()).toBe(false);
    // El v-if de la raiz deja solo un comentario de Vue.
    expect(wrapper.html()).toBe("<!--v-if-->");
  });

  it("tiene el rol de dialogo y el aria-modal", () => {
    const wrapper = montar();
    const dialogo = wrapper.find('[data-testid="prueba-confirmar-dialogo"]');
    expect(dialogo.attributes("role")).toBe("dialog");
    expect(dialogo.attributes("aria-modal")).toBe("true");
  });

  it("el boton si emite confirmar", async () => {
    const wrapper = montar();
    await wrapper.find('[data-testid="prueba-confirmar-si"]').trigger("click");
    expect(wrapper.emitted("confirmar")).toHaveLength(1);
  });

  it("el boton cancelar emite cancelar", async () => {
    const wrapper = montar();
    await wrapper.find('[data-testid="prueba-confirmar-no"]').trigger("click");
    expect(wrapper.emitted("cancelar")).toHaveLength(1);
  });

  it("el click en el fondo emite cancelar", async () => {
    const wrapper = montar();
    await wrapper.find('[data-testid="prueba-confirmar-fondo"]').trigger("click");
    expect(wrapper.emitted("cancelar")).toHaveLength(1);
  });

  it("el click dentro del dialogo no emite cancelar", async () => {
    const wrapper = montar();
    await wrapper.find('[data-testid="prueba-confirmar-dialogo"]').trigger("click");
    expect(wrapper.emitted("cancelar")).toBeUndefined();
  });

  it("Escape emite cancelar", async () => {
    const wrapper = montar();
    escape();
    await Promise.resolve();
    expect(wrapper.emitted("cancelar")).toHaveLength(1);
    wrapper.unmount();
  });

  it("Escape con abierto=false no emite", async () => {
    const wrapper = montar({ abierto: false });
    escape();
    await Promise.resolve();
    expect(wrapper.emitted("cancelar")).toBeUndefined();
    wrapper.unmount();
  });
});
