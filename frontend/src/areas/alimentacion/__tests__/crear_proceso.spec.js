import { flushPromises, mount } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";
import { beforeEach, describe, expect, it, vi } from "vitest";
import CrearProceso from "../vistas/CrearProceso.vue";
import { useCrearProcesoStore } from "../stores/crear_proceso.js";
import { usePlcStore } from "../../../nucleo/stores/plc.js";
import { useTiaStore } from "../../../nucleo/stores/tia.js";
import { useTrabajosStore } from "../../../nucleo/stores/trabajos.js";

/**
 * El listado de plantillas que sirve el backend, con la ruta de la carpeta.
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

/** El listado sin plantillas y con la carpeta sin configurar. */
const LISTADO_VACIO = {
  plantillas: [],
  plantillas_path: "",
  aviso: "Carpeta de plantillas sin configurar",
};

/** El listado con la carpeta caida: sin plantillas pero con la ruta. */
const LISTADO_CARPETA_CAIDA = {
  plantillas: [],
  plantillas_path: "X:\\no_existe",
  aviso: "Directorio no existe: X:\\no_existe",
};

/** La fila del proceso del Excel maestro (cubre los minimos de la A). */
const PROCESO = { uid: 100, nombre: "CPR", codigo: "CPR", preal: 12, pint: 6, alarmas: 25, alm_hmi: 8 };

/** La fila del proceso que no cubre los minimos de la A. */
const PROCESO_MINIMOS = { uid: 200, nombre: "PUM", codigo: "PUM", preal: 2, pint: 1, alarmas: 2, alm_hmi: 2 };

