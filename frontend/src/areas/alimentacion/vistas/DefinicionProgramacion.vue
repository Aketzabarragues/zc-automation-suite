<script setup>
/**
 * Definición programación: la consulta del Excel maestro.
 *
 * Vista de solo lectura: enseña lo que el backend tiene cacheado del Excel
 * (configuración, dispositivos, procesos y entidades). Subir un fichero es
 * un trabajo: el POST responde 202 y los datos llegan cuando el trabajo
 * termina, asi que la vista se recarga sola.
 */
import { computed, onMounted, ref, watch } from "vue";
import { useExcelStore } from "../stores/excel.js";

const excel = useExcelStore();

/** Las pestanas grandes de la vista. */
const PESTANAS = [
  { clave: "configuracion", etiqueta: "Configuración", icono: "⚙️" },
  { clave: "dispositivos", etiqueta: "Dispositivos", icono: "📟" },
  { clave: "procesos", etiqueta: "Procesos", icono: "📋" },
  { clave: "entidades", etiqueta: "Entidades", icono: "🗂️" },
];

/** Los subdominios de los procesos, en su orden. */
const SUBDOMINIOS_PROCESOS = [
  { clave: "Procesos", etiqueta: "Procesos" },
  { clave: "ParametrosEnteros", etiqueta: "Parámetros Enteros" },
  { clave: "ParametrosReales", etiqueta: "Parámetros Reales" },
  { clave: "Alarmas", etiqueta: "Alarmas" },
];

/** La pestaña grande activa. */
const pestana = ref("configuracion");

/** El tipo de dispositivo activo: el canonico, `DispED`, `DispEA`, ... */
const tipoDispositivo = ref("");

/** El subdominio de procesos activo. */
const subdominioProceso = ref("Procesos");

/** El input de fichero, para abrirlo desde un boton. */
const inputFichero = ref(null);

// ── las tablas ──────────────────────────────────────────────────────────────

/**
 * Normaliza una tabla del backend: `{columnas, etiquetas, filas}`.
 *
 * @param {object|null} tabla la tabla.
 * @returns {object} `{columnas, etiquetas, filas}`, siempre con las tres.
 */
function tablaDe(tabla) {
  if (!tabla) return { columnas: [], etiquetas: {}, filas: [] };
  return {
    columnas: Array.isArray(tabla.columnas) ? tabla.columnas : [],
    etiquetas: tabla.etiquetas && typeof tabla.etiquetas === "object" ? tabla.etiquetas : {},
    filas: Array.isArray(tabla.filas) ? tabla.filas : [],
  };
}

/**
 * Cuantas filas tiene una tabla.
 *
 * @param {object|null} tabla la tabla.
 * @returns {number} el numero de filas.
 */
function filasDe(tabla) {
  return tabla && Array.isArray(tabla.filas) ? tabla.filas.length : 0;
}

/**
 * El texto de una celda: los valores vacios salen como raya.
 *
 * @param {*} valor el valor de la celda.
 * @returns {string} el texto a mostrar.
 */
function textoCelda(valor) {
  if (valor === null || valor === undefined || valor === "") return "—";
  return valor;
}

/**
 * El titulo de una columna: la etiqueta del `col_labels` del config, o el
 * nombre del campo tal cual si no tiene.
 *
 * @param {string} columna el nombre del campo.
 * @returns {string} el titulo.
 */
function etiquetaDe(columna) {
  const etiquetas = tablaActiva.value.etiquetas || {};
  return etiquetas[columna] || columna;
}

/**
 * `true` si el valor parece un identificador de bloque o de tag.
 *
 * @param {*} valor el valor de la celda.
 * @returns {boolean} si va en monoespaciada.
 */
function esIdentificador(valor) {
  if (typeof valor !== "string") return false;
  const texto = valor.trim();
  if (!texto) return false;
  return /^[A-Za-z][A-Za-z0-9_]*$/.test(texto) && /[A-Z_]/.test(texto);
}

// ── las pestanas ────────────────────────────────────────────────────────────

/** Las pestanas grandes, con su contador. */
const pestanas = computed(() =>
  PESTANAS.map((item) => ({ ...item, contador: excel.contadores[item.clave] })),
);

/**
 * La etiqueta de un tipo de dispositivo: `DispED` -> `ED`, `DispM_VF` -> `MVF`.
 *
 * @param {string} canonico la clave del backend.
 * @returns {string} la etiqueta.
 */
function etiquetaTipo(canonico) {
  const corto = canonico.startsWith("Disp") ? canonico.slice(4) : canonico;
  return corto.replace(/_/g, "");
}

/** Los tipos de dispositivo, en el orden en que los manda el backend. */
const tiposDispositivo = computed(() =>
  (excel.dispositivos || []).map((tabla) => ({
    canonico: tabla.tipo,
    etiqueta: etiquetaTipo(tabla.tipo),
    contador: filasDe(tabla),
  })),
);

