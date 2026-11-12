import { createPinia, setActivePinia } from "pinia";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { usePlcStore } from "../stores/plc.js";
import { useSesionStore } from "../stores/sesion.js";
import { useTiaStore } from "../stores/tia.js";

/** El estado de la sesion, como lo sirve el backend. */
const ESTADO = {
  tia: { conectado: true, version_tia: "V21.0", ultimo_error: null, trabajo_actual: null },
  plcs: [{ nombre: "ZC_PLC_STD", designacion: "CPU 1516-3" }],
  proyecto: { nombre: "ZC_PLC_STD", ruta: "D:\\Proyectos\\ZC_PLC_STD.ap21" },
  plc_seleccionado: "ZC_PLC_STD",
  escaneo: {
    plc: "ZC_PLC_STD",
    bloques: [{ nombre: "OB1_MAIN", numero: 1, tipo: "OB", ruta: "" }],
    tablas: [],
    tipos: [],
    momento: "2026-11-12T10:00:00",
    caducado: false,
  },
  areas: {
    alimentacion: {
      excel: { cargado: true, archivo: "maestro.xlsm", datos: { plcs: [] } },
    },
  },
};

describe("store de la sesion", () => {
  let pinia;

  beforeEach(() => {
    pinia = createPinia();
    setActivePinia(pinia);
  });

  it("al hidratarse refleja el estado de TIA y el del PLC", async () => {
    global.fetch = vi.fn(() =>
      Promise.resolve({ ok: true, json: async () => ESTADO }),
    );
    const sesion = useSesionStore();

    await sesion.hidratar();

    const tia = useTiaStore();
    expect(tia.conectado).toBe(true);
    expect(tia.version_tia).toBe("V21.0");

    const plc = usePlcStore();
    expect(plc.plcs).toHaveLength(1);
    expect(plc.seleccionado).toBe("ZC_PLC_STD");
    expect(plc.bloques).toHaveLength(1);
    expect(sesion.hidratada).toBe(true);
  });

  it("el estado de cada area queda accesible", async () => {
    global.fetch = vi.fn(() =>
      Promise.resolve({ ok: true, json: async () => ESTADO }),
    );
    const sesion = useSesionStore();

    await sesion.hidratar();

    expect(sesion.area("alimentacion").excel.archivo).toBe("maestro.xlsm");
    expect(sesion.area("otro_area")).toBe(null);
  });

  it("sin backend no rompe la app", async () => {
    global.fetch = vi.fn(() => Promise.reject(new Error("sin backend")));
    const sesion = useSesionStore();

    await sesion.hidratar();

    expect(sesion.error).toContain("sin backend");
    expect(sesion.estado).toBe(null);
    expect(usePlcStore().seleccionado).toBe("");
  });

  it("no guarda nada en el navegador", async () => {
    global.fetch = vi.fn(() =>
      Promise.resolve({ ok: true, json: async () => ESTADO }),
    );
    const sesion = useSesionStore();

    await sesion.hidratar();

    expect(window.localStorage.length).toBe(0);
    expect(window.sessionStorage.length).toBe(0);
  });

  it("perder TIA vacia los PLCs, la seleccion y el escaneo (como main: resetPlcState)", () => {
    const tia = useTiaStore();
    const plc = usePlcStore();
    tia.aplicar({ conectado: true });
    plc.plcs = [{ nombre: "ZC_PLC_STD" }];
    plc.seleccionado = "ZC_PLC_STD";
    plc.bloques = [{ nombre: "OB1_MAIN" }];

    tia.aplicar({ conectado: false, ultimo_error: "TIA Portal se ha cerrado o no responde" });

    expect(plc.plcs).toEqual([]);
    expect(plc.seleccionado).toBe("");
    expect(plc.bloques).toEqual([]);
  });

  it("un evento tia sin cambio de conexion no vacia el PLC", () => {
    const tia = useTiaStore();
    const plc = usePlcStore();
    tia.aplicar({ conectado: true });
    plc.seleccionado = "ZC_PLC_STD";

    tia.aplicar({ conectado: true, trabajo_actual: "escanear" });

    expect(plc.seleccionado).toBe("ZC_PLC_STD");
  });
});
