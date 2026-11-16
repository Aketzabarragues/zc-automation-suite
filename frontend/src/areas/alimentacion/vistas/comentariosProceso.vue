<script setup>
/**
 * ComentariosProceso: el diff de los comentarios de los DBs de un proceso y
 * su aplicacion en TIA Portal.
 *
 * Se monta inline dentro de la vista de Procesos, debajo de las tarjetas de
 * accion. Recibe la fila del proceso (o su uid) y emite `cerrar` para que el
 * padre colapse el panel.
 *
 * El boton de "Aplicar" vive aqui (no en la vista padre): es el unico
 * indicador de feedback de una operacion larga contra TIA, asi que el
 * dialogo de confirmacion y el estado de las transacciones tambien.
 */
import { computed, ref } from "vue";
import { ARRAYS, PROC_STATUS, useProcesosStore } from "../stores/procesos.js";
import DialogoConfirmacion from "../../../nucleo/componentes/DialogoConfirmacion.vue";
import { useExcelStore } from "../stores/excel.js";
import { usePlcStore } from "../../../nucleo/stores/plc.js";
import { useTiaStore } from "../../../nucleo/stores/tia.js";

const props = defineProps({
  /** La fila del Excel del proceso, o `null`. */
  proceso: { type: Object, default: null },
  /** El uid del proceso, si se pasa en vez de la fila. */
  uid: { type: Number, default: null },
});

const emit = defineEmits(["cerrar"]);

const procesos = useProcesosStore();
const excel = useExcelStore();
const plc = usePlcStore();
const tia = useTiaStore();

/** El uid del proceso: del prop `proceso` o del prop `uid`. */
const procUid = computed(() =>
  props.proceso ? props.proceso.uid : props.uid,
);

/**
 * La prevision vigente del proceso.
 *
 * El store ya la filtra por PLC y por conexion con TIA: si el operario
 * cambia de PLC o se pierde TIA, la prevision deja de valer.
 */
const preview = computed(() => {
  const p = procesos.vigente;
  if (!p) return null;
  if (procUid.value == null) return null;
  if (p.proc_uid !== procUid.value) return null;
  return p;
});

/**
 * La prevision del proceso, sin el filtro de PLC ni de TIA.
 *
 * La tabla y las pestanas usan la prevision vigente (si no, no se ven).
 * El boton de aplicar y los avisos usan esta: el operario tiene que ver
 * por que no puede aplicar aunque el PLC se haya deseleccionado.
 */
const previewProceso = computed(() => {
  const p = procesos.preview;
  if (!p) return null;
  if (procUid.value == null) return null;
  if (p.proc_uid !== procUid.value) return null;
  return p;
});

/** `true` si hay prevision con las precondiciones cumplidas. */
const hayPreview = computed(() => Boolean(preview.value && preview.value.precondiciones_ok));

/** `true` si la prevision del proceso tiene las precondiciones cumplidas. */
const hayPreviewProceso = computed(() =>
  Boolean(previewProceso.value && previewProceso.value.precondiciones_ok),
);

/** La pestana activa: uno de `PReal`, `PInt` o `ALM`. */
const pestanaActiva = ref("PReal");

/** El nombre del proceso, para la cabecera. */
const nombreProceso = computed(() => (props.proceso ? props.proceso.nombre : ""));

/** El codigo del proceso, para la cabecera. */
const codigoProceso = computed(() => (props.proceso ? props.proceso.codigo : ""));

/**
 * El banner de precondiciones: los bloques que faltan en el PLC.
 */
const precondError = computed(() => {
  const p = previewProceso.value;
  if (!p) return null;
  if (p.precondiciones_ok) return null;
  return p.missing_blocks && p.missing_blocks.length > 0
    ? p.missing_blocks.join(" · ")
    : "Precondiciones no cumplidas";
});

/**
 * Las filas del bloque "Bloques TIA objetivo", con la marca de presencia en
 * el PLC. `existe` es `null` cuando el backend no lo dice.
 */
