<script setup>
/**
 * Procesos: selector de proceso y las dos acciones sobre el.
 *
 * La vista tiene tres tarjetas, como en main:
 *
 * 1. El selector de proceso (los procesos del PLC en el Excel).
 * 2. "¿Qué quieres hacer?": "Crear proceso completo" o "Actualizar
 *    comentarios de DB".
 * 3. La vista activa, montada inline: comentarios o crear, nunca las dos.
 *
 * El modo activo es estado local: no se guarda en el store ni en la sesion,
 * y no cambia al cambiar de proceso.
 */
import { computed, onMounted, ref } from "vue";
import { useProcesosStore } from "../stores/procesos.js";
import ComentariosProceso from "./ComentariosProceso.vue";
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

/** Cierra el modo de comentarios (lo emite ComentariosProceso con su boton Cerrar). */
function cerrarComentarios() {
  modo.value = "";
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

    <!-- ── la tarjeta del selector ──────────────────────────────────── -->
    <section class="bg-surface-raised border border-line rounded p-4">
      <label class="block text-xs font-semibold text-ink-muted uppercase mb-2">Proceso</label>
      <select
        data-testid="procesos-select"
        class="w-full bg-white border border-line text-accent font-bold text-sm rounded focus:border-accent-bright focus:outline-none px-3 py-1.5 font-mono disabled:opacity-50 cursor-pointer"
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
    </section>

    <!-- ── la tarjeta de "¿qué quieres hacer?" ──────────────────────── -->
    <section class="bg-surface-raised border border-line rounded p-4">
      <h3 class="text-sm font-semibold text-ink mb-3">¿Qué quieres hacer?</h3>
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

    <!-- ── la tarjeta de la vista activa (una sola a la vez) ────────── -->
    <section
      v-if="modo === 'comentarios'"
      class="flex-1 min-h-0 bg-surface-raised border border-line rounded p-4 flex flex-col overflow-y-auto"
      data-testid="procesos-contenido"
    >
      <ComentariosProceso
        :proceso="procesoElegido"
        :uid="procesos.procUid"
        @cerrar="cerrarComentarios"
      />
    </section>

    <section
      v-else-if="modo === 'crear'"
      class="flex-1 min-h-0 bg-surface-raised border border-line rounded p-4 flex flex-col overflow-y-auto"
      data-testid="procesos-contenido"
    >
      <CrearProceso :proceso="procesoElegido" @cerrar="cerrarCrear" />
    </section>
  </section>
</template>
