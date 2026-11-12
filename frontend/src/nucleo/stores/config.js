/**
 * Store de la configuracion de la app.
 *
 * Si el `config.json` del operario no vale (le falta la seccion de un area
 * registrada), la SPA enseña un banner rojo. El config **no** se sustituye
 * nunca: el del operario manda siempre.
 */
import { defineStore } from "pinia";
import { estadoConfig } from "../api.js";

export const useConfigStore = defineStore("config", {
  state: () => ({
    /** `true` si el backend ya contesto al estado de la configuracion. */
    cargada: false,
    /** Ruta del `config.json` en uso. */
    ruta: "",
    /** De donde sale: `usuario`, `copia`, `plantilla` o `entorno`. */
    origen: "",
    /** `true` si el config no sirve. */
    incompatible: false,
    /** El motivo, para el operario. */
    motivo: "",
  }),

  actions: {
    /**
     * Carga el estado de la configuracion.
     */
    async cargar() {
      try {
        const datos = await estadoConfig();
        this.ruta = (datos && datos.ruta) || "";
        this.origen = (datos && datos.origen) || "";
        this.incompatible = Boolean(datos && datos.incompatible);
        this.motivo = (datos && datos.motivo) || "";
      } catch (error) {
        // Sin backend detras (demo) no hay estado que leer.
        this.incompatible = false;
        this.motivo = "";
      } finally {
        this.cargada = true;
      }
    },
  },
});