const nombresTiaConEstado = computed(() => {
  const p = previewProceso.value;
  if (!p || !p.db_param_name) return [];
  const dp = p.db_present;
  return [
    {
      label: "DB parámetros",
      nombre: p.db_param_name,
      existe: dp && typeof dp.param === "boolean" ? dp.param : null,
    },
    {
      label: "DB alarmas",
      nombre: p.db_alm_name,
      existe: dp && typeof dp.alm === "boolean" ? dp.alm : null,
    },
    {
      label: "Tabla de variables",
      nombre: p.table_name,
      existe: typeof p.table_present === "boolean" ? p.table_present : null,
    },
  ];
});

/** Las filas del array de la pestana activa. */
const filas = computed(() => procesos.filasDe(pestanaActiva.value));

/**
 * El numero de cambios de una pestana (renombrar + agregar + eliminar), del
 * `summary` que calcula el backend. `sin_cambios` no cuenta.
 */
function cambiosDe(array) {
  return procesos.cambiosDe(array);
}

/**
 * Los N_MAX a actualizar: los que cambian de valor.
 *
 * En TIA V18 los arrays de comentarios salen vacios (no hay SimaticSD), asi
 * que el unico cambio posible es el N_MAX.
 */
const nmaxAAplicar = computed(() => {
  const p = previewProceso.value;
  if (!p || !p.nmax || !p.nmax.summary) return 0;
  return p.nmax.summary.actualizar || 0;
});

/** El total de slots analizados. */
const totalOps = computed(() => {
  const p = previewProceso.value;
  if (!p || !p.summary) return 0;
  return p.summary.total || 0;
});

/** El resumen de la prevision del proceso. */
const resumen = computed(() => {
  const p = previewProceso.value;
  if (!p || !p.summary) {
    return { total: 0, agregados: 0, renombrados: 0, eliminados: 0, sin_cambios: 0 };
  }
  return p.summary;
});

/** Las tarjetas de N_MAX de la prevision del proceso. */
const tarjetasNMax = computed(() => {
  const p = previewProceso.value;
  if (!p || !p.nmax) return [];
  return p.nmax.todos || [];
});

/** `true` si hay PLC seleccionado. */
const hayPlc = computed(() => Boolean(plc.seleccionado));

/**
 * `true` si se puede aplicar la prevision en TIA Portal.
 *
 * Con `summary.total > 0` es el criterio de main. El caso de V18 se cubre
 * con los N_MAX a actualizar: ahi los arrays salen vacios.
 */
const puedeAplicar = computed(
  () =>
    hayPreviewProceso.value &&
    tia.conectado &&
    excel.cargado &&
    hayPlc.value &&
    !procesos.aplicando &&
    (totalOps.value > 0 || nmaxAAplicar.value > 0),
);

/** `true` si se puede generar la prevision. */
const puedeGenerar = computed(
  () =>
    tia.conectado &&
    excel.cargado &&
    hayPlc.value &&
    procUid.value != null &&
    !procesos.generando &&
    !procesos.aplicando,
);

/** El estado de una fila, con su texto y su color. */
function estadoDe(fila) {
  return PROC_STATUS[fila.action] || { label: fila.action, clase: "text-ink-muted" };
}

/** El texto del boton de generar. */
const textoGenerar = computed(() => {
  if (procesos.generando) return "Generando…";
  return "🔍 Generar Previsión";
});

/** El texto del boton de aplicar. */
const textoAplicar = computed(() => {
  if (procesos.aplicando) return "⏳ Aplicando…";
  return "✅ Aplicar al PLC";
});

/** El motivo por el que el boton de aplicar esta deshabilitado. */
const motivoAplicar = computed(() => {
  if (!hayPlc.value) return "Selecciona un PLC primero";
  if (totalOps.value === 0 && nmaxAAplicar.value === 0) return "No hay cambios que aplicar";
  return "";
});

/** `true` mientras el dialogo de confirmacion esta abierto. */
const dialogoAbierto = ref(false);

/**
 * El texto de la confirmacion, con los numeros de la prevision actual.
 */