/** La prevision con todo en orden (2 bloques, 2 dependencias OK). */
const PREVISION_OK = {
  manifest_plantilla: { base: 1000, codigo: "PRC" },
  descripcion: "Proceso de referencia para clonar",
  dependencias_ok: ["FC100_AUX", "FC101_AUX"],
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

/** La misma prevision con una colision contra un bloque del PLC. */
const PREVISION_COLISION = {
  ...PREVISION_OK,
  colisiones: ["FB10100"],
  colisiones_con: { FB10100: "DB10100" },
  archivos_previstos: [{ nombre_original: "FB1000", nombre_nuevo: "FB10100", estado: "DUPLICADO - DB10100" }],
};

/** La misma prevision con una dependencia faltante. */
const PREVISION_FALTANTE = {
  ...PREVISION_OK,
  dependencias_ok: ["FC100_AUX"],
  dependencias_faltantes: ["FC101_AUX"],
};

/** La misma prevision sin escaneo fresco: no vale para crear. */
const PREVISION_SIN_ESCANEO = {
  ...PREVISION_OK,
  success: false,
  precondiciones_ok: false,
  missing_blocks: ["Escanear primero los bloques del PLC"],
};

/** El resultado del trabajo de crear el proceso. */
const RESULTADO_OK = {
  plc: "ZC_PLC_STD",
  proc_uid: 100,
  process_label: "100_CPR",
  archivos_generados: ["FB10100.xml", "FB10101.xml", "tabla.xml", "manifest.json"],
  colisiones: [],
  transacciones: [
    { nombre: "Importar proceso", estado: "confirmada", detalle: "tablas y bloques" },
    { nombre: "N_MAX", estado: "revertida", detalle: "fallo" },
    { nombre: "Compilar", estado: "no ejecutada", detalle: "" },
  ],
  compilacion: { ok: true, error: null, detalle: "compile=OK" },
  escaneo_actualizado: true,
  success: true,
};

/** El mismo resultado pero sin refrescar el escaneo. */
const RESULTADO_SIN_ESCANEO = {
  ...RESULTADO_OK,
  escaneo_actualizado: false,
  transacciones: [{ nombre: "Importar proceso", estado: "confirmada", detalle: "tablas y bloques" }],
};

/** El mismo resultado pero con la compilacion con errores (no tumba el apply). */
const RESULTADO_COMPILE_WARN = {
  ...RESULTADO_OK,
  compilacion: { ok: false, error: "FB10101: warning 1", detalle: "compile=WARN" },
  transacciones: [{ nombre: "Importar proceso", estado: "confirmada", detalle: "tablas y bloques" }],
};

/**
 * Crea un pinia limpio y pre-hidrata los stores antes de montar, para que
 * `hidratar()` de la vista no recargue nada de la sesion.
 *
 * @returns {object} `{pinia, crear, plc, tia, trabajos, wrapper?}`.
 */
function storesLimpios() {
  const pinia = createPinia();
  setActivePinia(pinia);
  const crear = useCrearProcesoStore();
  // La foto de la sesion ya esta leida: `hidratar()` no toca nada.
  crear.hidratado = true;
  return {
    pinia,
    crear,
    plc: usePlcStore(),
    tia: useTiaStore(),
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

/**
 * Monta la vista con el proceso dado. El listado llega del mock de fetch
 * (un GET plano: el store no dispara trabajos al montar).
 *
 * `attachTo` engancha la vista al `document.body`: sin eso la raiz queda
 * desligada y `document.activeElement` no refleja los `focus()` del panel
 * de la ruta.
 */
async function montar(proceso) {
  const stores = storesLimpios();
  const attachTo = document.createElement("div");
  document.body.appendChild(attachTo);
  const wrapper = mount(CrearProceso, {
    props: { proceso },
    global: { plugins: [stores.pinia] },
    attachTo,
  });
  await flushPromises();
  return { wrapper, ...stores };
}

/** Prepara la vista para el flujo completo: todo elegido, TIA conectado. */
async function montarConTodo(proceso) {
  const { wrapper, crear, plc, tia } = await montar(proceso ?? PROCESO);
  crear.plantillaSeleccionada = "PLANTILLA_A";
  plc.seleccionado = "ZC_PLC_STD";
  tia.conectado = true;
  await flushPromises();
  return { wrapper, crear, plc, tia, trabajos: useTrabajosStore() };
}

/** La vista con una prevision valida del proceso/PLC/plantilla actuales. */
async function montarConPrevision(proceso, prev = PREVISION_OK) {
  const { wrapper, crear, plc, tia, trabajos } = await montarConTodo(proceso);
  crear.preview = prev;
  crear.previewPlc = plc.seleccionado;
  crear.previewProcUid = (proceso ?? PROCESO).uid;
  crear.previewPlantilla = "PLANTILLA_A";
  await flushPromises();
  return { wrapper, crear, plc, tia, trabajos };
}

describe("CrearProceso", () => {
  beforeEach(() => {
    global.fetch = fetchPorDefecto();
  });

  describe("la cabecera", () => {
    it("enseña el proceso seleccionado y el boton Cerrar emite `cerrar`", async () => {
      const { wrapper } = await montar(PROCESO);

      expect(wrapper.find('h2').text()).toBe("Crear proceso completo desde plantilla");
      expect(wrapper.text()).toContain("Proceso seleccionado:");
      expect(wrapper.text()).toContain("100_CPR");

      await wrapper.find('[data-testid="crear-cerrar"]').trigger("click");
      expect(wrapper.emitted("cerrar")).toBeTruthy();
    });
  });

  describe("la ruta de plantillas", () => {
    it("sin ruta configurada: el boton y el aviso ambar (ruta no configurada)", async () => {
      global.fetch = vi.fn((ruta) => {
        if (String(ruta).includes("/procesos/plantillas")) {
          return Promise.resolve({ ok: true, json: async () => LISTADO_VACIO });
        }
        return fetchPorDefecto()(ruta);
      });

      const { wrapper } = await montar(PROCESO);

      expect(wrapper.find('[data-testid="crear-configurar-ruta"]').exists()).toBe(true);
      const sinConfigurar = wrapper.find('[data-testid="crear-ruta-sin-configurar"]');
      expect(sinConfigurar.exists()).toBe(true);
      expect(sinConfigurar.text()).toBe("(ruta no configurada)");
      expect(sinConfigurar.classes()).toContain("text-amber-700");
      expect(wrapper.find('[data-testid="crear-ruta-actual"]').exists()).toBe(false);
      expect(wrapper.find('[data-testid="crear-aviso"]').exists()).toBe(false);
      expect(wrapper.find('[data-testid="crear-plantilla-placeholder"]').text()).toContain("Sin plantillas");
    });

    it("con ruta configurada: se muestra la ruta y no el aviso", async () => {
      const { wrapper } = await montar(PROCESO);

      const ruta = wrapper.find('[data-testid="crear-ruta-actual"]');
      expect(ruta.text()).toBe("(C:\\datos\\plantillas)");
      expect(wrapper.find('[data-testid="crear-ruta-sin-configurar"]').exists()).toBe(false);
    });

    it("carpeta caida: la ruta y el aviso por separado", async () => {
      global.fetch = vi.fn((ruta) => {
        if (String(ruta).includes("/procesos/plantillas")) {
          return Promise.resolve({ ok: true, json: async () => LISTADO_CARPETA_CAIDA });
        }
        return fetchPorDefecto()(ruta);
      });

      const { wrapper } = await montar(PROCESO);

      expect(wrapper.find('[data-testid="crear-ruta-actual"]').text()).toContain("X:\\no_existe");
      const aviso = wrapper.find('[data-testid="crear-aviso"]');
      expect(aviso.exists()).toBe(true);
      expect(aviso.text()).toContain("Directorio no existe: X:\\no_existe");
    });

    it("el boton lleva el data-test de main y abre el panel con el input enfocado", async () => {
      const { wrapper } = await montar(PROCESO);

      const boton = wrapper.find('[data-testid="crear-configurar-ruta"]');
      expect(boton.attributes("data-test")).toBe("procesos-crear-configure-path");
      expect(wrapper.find('[data-testid="crear-ruta-panel"]').exists()).toBe(false);

      await boton.trigger("click");
      await flushPromises();

      const panel = wrapper.find('[data-testid="crear-ruta-panel"]');
      expect(panel.exists()).toBe(true);
      expect(panel.attributes("data-test")).toBe("procesos-crear-path-modal");
      expect(document.activeElement).toBe(document.getElementById("crear-ruta-input"));
      expect(document.getElementById("crear-ruta-input").value).toBe("C:\\datos\\plantillas");
      expect(boton.attributes("aria-expanded")).toBe("true");
    });

    it("Guardar esta deshabilitado con el input vacio y se habilita al escribir", async () => {
      const { wrapper } = await montar(PROCESO);

      await wrapper.find('[data-testid="crear-configurar-ruta"]').trigger("click");
      await flushPromises();

      // Con la ruta actual cargada como borrador, borrarla lo deshabilita.
      await wrapper.find('[data-testid="crear-ruta-input"]').setValue("   ");
      expect(wrapper.find('[data-testid="crear-ruta-guardar"]').attributes("disabled")).toBeDefined();

      await wrapper.find('[data-testid="crear-ruta-input"]').setValue("C:\\nuevas");
      expect(wrapper.find('[data-testid="crear-ruta-guardar"]').attributes("disabled")).toBeUndefined();
    });

    it("Guardar bien: PUT con el body correcto, el panel se cierra y el listado se recarga", async () => {
      const { wrapper, crear } = await montar(PROCESO);

      await wrapper.find('[data-testid="crear-configurar-ruta"]').trigger("click");
      await wrapper.find('[data-testid="crear-ruta-input"]').setValue("C:\\nuevas");
      const promesa = wrapper.find('[data-testid="crear-ruta-guardar"]').trigger("click");
      await promesa;
      await flushPromises();

      const put = global.fetch.mock.calls.find(
        ([ruta, opciones]) => opciones && opciones.method === "PUT" && String(ruta).includes("/procesos/plantillas"),
      );
      expect(put).toBeTruthy();
      expect(String(put[0])).toBe("/api/v1/areas/alimentacion/procesos/plantillas");
      expect(JSON.parse(put[1].body)).toEqual({ plantillas_path: "C:\\nuevas" });
      expect(put[1].headers).toEqual({ "Content-Type": "application/json" });
      // El listado se recarga: el GET se repite despues del PUT.
      const gets = global.fetch.mock.calls.filter(
        ([ruta, opciones]) => String(ruta).includes("/procesos/plantillas") && !(opciones && opciones.method === "PUT"),
      );
      expect(gets.length).toBe(2);
      expect(wrapper.find('[data-testid="crear-ruta-panel"]').exists()).toBe(false);
      expect(crear.plantillasPath).toBe("C:\\datos\\plantillas");
      expect(crear.errorRuta).toBe(null);
    });

    it("Guardar mal: el error en crear-ruta-error y el panel sigue abierto", async () => {
      global.fetch = vi.fn((ruta) => {
        if (String(ruta).includes("/procesos/plantillas")) {
          return Promise.resolve({ ok: true, json: async () => LISTADO });
        }
        return fetchPorDefecto()(ruta);
      });
      const { wrapper } = await montar(PROCESO);
      // El PUT devuelve un 500.
      global.fetch = vi.fn((ruta, opciones) => {
        if (opciones && opciones.method === "PUT") {
          return Promise.resolve({ ok: false, status: 500, json: async () => ({ error: "No se pudo escribir el config" }) });
        }
        return fetchPorDefecto()(ruta);
      });

      await wrapper.find('[data-testid="crear-configurar-ruta"]').trigger("click");
      await wrapper.find('[data-testid="crear-ruta-input"]').setValue("C:\\nuevas");
      await wrapper.find('[data-testid="crear-ruta-guardar"]').trigger("click");
      await flushPromises();

      const error = wrapper.find('[data-testid="crear-ruta-error"]');
      expect(error.exists()).toBe(true);
      expect(error.text()).toBe("No se pudo guardar: No se pudo escribir el config");
      expect(wrapper.find('[data-testid="crear-ruta-panel"]').exists()).toBe(true);
    });

    it("Cancelar cierra el panel sin llamar a la API", async () => {
      const { wrapper } = await montar(PROCESO);
      // La unica peticion hasta aqui es el GET del montaje.
      expect(global.fetch.mock.calls.length).toBe(1);

      await wrapper.find('[data-testid="crear-configurar-ruta"]').trigger("click");
      await flushPromises();
      await wrapper.find('[data-testid="crear-ruta-cancelar"]').trigger("click");
      await flushPromises();

      expect(wrapper.find('[data-testid="crear-ruta-panel"]').exists()).toBe(false);
      expect(global.fetch.mock.calls.length).toBe(1);
    });
  });

  describe("el selector de plantilla", () => {
    it("lista las plantillas como `carpeta — codigo nombre` y al elegir una muestra su descripcion", async () => {
      const { wrapper, crear } = await montar(PROCESO);

      const select = wrapper.find('[data-testid="crear-plantilla-select"]');
      const opciones = wrapper.findAll('[data-testid="crear-plantilla-opcion"]');
      expect(opciones.length).toBe(2);
      expect(opciones[0].text()).toBe("PLANTILLA_A — PRC Proceso de referencia");
      expect(opciones[1].text()).toBe("PLANTILLA_B — SEC Segunda plantilla");
      expect(wrapper.find('[data-testid="crear-plantilla-descripcion"]').exists()).toBe(false);

      await select.setValue("PLANTILLA_A");

      expect(crear.plantillaSeleccionada).toBe("PLANTILLA_A");
      expect(
        wrapper.find('[data-testid="crear-plantilla-descripcion"]').text(),
      ).toBe("Proceso de referencia para clonar");
    });
  });

  describe("la tabla DATO / PLANTILLA / PROCESO NUEVO", () => {
    it("muestra los valores de la plantilla y del proceso", async () => {
      const { wrapper } = await montarConTodo(PROCESO);

      const filas = wrapper.findAll('[data-testid="crear-tabla-nmax"] tbody tr');
      expect(filas.length).toBe(6);
      const celdas = filas.map((fila) => fila.findAll("td").map((td) => td.text()));
      expect(celdas).toEqual([
        ["PREAL", "10", "12"],
        ["PINT", "5", "6"],
        ["ALM", "20", "25"],
        ["ALM_HMI", "5", "8"],
        ["UID", "1000", "100"],
        ["CODIGO", "PRC", "CPR"],
      ]);
      // Sin problemas: ninguna celda del proceso sale en rojo.
      expect(celdas.some((fila) => fila[2].includes("text-red-700"))).toBe(false);
      expect(wrapper.find('[data-testid="crear-minimos-aviso"]').exists()).toBe(false);
      expect(wrapper.find('[data-testid="crear-generar"]').attributes("disabled")).toBeUndefined();
    });

    it("con minimos incumplidos el valor sale en rojo, aparece el aviso y generar esta deshabilitado", async () => {
      const { wrapper } = await montarConTodo(PROCESO_MINIMOS);

      const filas = wrapper.findAll('[data-testid="crear-tabla-nmax"] tbody tr');
      const celdas = filas.map((fila) => fila.findAll("td").map((td) => td.text()));
      expect(celdas).toEqual([
        ["PREAL", "10", "2"],
        ["PINT", "5", "1"],
        ["ALM", "20", "2"],
        ["ALM_HMI", "5", "2"],
        ["UID", "1000", "200"],
        ["CODIGO", "PRC", "PUM"],
      ]);

      // Los 4 N_MAX incumplen: cada celda del proceso en rojo y negrita.
      const rojas = filas
        .slice(0, 4)
        .map((fila) => fila.findAll("td")[2])
        .filter((td) => td.classes().includes("text-red-700") && td.classes().includes("font-bold"));
      expect(rojas.length).toBe(4);
      // UID y CODIGO no tienen minimo: no salen en rojo.
      expect(filas[4].findAll("td")[2].classes().includes("text-red-700")).toBe(false);
      expect(filas[5].findAll("td")[2].classes().includes("text-red-700")).toBe(false);

      expect(wrapper.find('[data-testid="crear-minimos-aviso"]').text()).toContain(
        "Los N_MAX del operario no cubren los minimos de la plantilla",
      );
      expect(wrapper.find('[data-testid="crear-generar"]').attributes("disabled")).toBeDefined();
    });
  });

  describe("el layout: alto natural y tablas que no se aplastan", () => {
    it("la raiz crece con su contenido (flex-none, sin min-h-0)", async () => {
      const { wrapper } = await montar(PROCESO);

      const raiz = wrapper.find('[data-testid="crear"]');
      expect(raiz.exists()).toBe(true);
      expect(raiz.classes()).toContain("flex-none");
      expect(raiz.classes()).not.toContain("min-h-0");
    });

    it("la tabla N_MAX no se aplasta: min-h-[14rem] y overflow-auto", async () => {
      const { wrapper } = await montar(PROCESO);

      const tabla = wrapper.find('[data-testid="crear-tabla-nmax"]');
      expect(tabla.exists()).toBe(true);
      expect(tabla.classes()).toContain("min-h-[14rem]");
      expect(tabla.classes()).toContain("overflow-auto");
    });

    it("las tablas de bloques y dependencias no se aplastan: min-h-[14rem] y overflow-auto", async () => {
      const { wrapper } = await montarConPrevision(PROCESO);

      const bloques = wrapper.find('[data-testid="crear-bloques"] .overflow-auto');
      expect(bloques.exists()).toBe(true);
      expect(bloques.classes()).toContain("min-h-[14rem]");
      expect(bloques.classes()).toContain("overflow-auto");

      const dependencias = wrapper.find('[data-testid="crear-dependencias"] .overflow-auto');
      expect(dependencias.exists()).toBe(true);
      expect(dependencias.classes()).toContain("min-h-[14rem]");
      expect(dependencias.classes()).toContain("overflow-auto");
    });
  });

  describe("el boton Generar Prevision", () => {
    it("esta deshabilitado sin plantilla", async () => {
      // Sin elegir plantilla (solo PLC y TIA): el boton queda deshabilitado.
      const { wrapper, crear, plc, tia } = await montar(PROCESO);
      plc.seleccionado = "ZC_PLC_STD";
      tia.conectado = true;
      await flushPromises();
      expect(crear.plantillaSeleccionada).toBe("");
      expect(wrapper.find('[data-testid="crear-generar"]').attributes("disabled")).toBeDefined();
    });

    it("esta deshabilitado sin PLC", async () => {
      const { wrapper, plc, crear, tia } = await montar(PROCESO);
      crear.plantillaSeleccionada = "PLANTILLA_A";
      tia.conectado = true;
      // Sin PLC seleccionado: el boton queda deshabilitado.
      expect(plc.seleccionado).toBe("");
      await flushPromises();
      expect(wrapper.find('[data-testid="crear-generar"]').attributes("disabled")).toBeDefined();
    });

    it("esta deshabilitado sin TIA conectado", async () => {
      const { wrapper, crear, plc } = await montar(PROCESO);
      crear.plantillaSeleccionada = "PLANTILLA_A";
      plc.seleccionado = "ZC_PLC_STD";
      // TIA sin conectar: el boton queda deshabilitado.
      expect(wrapper.find('[data-testid="crear-generar"]').attributes("disabled")).toBeDefined();
    });

    it("esta habilitado con plantilla, PLC y TIA", async () => {
      const { wrapper } = await montarConTodo(PROCESO);
      expect(wrapper.find('[data-testid="crear-generar"]').attributes("disabled")).toBeUndefined();
    });
  });

  describe("generar la prevision", () => {
    it("pulsa generar: POST a /procesos/crear/preview con el body correcto y muestra `Generando prevision…`", async () => {
      const { wrapper, crear, trabajos } = await montarConTodo(PROCESO);

      const promesa = (async () => {
        await wrapper.find('[data-testid="crear-generar"]').trigger("click");
        await flushPromises();
      })();
      await promesa;

      // Mientras el trabajo no termina, el boton esta deshabilitado y enseña el texto de carga.
      const post = global.fetch.mock.calls.find(
        ([ruta, opciones]) => opciones && opciones.method === "POST" && String(ruta).includes("crear/preview"),
      );
      expect(post).toBeTruthy();
      expect(String(post[0])).toBe("/api/v1/areas/alimentacion/procesos/crear/preview");
      expect(JSON.parse(post[1].body)).toEqual({
        plc: "ZC_PLC_STD",
        proc_uid: 100,
        dir_plantilla_nombre: "PLANTILLA_A",
      });
      expect(wrapper.find('[data-testid="crear-generar"]').text()).toContain("Generando previsión…");
      expect(wrapper.find('[data-testid="crear-generar"]').attributes("disabled")).toBeDefined();

      // Termina el trabajo: la prevision queda en el store.
      trabajos.aplicar({ type: "job", job: "j1", estado: "ok", resultado: PREVISION_OK, error: null });
      await flushPromises();

      expect(crear.preview).toStrictEqual(PREVISION_OK);
      expect(wrapper.find('[data-testid="crear-generar"]').text()).toContain("Generar Previsión");
      expect(wrapper.find('[data-testid="crear-generar"]').attributes("disabled")).toBeUndefined();
    });

    it("con el job en error (manifest invalido) el error del store sale en rojo y sin resultado", async () => {
      const { wrapper, trabajos } = await montarConTodo(PROCESO);

      await wrapper.find('[data-testid="crear-generar"]').trigger("click");
      await flushPromises();

      trabajos.aplicar({
        type: "job",
        job: "j1",
        estado: "error",
        resultado: null,
        error: "El manifest de la plantilla no es valido: falta la clave base",
      });
      await flushPromises();

      expect(wrapper.find('[data-testid="crear-error"]').text()).toContain(
        "El manifest de la plantilla no es valido: falta la clave base",
      );
      expect(wrapper.find('[data-testid="crear-preview"]').exists()).toBe(false);
      expect(wrapper.find('[data-testid="crear-resultado"]').exists()).toBe(false);
    });
  });

  describe("la preview", () => {
    it("con colisiones: banner rojo con las colisiones y el bloque del PLC, y crear deshabilitado", async () => {
      const { wrapper } = await montarConPrevision(PROCESO, PREVISION_COLISION);

      const banner = wrapper.find('[data-testid="crear-colisiones"]');
      expect(banner.exists()).toBe(true);
      expect(banner.text()).toContain("1 colision(es) detectada(s)");
      expect(banner.text()).toContain("FB10100");
      expect(banner.text()).toContain("DB10100");
      expect(banner.text()).toContain("Cambia el proceso o plantilla");

      // La tabla de bloques previstos muestra el estado DUPLICADO en rojo.
      const bloques = wrapper.find('[data-testid="crear-bloques"]');
      const filas = bloques.findAll("tbody tr");
      const celdas = filas.map((fila) => fila.findAll("td").map((td) => td.text()));
      expect(celdas).toContainEqual(["FB1000", "FB10100", "DUPLICADO - DB10100"]);
      const estado = filas[0].findAll("td")[2];
      expect(estado.classes()).toContain("text-red-700");

      expect(wrapper.find('[data-testid="crear-aplicar"]').attributes("disabled")).toBeDefined();
    });

    it("las dependencias salen en verde si estan OK y en rojo si faltan, y con faltantes crear esta deshabilitado", async () => {
      const { wrapper } = await montarConPrevision(PROCESO, PREVISION_FALTANTE);

      const tabla = wrapper.find('[data-testid="crear-dependencias"]');
      expect(tabla.text()).toContain("FC100_AUX");
      expect(tabla.text()).toContain("FC101_AUX");
      expect(tabla.text()).toContain("OK");
      expect(tabla.text()).toContain("FALTA");

      const filas = tabla.findAll("tbody tr");
      expect(filas.length).toBe(2);
      const celdas = filas.map((fila) => fila.findAll("td").map((td) => td.text()));
      expect(celdas).toContainEqual(["FC100_AUX", "OK"]);
      expect(celdas).toContainEqual(["FC101_AUX", "FALTA"]);

      expect(wrapper.find('[data-testid="crear-aplicar"]').attributes("disabled")).toBeDefined();
    });

    it("la tabla de bloques previstos muestra original, nuevo y estado", async () => {
      const { wrapper } = await montarConPrevision(PROCESO, PREVISION_OK);

      const bloques = wrapper.find('[data-testid="crear-bloques"]');
      expect(bloques.text()).toContain("Bloques a generar (2)");
      const filas = bloques.findAll("tbody tr");
      expect(filas.length).toBe(2);
      const celdas = filas.map((fila) => fila.findAll("td").map((td) => td.text()));
      expect(celdas).toContainEqual(["FB1000", "FB10100", "OK"]);
      expect(celdas).toContainEqual(["FB1001", "FB10101", "OK"]);
    });

    it("sin escaneo: aviso ambar con el hint y crear deshabilitado", async () => {
      const { wrapper } = await montarConPrevision(PROCESO, PREVISION_SIN_ESCANEO);

      const aviso = wrapper.find('[data-testid="crear-preview-aviso"]');
      expect(aviso.exists()).toBe(true);
      expect(aviso.text()).toContain("Escanear primero los bloques del PLC");

      expect(wrapper.find('[data-testid="crear-aplicar"]').attributes("disabled")).toBeDefined();
    });

    it("la preview de otro proceso no se ve: aviso gris y sin resultado ni boton habilitado", async () => {
      const { wrapper } = await montarConPrevision(PROCESO, PREVISION_OK);
      expect(wrapper.find('[data-testid="crear-preview"]').exists()).toBe(true);

      // El proceso cambia: la preview ya no vale.
      wrapper.setProps({ proceso: { uid: 200, nombre: "PUM", codigo: "PUM", preal: 12, pint: 6, alarmas: 25, alm_hmi: 8 } });
      await flushPromises();

      expect(wrapper.find('[data-testid="crear-preview-invalida"]').text()).toContain(
        "La previsión es de otro proceso, PLC o plantilla: genera una nueva.",
      );
      expect(wrapper.find('[data-testid="crear-preview"]').exists()).toBe(false);
      expect(wrapper.find('[data-testid="crear-aplicar"]').attributes("disabled")).toBeDefined();
    });

    it("la preview de otro PLC no se ve", async () => {
      const { wrapper, plc } = await montarConPrevision(PROCESO, PREVISION_OK);
      plc.seleccionado = "OTRO_PLC";
      await flushPromises();

      expect(wrapper.find('[data-testid="crear-preview-invalida"]').exists()).toBe(true);
      expect(wrapper.find('[data-testid="crear-preview"]').exists()).toBe(false);
      expect(wrapper.find('[data-testid="crear-aplicar"]').attributes("disabled")).toBeDefined();
    });

    it("la preview de otra plantilla no se ve", async () => {
      const { wrapper, crear } = await montarConPrevision(PROCESO, PREVISION_OK);
      // La preview es de la A pero la elegida ahora es la B (el operario
      // cambio la plantilla sin regenerar): la preview no vale.
      crear.plantillaSeleccionada = "PLANTILLA_B";
      await flushPromises();

      expect(wrapper.find('[data-testid="crear-preview-invalida"]').exists()).toBe(true);
      expect(wrapper.find('[data-testid="crear-preview"]').exists()).toBe(false);
      expect(wrapper.find('[data-testid="crear-aplicar"]').attributes("disabled")).toBeDefined();
    });
  });

  describe("crear en TIA Portal", () => {
    it("con preview valida el boton esta habilitado y al pulsarlo el dialogo se abre con el texto exacto", async () => {
      const { wrapper } = await montarConPrevision(PROCESO, PREVISION_OK);

      const boton = wrapper.find('[data-testid="crear-aplicar"]');
      expect(boton.attributes("disabled")).toBeUndefined();
      expect(boton.text()).toContain("Crear en TIA Portal");

      await boton.trigger("click");
      await flushPromises();

      const dialogo = wrapper.find('[data-testid="crear-proceso-confirmar-dialogo"]');
      expect(dialogo.exists()).toBe(true);
      const texto = wrapper.find('[data-testid="crear-proceso-confirmar-texto"]').text();
      expect(texto).toBe(
        "¿Crear el proceso 100_CPR en TIA Portal?\n\n" +
          "Plantilla: PLANTILLA_A\n" +
          "Bloques a importar: 2\n" +
          "Dependencias validadas: 2\n" +
          "Se importan las tablas y los bloques en una sola transaccion y se compila.\n" +
          "Esta operacion modifica el PLC.",
      );
    });

    it("Escape cierra el dialogo sin llamar a la API", async () => {
      const { wrapper } = await montarConPrevision(PROCESO, PREVISION_OK);

      await wrapper.find('[data-testid="crear-aplicar"]').trigger("click");
      expect(wrapper.find('[data-testid="crear-proceso-confirmar-dialogo"]').exists()).toBe(true);

      window.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape" }));
      await flushPromises();

      expect(wrapper.find('[data-testid="crear-proceso-confirmar-dialogo"]').exists()).toBe(false);
      // No se envio ninguna peticion de aplicar.
      const post = global.fetch.mock.calls.find(
        ([, opciones]) => opciones && opciones.method === "POST" && String(opciones.body || "").includes("aplicar"),
      );
      expect(post).toBeUndefined();
    });

    it("Cancelar cierra el dialogo sin llamar a la API", async () => {
      const { wrapper } = await montarConPrevision(PROCESO, PREVISION_OK);

      await wrapper.find('[data-testid="crear-aplicar"]').trigger("click");
      await wrapper.find('[data-testid="crear-proceso-confirmar-no"]').trigger("click");
      await flushPromises();

      expect(wrapper.find('[data-testid="crear-proceso-confirmar-dialogo"]').exists()).toBe(false);
      const post = global.fetch.mock.calls.find(
        ([, opciones]) => opciones && opciones.method === "POST" && String(opciones.body || "").includes("aplicar"),
      );
      expect(post).toBeUndefined();
    });

    it("Confirmar hace el POST a /procesos/crear/aplicar con el body correcto", async () => {
      const { wrapper, trabajos } = await montarConPrevision(PROCESO, PREVISION_OK);

      await wrapper.find('[data-testid="crear-aplicar"]').trigger("click");
      await wrapper.find('[data-testid="crear-proceso-confirmar-si"]').trigger("click");
      await flushPromises();

      const post = global.fetch.mock.calls.find(
        ([ruta, opciones]) => opciones && opciones.method === "POST" && String(ruta).includes("crear/aplicar"),
      );
      expect(post).toBeTruthy();
      expect(String(post[0])).toBe("/api/v1/areas/alimentacion/procesos/crear/aplicar");
      expect(JSON.parse(post[1].body)).toEqual({
        plc: "ZC_PLC_STD",
        proc_uid: 100,
        dir_plantilla_nombre: "PLANTILLA_A",
      });

      // Termina el trabajo: el resultado queda en el store.
      trabajos.aplicar({ type: "job", job: "j2", estado: "ok", resultado: RESULTADO_OK, error: null });
      await flushPromises();

      expect(wrapper.find('[data-testid="crear-resultado"]').exists()).toBe(true);
    });
  });

  describe("el resultado de crear", () => {
    it("tras crear OK: panel verde con el proceso creado, el numero de archivos, las transacciones y la compilacion", async () => {
      const { wrapper, trabajos } = await montarConPrevision(PROCESO, PREVISION_OK);

      await wrapper.find('[data-testid="crear-aplicar"]').trigger("click");
      await wrapper.find('[data-testid="crear-proceso-confirmar-si"]').trigger("click");
      await flushPromises();

      trabajos.aplicar({ type: "job", job: "j2", estado: "ok", resultado: RESULTADO_OK, error: null });
      await flushPromises();

      const panel = wrapper.find('[data-testid="crear-resultado"]');
      expect(panel.exists()).toBe(true);
      expect(panel.text()).toContain("Proceso 100_CPR creado");
      expect(panel.text()).toContain("4 archivos generados");

      const transacciones = wrapper.find('[data-testid="crear-transacciones"]');
      expect(transacciones.text()).toContain("Importar proceso:");
      expect(transacciones.text()).toContain("confirmada");
      expect(transacciones.text()).toContain("N_MAX:");
      expect(transacciones.text()).toContain("revertida");
      expect(transacciones.text()).toContain("Compilar:");
      expect(transacciones.text()).toContain("no ejecutada");

      const compilacion = wrapper.find('[data-testid="crear-compilacion"]');
      expect(compilacion.text()).toContain("Compilación: compile=OK");
      expect(compilacion.classes()).toContain("text-green-700");

      expect(wrapper.find('[data-testid="crear-escaneo-aviso"]').exists()).toBe(false);

      // El proceso ya existe: la prevision se vacio y crear no esta habilitado.
      expect(wrapper.find('[data-testid="crear-preview"]').exists()).toBe(false);
      expect(wrapper.find('[data-testid="crear-aplicar"]').attributes("disabled")).toBeDefined();
    });

    it("con compilacion con errores: aviso ambar sin tumbar el resultado", async () => {
      const { wrapper, trabajos } = await montarConPrevision(PROCESO, PREVISION_OK);

      await wrapper.find('[data-testid="crear-aplicar"]').trigger("click");
      await wrapper.find('[data-testid="crear-proceso-confirmar-si"]').trigger("click");
      await flushPromises();

      trabajos.aplicar({
        type: "job",
        job: "j2",
        estado: "ok",
        resultado: RESULTADO_COMPILE_WARN,
        error: null,
      });
      await flushPromises();

      expect(wrapper.find('[data-testid="crear-resultado"]').exists()).toBe(true);
      const compilacion = wrapper.find('[data-testid="crear-compilacion"]');
      expect(compilacion.text()).toContain("Compilación: FB10101: warning 1");
      expect(compilacion.classes()).toContain("text-amber-700");
    });

    it("si el escaneo no se refresco: aviso ambar", async () => {
      const { wrapper, trabajos } = await montarConPrevision(PROCESO, PREVISION_OK);

      await wrapper.find('[data-testid="crear-aplicar"]').trigger("click");
      await wrapper.find('[data-testid="crear-proceso-confirmar-si"]').trigger("click");
      await flushPromises();

      trabajos.aplicar({
        type: "job",
        job: "j2",
        estado: "ok",
        resultado: RESULTADO_SIN_ESCANEO,
        error: null,
      });
      await flushPromises();

      const aviso = wrapper.find('[data-testid="crear-escaneo-aviso"]');
      expect(aviso.exists()).toBe(true);
      expect(aviso.text()).toContain("No se pudo refrescar el escaneo: vuelve a escanear el PLC.");
    });

    it("si crear falla: error en rojo y sin transacciones", async () => {
      const { wrapper, trabajos } = await montarConPrevision(PROCESO, PREVISION_OK);

      await wrapper.find('[data-testid="crear-aplicar"]').trigger("click");
      await wrapper.find('[data-testid="crear-proceso-confirmar-si"]').trigger("click");
      await flushPromises();

      trabajos.aplicar({
        type: "job",
        job: "j2",
        estado: "error",
        resultado: null,
        error: "La transaccion de importacion se revirtio",
      });
      await flushPromises();

      expect(wrapper.find('[data-testid="crear-error"]').text()).toContain(
        "La transaccion de importacion se revirtio",
      );
      expect(wrapper.find('[data-testid="crear-resultado"]').exists()).toBe(false);
      expect(wrapper.find('[data-testid="crear-transacciones"]').exists()).toBe(false);
    });
  });
});
