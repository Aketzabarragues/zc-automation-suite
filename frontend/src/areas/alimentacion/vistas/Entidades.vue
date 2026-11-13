<script setup>
/**
 * Entidades: la prevision de las entidades del PLC frente al Excel.
 *
 * La prevision la calcula el backend (exporta del PLC y compara con el
 * Excel). Aplicarla en TIA es un trabajo: la vista encola el sync, espera a
 * que termine y se queda con la prevision posterior.
 *
 * Solo hay un tipo de entidad, asi que no hay pestañas: una sola tabla con
 * el tag y el comentario, tanto de TIA como del Excel.
 */
import { computed, onBeforeUnmount, onMounted, ref } from "vue";
import { ENT_STATUS, useEntidadesStore } from "../stores/entidades.js";
import { useExcelStore } from "../stores/excel.js";
import { usePlcStore } from "../../../nucleo/stores/plc.js";
import { useTiaStore } from "../../../nucleo/stores/tia.js";

const entidades = useEntidadesStore();
const excel = useExcelStore();
const plc = usePlcStore();
const tia = useTiaStore();

/** `true` si se puede generar la prevision. */
const puedeGenerar = computed(
  () =>
    tia.conectado &&
    excel.cargado &&
    Boolean(plc.seleccionado) &&
    !entidades.generando &&
    !entidades.aplicando,
);

/** `true` si se puede aplicar la prevision en TIA Portal. */
const puedeAplicar = computed(
  () =>
    entidades.hayPreview &&
    tia.conectado &&
    excel.cargado &&
    Boolean(plc.seleccionado) &&
    !entidades.aplicando,
);

/** El estado de una fila, con su texto y su color. */
function estadoDe(fila) {
  return ENT_STATUS[fila.status] || { label: fila.status, clase: "text-ink-muted" };
}

/** El texto del boton de generar. */
const textoGenerar = computed(() => {
  if (entidades.generando) return "Generando prevision…";
  return "🔍 Generar Previsión";
});

/** El texto del boton de aplicar. */
const textoAplicar = computed(
  () => `✅ Aplicar Cambios en TIA Portal (${entidades.numeroDeCambios} cambios)`,
);

/** `true` mientras el dialogo de confirmacion esta abierto. */
const dialogoAbierto = ref(false);

/**
 * El texto de la confirmacion, con los numeros de la prevision actual.
 */
const textoConfirmacion = computed(
  () =>
    `¿Aplicar ${entidades.numeroDeCambios} cambios en TIA Portal?\n\n` +
    `Entities:\n` +
    `  Agregar: ${entidades.resumen.agregados}\n` +
    `  Renombrar: ${entidades.resumen.renombrados}\n` +
    `  Eliminar: ${entidades.resumen.eliminados}\n\n` +
    `N_MAX (dimensiones):\n` +
    `  Actualizar: ${entidades.resumenNMax.actualizar}\n\n` +
    `Los "sin cambios" no se tocan.\n` +
    `Esta operacion modifica el PLC.`,
);

/** Genera la prevision. */
async function generar() {
  await entidades.generar(plc.seleccionado);
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
  await entidades.aplicar(plc.seleccionado);
}

/** Cierra el dialogo con Escape. */
function onTecla(evento) {
  if (!dialogoAbierto.value) return;
  if (evento.key === "Escape" || evento.key === "Esc" || evento.keyCode === 27) {
    cerrarDialogo();
  }
}

/** La clase del estado de una transaccion. */
function claseDeTransaccion(estado) {
  if (estado === "confirmada") return "text-green-600";
  if (estado === "revertida") return "text-red-600";
  return "text-ink-muted";
}

onMounted(() => {
  excel.hidratar();
  entidades.hidratar();
  entidades.cargarCatalogo();
  window.addEventListener("keydown", onTecla);
});

onBeforeUnmount(() => {
  window.removeEventListener("keydown", onTecla);
});
</script>

