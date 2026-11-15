<script setup>
/**
 * CrearProceso: crear un proceso completo a partir de una plantilla TIA.
 *
 * La plantilla se elige de la carpeta de plantillas (listado plano, sin
 * trabajo). Con la plantilla elegida se genera la prevision (un trabajo:
 * 202 + job_id, el resultado por el stream) y, si esta deja crear, se
 * crea el proceso en TIA Portal tras la confirmacion. La vista no toca
 * TIA ni el backend mas que a traves del store de crear_proceso.
 */
import { computed, onMounted, ref } from "vue";
import { useCrearProcesoStore } from "../stores/crear_proceso.js";
import DialogoConfirmacion from "../../../nucleo/componentes/DialogoConfirmacion.vue";
import { usePlcStore } from "../../../nucleo/stores/plc.js";
import { useTiaStore } from "../../../nucleo/stores/tia.js";

const props = defineProps({
  /** La fila del Excel del proceso a crear (uid, codigo, ...), o `null`. */
  proceso: { type: Object, default: null },
});

const emit = defineEmits(["cerrar"]);

const crear = useCrearProcesoStore();
const plc = usePlcStore();
const tia = useTiaStore();

/** El nombre corto del proceso: `uid_codigo`, como en main. */
const procesoLabel = computed(
  () => (props.proceso ? `${props.proceso.uid}_${props.proceso.codigo}` : ""),
);

/** `true` si hay una preview para el PLC y el proceso actuales. */
const previewActual = computed(() =>
  props.proceso ? crear.previewVale(plc.seleccionado, props.proceso.uid) : false,
);

/** Los N_MAX del proceso que no cubren los minimos de la plantilla elegida. */
const minimosProblemas = computed(() =>
  crear.minimosProblemas(props.proceso),
);

/** `true` si todos los N_MAX del proceso cubren los minimos de la plantilla. */
const minimosCumplidos = computed(() => minimosProblemas.value.length === 0);

/**
 * La columna "PROCESO NUEVO" de la tabla comparativa, para marcarla en rojo
 * si no cumple.
 */
const problemaDe = (clave) => minimosProblemas.value.some((p) => p.clave === clave);

/** Las filas de la tabla DATO / PLANTILLA / PROCESO NUEVO. */
const filasNMax = computed(() => {
  const planta = crear.plantilla;
  const min = (planta && planta.minimos) || {};
  const p = props.proceso;
  return [
    { dato: "PREAL", plantilla: min.N_MAX_PREAL ?? "-", nuevo: p ? p.preal : "-", clave: "N_MAX_PREAL" },
    { dato: "PINT", plantilla: min.N_MAX_PINT ?? "-", nuevo: p ? p.pint : "-", clave: "N_MAX_PINT" },
    { dato: "ALM", plantilla: min.N_MAX_ALM ?? "-", nuevo: p ? p.alarmas : "-", clave: "N_MAX_ALM" },
    { dato: "ALM_HMI", plantilla: min.N_MAX_ALM_HMI ?? "-", nuevo: p ? p.alm_hmi : "-", clave: "N_MAX_ALM_HMI" },
    { dato: "UID", plantilla: planta ? planta.base : "-", nuevo: p ? p.uid : "-", clave: null },
    { dato: "CODIGO", plantilla: planta ? planta.codigo : "-", nuevo: p ? p.codigo : "-", clave: null },
  ];
});

/** `true` si se puede generar la prevision. */
const puedeGenerar = computed(
  () =>
    Boolean(crear.plantillaSeleccionada) &&
    Boolean(plc.seleccionado) &&
    tia.conectado &&
    minimosCumplidos.value &&
    !crear.generando &&
    !crear.aplicando,
);

/** `true` si se puede crear el proceso en TIA Portal. */
const puedeCrear = computed(
  () =>
    Boolean(props.proceso) &&
    crear.puedeCrearPara(plc.seleccionado, props.proceso.uid) &&
    tia.conectado &&
    !crear.aplicando,
);

/** El texto del boton de generar. */
const textoGenerar = computed(() =>
  crear.generando ? "Generando previsión…" : "🔍 Generar Previsión",
);

/** El texto del boton de aplicar. */
const textoAplicar = computed(() =>
  crear.aplicando ? "⏳ Creando…" : "✅ Crear en TIA Portal",
);

