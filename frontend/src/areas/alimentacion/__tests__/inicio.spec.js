import { mount } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";
import { describe, expect, it } from "vitest";
import Inicio from "../vistas/Inicio.vue";
import { useAreasStore } from "../../../nucleo/stores/areas.js";

/**
 * Monta la vista de inicio del area con un pinia limpio y el area activa.
 *
 * @returns {object} `{wrapper, areas}`.
 */
function montar() {
  const pinia = createPinia();
  setActivePinia(pinia);
  const areas = useAreasStore();
  areas.entrar("alimentacion");
  const wrapper = mount(Inicio, { global: { plugins: [pinia] } });
  return { wrapper, areas };
}

describe("Inicio del area", () => {
  it("enseña una tarjeta por accion, en el orden del menu del area", () => {
    const { wrapper } = montar();

    const claves = wrapper
      .findAll('[data-testid^="area-accion-"]')
      .map((boton) => boton.attributes("data-testid").replace("area-accion-", ""));

    expect(claves).toEqual(["def", "disp", "ent", "proc"]);
  });

  it("cada boton Abrir lleva a su vista", async () => {
    const { wrapper, areas } = montar();

    for (const clave of ["def", "disp", "ent", "proc"]) {
      areas.irA("inicio");
      await wrapper.find(`[data-testid="area-accion-${clave}"]`).trigger("click");
      expect(areas.vista).toBe(clave);
    }
  });
});
