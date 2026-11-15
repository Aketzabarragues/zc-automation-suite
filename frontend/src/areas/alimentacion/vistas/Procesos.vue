<script setup>
/**
 * Procesos: dos modos de trabajo para el proceso elegido.
 *
 * El proceso se elige en un selector (los procesos del PLC en el Excel).
 * Debajo del selector hay dos tarjetas que activan un modo:
 *
 * - "Crear proceso completo": monta CrearProceso (clona el proceso desde
 *   una plantilla TIA, paso a paso).
 * - "Actualizar comentarios de DB": la sincronizacion de 4.5 (prevision
 *   del diff de comentarios, N_MAX y aplicacion en TIA).
 *
 * Solo un modo a la vez: al activar uno se apaga el otro. El modo no
 * cambia al cambiar de proceso ni al cerrar la app: es estado local.
 */
import { computed, onMounted, ref } from "vue";
import { ARRAYS, PROC_STATUS, useProcesosStore } from "../stores/procesos.js";
import DialogoConfirmacion from "../../../nucleo/componentes/DialogoConfirmacion.vue";
import CrearProceso from "./CrearProceso.vue";
import { useExcelStore } from "../stores/excel.js";
import { usePlcStore } from "../../../nucleo/stores/plc.js";
import { useTiaStore } from "../../../nucleo/stores/tia.js";

const procesos = useProcesosStore();
const excel = useExcelStore();
const plc = usePlcStore();
const tia = useTiaStore();

/** Los procesos del PLC seleccionado en el Excel. */
const procesosExcel = computed(() => {
  const tabla = (excel.datos && excel.datos.procesos && excel.datos.procesos.Procesos) || null;
  const filas = (tabla && tabla.filas) || [];
  return filas.filter((fila) => !plc.seleccionado || String(fila.plc_name) === plc.seleccionado);
});

/** `true` si hay procesos para el PLC seleccionado. */
const hayProcesos = computed(() => procesosExcel.value.length > 0);

/** La fila del Excel del proceso elegido, o `null`. */
const procesoElegido = computed(
  () => procesosExcel.value.find((fila) => fila.uid === procesos.procUid) || null,
);

/**
 * El modo activo: `""` (ninguno), `"comentarios"` o `"crear"`.
 * Estado local de la vista: no se guarda en el store ni en la sesion.
 */
const modo = ref("");

/**
 * `true` si se puede activar un modo: Excel cargado, PLC y TIA conectados
 * y un proceso elegido. Sin esto las tarjetas quedan deshabilitadas.
 */
const tarjetasHabilitadas = computed(
  () => excel.cargado && Boolean(plc.seleccionado) && tia.conectado && procesoElegido.value !== null,
);

/** El motivo por el que las tarjetas no se habilitan, en el orden de comprobacion. */
const motivoTarjetas = computed(() => {
  if (!excel.cargado) {
    return "Carga primero el Excel y pulsa 'Actualizar' en 'Definición programación'.";
  }
  if (!plc.seleccionado) return "Selecciona un PLC en el topbar.";
  if (!tia.conectado) return "Conecta a TIA Portal en el topbar.";
  return "Selecciona un proceso de la lista.";
});

/** El motivo de la tarjeta de comentarios (el escaneo lo exige la prevision). */
const motivoComentarios = computed(() =>
  tarjetasHabilitadas.value ? "" : motivoTarjetas.value,
);

/** El motivo de la tarjeta de crear. */
const motivoCrear = computed(() => (tarjetasHabilitadas.value ? "" : motivoTarjetas.value));

/** Activa un modo: al activar uno se apaga el otro (solo un modo a la vez). */
function activarModo(nuevo) {
  modo.value = nuevo;
}

/** Cierra el modo de crear (lo emite CrearProceso con su boton Cerrar). */
function cerrarCrear() {
  modo.value = "";
}

/** `true` si se puede generar la prevision. */
const puedeGenerar = computed(
  () =>
    modo.value === "comentarios" &&
    tia.conectado &&
    excel.cargado &&
    Boolean(plc.seleccionado) &&
    procesos.procUid != null &&
    !procesos.generando &&
    !procesos.aplicando,
);

/** `true` si se puede aplicar la prevision en TIA Portal. */
const puedeAplicar = computed(
  () =>
    modo.value === "comentarios" &&
    procesos.hayPreview &&
    procesos.numeroDeCambios > 0 &&
    tia.conectado &&
    excel.cargado &&
    Boolean(plc.seleccionado) &&
    !procesos.aplicando,
);