/** `true` mientras el dialogo de confirmacion esta abierto. */
const dialogoAbierto = ref(false);

/**
 * El texto de la confirmacion: el proceso, la plantilla, los bloques y las
 * dependencias de la prevision actual.
 */
const textoConfirmacion = computed(() => {
  const p = props.proceso;
  const planta = crear.plantilla;
  const nBloques = crear.bloquesPrevistos.length;
  const nDeps = (crear.preview && crear.preview.dependencias_ok &&
    crear.preview.dependencias_ok.length) || 0;
  return (
    `¿Crear el proceso ${p ? `${p.uid}_${p.codigo}` : ""} en TIA Portal?\n\n` +
    `Plantilla: ${planta ? planta.carpeta : ""}\n` +
    `Bloques a importar: ${nBloques} bloques previstos\n` +
    `Dependencias validadas: ${nDeps}\n` +
    `Se importan las tablas y los bloques en una sola transaccion y se compila.\n` +
    `Esta operacion modifica el PLC.`
  );
});

/** El estado de una fila, con su color. */
function estadoDeBloque(estado) {
  return estado === "OK" ? "text-green-600" : "text-red-600";
}

/** La clase del estado de una transaccion (igual que en Procesos). */
function claseDeTransaccion(estado) {
  if (estado === "confirmada") return "text-green-600";
  if (estado === "revertida") return "text-red-600";
  return "text-ink-muted";
}

/** Genera la prevision de crear el proceso. */
async function generar() {
  if (!props.proceso) return;
  await crear.generarPrevision(plc.seleccionado, props.proceso.uid);
}

/** Abre el dialogo de confirmacion. */
function abrirDialogo() {
  dialogoAbierto.value = true;
}

/** Cierra el dialogo sin crear nada. */
function cerrarDialogo() {
  dialogoAbierto.value = false;
}

/** Confirma: crea el proceso en TIA Portal. */
async function confirmar() {
  dialogoAbierto.value = false;
  if (!props.proceso) return;
  await crear.aplicar(plc.seleccionado, props.proceso.uid);
}

onMounted(() => {
  crear.hidratar();
  crear.cargarPlantillas();
});
</script>

