<script setup>
/**
 * Dispositivos: la prevision de los dispositivos del PLC frente al Excel.
 *
 * Es una vista de solo lectura: la prevision la calcula el backend (exporta
 * del PLC y compara con el Excel). El boton de aplicar todavia no hace nada:
 * es la fase 4.3.
 */
import { computed, onMounted, ref, watch } from "vue";
import { DISP_STATUS, useDispositivosStore } from "../stores/dispositivos.js";
import { useExcelStore } from "../stores/excel.js";
import { usePlcStore } from "../../../nucleo/stores/plc.js";
import { useTiaStore } from "../../../nucleo/stores/tia.js";

const dispositivos = useDispositivosStore();
const excel = useExcelStore();
const plc = usePlcStore();
const tia = useTiaStore();

/** El tipo de dispositivo cuyo diff se muestra. */
const tipoActivo = ref("");

/** `true` si se puede generar la prevision. */
const puedeGenerar = computed(
  () => tia.conectado && excel.cargado && Boolean(plc.seleccionado) && !dispositivos.generando,
);

/** Las filas del diff del tipo activo, ordenadas por numero. */
const filas = computed(() => {
  const todas = (dispositivos.vigente && dispositivos.vigente.todos) || [];
  return todas
    .filter((fila) => fila.type === tipoActivo.value)
    .sort((a, b) => {
      const an = typeof a.numero === "number" ? a.numero : 0;
      const bn = typeof b.numero === "number" ? b.numero : 0;
      return an - bn;
    });
});

/** El estado de una fila, con su texto y su color. */
function estadoDe(fila) {
  return DISP_STATUS[fila.status] || { label: fila.status, clase: "text-ink-muted" };
}

/** El texto del boton de generar. */
const textoGenerar = computed(() => {
  if (dispositivos.generando) return "Generando prevision…";
  return "🔍 Generar Previsión";
});

/** Genera la prevision. */
async function generar() {
  await dispositivos.generar(plc.seleccionado);
}

// Al llegar el catalogo, se ensena la primera pestaña.
watch(
  () => dispositivos.pestanas,
  (pestanas) => {
    if (!pestanas.length) {
      tipoActivo.value = "";
      return;
    }
    if (!pestanas.some((pestana) => pestana.hw_type === tipoActivo.value)) {
      tipoActivo.value = pestanas[0].hw_type;
    }
  },
  { immediate: true },
);

onMounted(() => {
  excel.hidratar();
  dispositivos.hidratar();
  dispositivos.cargarCatalogo();
});
</script>