const textoConfirmacion = computed(() => {
  const resumen = procesos.resumen;
  const nmax = procesos.resumenNMax;
  return (
    `¿Aplicar ${procesos.numeroDeCambios} cambios en TIA Portal?\n\n` +
    `Comentarios de DB:\n` +
    `  Agregar: ${resumen.agregados}\n` +
    `  Renombrar: ${resumen.renombrados}\n` +
    `  Eliminar: ${resumen.eliminados}\n\n` +
    `N_MAX (dimensiones):\n` +
    `  Actualizar: ${nmax.actualizar}\n\n` +
    `Los "sin cambios" no se tocan.\n` +
    `Esta operacion modifica el PLC.`
  );
});

/** Genera la prevision. */
async function generar() {
  await procesos.generar(plc.seleccionado, procUid.value);
}

/** Abre el dialogo de confirmacion. */
function abrirDialogo() {
  dialogoAbierto.value = true;
}

/** Cierra el dialogo sin aplicar nada. */
function cerrarDialogo() {
  dialogoAbierto.value = false;
}

/** Confirma: aplica los cambios en TIA Portal. */
async function confirmar() {
  dialogoAbierto.value = false;
  await procesos.aplicar(plc.seleccionado, procUid.value);
}

/** La clase del estado de una transaccion. */
function claseDeTransaccion(estado) {
  if (estado === "confirmada") return "text-green-600";
  if (estado === "revertida") return "text-red-600";
  return "text-ink-muted";
}
</script>

