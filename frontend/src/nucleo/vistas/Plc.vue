<script setup>
/**
 * Vista PLC: el estado de TIA, los PLCs disponibles y el contenido del PLC
 * seleccionado (bloques, variables y tipos de usuario).
 *
 * La conexion se hace aqui, no en la barra superior. Todas las operaciones
 * contra TIA son trabajos: el backend responde 202 y el resultado llega por
 * el stream de eventos.
 */
import { computed, onMounted, ref } from "vue";
import { usePlcStore } from "../stores/plc.js";
import { useTiaStore } from "../stores/tia.js";

const plc = usePlcStore();
const tia = useTiaStore();

/** Pestaña activa: bloques, variables o udt. */
const pestana = ref("bloques");

/** El estado de TIA, para la lista de "Estado del sistema". */
const estadoTia = computed(() => (tia.conectado ? "connected" : "idle"));

/** El color del estado de TIA. */
const claseTia = computed(() =>
  tia.conectado ? "text-green-600 font-semibold" : "text-ink-muted font-semibold",
);

/** `true` si se puede conectar. */
const puedeConectar = computed(() => !tia.conectado && !tia.ocupado);

/** `true` si se puede desconectar. */
const puedeDesconectar = computed(() => tia.conectado && !tia.ocupado);

/** Los bloques agrupados por tipo, como en la version anterior. */
const TIPOS = ["OB", "DB", "FB", "FC", "UDT", "OTHER"];

const bloquesAgrupados = computed(() => {
  const grupos = new Map();
  for (const bloque of plc.bloques) {
    const tipo = String(bloque.tipo || "OTHER").toUpperCase();
    if (!grupos.has(tipo)) grupos.set(tipo, []);
    grupos.get(tipo).push(bloque);
  }
  for (const lista of grupos.values()) {
    lista.sort((a, b) => String(a.nombre).localeCompare(String(b.nombre), undefined, {
      sensitivity: "base",
      numeric: true,
    }));
  }
  const salida = [];
  for (const tipo of TIPOS) {
    const lista = grupos.get(tipo);
    if (lista && lista.length) salida.push({ tipo, bloques: lista });
  }
  for (const [tipo, lista] of grupos) {
    if (TIPOS.includes(tipo)) continue;
    if (lista.length) salida.push({ tipo, bloques: lista });
  }
  return salida;
});

/** Las filas de la pestaña activa. */
const filas = computed(() => {
  if (pestana.value === "variables") return plc.tablas;
  if (pestana.value === "udt") return plc.tipos;
  return [];
});

/** El numero de una celda. Vacio cuando el bloque no tiene numero. */
function numero(valor) {
  if (valor === null || valor === undefined || valor === "") return "—";
  return String(valor);
}

/** El texto de una celda. */
function texto(valor) {
  if (valor === null || valor === undefined || valor === "") return "—";
  return String(valor);
}

/** Escanea el PLC seleccionado. */
function actualizar() {
  plc.escanear();
}

onMounted(() => {
  if (tia.conectado && plc.plcs.length === 0) {
    plc.buscarPlcs();
  }
});
</script>