/** Los subdominios de los procesos, con su contador. */
const subdominiosProceso = computed(() => {
  const procesos = excel.procesos || {};
  const extras = Object.keys(procesos).filter(
    (clave) => !SUBDOMINIOS_PROCESOS.some((item) => item.clave === clave),
  );
  const lista = [
    ...SUBDOMINIOS_PROCESOS,
    ...extras.map((clave) => ({ clave, etiqueta: clave })),
  ];
  return lista.map((item) => ({ ...item, contador: filasDe(procesos[item.clave]) }));
});

/** La tabla de la pestaña activa. */
const tablaActiva = computed(() => {
  if (pestana.value === "dispositivos") {
    const tabla = (excel.dispositivos || []).find(
      (item) => item.tipo === tipoDispositivo.value,
    );
    return tablaDe(tabla);
  }
  if (pestana.value === "procesos") {
    return tablaDe(excel.procesos[subdominioProceso.value]);
  }
  if (pestana.value === "entidades") {
    return tablaDe(excel.entidades);
  }
  return tablaDe(excel.configuracion);
});

// Si el tipo de dispositivo activo no existe (o no hay ninguno), se enseña
// el primero: la sub-pestaña nunca se queda en blanco.
watch(
  tiposDispositivo,
  (tipos) => {
    if (tipos.some((tipo) => tipo.canonico === tipoDispositivo.value)) return;
    tipoDispositivo.value = tipos.length ? tipos[0].canonico : "";
  },
  { immediate: true },
);

// ── la carga del Excel ─────────────────────────────────────────────────────

/** Sube el fichero elegido. El parseo lo hace el backend, en un trabajo. */
async function elegirFichero(evento) {
  const fichero = evento.target.files && evento.target.files[0];
  if (!fichero) return;
  await excel.subir(fichero);
  // Se vacia el input para que elegir el MISMO fichero otra vez dispare
  // el cambio.
  if (inputFichero.value) inputFichero.value.value = "";
}

/** Abre el selector de ficheros. */
function abrirSelector() {
  if (inputFichero.value) inputFichero.value.click();
}

onMounted(() => {
  excel.cargar();
});
</script>

