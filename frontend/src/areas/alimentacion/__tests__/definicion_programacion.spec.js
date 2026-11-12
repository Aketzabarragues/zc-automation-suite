import { flushPromises, mount } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";
import { beforeEach, describe, expect, it, vi } from "vitest";
import DefinicionProgramacion from "../vistas/DefinicionProgramacion.vue";
import { useTrabajosStore } from "../../../nucleo/stores/trabajos.js";

/** El Excel maestro que devuelve el backend. */
const EXCEL = {
  cargado: true,
  archivo: "maestro.xlsx",
  cargado_en: "2026-11-11T09:30:00",
  plcs: ["PLC1"],
  configuracion: {
    columnas: ["PLC", "N_MAX_DISP_EA"],
    filas: [{ PLC: "PLC1", N_MAX_DISP_EA: 10 }],
  },
  dispositivos: [
    {
      tipo: "DispED",
      columnas: ["plc_name", "numero", "tag"],
      etiquetas: { numero: "Número", tag: "TAG" },
      filas: [
        { plc_name: "PLC1", numero: 1, tag: "V_ED_001" },
        { plc_name: "PLC1", numero: 2, tag: "" },
      ],
    },
    {
      tipo: "DispEA",
      columnas: ["plc_name", "numero", "tag"],
      etiquetas: { numero: "Número", tag: "TAG" },
      filas: [{ plc_name: "PLC1", numero: 2, tag: "V_EA_002" }],
    },
  ],
  procesos: {
    Procesos: {
      columnas: ["PLC", "CODIGO"],
      filas: [{ PLC: "PLC1", CODIGO: "PR1" }],
    },
    ParametrosEnteros: { columnas: ["PLC", "PARAM"], filas: [] },
    ParametrosReales: { columnas: ["PLC", "PARAM"], filas: [] },
    Alarmas: { columnas: ["PLC", "ALARMA"], filas: [] },
  },
  entidades: {
    columnas: ["PLC", "NUMERO"],
    filas: [{ PLC: "PLC1", NUMERO: 1 }],
  },
  avisos: [],
};

/** El backend sin ningun Excel cargado. */
const VACIO = {
  cargado: false,
  archivo: null,
  cargado_en: null,
  plcs: [],
  configuracion: null,
  dispositivos: [],
  procesos: {},
  entidades: null,
};

/**
 * Monta la vista con un pinia limpio.
 *
 * @returns {object} `{wrapper, trabajos}`.
 */
function montar() {
  const pinia = createPinia();
  setActivePinia(pinia);
  const wrapper = mount(DefinicionProgramacion, { global: { plugins: [pinia] } });
  return { wrapper, trabajos: useTrabajosStore() };
}

