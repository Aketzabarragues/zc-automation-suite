/**
 * Store de las areas y de la vista activa.
 *
 * El shell tiene dos niveles: la pantalla de inicio (selector de area) y el
 * interior de un area. Dentro del area hay vistas: las del area (las aporta
 * su menu) y las del shell (PLC y editor de bloques), que son las mismas
 * para todas las areas.
 */
import { defineStore } from "pinia";
import { AREAS, VISTAS } from "../../areas/index.js";

/** Vistas del shell, comunes a todas las areas. */
export const VISTAS_SHELL = [
  { clave: "plc", etiqueta: "PLC", icono: "🔌" },
  { clave: "block-editor", etiqueta: "Editor de bloques", icono: "🔧" },
];

export const useAreasStore = defineStore("areas", {
  state: () => ({
    /** Id del area activa. Vacio en la pantalla de inicio. */
    areaId: "",
    /** Clave de la vista activa. */
    vista: "inicio",
  }),

  getters: {
    /** Todas las areas de la app. */
    areas: () => AREAS,

    /** El area activa, o ``null``. */
    area: (state) => AREAS.find((area) => area.id === state.areaId) || null,

    /** El menu del area activa. */
    menu() {
      return this.area ? this.area.menu : [];
    },

    /** La etiqueta de la vista activa, para las migas. */
    etiquetaVista() {
      const shell = VISTAS_SHELL.find((vista) => vista.clave === this.vista);
      if (shell) return shell.etiqueta;
      const item = this.menu.find((entrada) => entrada.clave === this.vista);
      return item ? item.etiqueta : "Inicio";
    },

    /** El componente de la vista activa, si existe. */
    componenteVista() {
      const item = this.menu.find((entrada) => entrada.clave === this.vista);
      if (!item || !item.vista) return null;
      return VISTAS[item.vista] || null;
    },
  },

  actions: {
    /** Entra en un area. */
    entrar(areaId) {
      this.areaId = areaId;
      this.vista = "inicio";
    },

    /** Cambia de vista dentro del area. */
    irA(vista) {
      this.vista = vista;
    },

    /** Vuelve a la pantalla de inicio. */
    volver() {
      this.areaId = "";
      this.vista = "inicio";
    },
  },
});