<template>
  <section class="flex-1 flex flex-col overflow-hidden" data-testid="vista-plc">
    <div
      class="mb-4 bg-surface-raised border border-line rounded p-4 space-y-5"
      data-testid="plc-card-info"
    >
      <div class="grid grid-cols-1 md:grid-cols-2 gap-x-6 gap-y-3">
        <div>
          <h4 class="text-[10px] font-bold text-ink-muted uppercase tracking-widest mb-2">
            Estado del sistema
          </h4>
          <ul class="space-y-1 text-xs">
            <li class="flex items-center gap-2">
              <span class="text-green-600">●</span>
              <span class="text-ink-muted">Worker:</span>
              <span class="text-green-600 font-semibold">activo</span>
            </li>
            <li class="flex items-center gap-2">
              <span :class="claseTia">●</span>
              <span class="text-ink-muted">TIA:</span>
              <span :class="claseTia">{{ estadoTia }}</span>
            </li>
            <li v-if="plc.proyecto && plc.proyecto.nombre" class="flex items-center gap-2">
              <span class="text-ink-muted">●</span>
              <span class="text-ink-muted">Proyecto:</span>
              <span class="font-mono text-ink">{{ plc.proyecto.nombre }}</span>
            </li>
            <li v-if="plc.proyecto && plc.proyecto.ruta" class="flex items-center gap-2">
              <span class="text-ink-muted">●</span>
              <span class="text-ink-muted">Ruta:</span>
              <span class="font-mono text-ink-muted break-all" data-testid="plc-ruta">
                {{ plc.proyecto.ruta }}
              </span>
            </li>
          </ul>
        </div>

        <div>
          <h4 class="text-[10px] font-bold text-ink-muted uppercase tracking-widest mb-2">
            Controles
          </h4>
          <div class="grid grid-cols-2 gap-2">
            <button
              type="button"
              :disabled="!puedeConectar"
              data-testid="plc-conectar"
              class="px-3 py-1.5 text-accent font-semibold text-xs bg-surface-sunken hover:bg-accent-subtle rounded-md transition-colors duration-200 border border-line flex items-center justify-center gap-1.5 disabled:opacity-50 disabled:cursor-not-allowed focus:outline-none focus:ring-2 focus:ring-accent focus:ring-offset-2 focus:ring-offset-surface"
              @click="tia.conectar()"
            >
              <span>🔌</span>
              Conectar
            </button>
            <button
              type="button"
              :disabled="!puedeDesconectar"
              data-testid="plc-desconectar"
              class="px-3 py-1.5 text-accent font-semibold text-xs bg-surface-sunken hover:bg-accent-subtle rounded-md transition-colors duration-200 border border-line flex items-center justify-center gap-1.5 disabled:opacity-50 disabled:cursor-not-allowed focus:outline-none focus:ring-2 focus:ring-accent focus:ring-offset-2 focus:ring-offset-surface"
              @click="tia.desconectar()"
            >
              <span>⏏</span>
              Desconectar
            </button>
          </div>
          <p
            v-if="tia.ultimo_error"
            class="mt-2 text-xs text-red-600 font-semibold"
            data-testid="plc-error"
          >
            {{ tia.ultimo_error }}
          </p>
        </div>
      </div>

      <div class="my-4 border-t border-line"></div>

      <div>
        <div class="flex justify-between items-center mb-2">
          <h4 class="text-[10px] font-bold text-ink-muted uppercase tracking-widest">
            PLC disponibles
          </h4>
          <button
            type="button"
            :disabled="!plc.seleccionado || plc.ocupado"
            data-testid="plc-actualizar"
            class="px-3 py-1.5 text-accent font-semibold text-xs bg-surface-sunken hover:bg-accent-subtle rounded-md transition-colors duration-200 border border-line flex items-center gap-1.5 disabled:opacity-50 disabled:cursor-not-allowed focus:outline-none focus:ring-2 focus:ring-accent focus:ring-offset-2 focus:ring-offset-surface"
            @click="actualizar"
          >
            <span :class="plc.ocupado ? 'animate-spin' : ''">↻</span>
            Actualizar
          </button>
        </div>

        <div
          v-if="plc.plcs.length > 0"
          class="flex flex-col gap-3"
          data-testid="plc-lista"
        >
          <button
            v-for="disponible in plc.plcs"
            :key="disponible.nombre"
            type="button"
            :data-testid="'plc-card-' + disponible.nombre"
            :data-active="disponible.nombre === plc.seleccionado"
            :class="[
              'w-full flex items-center justify-between gap-4 p-4 rounded-xl border shadow-sm transition-all duration-200 group text-left',
              disponible.nombre === plc.seleccionado
                ? 'border-green-500 bg-green-50 ring-1 ring-green-500'
                : 'border-line bg-surface-sunken hover:border-accent hover:bg-accent-subtle',
            ]"
            @click="plc.seleccionar(disponible.nombre)"
          >
            <div class="flex items-center gap-4 min-w-0 flex-1">
              <div
                :class="[
                  'w-10 h-10 rounded-xl flex items-center justify-center text-lg shrink-0 transition-colors',
                  disponible.nombre === plc.seleccionado
                    ? 'bg-green-500 text-white'
                    : 'bg-surface-raised text-ink-muted group-hover:bg-accent-subtle group-hover:text-accent',
                ]"
              >
                <span aria-hidden="true">&#128187;</span>
              </div>
              <div class="text-left min-w-0 flex-1">
                <h4
                  :class="[
                    'font-mono font-bold text-sm leading-none mb-1 truncate',
                    disponible.nombre === plc.seleccionado ? 'text-green-800' : 'text-ink',
                  ]"
                >
                  {{ disponible.nombre }}
                </h4>
                <p class="text-xs text-ink-muted truncate">
                  {{ disponible.designacion || "modelo no disponible" }}
                </p>
              </div>
            </div>
            <div
              :class="[
                'px-5 py-2 rounded-full text-xs font-bold border shrink-0 transition-colors',
                disponible.nombre === plc.seleccionado
                  ? 'bg-surface-raised border-green-300 text-green-700'
                  : 'bg-surface-sunken border-line text-ink-muted group-hover:border-accent group-hover:text-accent group-hover:bg-accent-subtle',
              ]"
            >
              {{ disponible.nombre === plc.seleccionado ? "Seleccionado" : "Seleccionar" }}
            </div>
          </button>
        </div>

        <div
          v-else
          class="flex items-center justify-center p-6 text-center text-ink-muted text-xs italic border border-dashed border-line rounded"
          data-testid="plc-lista-vacia"
        >
          No se han encontrado PLCs disponibles.
        </div>
      </div>
    </div>

    <div
      class="flex-1 bg-surface-raised border border-line rounded p-4 mb-4 flex flex-col overflow-hidden"
      data-testid="plc-card-tabla"
    >
      <div v-if="plc.escaneado" class="flex border-b border-line bg-surface-sunken overflow-x-auto mb-3">
        <button
          type="button"
          :class="[
            'tab-btn px-4 py-2 text-xs font-medium border-r border-line whitespace-nowrap',
            pestana === 'bloques'
              ? 'active bg-surface-raised text-ink font-semibold'
              : 'bg-surface-raised text-ink-muted hover:bg-surface-sunken',
          ]"
          @click="pestana = 'bloques'"
        >
          Bloques
          <span class="ml-1 text-[10px] opacity-70">({{ plc.bloques.length }})</span>
        </button>
        <button
          type="button"
          :class="[
            'tab-btn px-4 py-2 text-xs font-medium border-r border-line whitespace-nowrap',
            pestana === 'variables'
              ? 'active bg-surface-raised text-ink font-semibold'
              : 'bg-surface-raised text-ink-muted hover:bg-surface-sunken',
          ]"
          @click="pestana = 'variables'"
        >
          Variables
          <span class="ml-1 text-[10px] opacity-70">({{ plc.tablas.length }})</span>
        </button>
        <button
          type="button"
          :class="[
            'tab-btn px-4 py-2 text-xs font-medium border-r border-line whitespace-nowrap',
            pestana === 'udt'
              ? 'active bg-surface-raised text-ink font-semibold'
              : 'bg-surface-raised text-ink-muted hover:bg-surface-sunken',
          ]"
          @click="pestana = 'udt'"
        >
          UDT
          <span class="ml-1 text-[10px] opacity-70">({{ plc.tipos.length }})</span>
        </button>
      </div>

      <div class="flex-1 overflow-auto mt-2 bg-surface-raised border border-line rounded">
        <table v-if="pestana === 'bloques' && plc.escaneado" class="w-full text-xs">
          <thead class="sticky top-0 bg-surface-sunken text-[10px] uppercase">
            <tr>
              <th class="px-3 py-2 text-left text-ink-muted">Nombre</th>
              <th class="px-3 py-2 text-left text-ink-muted">Tipo</th>
              <th class="px-3 py-2 text-left text-ink-muted">Número</th>
              <th class="px-3 py-2 text-left text-ink-muted">Ruta</th>
            </tr>
          </thead>
          <tbody>
            <template v-for="grupo in bloquesAgrupados" :key="grupo.tipo">
              <tr class="bg-surface-sunken border-y border-line">
                <td
                  colspan="4"
                  class="px-3 py-1 text-[11px] font-semibold text-ink-muted uppercase tracking-wide"
                >
                  <span class="inline-block min-w-[3rem] font-mono">{{ grupo.tipo }}</span>
                  <span class="ml-2 text-ink-muted normal-case font-normal">
                    {{ grupo.bloques.length }}
                    {{ grupo.bloques.length === 1 ? "bloque" : "bloques" }}
                  </span>
                </td>
              </tr>
              <tr
                v-for="bloque in grupo.bloques"
                :key="bloque.ruta + '/' + bloque.nombre"
                class="border-b border-line"
              >
                <td class="px-3 py-1.5 font-mono text-ink whitespace-nowrap pl-6">
                  {{ bloque.nombre }}
                </td>
                <td class="px-3 py-1.5 text-ink-muted whitespace-nowrap font-mono">
                  {{ bloque.tipo }}
                </td>
                <td class="px-3 py-1.5 font-mono text-ink whitespace-nowrap">
                  {{ numero(bloque.numero) }}
                </td>
                <td class="px-3 py-1.5 font-mono text-ink-muted">{{ texto(bloque.ruta) }}</td>
              </tr>
            </template>
            <tr v-if="bloquesAgrupados.length === 0">
              <td colspan="4" class="px-3 py-6 text-center text-ink-muted italic">
                ⚠️ No hay bloques escaneados. Pulsa "↻ Actualizar" para escanear el PLC.
              </td>
            </tr>
          </tbody>
        </table>

        <table v-else-if="pestana === 'variables' && plc.escaneado" class="w-full text-xs">
          <thead class="sticky top-0 bg-surface-sunken text-[10px] uppercase">
            <tr>
              <th class="px-3 py-2 text-left text-ink-muted">Nombre</th>
              <th class="px-3 py-2 text-left text-ink-muted">Ruta</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="tabla in filas" :key="tabla.nombre" class="border-b border-line">
              <td class="px-3 py-1.5 font-mono text-ink whitespace-nowrap">{{ tabla.nombre }}</td>
              <td class="px-3 py-1.5 font-mono text-ink-muted">{{ texto(tabla.ruta) }}</td>
            </tr>
            <tr v-if="filas.length === 0">
              <td colspan="2" class="px-3 py-6 text-center text-ink-muted italic">
                ⚠️ No hay variables (tablas de tags) escaneadas. Pulsa "↻ Actualizar".
              </td>
            </tr>
          </tbody>
        </table>

        <table v-else-if="pestana === 'udt' && plc.escaneado" class="w-full text-xs">
          <thead class="sticky top-0 bg-surface-sunken text-[10px] uppercase">
            <tr>
              <th class="px-3 py-2 text-left text-ink-muted">Nombre</th>
              <th class="px-3 py-2 text-left text-ink-muted">Tipo</th>
              <th class="px-3 py-2 text-left text-ink-muted">Número</th>
              <th class="px-3 py-2 text-left text-ink-muted">Ruta</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="tipo in filas" :key="tipo.nombre" class="border-b border-line">
              <td class="px-3 py-1.5 font-mono text-ink whitespace-nowrap">{{ tipo.nombre }}</td>
              <td class="px-3 py-1.5 text-ink-muted whitespace-nowrap font-mono">{{ tipo.tipo }}</td>
              <td class="px-3 py-1.5 font-mono text-ink whitespace-nowrap">
                {{ numero(tipo.numero) }}
              </td>
              <td class="px-3 py-1.5 font-mono text-ink-muted">{{ texto(tipo.ruta) }}</td>
            </tr>
            <tr v-if="filas.length === 0">
              <td colspan="4" class="px-3 py-6 text-center text-ink-muted italic">
                ⚠️ No hay tipos de datos de usuario escaneados. Pulsa "↻ Actualizar".
              </td>
            </tr>
          </tbody>
        </table>

        <div
          v-else
          class="flex-1 flex items-center justify-center bg-surface-raised border border-dashed border-line rounded p-10 text-center text-ink-muted"
          data-testid="plc-vacio"
        >
          <div>
            <div class="text-5xl mb-3 opacity-40">📦</div>
            <p v-if="!plc.seleccionado" class="mb-2">Selecciona un PLC primero.</p>
            <p v-else class="mb-2">El contenido del PLC está vacío.</p>
            <p class="text-xs">
              Pulsa <strong class="text-accent">"↻ Actualizar"</strong> para escanear el PLC.
            </p>
          </div>
        </div>
      </div>
    </div>
  </section>
</template>