describe("DefinicionProgramacion", () => {
  beforeEach(() => {
    global.fetch = vi.fn().mockResolvedValue({ ok: true, json: async () => VACIO });
  });

  it("sin Excel cargado enseña el estado vacio", async () => {
    const { wrapper } = montar();
    await flushPromises();

    expect(wrapper.find('[data-testid="definicion-vacio"]').text()).toContain(
      "La cache del excel está vacía",
    );
    expect(wrapper.find('[data-testid="definicion-pestanas"]').exists()).toBe(false);
  });

  it("con Excel cargado enseña las cuatro pestanas con su contador", async () => {
    global.fetch = vi.fn().mockResolvedValue({ ok: true, json: async () => EXCEL });
    const { wrapper } = montar();
    await flushPromises();

    expect(wrapper.find('[data-testid="definicion-pestana-configuracion"]').text()).toContain(
      "Configuración (1)",
    );
    expect(wrapper.find('[data-testid="definicion-pestana-dispositivos"]').text()).toContain(
      "Dispositivos (3)",
    );
    expect(wrapper.find('[data-testid="definicion-pestana-procesos"]').text()).toContain(
      "Procesos (1)",
    );
    expect(wrapper.find('[data-testid="definicion-pestana-entidades"]').text()).toContain(
      "Entidades (1)",
    );
  });

  it("la tabla de configuracion sale con sus columnas", async () => {
    global.fetch = vi.fn().mockResolvedValue({ ok: true, json: async () => EXCEL });
    const { wrapper } = montar();
    await flushPromises();

    const tabla = wrapper.find('[data-testid="definicion-tabla-datos"]');
    expect(tabla.text()).toContain("PLC");
    expect(tabla.text()).toContain("N_MAX_DISP_EA");
    expect(tabla.text()).toContain("PLC1");
  });

  it("la sub-pestana de dispositivos cambia la tabla", async () => {
    global.fetch = vi.fn().mockResolvedValue({ ok: true, json: async () => EXCEL });
    const { wrapper } = montar();
    await flushPromises();

    await wrapper.find('[data-testid="definicion-pestana-dispositivos"]').trigger("click");
    await wrapper.find('[data-testid="definicion-subpestana-DispEA"]').trigger("click");

    const tabla = wrapper.find('[data-testid="definicion-tabla-datos"]');
    expect(tabla.text()).toContain("V_EA_002");
    expect(tabla.text()).not.toContain("V_ED_001");
  });

  it("las celdas vacias salen como raya", async () => {
    global.fetch = vi.fn().mockResolvedValue({ ok: true, json: async () => EXCEL });
    const { wrapper } = montar();
    await flushPromises();

    await wrapper.find('[data-testid="definicion-pestana-dispositivos"]').trigger("click");

    const tabla = wrapper.find('[data-testid="definicion-tabla-datos"]');
    expect(tabla.text()).toContain("V_ED_001");
    expect(tabla.text()).toContain("—");
  });

  it("los titulos de columna salen de las etiquetas", async () => {
    global.fetch = vi.fn().mockResolvedValue({ ok: true, json: async () => EXCEL });
    const { wrapper } = montar();
    await flushPromises();

    await wrapper.find('[data-testid="definicion-pestana-dispositivos"]').trigger("click");

    const tabla = wrapper.find('[data-testid="definicion-tabla-datos"]');
    expect(tabla.text()).toContain("Número");
    expect(tabla.text()).toContain("TAG");
  });

  it("los avisos del parseo se ven en la vista", async () => {
    const conAvisos = { ...EXCEL, avisos: ["No se encuentra la tabla Tabla_Disp_ED en la hoja DISP_ED"] };
    global.fetch = vi.fn().mockResolvedValue({ ok: true, json: async () => conAvisos });
    const { wrapper } = montar();
    await flushPromises();

    const avisos = wrapper.find('[data-testid="definicion-avisos"]');
    expect(avisos.exists()).toBe(true);
    expect(avisos.text()).toContain("No se encuentra la tabla Tabla_Disp_ED en la hoja DISP_ED");
  });

  it("sin avisos no sale el aviso", async () => {
    global.fetch = vi.fn().mockResolvedValue({ ok: true, json: async () => EXCEL });
    const { wrapper } = montar();
    await flushPromises();

    expect(wrapper.find('[data-testid="definicion-avisos"]').exists()).toBe(false);
  });

  it("un error del backend se ve en la vista y no en un alert", async () => {
    global.fetch = vi.fn().mockResolvedValue({
      ok: false,
      status: 500,
      json: async () => ({ error: "No se pudo leer el Excel" }),
    });
    const alerta = vi.spyOn(window, "alert").mockImplementation(() => {});

    const { wrapper } = montar();
    await flushPromises();

    expect(wrapper.find('[data-testid="definicion-error"]').text()).toContain(
      "No se pudo leer el Excel",
    );
    expect(alerta).not.toHaveBeenCalled();

    // El aviso se puede cerrar: el error se va de la vista.
    await wrapper.find('[data-testid="definicion-error-cerrar"]').trigger("click");
    expect(wrapper.find('[data-testid="definicion-error"]').exists()).toBe(false);

    alerta.mockRestore();
  });

  it("elegir un fichero lo sube y al terminar el trabajo se ven los datos", async () => {
    let hayExcel = false;
    global.fetch = vi.fn((ruta, opciones = {}) => {
      if (opciones.method === "POST") {
        return Promise.resolve({ ok: true, json: async () => ({ job_id: "j1" }) });
      }
      return Promise.resolve({ ok: true, json: async () => (hayExcel ? EXCEL : VACIO) });
    });

    const { wrapper, trabajos } = montar();
    await flushPromises();
    expect(wrapper.find('[data-testid="definicion-cargado"]').exists()).toBe(false);

    const input = wrapper.find('[data-testid="definicion-fichero"]');
    const fichero = new File(["contenido"], "maestro.xlsx", {
      type: "application/vnd.ms-excel",
    });
    Object.defineProperty(input.element, "files", { value: [fichero], configurable: true });
    await input.trigger("change");
    await flushPromises();

    const subida = global.fetch.mock.calls.find(([, opciones]) => opciones.method === "POST");
    expect(subida).toBeTruthy();
    expect(subida[0]).toBe("/api/v1/areas/alimentacion/excel");
    expect(subida[1].body).toBeInstanceOf(FormData);
    expect(subida[1].body.get("fichero").name).toBe("maestro.xlsx");

    // El backend parsea en un trabajo: cuando termina, se recargan los datos.
    hayExcel = true;
    trabajos.aplicar({
      type: "job",
      job: "j1",
      estado: "ok",
      resultado: {},
      error: null,
    });
    await flushPromises();
    await flushPromises();

    expect(wrapper.find('[data-testid="definicion-cargado"]').text()).toContain("Excel cargado");
    expect(wrapper.find('[data-testid="definicion-archivo"]').text()).toContain("maestro.xlsx");
  });
});