<template>
  <section class="flex-none flex flex-col" data-testid="procesos-comentarios">
    <!-- ── la cabecera ────────────────────────────────────────────── -->
    <header class="flex justify-between items-start mb-4">
      <div>
        <h2 class="text-lg font-bold text-ink">💬 Actualizar comentarios de DB</h2>
        <p v-if="proceso" class="text-xs text-ink-muted mt-0.5">
          Proceso
          <span class="font-semibold text-ink">{{ nombreProceso }}</span>
          (<span class="font-mono">{{ codigoProceso }}</span>,
          uid <span class="font-mono">{{ procUid }}</span>)
        </p>
        <p v-else class="text-xs text-amber-700 mt-0.5">
          Selecciona un proceso en la vista "Procesos" primero.
        </p>

        <!-- el resumen de la prevision -->
        <p
          v-if="hayPreviewProceso"
          class="text-xs text-ink-muted mt-0.5"
          data-testid="procesos-resumen"
        >
          <span class="text-ink-muted">{{ totalOps }} slots analizados —</span>
          <span class="text-amber-700">{{ resumen.renombrados }} a renombrar</span>
          ·
          <span class="text-accent">{{ resumen.agregados }} a agregar</span>
          ·
          <span class="text-red-700">{{ resumen.eliminados }} a eliminar</span>
          ·
          <span class="text-ink-muted">{{ resumen.sin_cambios }} sin cambios</span>
        </p>
      </div>

      <div class="flex gap-2">
        <button
          type="button"
          data-testid="proc-sync-close"
          class="px-3 py-1.5 text-ink-muted font-semibold text-xs bg-surface-sunken hover:bg-surface rounded-md transition-colors duration-200 border border-line flex items-center gap-1.5 disabled:opacity-50 disabled:cursor-not-allowed"
          @click="emit('cerrar')"
        >
          Cerrar
        </button>
        <button
          type="button"
          data-testid="proc-sync-generate-preview"
          class="px-3 py-1.5 text-accent font-semibold text-xs bg-surface-sunken hover:bg-accent-subtle rounded-md transition-colors duration-200 border border-line flex items-center gap-1.5 disabled:opacity-50 disabled:cursor-not-allowed"
          :disabled="!puedeGenerar"
          @click="generar"
        >
          <span :class="procesos.generando ? 'animate-spin' : ''" aria-hidden="true">🔍</span>
          {{ textoGenerar }}
        </button>
      </div>
    </header>

    <!-- ── el error del flujo ─────────────────────────────────────── -->
    <div
      v-if="procesos.error"
      class="mb-3 px-3 py-2 bg-red-100 border border-red-300 rounded text-xs text-red-800"
      data-testid="procesos-error"
    >
      ⚠️ {{ procesos.error }}
    </div>

    <!-- ── el banner de precondiciones ────────────────────────────── -->
    <div
      v-if="precondError"
      class="mb-3 px-3 py-2 bg-amber-100 border border-amber-300 rounded text-xs text-amber-800"
      data-testid="procesos-precond"
    >
      ⚠️ Precondiciones no cumplidas: {{ precondError }}
    </div>

    <!-- ── los bloques TIA objetivo ───────────────────────────────── -->
    <div
      v-if="previewProceso && previewProceso.db_param_name"
      class="mb-3 bg-surface-raised border border-line rounded p-3 text-xs"
      data-testid="procesos-bloques-tia"
    >
      <div class="text-ink-muted mb-1 font-semibold">Bloques TIA objetivo</div>
      <div
        v-for="row in nombresTiaConEstado"
        :key="row.label"
        class="font-mono"
        :class="row.existe === false ? 'text-red-700' : 'text-ink'"
      >
        {{ row.label }}:
        <span class="font-semibold">{{ row.nombre }}</span>
        <span v-if="row.existe === false" class="ml-1 text-[10px] text-red-600">
          (no existe en PLC)
        </span>
      </div>
    </div>

    <!-- ── las tarjetas de N_MAX ──────────────────────────────────── -->
    <div
      v-if="tarjetasNMax.length > 0"
      class="grid grid-cols-1 md:grid-cols-3 gap-2 mb-3"
      data-testid="proc-sync-nmax-cards"
    >
      <div
        v-for="tarjeta in tarjetasNMax"
        :key="tarjeta.name"
        :data-testid="'proc-sync-nmax-' + tarjeta.kind"
        class="bg-surface-raised border border-line rounded p-3"
      >
        <div class="text-[10px] uppercase text-ink-muted">
          {{ procesos.etiquetaNMax(tarjeta) }}
        </div>
        <div class="text-xl font-bold">
          <template v-if="tarjeta.status === 'actualizar'">
            <span class="inline-flex items-baseline gap-1.5">
              <span
                v-if="tarjeta.actual !== null && tarjeta.actual !== undefined"
                class="text-accent"
              >
                {{ tarjeta.actual }}
              </span>
              <span v-else class="text-ink-muted">?</span>
              <span class="text-ink-muted">→</span>
              <span class="text-amber-700">{{ tarjeta.nuevo }}</span>
            </span>
          </template>
          <template v-else>
            <span class="text-accent">{{ tarjeta.nuevo }}</span>
          </template>
        </div>
      </div>
    </div>

    <!-- ── las pestanas de los arrays ─────────────────────────────── -->
    <div
      v-if="hayPreview"
      class="flex border-b border-line bg-surface-sunken overflow-x-auto"
      data-testid="procesos-pestanas"
    >
      <button
        v-for="array in ARRAYS"
        :key="array"
        type="button"
        class="px-4 py-2 text-xs font-medium border-r border-line whitespace-nowrap"
        :class="
          pestanaActiva === array
            ? 'bg-surface-raised text-ink'
            : 'bg-surface-raised text-ink-muted hover:bg-surface-sunken'
        "
        @click="pestanaActiva = array"
      >
        {{ array === "PReal" ? "Parámetros reales" : array === "PInt" ? "Parámetros Enteros" : "Alarmas" }}
        <span
          v-if="cambiosDe(array) > 0"
          class="ml-1 text-[10px] px-1.5 py-0.5 rounded-full bg-accent text-ink-inverse"
        >
          {{ cambiosDe(array) }}
        </span>
      </button>
    </div>

    <!-- ── la tabla del diff ──────────────────────────────────────── -->
    <div
      v-if="hayPreview"
      class="flex-1 min-h-[14rem] bg-surface-raised border border-line rounded overflow-auto mt-2"
    >
      <table class="w-full text-xs" data-testid="procesos-tabla">
        <thead class="sticky top-0 bg-surface-sunken text-[10px] uppercase">
          <tr>
            <th class="px-3 py-2 text-left text-ink-muted w-14">#</th>
            <th class="px-3 py-2 text-left text-ink-muted">Actual (TIA)</th>
            <th class="px-3 py-2 text-left text-ink-muted">Deseado (Excel)</th>
            <th class="px-3 py-2 text-left text-ink-muted w-28">Estado</th>
          </tr>
        </thead>
        <tbody>
          <tr
            v-for="fila in filas"
            :key="pestanaActiva + '-' + fila.slot"
            :data-testid="'proc-sync-row-' + pestanaActiva + '-' + fila.slot"
            class="border-b border-line"
          >
            <td class="px-3 py-1.5 font-mono text-ink whitespace-nowrap">{{ fila.slot }}</td>
            <td class="px-3 py-1.5 text-ink-muted">
              <span v-if="fila.current === null || fila.current === undefined" class="italic">—</span>
              <span v-else>{{ fila.current }}</span>
            </td>
            <td class="px-3 py-1.5 font-mono text-ink">{{ fila.desired }}</td>
            <td class="px-3 py-1.5 whitespace-nowrap" :class="estadoDe(fila).clase">
              {{ estadoDe(fila).label }}
            </td>
          </tr>
          <tr v-if="filas.length === 0">
            <td colspan="4" class="px-3 py-6 text-center text-ink-muted italic">
              No hay slots en este array.
            </td>
          </tr>
        </tbody>
      </table>
    </div>

    <!-- ── el vacio: sin prevision todavia ────────────────────────── -->
    <div
      v-else
      class="flex-1 flex items-center justify-center p-10 text-center text-ink-muted bg-surface-raised border border-line rounded"
      data-testid="procesos-vacio"
    >
      <div>
        <div class="text-5xl mb-3 opacity-40" aria-hidden="true">⚙️</div>
        <p class="mb-2">Sin prevision generada.</p>
        <p class="text-xs">
          Pulsa <strong class="text-accent">"🔍 Generar Previsión"</strong> para ver el diff completo.
        </p>
      </div>
    </div>

    <!-- ── el boton de aplicar ────────────────────────────────────── -->
    <div v-if="hayPreviewProceso" class="mt-3">
      <div
        v-if="procesos.aplicadoEn"
        class="flex justify-end items-center gap-3 mb-2"
        data-testid="procesos-aplicado"
      >
        <span class="text-xs text-green-600">✓ Aplicado: {{ procesos.aplicadoEn }}</span>
      </div>
      <button
        type="button"
        data-testid="procesos-aplicar"
        :title="motivoAplicar"
        class="w-full py-3 text-accent font-semibold text-sm bg-surface-sunken hover:bg-accent-subtle rounded-md transition-colors duration-200 border border-line flex items-center justify-center gap-2 disabled:opacity-50 disabled:cursor-not-allowed"
        :disabled="!puedeAplicar"
        @click="abrirDialogo"
      >
        {{ textoAplicar }}
      </button>
    </div>

    <!-- ── el estado de las transacciones del ultimo sync ─────────── -->
    <div
      v-if="procesos.transacciones.length > 0"
      class="mt-3 bg-surface-raised border border-line rounded p-3"
      data-testid="procesos-transacciones"
    >
      <div class="text-[10px] uppercase text-ink-muted mb-1">Transacciones</div>
      <ul class="text-xs">
        <li
          v-for="transaccion in procesos.transacciones"
          :key="transaccion.nombre"
          class="flex flex-wrap items-baseline gap-x-2"
        >
          <span class="text-ink">{{ transaccion.nombre }}: </span>
          <span :class="claseDeTransaccion(transaccion.estado)">{{ transaccion.estado }}</span>
          <span v-if="transaccion.detalle" class="text-[10px] text-ink-muted">
            {{ transaccion.detalle }}
          </span>
        </li>
      </ul>
    </div>

    <!-- ── el dialogo de confirmacion ─────────────────────────────── -->
    <DialogoConfirmacion
      :abierto="dialogoAbierto"
      :texto="textoConfirmacion"
      prefijo="procesos"
      @confirmar="confirmar"
      @cancelar="cerrarDialogo"
    />
  </section>
</template>