/** La pestana activa: uno de `PReal`, `PInt` o `ALM`. */
const pestanaActiva = ref("PReal");

/** El resumen del preview: "N slots — X a renombrar · ...". */
const resumenTexto = computed(() => {
  const resumen = procesos.resumen;
  return {
    total: resumen.total,
    agregados: resumen.agregados,
    renombrados: resumen.renombrados,
    eliminados: resumen.eliminados,
    sin_cambios: resumen.sin_cambios,
  };
});

/** El estado de una fila, con su texto y su color. */
function estadoDe(fila) {
  return PROC_STATUS[fila.action] || { label: fila.action, clase: "text-ink-muted" };
}

/** El texto del boton de generar. */
const textoGenerar = computed(() => {
  if (procesos.generando) return "Generando prevision…";
  return "🔍 Generar Previsión";
});

/** El texto del boton de aplicar. */
const textoAplicar = computed(
  () => `✅ Aplicar Cambios en TIA Portal (${procesos.numeroDeCambios} cambios)`,
);

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
  await procesos.generar(plc.seleccionado, procesos.procUid);
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
  await procesos.aplicar(plc.seleccionado, procesos.procUid);
}

/** La clase del estado de una transaccion. */
function claseDeTransaccion(estado) {
  if (estado === "confirmada") return "text-green-600";
  if (estado === "revertida") return "text-red-600";
  return "text-ink-muted";
}

/** Elige un proceso del selector. El modo no cambia. */
function elegirProceso(evento) {
  const valor = evento.target.value;
  procesos.elegir(valor === "" ? null : Number(valor));
}

onMounted(() => {
  excel.hidratar();
  procesos.hidratar();
});
</script>