<template>
  <section class="flex-1 min-h-0 flex flex-col gap-4" data-testid="entidades">
    <!-- ── la tarjeta de arriba: resumen y boton ────────────────────── -->
    <section class="bg-surface-raised border border-line rounded p-4 flex justify-between items-center">
      <p v-if="entidades.hayPreview" class="text-xs text-ink-muted" data-testid="entidades-resumen">
        {{ entidades.resumen.total }} entidades analizadas —
        <span class="text-accent">{{ entidades.resumen.agregados }} a agregar</span> ·
        <span class="text-amber-700">{{ entidades.resumen.renombrados }} a renombrar</span> ·
        <span class="text-red-700">{{ entidades.resumen.eliminados }} a eliminar</span> ·
        <span class="text-ink-muted">{{ entidades.resumen.sin_cambios }} sin cambios</span>
      </p>
      <span v-else></span>
      <button
        type="button"
        data-testid="entidades-generar"
        class="px-3 py-1.5 text-accent font-semibold text-xs bg-surface-sunken hover:bg-accent-subtle rounded-md transition-colors duration-200 border border-line flex items-center gap-1.5 disabled:opacity-50 disabled:cursor-not-allowed"
        :disabled="!puedeGenerar"
        @click="generar"
      >
        {{ textoGenerar }}
      </button>
    </section>

    <!-- ── el error ─────────────────────────────────────────────────── -->
    <div
      v-if="entidades.error"
      class="bg-surface-raised border border-red-600 rounded p-3 text-xs text-red-600"
      data-testid="entidades-error"
    >
      ✗ {{ entidades.error }}
    </div>

    <!-- ── la tarjeta del contenido ─────────────────────────────────── -->
    <section
      class="flex-1 min-h-0 bg-surface-raised border border-line rounded p-4 flex flex-col overflow-hidden"
      data-testid="entidades-contenido"
    >
      <!-- la tarjeta de N_MAX -->
      <div
        v-if="entidades.hayPreview && entidades.tarjetasNMax.length > 0"
        class="grid grid-cols-1 md:grid-cols-2 gap-2 mb-3"
        data-testid="entidades-nmax"
      >
        <div
          v-for="tarjeta in entidades.tarjetasNMax"
          :key="tarjeta.name"
          class="bg-surface-raised border border-line rounded p-3"
        >
          <div class="text-[10px] uppercase text-ink-muted">
            {{ entidades.etiquetaNMax[tarjeta.name] || tarjeta.name }}
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

      <!-- la tabla del diff -->
      <div
        class="flex-1 min-h-0 overflow-auto bg-surface-raised border border-line rounded mt-2"
      >
        <table v-if="entidades.hayPreview" class="w-full text-xs" data-testid="entidades-tabla">
          <thead class="sticky top-0 bg-surface-sunken text-[10px] uppercase">
            <tr>
              <th class="px-3 py-2 text-left text-ink-muted w-14">#</th>
              <th class="px-3 py-2 text-left text-ink-muted">Tag Actual (TIA)</th>
              <th class="px-3 py-2 text-left text-ink-muted">Comentario Actual (TIA)</th>
              <th class="px-3 py-2 text-left text-ink-muted">Tag Deseado (Excel)</th>
              <th class="px-3 py-2 text-left text-ink-muted">Comentario Deseado (Excel)</th>
              <th class="px-3 py-2 text-left text-ink-muted">Estado</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="fila in entidades.filas" :key="fila.plc_tag + '-' + fila.status">
              <td class="px-3 py-1.5 font-mono text-xs text-ink-muted">
                {{ fila.numero_excel ?? fila.numero_tia ?? "—" }}
              </td>
              <td
                class="px-3 py-1.5 font-mono text-xs"
                :class="fila.status === 'eliminar' ? 'text-red-700 line-through' : 'text-ink'"
              >
                {{ fila.status === "agregar" ? "—" : fila.plc_tag }}
              </td>
              <td
                class="px-3 py-1.5 text-xs"
                :class="fila.status === 'eliminar' ? 'text-red-700 line-through' : 'text-ink'"
              >
                {{ fila.comment_tia ?? "—" }}
              </td>
              <td
                class="px-3 py-1.5 font-mono text-xs"
                :class="
                  fila.status === 'agregar'
                    ? 'text-accent'
                    : fila.status === 'renombrar'
                      ? 'text-amber-800'
                      : 'text-ink-muted'
                "
              >
                {{ fila.status === "eliminar" ? "—" : fila.plc_tag }}
              </td>
              <td
                class="px-3 py-1.5 text-xs"
                :class="
                  fila.status === 'agregar'
                    ? 'text-accent'
                    : fila.status === 'renombrar'
                      ? 'text-amber-800'
                      : 'text-ink-muted'
                "
              >
                {{ fila.comment_excel ?? "—" }}
              </td>
              <td class="px-3 py-1.5 text-xs whitespace-nowrap" :class="estadoDe(fila).clase">
                {{ estadoDe(fila).label }}
              </td>
            </tr>
          </tbody>
        </table>

        <div
          v-else
          class="flex-1 flex items-center justify-center p-10 text-center text-ink-muted"
          data-testid="entidades-vacio"
        >
          <div>
            <div class="text-5xl mb-3 opacity-40" aria-hidden="true">🗂️</div>
            <p class="mb-2">Sin prevision generada.</p>
            <p class="text-xs">
              Pulsa <strong class="text-accent">"🔍 Generar Previsión"</strong> para ver el diff
              completo.
            </p>
          </div>
        </div>
      </div>

      <!-- el boton de aplicar -->
      <button
        type="button"
        data-testid="entidades-aplicar"
        class="mt-3 w-full py-3 font-semibold text-sm bg-accent text-ink-inverse rounded-md border border-line hover:bg-accent-hover transition-colors duration-200 disabled:opacity-50 disabled:cursor-not-allowed"
        :disabled="!puedeAplicar"
        @click="abrirDialogo"
      >
        {{ textoAplicar }}
      </button>

      <!-- el estado de las transacciones del ultimo sync -->
      <div
        v-if="entidades.transacciones.length > 0"
        class="mt-3 bg-surface-raised border border-line rounded p-3"
        data-testid="entidades-transacciones"
      >
        <div class="text-[10px] uppercase text-ink-muted mb-1">Transacciones</div>
        <ul class="text-xs">
          <li
            v-for="transaccion in entidades.transacciones"
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

    <!-- ── el dialogo de confirmacion ────────────────────────────────── -->
    <div
      v-if="dialogoAbierto"
      class="fixed inset-0 z-50 flex items-center justify-center bg-shell-deep/50 p-4"
      data-testid="entidades-confirmar-fondo"
      @click.self="cerrarDialogo"
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-label="Confirmar cambios en TIA Portal"
        data-testid="entidades-confirmar-dialogo"
        class="w-full max-w-md bg-surface-raised border border-line rounded-lg shadow-lg p-5"
      >
        <div
          class="font-mono text-xs text-ink bg-surface-sunken border border-line rounded p-3 mb-4 whitespace-pre-wrap"
          data-testid="entidades-confirmar-texto"
        >
          {{ textoConfirmacion }}
        </div>
        <div class="flex justify-end gap-2">
          <button
            type="button"
            data-testid="entidades-confirmar-no"
            class="px-3 py-1.5 text-xs font-semibold text-ink bg-surface-sunken hover:bg-line rounded-md border border-line transition-colors duration-200"
            @click="cerrarDialogo"
          >
            Cancelar
          </button>
          <button
            type="button"
            data-testid="entidades-confirmar-si"
            class="px-3 py-1.5 text-xs font-semibold text-ink-inverse bg-accent hover:bg-accent-hover rounded-md border border-line transition-colors duration-200"
            @click="confirmar"
          >
            Sí, aplicar
          </button>
        </div>
      </div>
    </div>
  </section>
</template>
