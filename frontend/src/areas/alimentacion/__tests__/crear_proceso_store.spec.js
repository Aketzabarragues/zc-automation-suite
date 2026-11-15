import { flushPromises } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { useCrearProcesoStore } from "../stores/crear_proceso.js";
import { useExcelStore } from "../stores/excel.js";
import { useSesionStore } from "../../../nucleo/stores/sesion.js";
import { useTrabajosStore } from "../../../nucleo/stores/trabajos.js";

/**
 * El listado de plantillas que sirve el backend: dos plantillas, una con
 * minimos y otra sin la clave de minimos.
 */
const LISTADO = {
  plantillas: [
    {
      carpeta: "PLANTILLA_A",
      base: 1000,
      codigo: "PRC",
      nombre: "Proceso de referencia",
      descripcion: "Proceso de referencia para clonar",
      minimos: { N_MAX_PREAL: 10, N_MAX_PINT: 5, N_MAX_ALM: 20, N_MAX_ALM_HMI: 5 },
    },
    {
      carpeta: "PLANTILLA_B",
      base: 2000,
      codigo: "SEC",
      nombre: "Segunda plantilla",
      descripcion: "Otra plantilla",
      minimos: {},
    },
  ],
  plantillas_path: "C:\\datos\\plantillas",
  aviso: null,
};

/** La fila del proceso del Excel maestro, tal cual la sirve el volcado. */
const PROCESO_EXCEL = {
  uid: 100,
  nombre: "CPR",
  codigo: "CPR",
  preal: 2,
  pint: 1,
  alarmas: 2,
  alm_hmi: 2,
};

/** La prevision que devuelve el trabajo, con todo en orden. */
const PREVISION_OK = {
  manifest_plantilla: { base: 1000, codigo: "PRC" },
  descripcion: "Proceso de referencia para clonar",
  dependencias_ok: ["FC100_AUX"],
  dependencias_faltantes: [],
  archivos_previstos: [
    { nombre_original: "FB1000", nombre_nuevo: "FB10100", estado: "OK" },
    { nombre_original: "FB1001", nombre_nuevo: "FB10101", estado: "OK" },
  ],
  colisiones: [],
  colisiones_con: {},
  plantilla_copia_dir: "C:\\datos\\copia",
  success: true,
  precondiciones_ok: true,
  missing_blocks: [],
  warnings: [],
};

/** La misma prevision pero con una colision. */
const PREVISION_COLISION = {
  ...PREVISION_OK,
  colisiones: ["FB10100"],
  colisiones_con: { FB10100: "FB10100 (DB)" },
  archivos_previstos: [
    { nombre_original: "FB1000", nombre_nuevo: "FB10100", estado: "DUPLICADO - DB" },
  ],
};

/** La misma prevision pero con dependencias faltantes. */
const PREVISION_FALTANTE = {
  ...PREVISION_OK,
  dependencias_ok: [],
  dependencias_faltantes: ["FC100_AUX"],
};

/** La misma prevision pero sin un escaneo fresco: no vale para crear. */
const PREVISION_SIN_ESCANEO = {
  ...PREVISION_OK,
  success: false,
  precondiciones_ok: false,
  missing_blocks: ["Escanear primero los bloques del PLC"],
};

/** El resultado del trabajo de aplicar. */
const RESULTADO_APLICAR = {
  plc: "ZC_PLC_STD",
  proc_uid: 100,
  process_label: "100_CPR",
  archivos_generados: 4,
  colisiones: [],
  transacciones: [
    { nombre: "Importar bloques", estado: "confirmada", detalle: "2 bloques" },
    { nombre: "N_MAX", estado: "confirmada", detalle: "4 N_MAX" },
  ],
  compilacion: { ok: true, error: null, detalle: "" },
  escaneo_actualizado: true,
  success: true,
};

/**
 * Crea un pinia limpio y los stores que usa la prueba. El fetch se mockea
 * por prueba: no hay red.
 *
 * @returns {object} `{crear, excel, sesion, trabajos}`.
 */