<template>
  <section class="flex-1 min-h-0 flex flex-col gap-4" data-testid="procesos">
    <!-- ── banner: sin Excel / sin PLC / sin procesos ────────────────── -->
    <div
      v-if="!excel.cargado || !plc.seleccionado || !hayProcesos"
      class="bg-surface-raised border border-amber-300 rounded p-3 text-xs text-amber-800"
      data-testid="procesos-banner"
    >
      <span v-if="!excel.cargado">
        ⚠️ No hay Excel cargado. Sube un Excel y pulsa <strong class="text-accent">"Actualizar"</strong>
        en "Definición programación".
      </span>
      <span v-else-if="!plc.seleccionado">
        ⚠️ Selecciona un PLC en el <strong class="text-accent">topbar</strong> para ver sus procesos.
      </span>
      <span v-else>
        ⚠️ El PLC <strong>{{ plc.seleccionado }}</strong> no tiene procesos definidos en el Excel cargado.
      </span>
    </div>

    <!-- ── la tarjeta de arriba: selector, tarjetas de modo y botones ── -->
    <section class="bg-surface-raised border border-line rounded p-4 flex flex-col gap-3">
      <!-- el selector de proceso -->
      <div data-testid="procesos-selector">
        <label class="block text-xs font-semibold text-ink-muted uppercase mb-2">Proceso</label>
        <select
          data-testid="procesos-select"
          class="w-full bg-surface-raised border border-line text-accent font-bold text-sm rounded px-3 py-1.5 font-mono disabled:opacity-50 cursor-pointer"
          :disabled="!hayProcesos"
          :value="procesos.procUid ?? ''"
          @change="elegirProceso"
        >
          <option value="" disabled data-testid="procesos-select-placeholder">
            {{ hayProcesos ? "Selecciona un proceso…" : "No hay procesos cargados" }}
          </option>
          <option v-for="p in procesosExcel" :key="p.uid" :value="p.uid" data-testid="procesos-select-opcion">
            {{ p.codigo }} — {{ p.nombre }}
          </option>
        </select>
      </div>

      <!-- las tarjetas de modo: ¿que quieres hacer? -->
      <div class="grid grid-cols-1 sm:grid-cols-2 gap-3">
        <button
          type="button"
          data-testid="procesos-tarjeta-crear"
          class="bg-surface-raised border rounded-lg p-3 text-left flex flex-col items-start transition hover:border-accent hover:shadow-lg disabled:opacity-50 disabled:cursor-not-allowed disabled:hover:border-line disabled:hover:shadow-none focus:outline-none focus:ring-2 focus:ring-accent focus:ring-offset-2 focus:ring-offset-surface"
          :class="modo === 'crear' ? 'border-accent' : 'border-line'"
          :disabled="!tarjetasHabilitadas"
          :title="motivoCrear"
          @click="activarModo('crear')"
        >
          <span class="text-2xl mb-1" aria-hidden="true">🏗️</span>
          <span class="text-sm font-semibold text-ink leading-snug">Crear proceso completo</span>
          <span class="text-xs text-ink-muted mt-0.5 leading-snug">
            Genera el DB + bloques + UDTs del proceso.
          </span>
        </button>

        <button
          type="button"
          data-testid="procesos-tarjeta-comentarios"
          class="bg-surface-raised border rounded-lg p-3 text-left flex flex-col items-start transition hover:border-accent hover:shadow-lg disabled:opacity-50 disabled:cursor-not-allowed disabled:hover:border-line disabled:hover:shadow-none focus:outline-none focus:ring-2 focus:ring-accent focus:ring-offset-2 focus:ring-offset-surface"
          :class="modo === 'comentarios' ? 'border-accent' : 'border-line'"
          :disabled="!tarjetasHabilitadas"
          :title="motivoComentarios"
          @click="activarModo('comentarios')"
        >
          <span class="text-2xl mb-1" aria-hidden="true">💬</span>
          <span class="text-sm font-semibold text-ink leading-snug">Actualizar comentarios de DB</span>
          <span class="text-xs text-ink-muted mt-0.5 leading-snug">
            Sincroniza los comentarios de los DBs existentes.
          </span>
        </button>
      </div>
    </section>

    <!-- ── el error ─────────────────────────────────────────────────── -->
    <div
      v-if="modo === 'comentarios' && procesos.error"
      class="bg-surface-raised border border-red-600 rounded p-3 text-xs text-red-600"
      data-testid="procesos-error"
    >
      ✗ {{ procesos.error }}
    </div>

    <!-- ── el banner de precondiciones (DBs ausentes) ───────────────── -->
    <div
      v-if="modo === 'comentarios' && procesos.preview && !procesos.preview.precondiciones_ok"
      class="bg-surface-raised border border-amber-300 rounded p-3 text-xs text-amber-800"
      data-testid="procesos-precond"
    >
      ⚠️ Precondiciones no cumplidas:
      {{ (procesos.preview.missing_blocks || []).join(" · ") || "revisa el PLC y el Excel" }}
    </div>

    <!-- ── el contenido del modo comentarios (la vista 4.5) ─────────── -->
    <section
      v-if="modo === 'comentarios'"
      class="flex-1 min-h-0 bg-surface-raised border border-line rounded p-4 flex flex-col overflow-hidden"
      data-testid="procesos-contenido"
    >
      <!-- las tarjetas de N_MAX -->
      <div
        v-if="procesos.hayPreview && procesos.tarjetasNMax.length > 0"
        class="grid grid-cols-2 md:grid-cols-4 gap-2 mb-3"
        data-testid="procesos-nmax"
      >
        <div
          v-for="tarjeta in procesos.tarjetasNMax"
          :key="tarjeta.name"
          class="bg-surface-raised border border-line rounded p-3"
        >
          <div class="text-[10px] uppercase text-ink-muted">{{ tarjeta.kind || tarjeta.name }}</div>
          <div class="text-xl font-bold">
            <template v-if="tarjeta.status === 'actualizar'">
              <span class="inline-flex items-baseline gap-1.5">
                <span
                  v-if="tarjeta.actual !== null && tarjeta.actual !== undefined"
                  class="text-accent"
                >
                  {{ tarjeta.actual }}
                </span>
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

      <!-- las pestanas de los arrays -->
      <div
        v-if="procesos.hayPreview"
        class="flex gap-1 border-b border-line mb-3"
        data-testid="procesos-pestanas"
      >
        <button
          v-for="array in ARRAYS"
          :key="array"
          type="button"
          class="px-3 py-1.5 text-xs font-semibold border-b-2 transition-colors"
          :class="
            pestanaActiva === array
              ? 'text-accent border-accent'
              : 'text-ink-muted border-transparent hover:text-ink'
          "
          @click="pestanaActiva = array"
        >
          {{ array }}
          <span v-if="procesos.cambiosDe(array) > 0" class="ml-1 text-[10px] text-amber-700">
            ({{ procesos.cambiosDe(array) }})
          </span>
        </button>
      </div>

      <!-- la tabla del diff -->
      <div class="flex-1 min-h-0 overflow-auto bg-surface-raised border border-line rounded">
        <table v-if="procesos.hayPreview" class="w-full text-xs" data-testid="procesos-tabla">
          <thead class="sticky top-0 bg-surface-sunken text-[10px] uppercase">
            <tr>
              <th class="px-3 py-2 text-left text-ink-muted w-14">#</th>
              <th class="px-3 py-2 text-left text-ink-muted">Comentario Actual (TIA)</th>
              <th class="px-3 py-2 text-left text-ink-muted">Comentario Deseado (Excel)</th>
              <th class="px-3 py-2 text-left text-ink-muted w-28">Estado</th>
            </tr>
          </thead>
          <tbody>
            <tr
              v-for="fila in procesos.filasDe(pestanaActiva)"
              :key="pestanaActiva + '-' + fila.slot"
              class="border-b border-line"
            >
              <td class="px-3 py-1.5 font-mono text-ink whitespace-nowrap">{{ fila.slot }}</td>
              <td
                class="px-3 py-1.5"
                :class="
                  fila.action === 'eliminar'
                    ? 'text-red-700 line-through'
                    : fila.action === 'agregar'
                      ? 'text-ink-muted italic'
                      : 'text-ink-muted'
                "
              >
                {{ fila.current ?? "—" }}
              </td>
              <td
                class="px-3 py-1.5 font-mono"
                :class="
                  fila.action === 'agregar'
                    ? 'text-accent'
                    : fila.action === 'renombrar'
                      ? 'text-amber-800'
                      : 'text-ink-muted'
                "
              >
                {{ fila.desired ?? "—" }}
              </td>
              <td class="px-3 py-1.5 whitespace-nowrap" :class="estadoDe(fila).clase">
                {{ estadoDe(fila).label }}
              </td>
            </tr>
          </tbody>
        </table>

        <div
          v-else
          class="flex-1 flex items-center justify-center p-10 text-center text-ink-muted"
          data-testid="procesos-vacio"
        >
          <div>
            <div class="text-5xl mb-3 opacity-40" aria-hidden="true">⚙️</div>
            <p class="mb-2">Sin prevision generada.</p>
            <p class="text-xs">
              Elige un proceso y pulsa
              <strong class="text-accent">"🔍 Generar Previsión"</strong> para ver el diff
              completo.
            </p>
          </div>
        </div>
      </div>

      <!-- el resumen de la prevision y el boton de generar -->
      <div class="flex justify-between items-center gap-3">
        <p
          v-if="procesos.hayPreview"
          class="text-xs text-ink-muted"
          data-testid="procesos-resumen"
        >
          {{ resumenTexto.total }} slots analizados —
          <span class="text-accent">{{ resumenTexto.agregados }} a agregar</span> ·
          <span class="text-amber-700">{{ resumenTexto.renombrados }} a renombrar</span> ·
          <span class="text-red-700">{{ resumenTexto.eliminados }} a eliminar</span> ·
          <span class="text-ink-muted">{{ resumenTexto.sin_cambios }} sin cambios</span>
        </p>
        <span v-else></span>
        <button
          type="button"
          data-testid="procesos-generar"
          class="px-3 py-1.5 text-accent font-semibold text-xs bg-surface-sunken hover:bg-accent-subtle rounded-md transition-colors duration-200 border border-line flex items-center gap-1.5 disabled:opacity-50 disabled:cursor-not-allowed"
          :disabled="!puedeGenerar"
          @click="generar"
        >
          {{ textoGenerar }}
        </button>
      </div>

      <!-- el boton de aplicar -->
      <button
        type="button"
        data-testid="procesos-aplicar"
        class="mt-3 w-full py-3 font-semibold text-sm bg-accent text-ink-inverse rounded-md border border-line hover:bg-accent-hover transition-colors duration-200 disabled:opacity-50 disabled:cursor-not-allowed"
        :disabled="!puedeAplicar"
        @click="abrirDialogo"
      >
        {{ textoAplicar }}
      </button>

      <!-- el estado de las transacciones del ultimo sync -->
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
    </section>

    <!-- ── el contenido del modo crear (CrearProceso) ───────────────── -->
    <CrearProceso
      v-if="modo === 'crear'"
      :proceso="procesoElegido"
      data-testid="crear"
      @cerrar="cerrarCrear"
    />

    <!-- ── el dialogo de confirmacion ────────────────────────────────── -->
    <DialogoConfirmacion
      :abierto="dialogoAbierto"
      :texto="textoConfirmacion"
      prefijo="procesos"
      @confirmar="confirmar"
      @cancelar="cerrarDialogo"
    />
  </section>
</template>