<template>
  <section class="flex-1 min-h-0 flex flex-col gap-4" data-testid="crear">
    <!-- ── la cabecera ────────────────────────────────────────────── -->
    <header class="flex justify-between items-start">
      <div>
        <h2 class="text-lg font-bold text-ink">Crear proceso completo desde plantilla</h2>
        <p class="text-xs text-ink-muted mt-0.5">
          Proceso seleccionado:
          <span class="font-mono font-bold text-accent">{{ procesoLabel }}</span>
        </p>
      </div>
      <button
        type="button"
        class="bg-surface border border-line rounded px-3 py-1 text-xs text-ink hover:bg-surface-sunken"
        data-testid="crear-cerrar"
        @click="emit('cerrar')"
      >
        Cerrar
      </button>
    </header>

    <!-- ── la carpeta de plantillas ────────────────────────────────── -->
    <div class="flex items-center gap-2 flex-wrap" data-testid="crear-carpeta">
      <span v-if="crear.plantillasPath" class="text-xs text-ink-muted">
        Carpeta de plantillas:
        <span class="font-mono text-ink">{{ crear.plantillasPath }}</span>
      </span>
      <span
        v-else
        class="text-xs text-amber-700"
        data-testid="crear-carpeta-sin-configurar"
      >
        ⚠️ {{ crear.aviso || "Carpeta de plantillas sin configurar" }}
      </span>
      <button
        type="button"
        class="ml-auto bg-surface border border-line rounded px-3 py-1 text-xs text-ink hover:bg-surface-sunken disabled:opacity-50"
        :disabled="crear.cargandoPlantillas"
        data-testid="crear-recargar-plantillas"
        @click="crear.cargarPlantillas()"
      >
        {{ crear.cargandoPlantillas ? "Recargando…" : "Recargar plantillas" }}
      </button>
    </div>

    <!-- el aviso del listado (carpeta inexistente o caida) -->
    <div
      v-if="crear.aviso && crear.plantillasPath"
      class="bg-surface-raised border border-amber-300 rounded p-3 text-xs text-amber-800"
      data-testid="crear-aviso"
    >
      ⚠️ {{ crear.aviso }}
    </div>

    <!-- ── el selector de plantilla ────────────────────────────────── -->
    <div data-testid="crear-plantilla">
      <label class="block text-xs font-semibold text-ink-muted uppercase mb-2">Plantilla</label>
      <select
        class="w-full bg-surface-raised border border-line text-accent font-bold text-sm rounded px-3 py-1.5 font-mono disabled:opacity-50 cursor-pointer"
        :disabled="!crear.plantillas.length || crear.cargandoPlantillas"
        :value="crear.plantillaSeleccionada"
        data-testid="crear-plantilla-select"
        @change="crear.seleccionarPlantilla($event.target.value)"
      >
        <option value="" disabled data-testid="crear-plantilla-placeholder">
          {{
            crear.cargandoPlantillas
              ? "Cargando…"
              : crear.plantillas.length
                ? "Selecciona…"
                : "Sin plantillas"
          }}
        </option>
        <option
          v-for="p in crear.plantillas"
          :key="p.carpeta"
          :value="p.carpeta"
          data-testid="crear-plantilla-opcion"
        >
          {{ p.carpeta }} — {{ p.codigo }} {{ p.nombre }}
        </option>
      </select>
      <p
        v-if="crear.plantilla && crear.plantilla.descripcion"
        class="mt-1 text-xs text-ink-muted italic"
        data-testid="crear-plantilla-descripcion"
      >
        {{ crear.plantilla.descripcion }}
      </p>
    </div>

    <!-- ── la tabla comparativa DATO / PLANTILLA / PROCESO NUEVO ───── -->
    <div
      class="flex-1 overflow-auto bg-surface-raised border border-line rounded"
      data-testid="crear-tabla-nmax"
    >
      <table class="w-full text-xs">
        <thead class="sticky top-0 bg-surface-sunken text-[10px] uppercase">
          <tr>
            <th class="px-3 py-2 text-left text-ink-muted">DATO</th>
            <th class="px-3 py-2 text-left text-ink-muted">PLANTILLA</th>
            <th class="px-3 py-2 text-left text-ink-muted">PROCESO NUEVO</th>
          </tr>
        </thead>
        <tbody>
          <tr
            v-for="fila in filasNMax"
            :key="fila.dato"
            class="border-b border-line"
            :class="fila.clave && problemaDe(fila.clave) ? 'bg-red-50' : ''"
          >
            <td class="px-3 py-1.5 align-top text-ink font-semibold">{{ fila.dato }}</td>
            <td class="px-3 py-1.5 align-top text-ink font-mono">{{ fila.plantilla }}</td>
            <td
              class="px-3 py-1.5 align-top text-ink font-mono"
              :class="fila.clave && problemaDe(fila.clave) ? 'text-red-700 font-bold' : ''"
            >
              {{ fila.nuevo }}
            </td>
          </tr>
        </tbody>
      </table>
    </div>

    <!-- el aviso de minimos incumplidos -->
    <div
      v-if="!minimosCumplidos"
      class="bg-surface-raised border border-red-600 rounded p-3 text-xs text-red-600"
      data-testid="crear-minimos-aviso"
    >
      ⚠️ Los N_MAX del operario no cubren los minimos de la plantilla
    </div>

    <!-- ── el boton de generar la prevision ────────────────────────── -->
    <button
      type="button"
      class="px-3 py-1.5 text-accent font-semibold text-xs bg-surface-sunken hover:bg-accent-subtle rounded-md transition-colors duration-200 border border-line flex items-center gap-1.5 disabled:opacity-50 disabled:cursor-not-allowed"
      :disabled="!puedeGenerar"
      data-testid="crear-generar"
      @click="generar"
    >
      {{ textoGenerar }}
    </button>

    <!-- ── el error del store ──────────────────────────────────────── -->
    <div
      v-if="crear.error"
      class="bg-surface-raised border border-red-600 rounded p-3 text-xs text-red-600"
      data-testid="crear-error"
    >
      ✗ {{ crear.error }}
    </div>

    <!-- ── la preview, solo si vale para el PLC/proceso/plantilla ──── -->
    <div v-if="previewActual" class="flex flex-col gap-3" data-testid="crear-preview">
      <!-- el aviso de bloques ausentes y warnings -->
      <div
        v-if="
          (crear.preview && crear.preview.missing_blocks && crear.preview.missing_blocks.length) ||
          (crear.preview && crear.preview.warnings && crear.preview.warnings.length)
        "
        class="bg-surface-raised border border-amber-300 rounded p-3 text-xs text-amber-800"
        data-testid="crear-preview-aviso"
      >
        <p v-for="linea in [
          ...(crear.preview ? crear.preview.missing_blocks || [] : []),
          ...(crear.preview ? crear.preview.warnings || [] : []),
        ]" :key="linea">
          ⚠️ {{ linea }}
        </p>
      </div>

      <!-- el banner de colisiones -->
      <div
        v-if="crear.colisiones.length"
        class="bg-surface-raised border border-red-600 rounded p-3 text-xs text-red-700"
        data-testid="crear-colisiones"
      >
        <p class="font-semibold mb-1">
          ⚠️ {{ crear.colisiones.length }} colision(es) detectada(s) con bloques ya existentes en el PLC.
        </p>
        <ul class="list-disc list-inside font-mono mb-1">
          <li v-for="c in crear.colisiones" :key="c">
            {{ c }}
            <span v-if="crear.preview && crear.preview.colisiones_con && crear.preview.colisiones_con[c]">
              ({{ crear.preview.colisiones_con[c] }})
            </span>
          </li>
        </ul>
        <p class="text-red-600">
          Cambia el proceso o plantilla para evitar pisar bloques existentes.
        </p>
      </div>

      <!-- la tabla de bloques previstos -->
      <div data-testid="crear-bloques">
        <h3 class="text-sm font-semibold text-ink mb-2">
          Bloques a generar ({{ crear.bloquesPrevistos.length }})
        </h3>
        <div class="flex-1 overflow-auto bg-surface-raised border border-line rounded">
          <table class="w-full text-xs">
            <thead class="sticky top-0 bg-surface-sunken text-[10px] uppercase">
              <tr>
                <th class="px-3 py-2 text-left text-ink-muted">BLOQUE ORIGINAL</th>
                <th class="px-3 py-2 text-left text-ink-muted">BLOQUE NUEVO</th>
                <th class="px-3 py-2 text-left text-ink-muted">ESTADO</th>
              </tr>
            </thead>
            <tbody>
              <tr
                v-for="fila in crear.bloquesPrevistos"
                :key="fila.nombre_original + '|' + fila.nombre_nuevo"
                class="border-b border-line"
              >
                <td class="px-3 py-1.5 align-top font-mono text-ink whitespace-nowrap">
                  {{ fila.nombre_original }}
                </td>
                <td class="px-3 py-1.5 align-top font-mono text-ink whitespace-nowrap">
                  {{ fila.nombre_nuevo }}
                </td>
                <td
                  class="px-3 py-1.5 align-top font-mono font-bold whitespace-nowrap"
                  :class="estadoDeBloque(fila.estado)"
                >
                  {{ fila.estado }}
                </td>
              </tr>
              <tr v-if="crear.bloquesPrevistos.length === 0">
                <td colspan="3" class="px-3 py-6 text-center text-ink-muted italic">
                  (no hay bloques previstos)
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>

      <!-- la tabla de dependencias -->
      <div data-testid="crear-dependencias">
        <h3 class="text-sm font-semibold text-ink mb-2">
          Dependencias ({{
            ((crear.preview && crear.preview.dependencias_ok &&
              crear.preview.dependencias_ok.length) || 0) +
              crear.dependenciasFaltantes.length
          }})
        </h3>
        <div class="flex-1 overflow-auto bg-surface-raised border border-line rounded">
          <table class="w-full text-xs">
            <thead class="sticky top-0 bg-surface-sunken text-[10px] uppercase">
              <tr>
                <th class="px-3 py-2 text-left text-ink-muted">DEPENDENCIA PLC</th>
                <th class="px-3 py-2 text-left text-ink-muted">ESTADO</th>
              </tr>
            </thead>
            <tbody>
              <tr
                v-for="dep in [
                  ...(crear.preview ? crear.preview.dependencias_ok || [] : []).map((d) => ({ dep: d, falta: false })),
                  ...(crear.dependenciasFaltantes || []).map((d) => ({ dep: d, falta: true })),
                ]"
                :key="dep.dep"
                class="border-b border-line"
              >
                <td class="px-3 py-1.5 align-top font-mono text-ink whitespace-nowrap">{{ dep.dep }}</td>
                <td
                  class="px-3 py-1.5 align-top font-mono font-bold whitespace-nowrap"
                  :class="dep.falta ? 'text-red-700' : 'text-green-700'"
                >
                  {{ dep.falta ? "FALTA" : "OK" }}
                </td>
              </tr>
              <tr v-if="!crear.preview || ((crear.preview.dependencias_ok || []).length + (crear.dependenciasFaltantes || []).length === 0)">
                <td colspan="2" class="px-3 py-4 text-center text-ink-muted italic">
                  (la plantilla no declara dependencias externas)
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
    </div>

    <!-- la preview no vale para el PLC/proceso/plantilla actuales -->
    <div
      v-if="crear.hayPreview && !previewActual"
      class="bg-surface-raised border border-line rounded p-3 text-xs text-ink-muted"
      data-testid="crear-preview-invalida"
    >
      La previsión es de otro proceso, PLC o plantilla: genera una nueva.
    </div>

    <!-- ── el boton de crear en TIA Portal ─────────────────────────── -->
    <button
      type="button"
      class="w-full py-3 font-semibold text-sm bg-accent text-ink-inverse rounded-md border border-line hover:bg-accent-hover transition-colors duration-200 disabled:opacity-50 disabled:cursor-not-allowed"
      :disabled="!puedeCrear"
      data-testid="crear-aplicar"
      @click="abrirDialogo"
    >
      {{ textoAplicar }}
    </button>

    <!-- ── el resultado del aplicar ────────────────────────────────── -->
    <div
      v-if="crear.resultadoAplicar"
      class="bg-surface-raised border border-green-600 rounded p-3 text-xs text-green-700"
      data-testid="crear-resultado"
    >
      <p class="text-sm font-semibold flex items-center gap-2">
        <span>✅</span>
        <span>Proceso {{ crear.resultadoAplicar.process_label }} creado</span>
      </p>
      <p class="mt-1">
        {{ (crear.resultadoAplicar.archivos_generados || []).length }} archivos generados
      </p>

      <!-- el estado de cada transaccion -->
      <div
        v-if="crear.transacciones.length > 0"
        class="mt-3 bg-surface-raised border border-line rounded p-3"
        data-testid="crear-transacciones"
      >
        <div class="text-[10px] uppercase text-ink-muted mb-1">Transacciones</div>
        <ul class="text-xs">
          <li
            v-for="transaccion in crear.transacciones"
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

      <!-- el resultado de la compilacion -->
      <p
        v-if="crear.resultadoAplicar.compilacion"
        class="mt-2"
        :class="crear.resultadoAplicar.compilacion.ok ? 'text-green-700' : 'text-amber-700'"
        data-testid="crear-compilacion"
      >
        {{
          crear.resultadoAplicar.compilacion.ok
            ? `Compilación: ${crear.resultadoAplicar.compilacion.detalle || "OK"}`
            : `⚠️ Compilación: ${crear.resultadoAplicar.compilacion.error || "con errores"}`
        }}
      </p>

      <!-- el escaneo no se pudo refrescar -->
      <p
        v-if="crear.resultadoAplicar.escaneo_actualizado === false"
        class="mt-2 text-amber-700"
        data-testid="crear-escaneo-aviso"
      >
        ⚠️ No se pudo refrescar el escaneo: vuelve a escanear el PLC.
      </p>
    </div>

    <!-- ── la nota de version ──────────────────────────────────────── -->
    <p class="text-[10px] text-ink-muted" data-testid="crear-nota-version">
      Crear un proceso necesita TIA Portal V21 o superior.
    </p>

    <!-- ── el dialogo de confirmacion ──────────────────────────────── -->
    <DialogoConfirmacion
      :abierto="dialogoAbierto"
      :texto="textoConfirmacion"
      prefijo="crear-proceso"
      @confirmar="confirmar"
      @cancelar="cerrarDialogo"
    />
  </section>
</template>