<template>
  <section class="flex-1 min-h-0 flex flex-col gap-4" data-testid="definicion-programacion">
    <!-- ── CARGA EXCEL ────────────────────────────────────────────────── -->
    <section class="bg-surface-raised border border-line rounded p-4" data-testid="definicion-carga">
      <h2 class="text-xs font-semibold text-ink-muted uppercase mb-3">Carga Excel</h2>

      <div class="flex items-center gap-3">
        <input
          ref="inputFichero"
          type="file"
          accept=".xlsx"
          data-testid="definicion-fichero"
          class="flex-1 text-xs text-ink file:mr-2 file:py-1 file:px-2 file:rounded file:border-0 file:bg-surface-sunken file:text-ink"
          :disabled="excel.subiendo"
          @change="elegirFichero"
        />
        <button
          type="button"
          data-testid="definicion-reseleccionar"
          class="px-3 py-1.5 text-xs font-semibold text-accent bg-surface-sunken hover:bg-accent-subtle rounded-md transition-colors duration-200 border border-line flex items-center gap-1.5 disabled:opacity-50 disabled:cursor-not-allowed"
          :disabled="excel.subiendo"
          @click="abrirSelector"
        >
          🔄 Volver a seleccionar
        </button>
      </div>

      <p v-if="excel.subiendo" class="mt-2 text-xs text-ink-muted" data-testid="definicion-subiendo">
        ⏳ Subiendo el Excel…
      </p>

      <div v-if="excel.cargado" class="mt-2 text-xs">
        <p class="text-green-600 font-semibold" data-testid="definicion-cargado">✅ Excel cargado</p>
        <p class="text-ink-muted mt-1" data-testid="definicion-archivo">
          📎 Último archivo: <span class="font-mono text-ink">{{ excel.archivo }}</span>
        </p>
      </div>
    </section>

    <!-- ── ERROR ──────────────────────────────────────────────────────── -->
    <div
      v-if="excel.error"
      class="flex items-start gap-3 bg-surface-raised border border-red-600 rounded p-3 text-xs text-red-600"
      data-testid="definicion-error"
    >
      <span class="flex-1">✗ {{ excel.error }}</span>
      <button
        type="button"
        class="text-red-600 hover:text-ink"
        title="Cerrar el aviso"
        data-testid="definicion-error-cerrar"
        @click="excel.limpiarError()"
      >
        ✕
      </button>
    </div>

    <!-- ── AVISOS ─────────────────────────────────────────────────────── -->
    <div
      v-if="excel.avisos.length"
      class="bg-surface-raised border border-amber-500 rounded p-3 text-xs text-ink"
      data-testid="definicion-avisos"
    >
      <p
        v-for="(aviso, indice) in excel.avisos"
        :key="indice"
        class="flex items-start gap-2"
        :class="indice > 0 ? 'mt-1' : ''"
      >
        <span class="text-amber-600">⚠️</span>
        <span>{{ aviso }}</span>
      </p>
    </div>

    <!-- ── CONTENIDO ───────────────────────────────────────────────────── -->
    <section
      class="flex-1 min-h-0 flex flex-col bg-surface-raised border border-line rounded p-4"
      data-testid="definicion-contenido"
    >
      <template v-if="excel.cargado">
        <div class="flex border-b-2 border-line bg-surface-sunken overflow-x-auto" data-testid="definicion-pestanas">
          <button
            v-for="item in pestanas"
            :key="item.clave"
            type="button"
            class="px-6 py-3 text-sm font-semibold border-r border-line whitespace-nowrap"
            :class="
              item.clave === pestana
                ? 'bg-surface-raised text-ink border-b-2 border-accent -mb-px'
                : 'bg-surface-sunken text-ink-muted hover:bg-surface-raised'
            "
            :data-testid="'definicion-pestana-' + item.clave"
            @click="pestana = item.clave"
          >
            <span class="mr-1">{{ item.icono }}</span>
            {{ item.etiqueta }}
            <span class="ml-2 text-[11px] opacity-70">({{ item.contador }})</span>
          </button>
        </div>

        <div
          v-if="pestana === 'dispositivos'"
          class="flex border-b border-line bg-surface-sunken overflow-x-auto mt-3"
          data-testid="definicion-subpestanas-dispositivos"
        >
          <button
            v-for="tipo in tiposDispositivo"
            :key="tipo.canonico"
            type="button"
            class="px-4 py-2 text-xs font-semibold border-r border-line whitespace-nowrap"
            :class="
              tipo.canonico === tipoDispositivo
                ? 'bg-surface-raised text-ink border-b-2 border-accent -mb-px'
                : 'bg-surface-sunken text-ink-muted hover:bg-surface-raised'
            "
            :data-testid="'definicion-subpestana-' + tipo.canonico"
            @click="tipoDispositivo = tipo.canonico"
          >
            {{ tipo.etiqueta }}
            <span class="ml-1 text-[10px] opacity-70">({{ tipo.contador }})</span>
          </button>
        </div>

        <div
          v-if="pestana === 'procesos'"
          class="flex border-b border-line bg-surface-sunken overflow-x-auto mt-3"
          data-testid="definicion-subpestanas-procesos"
        >
          <button
            v-for="sub in subdominiosProceso"
            :key="sub.clave"
            type="button"
            class="px-4 py-2 text-xs font-semibold border-r border-line whitespace-nowrap"
            :class="
              sub.clave === subdominioProceso
                ? 'bg-surface-raised text-ink border-b-2 border-accent -mb-px'
                : 'bg-surface-sunken text-ink-muted hover:bg-surface-raised'
            "
            :data-testid="'definicion-subpestana-' + sub.clave"
            @click="subdominioProceso = sub.clave"
          >
            {{ sub.etiqueta }}
            <span class="ml-1 text-[10px] opacity-70">({{ sub.contador }})</span>
          </button>
        </div>

        <div
          class="mt-3 flex-1 min-h-0 overflow-auto bg-surface-raised border border-line rounded p-4"
          data-testid="definicion-tabla"
        >
          <table class="w-full text-xs" data-testid="definicion-tabla-datos">
            <thead>
              <tr class="bg-surface-sunken">
                <th
                  v-for="columna in tablaActiva.columnas"
                  :key="columna"
                  class="px-3 py-2 text-left text-[10px] uppercase text-ink-muted font-semibold border-b border-line"
                >
                  {{ etiquetaDe(columna) }}
                </th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="(fila, indice) in tablaActiva.filas" :key="indice" class="border-b border-line">
                <td
                  v-for="columna in tablaActiva.columnas"
                  :key="columna"
                  class="px-3 py-1.5 text-ink"
                  :class="esIdentificador(fila[columna]) ? 'font-mono' : ''"
                >
                  {{ textoCelda(fila[columna]) }}
                </td>
              </tr>
            </tbody>
          </table>

          <p v-if="tablaActiva.filas.length === 0" class="text-xs text-ink-muted">Sin filas.</p>
        </div>
      </template>

      <div
        v-else
        class="flex-1 flex items-center justify-center border border-dashed border-line rounded p-10 text-center"
        data-testid="definicion-vacio"
      >
        <div>
          <div class="text-5xl mb-3 opacity-40" aria-hidden="true">📊</div>
          <p class="mb-2 font-semibold text-ink">La cache del excel está vacía.</p>
          <p class="text-xs text-ink-muted">
            Sube un Excel y pulsa <span class="font-semibold text-accent">"Actualizar"</span>.
          </p>
        </div>
      </div>
    </section>
  </section>
</template>