function storesLimpios() {
  setActivePinia(createPinia());
  return {
    crear: useCrearProcesoStore(),
    excel: useExcelStore(),
    sesion: useSesionStore(),
    trabajos: useTrabajosStore(),
  };
}

/** El fetch por defecto: el listado de plantillas y un 202 para los POST. */
function fetchPorDefecto() {
  return vi.fn((ruta) => {
    const url = String(ruta);
    if (url.includes("/procesos/plantillas")) {
      return Promise.resolve({ ok: true, json: async () => LISTADO });
    }
    if (url.includes("/procesos/crear/preview")) {
      return Promise.resolve({ ok: true, json: async () => ({ job_id: "j1" }) });
    }
    if (url.includes("/procesos/crear/aplicar")) {
      return Promise.resolve({ ok: true, json: async () => ({ job_id: "j2" }) });
    }
    return Promise.resolve({ ok: true, json: async () => ({}) });
  });
}

/** Termina el trabajo encolado con el estado dado. */
function terminar(trabajos, job, estado, resultado, error) {
  trabajos.aplicar({ type: "job", job, estado, resultado, error });
}

describe("crearProceso", () => {
  beforeEach(() => {
    global.fetch = fetchPorDefecto();
  });

  it("cargarPlantillas guarda el listado, la ruta y sin aviso", async () => {
    const { crear } = storesLimpios();

    const ok = await crear.cargarPlantillas();

    expect(ok).toBe(true);
    expect(crear.plantillas).toEqual(LISTADO.plantillas);
    expect(crear.plantillasPath).toBe("C:\\datos\\plantillas");
    expect(crear.aviso).toBe(null);
    expect(crear.cargandoPlantillas).toBe(false);
    expect(crear.plantilla).toBe(null);

    // Elegir una plantilla la deja en `plantilla`.
    crear.seleccionarPlantilla("PLANTILLA_A");
    expect(crear.plantilla.carpeta).toBe("PLANTILLA_A");
    expect(crear.plantilla.descripcion).toBe("Proceso de referencia para clonar");
  });

  it("cargarPlantillas con aviso de carpeta caida lo guarda", async () => {
    const { crear } = storesLimpios();
    global.fetch = vi.fn((ruta) => {
      if (String(ruta).includes("/procesos/plantillas")) {
        return Promise.resolve({
          ok: true,
          json: async () => ({ plantillas: [], plantillas_path: "X:\\no_existe", aviso: "Directorio no existe: X:\\no_existe" }),
        });
      }
      return fetchPorDefecto()(ruta);
    });

    await crear.cargarPlantillas();

    expect(crear.plantillas).toEqual([]);
    expect(crear.aviso).toBe("Directorio no existe: X:\\no_existe");
  });

  it("cargarPlantillas con 400 (config invalido) deja el mensaje y sin plantillas", async () => {
    const { crear } = storesLimpios();
    global.fetch = vi.fn((ruta) => {
      if (String(ruta).includes("/procesos/plantillas")) {
        return Promise.resolve({
          ok: false,
          status: 400,
          json: async () => ({ error: "El config del area no es valido: revisa el config.json en uso." }),
        });
      }
      return fetchPorDefecto()(ruta);
    });

    const ok = await crear.cargarPlantillas();

    expect(ok).toBe(false);
    expect(crear.plantillas).toEqual([]);
    expect(crear.error).toBe("El config del area no es valido: revisa el config.json en uso.");
  });

  it("seleccionarPlantilla elige la plantilla y limpiar la no cambia nada", () => {
    const { crear } = storesLimpios();

    crear.plantillas = LISTADO.plantillas;
    crear.seleccionarPlantilla("PLANTILLA_B");
    expect(crear.plantillaSeleccionada).toBe("PLANTILLA_B");
    expect(crear.plantilla.codigo).toBe("SEC");

    // La misma carpeta: no hace nada.
    crear.seleccionarPlantilla("PLANTILLA_B");
    expect(crear.plantillaSeleccionada).toBe("PLANTILLA_B");

    // Volver a la primera.
    crear.seleccionarPlantilla("PLANTILLA_A");
    expect(crear.plantillaSeleccionada).toBe("PLANTILLA_A");
  });

  it("cambiar de plantilla borra la preview y el resultado del aplicar", () => {
    const { crear } = storesLimpios();
    crear.plantillas = LISTADO.plantillas;
    crear.seleccionarPlantilla("PLANTILLA_A");
    crear.preview = PREVISION_OK;
    crear.resultadoAplicar = RESULTADO_APLICAR;
    crear.transacciones = RESULTADO_APLICAR.transacciones;
    crear.error = "un error anterior";

    crear.seleccionarPlantilla("PLANTILLA_B");

    expect(crear.plantillaSeleccionada).toBe("PLANTILLA_B");
    expect(crear.preview).toBe(null);
    expect(crear.resultadoAplicar).toBe(null);
    expect(crear.transacciones).toEqual([]);
    expect(crear.error).toBe(null);
  });

  it("generarPrevision manda el body correcto y guarda la preview del evento job", async () => {
    const { crear, trabajos } = storesLimpios();
    crear.plantillas = LISTADO.plantillas;
    crear.seleccionarPlantilla("PLANTILLA_A");

    const promesa = crear.generarPrevision("ZC_PLC_STD", 100);
    // Deja pasar el POST (fetch mockeado, sin red) antes de leerlo.
    await flushPromises();

    const post = global.fetch.mock.calls.find(
      ([ruta, opciones]) => opciones && opciones.method === "POST" && String(ruta).includes("preview"),
    );
    expect(post).toBeTruthy();
    expect(String(post[0])).toBe("/api/v1/areas/alimentacion/procesos/crear/preview");
    expect(JSON.parse(post[1].body)).toEqual({
      plc: "ZC_PLC_STD",
      proc_uid: 100,
      dir_plantilla_nombre: "PLANTILLA_A",
    });

    terminar(trabajos, "j1", "ok", PREVISION_OK, null);
    const ok = await promesa;
    expect(ok).toBe(true);
    expect(crear.generando).toBe(false);
    // El store guarda la referencia: pinia la refleja sin copiarla.
    expect(crear.preview).toStrictEqual(PREVISION_OK);
    expect(crear.bloquesPrevistos).toEqual(PREVISION_OK.archivos_previstos);
    expect(crear.colisiones).toEqual([]);
    expect(crear.error).toBe(null);
  });

  it("generarPrevision sin PLC ni proceso ni plantilla no encola", async () => {
    const { crear } = storesLimpios();
    crear.plantillas = LISTADO.plantillas;

    expect(await crear.generarPrevision("", 100)).toBe(false);
    expect(await crear.generarPrevision("ZC_PLC_STD", null)).toBe(false);
    expect(await crear.generarPrevision("ZC_PLC_STD", 100)).toBe(false);
    expect(crear.error).toBeTruthy();
    expect(global.fetch.mock.calls).toEqual([]);
  });

  it("un error de trabajo (manifest invalido) deja el error y sin preview", async () => {
    const { crear, trabajos } = storesLimpios();
    crear.plantillas = LISTADO.plantillas;
    crear.seleccionarPlantilla("PLANTILLA_A");

    const promesa = crear.generarPrevision("ZC_PLC_STD", 100);
    terminar(
      trabajos,
      "j1",
      "error",
      null,
      "manifest.json invalido: la plantilla no se puede clonar",
    );
    const ok = await promesa;

    expect(ok).toBe(false);
    expect(crear.error).toBe("manifest.json invalido: la plantilla no se puede clonar");
    expect(crear.preview).toBe(null);
  });

  it("un 409 al encolar deja el mensaje de trabajo en curso", async () => {
    const { crear } = storesLimpios();
    crear.plantillas = LISTADO.plantillas;
    crear.seleccionarPlantilla("PLANTILLA_A");
    global.fetch = vi.fn((ruta) => {
      if (String(ruta).includes("/procesos/crear/preview")) {
        return Promise.resolve({
          ok: false,
          status: 409,
          json: async () => ({ error: "Hay un trabajo en curso. Espera a que termine." }),
        });
      }
      return fetchPorDefecto()(ruta);
    });

    const ok = await crear.generarPrevision("ZC_PLC_STD", 100);

    expect(ok).toBe(false);
    expect(crear.error).toContain("trabajo en curso");
    expect(crear.preview).toBe(null);
  });

  describe("puedeCrear", () => {
    it("es true con una prevision completa", () => {
      const { crear } = storesLimpios();
      crear.preview = PREVISION_OK;
      expect(crear.puedeCrear).toBe(true);
    });

    it("es false sin preview", () => {
      const { crear } = storesLimpios();
      expect(crear.puedeCrear).toBe(false);
    });

    it("es false con una colision", () => {
      const { crear } = storesLimpios();
      crear.preview = PREVISION_COLISION;
      expect(crear.hayColisiones).toBe(true);
      expect(crear.puedeCrear).toBe(false);
    });

    it("es false con una dependencia faltante", () => {
      const { crear } = storesLimpios();
      crear.preview = PREVISION_FALTANTE;
      expect(crear.dependenciasFaltantes).toEqual(["FC100_AUX"]);
      expect(crear.puedeCrear).toBe(false);
    });

    it("es false sin escaneo fresco (precondiciones_ok false)", () => {
      const { crear } = storesLimpios();
      crear.preview = PREVISION_SIN_ESCANEO;
      expect(crear.puedeCrear).toBe(false);
    });
  });

  describe("minimosProblemas", () => {
    it("suficiente: sin problemas", () => {
      const { crear } = storesLimpios();
      crear.plantillas = LISTADO.plantillas;
      crear.seleccionarPlantilla("PLANTILLA_A");

      const proceso = { preal: 10, pint: 5, alarmas: 20, alm_hmi: 5 };
      expect(crear.minimosProblemas(proceso)).toEqual([]);
    });

    it("insuficiente en 2 claves: las lista con usuario y plantilla", () => {
      const { crear } = storesLimpios();
      crear.plantillas = LISTADO.plantillas;
      crear.seleccionarPlantilla("PLANTILLA_A");

      const proceso = { preal: 2, pint: 1, alarmas: 20, alm_hmi: 5 };
      expect(crear.minimosProblemas(proceso)).toEqual([
        { clave: "N_MAX_PREAL", usuario: 2, plantilla: 10 },
        { clave: "N_MAX_PINT", usuario: 1, plantilla: 5 },
      ]);
    });

    it("los campos ausentes valen 0", () => {
      const { crear } = storesLimpios();
      crear.plantillas = LISTADO.plantillas;
      crear.seleccionarPlantilla("PLANTILLA_A");

      const proceso = {};
      const problemas = crear.minimosProblemas(proceso);
      expect(problemas).toHaveLength(4);
      expect(problemas[0]).toEqual({ clave: "N_MAX_PREAL", usuario: 0, plantilla: 10 });
    });

    it("plantilla sin minimos: nunca hay problemas", () => {
      const { crear } = storesLimpios();
      crear.plantillas = LISTADO.plantillas;
      crear.seleccionarPlantilla("PLANTILLA_B");

      expect(crear.minimosProblemas({})).toEqual([]);
      expect(crear.minimosProblemas({ preal: 0, pint: 0, alarmas: 0, alm_hmi: 0 })).toEqual([]);
    });

    it("sin plantilla ni proceso: sin problemas", () => {
      const { crear } = storesLimpios();
      expect(crear.minimosProblemas(PROCESO_EXCEL)).toEqual([]);
      expect(crear.minimosProblemas(null)).toEqual([]);
    });
  });

  it("aplicar ok guarda el resultado y las transacciones", async () => {
    const { crear, trabajos } = storesLimpios();
    crear.plantillas = LISTADO.plantillas;
    crear.seleccionarPlantilla("PLANTILLA_A");

    const promesa = crear.aplicar("ZC_PLC_STD", 100);
    await flushPromises();

    const post = global.fetch.mock.calls.find(
      ([ruta, opciones]) => opciones && opciones.method === "POST" && String(ruta).includes("aplicar"),
    );
    expect(post).toBeTruthy();
    expect(String(post[0])).toBe("/api/v1/areas/alimentacion/procesos/crear/aplicar");
    expect(JSON.parse(post[1].body)).toEqual({
      plc: "ZC_PLC_STD",
      proc_uid: 100,
      dir_plantilla_nombre: "PLANTILLA_A",
    });

    terminar(trabajos, "j2", "ok", RESULTADO_APLICAR, null);
    const ok = await promesa;

    expect(ok).toBe(true);
    expect(crear.resultadoAplicar).toStrictEqual(RESULTADO_APLICAR);
    expect(crear.transacciones).toEqual(RESULTADO_APLICAR.transacciones);
    expect(crear.error).toBe(null);
    expect(crear.aplicando).toBe(false);
  });

  it("aplicar con error deja el mensaje y sin resultado", async () => {
    const { crear, trabajos } = storesLimpios();
    crear.plantillas = LISTADO.plantillas;
    crear.seleccionarPlantilla("PLANTILLA_A");

    const promesa = crear.aplicar("ZC_PLC_STD", 100);
    terminar(trabajos, "j2", "error", null, "La transaccion de importacion se revirtio");
    const ok = await promesa;

    expect(ok).toBe(false);
    expect(crear.error).toBe("La transaccion de importacion se revirtio");
    expect(crear.resultadoAplicar).toBe(null);
    expect(crear.transacciones).toEqual([]);
  });

  it("aplicar sin plantilla no encola", async () => {
    const { crear } = storesLimpios();

    expect(await crear.aplicar("ZC_PLC_STD", 100)).toBe(false);
    expect(crear.error).toContain("plantilla");
    expect(global.fetch.mock.calls).toEqual([]);
  });

  it("hidratar recupera la preview de la sesion, una sola vez", () => {
    const { crear, sesion } = storesLimpios();
    sesion.estado = {
      areas: {
        alimentacion: {
          excel: { cargado: true },
          prevision_crear_proceso: {
            plc: "ZC_PLC_STD",
            proc_uid: 100,
            resultado: PREVISION_OK,
          },
        },
      },
    };

    crear.hidratar();
    expect(crear.hidratado).toBe(true);
    expect(crear.preview).toStrictEqual(PREVISION_OK);

    // La foto de la sesion se aplica una vez: lo que pase despues manda.
    sesion.estado.areas.alimentacion.prevision_crear_proceso.resultado = PREVISION_COLISION;
    crear.hidratar();
    expect(crear.preview).toStrictEqual(PREVISION_OK);
    expect(crear.preview).not.toStrictEqual(PREVISION_COLISION);
  });

  it("hidratar sin nada en la sesion deja el store limpio", () => {
    const { crear, sesion } = storesLimpios();
    sesion.estado = { areas: { alimentacion: { excel: { cargado: true } } } };

    crear.hidratar();

    expect(crear.hidratado).toBe(true);
    expect(crear.preview).toBe(null);
    expect(crear.plantillaSeleccionada).toBe("");
  });

  it("el store empieza limpio", () => {
    const { crear } = storesLimpios();
    expect(crear.plantillas).toEqual([]);
    expect(crear.plantillasPath).toBe("");
    expect(crear.aviso).toBe(null);
    expect(crear.plantillaSeleccionada).toBe("");
    expect(crear.preview).toBe(null);
    expect(crear.resultadoAplicar).toBe(null);
    expect(crear.transacciones).toEqual([]);
    expect(crear.error).toBe(null);
    expect(crear.generando).toBe(false);
    expect(crear.aplicando).toBe(false);
    expect(crear.hidratado).toBe(false);
    expect(crear.plantilla).toBe(null);
    expect(crear.hayPreview).toBe(false);
    expect(crear.bloquesPrevistos).toEqual([]);
    expect(crear.colisiones).toEqual([]);
    expect(crear.dependenciasFaltantes).toEqual([]);
    expect(crear.hayColisiones).toBe(false);
    expect(crear.puedeCrear).toBe(false);
  });
});