<template>
  <section class="flex-1 min-h-0 flex flex-col gap-4" data-testid="dispositivos">
    <!-- ── la tarjeta de arriba: resumen y boton ────────────────────── -->
    <section class="bg-surface-raised border border-line rounded p-4 flex justify-between items-center">
      <p v-if="dispositivos.hayPreview" class="text-xs text-ink-muted" data-testid="dispositivos-resumen">
        {{ dispositivos.resumen.total }} dispositivos analizados —
        <span class="text-accent">{{ dispositivos.resumen.agregados }} a agregar</span> ·
        <span class="text-amber-700">{{ dispositivos.resumen.renombrados }} a renombrar</span> ·
        <span class="text-red-700">{{ dispositivos.resumen.eliminados }} a eliminar</span> ·
        <span class="text-ink-muted">{{ dispositivos.resumen.sin_cambios }} sin cambios</span>
      </p>
      <span v-else></span>
      <button
        type="button"
        data-testid="dispositivos-generar"
        class="px-3 py-1.5 text-accent font-semibold text-xs bg-surface-sunken hover:bg-accent-subtle rounded-md transition-colors duration-200 border border-line flex items-center gap-1.5 disabled:opacity-50 disabled:cursor-not-allowed"
        :disabled="!puedeGenerar"
        @click="generar"
      >
        {{ textoGenerar }}
      </button>
    </section>

    <!-- ── el error ─────────────────────────────────────────────────── -->
    <div
      v-if="dispositivos.error"
      class="bg-surface-raised border border-red-600 rounded p-3 text-xs text-red-600"
      data-testid="dispositivos-error"
    >
      ✗ {{ dispositivos.error }}
    </div>

    <!-- ── la tarjeta del contenido ─────────────────────────────────── -->
    <section
      class="flex-1 min-h-0 bg-surface-raised border border-line rounded p-4 flex flex-col overflow-hidden"
      data-testid="dispositivos-contenido"
    >
      <!-- las tarjetas de N_MAX -->
      <div
        v-if="dispositivos.hayPreview && dispositivos.tarjetasNMax.length > 0"
        class="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-2 mb-3"
        data-testid="dispositivos-nmax"
      >
        <div
          v-for="tarjeta in dispositivos.tarjetasNMax"
          :key="tarjeta.name"
          class="bg-surface-raised border border-line rounded p-3"
        >
          <div class="text-[10px] uppercase text-ink-muted">
            {{ dispositivos.etiquetaNMax[tarjeta.name] || tarjeta.name }}
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

      <!-- las pestañas por tipo -->
      <div
        v-if="dispositivos.hayPreview"
        class="flex border-b border-line bg-surface-sunken overflow-x-auto mb-3"
        data-testid="dispositivos-pestanas"
      >
        <button
          v-for="pestana in dispositivos.pestanas"
          :key="pestana.hw_type"
          type="button"
          :data-testid="'dispositivos-tipo-' + pestana.hw_type"
          class="px-4 py-2 text-xs font-medium border-r border-line whitespace-nowrap"
          :class="
            pestana.hw_type === tipoActivo
              ? 'bg-surface-raised text-ink'
              : 'bg-surface-sunken text-ink-muted hover:bg-surface-sunken'
          "
          @click="tipoActivo = pestana.hw_type"
        >
          {{ pestana.label }}
          <span class="ml-1 text-[10px] opacity-70">
            ({{ dispositivos.contadorPorTipo[pestana.hw_type] || 0 }})
          </span>
        </button>
      </div>

      <!-- la tabla del diff -->
      <div
        class="flex-1 min-h-0 overflow-auto bg-surface-raised border border-line rounded mt-2"
      >
        <table v-if="dispositivos.hayPreview" class="w-full text-xs" data-testid="dispositivos-tabla">
          <thead class="sticky top-0 bg-surface-sunken text-[10px] uppercase">
            <tr>
              <th class="px-3 py-2 text-left text-ink-muted w-14">#</th>
              <th class="px-3 py-2 text-left text-ink-muted">Actual (TIA)</th>
              <th class="px-3 py-2 text-left text-ink-muted">Deseado (Excel)</th>
              <th class="px-3 py-2 text-left text-ink-muted">Estado</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="fila in filas" :key="fila.type + '-' + fila.uid" class="border-b border-line">
              <td class="px-3 py-1.5 font-mono text-xs text-ink-muted">{{ fila.numero }}</td>
              <td
                class="px-3 py-1.5 font-mono text-xs"
                :class="fila.status === 'eliminar' ? 'text-red-700 line-through' : 'text-ink'"
              >
                {{ fila.actual || "—" }}
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
                {{ fila.nuevo || "—" }}
              </td>
              <td class="px-3 py-1.5 text-xs whitespace-nowrap" :class="estadoDe(fila).clase">
                {{ estadoDe(fila).label }}
              </td>
            </tr>
            <tr v-if="filas.length === 0">
              <td colspan="4" class="px-3 py-6 text-center text-ink-muted italic">
                ⚠️ Sin dispositivos para "{{ tipoActivo }}".
              </td>
            </tr>
          </tbody>
        </table>

        <div
          v-else
          class="flex-1 flex items-center justify-center p-10 text-center text-ink-muted"
          data-testid="dispositivos-vacio"
        >
          <div>
            <div class="text-5xl mb-3 opacity-40" aria-hidden="true">⚡</div>
            <p class="mb-2">Sin prevision generada.</p>
            <p class="text-xs">
              Pulsa <strong class="text-accent">"🔍 Generar Previsión"</strong> para ver el diff
              completo.
            </p>
          </div>
        </div>
      </div>

      <!-- el boton de aplicar: todavia no hace nada -->
      <button
        type="button"
        disabled
        data-testid="dispositivos-aplicar"
        class="mt-3 w-full py-3 font-semibold text-sm bg-surface-sunken rounded-md border border-line text-ink-muted cursor-not-allowed"
      >
        Pendiente (fase 4.3)
      </button>
    </section>
  </section>
</template>
