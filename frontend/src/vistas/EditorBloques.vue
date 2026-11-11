<script setup>
/**
 * Editor de bloques: elegir bloques y editar su nombre y su numero.
 *
 * El arbol sale del escaneo del PLC (la vista PLC). Los cambios se aplican
 * contra TIA Portal en una transaccion: o se aplican todos, o no se aplica
 * ninguno.
 *
 * Solo Name y Number son editables. Title, Comment, Author y Version se
 * leen de TIA pero no se pueden cambiar.
 */
import { computed, ref } from "vue";
import { usePlcStore } from "../stores/plc.js";
import { useTrabajosStore } from "../stores/trabajos.js";
import { useTiaStore } from "../stores/tia.js";
import { editarBloques, prepararBloques } from "../api.js";

const plc = usePlcStore();
const trabajos = useTrabajosStore();
const tia = useTiaStore();

/** Orden de los tipos de bloque en el arbol. */
const TIPOS = ["OB", "FC", "FB", "DB", "UDT", "OTHER"];

/** Modo del editor: idle, preparando o editando. */
const modo = ref("idle");

/** Error de la ultima operacion. */
const error = ref("");

/** Bloques preparados contra TIA. */
const preparados = ref([]);

/** Cambios pendientes: ``{nombre: {"Name": ..., "Number": ...}}``. */
const pendientes = ref({});

/** Nombres de los bloques marcados en el arbol. */
const seleccionados = ref(new Set());

/** Carpetas desplegadas del arbol. */
const desplegadas = ref(new Set());

/** `true` mientras hay un trabajo en curso. */
const ocupado = computed(() => modo.value === "preparando" || aplicando.value);

/** `true` mientras se aplican los cambios. */
const aplicando = ref(false);

// ── el arbol ───────────────────────────────────────────────────────────────

/** La clave de tipo de un bloque. */
function claveTipo(bloque) {
  const tipo = String((bloque && bloque.tipo) || "OTHER").toUpperCase();
  return TIPOS.includes(tipo) ? tipo : "OTHER";
}

/** Compara dos bloques: primero por tipo, luego por nombre. */
function compararBloques(a, b) {
  const porTipo = TIPOS.indexOf(claveTipo(a)) - TIPOS.indexOf(claveTipo(b));
  if (porTipo !== 0) return porTipo;
  return String(a.nombre || "").localeCompare(String(b.nombre || ""), undefined, {
    sensitivity: "base",
    numeric: true,
  });
}

/** Monta el arbol de carpetas a partir de la ruta de cada bloque. */
function montarArbol(lista) {
  const raiz = { nombre: "", ruta: "", bloques: [], hijos: new Map() };
  for (const bloque of lista) {
    if (!bloque) continue;
    const ruta = String(bloque.ruta || "")
      .replace(/\\/g, "/")
      .replace(/^\/+|\/+$/g, "")
      .trim();
    if (!ruta) {
      raiz.bloques.push(bloque);
      continue;
    }
    const partes = ruta.split("/").filter((parte) => parte.length > 0);
    let actual = raiz;
    let camino = "";
    for (const parte of partes) {
      camino = camino ? `${camino}/${parte}` : parte;
      if (!actual.hijos.has(parte)) {
        actual.hijos.set(parte, { nombre: parte, ruta: camino, bloques: [], hijos: new Map() });
      }
      actual = actual.hijos.get(parte);
    }
    actual.bloques.push(bloque);
  }
  ordenarCarpeta(raiz);
  return raiz;
}

/** Ordena las carpetas y los bloques de una carpeta. */
function ordenarCarpeta(carpeta) {
  carpeta.hijos = new Map(
    [...carpeta.hijos.entries()].sort(([a], [b]) =>
      a.localeCompare(b, undefined, { sensitivity: "base", numeric: true }),
    ),
  );
  for (const hijo of carpeta.hijos.values()) ordenarCarpeta(hijo);
  carpeta.bloques.sort(compararBloques);
}

/** Los bloques de una carpeta y de sus subcarpetas. */
function bloquesDescendientes(carpeta) {
  let lista = [...carpeta.bloques];
  for (const hijo of carpeta.hijos.values()) lista = lista.concat(bloquesDescendientes(hijo));
  return lista;
}

/** Cuantos bloques hay en una carpeta y sus subcarpetas. */
function contarDescendientes(carpeta) {
  let total = carpeta.bloques.length;
  for (const hijo of carpeta.hijos.values()) total += contarDescendientes(hijo);
  return total;
}

/** Las filas del arbol, ya desplegadas. */
const nodos = computed(() => {
  const raiz = montarArbol(plc.bloques);
  const lista = [];
  function visitar(carpeta, profundidad) {
    if (profundidad === 0) {
      for (const bloque of carpeta.bloques) {
        lista.push({ tipo: "bloque", id: `bloque:${bloque.nombre}`, profundidad, bloque });
      }
      for (const hijo of carpeta.hijos.values()) visitar(hijo, profundidad + 1);
      return;
    }
    const abierto = desplegadas.value.has(carpeta.ruta);
    const descendientes = bloquesDescendientes(carpeta);
    lista.push({
      tipo: "carpeta",
      id: `carpeta:${carpeta.ruta}`,
      nombre: carpeta.nombre,
      ruta: carpeta.ruta,
      profundidad,
      tieneHijos: carpeta.hijos.size > 0 || carpeta.bloques.length > 0,
      abierto,
      descendientes,
      total: contarDescendientes(carpeta),
    });
    if (!abierto) return;
    for (const bloque of carpeta.bloques) {
      lista.push({ tipo: "bloque", id: `bloque:${bloque.nombre}`, profundidad: profundidad + 1, bloque });
    }
    for (const hijo of carpeta.hijos.values()) visitar(hijo, profundidad + 1);
  }
  visitar(raiz, 0);
  return lista;
});

/** Todas las carpetas del arbol, para desplegarlas todas de golpe. */
const rutasCarpetas = computed(() => {
  const raiz = montarArbol(plc.bloques);
  const rutas = [];
  function visitar(carpeta) {
    if (carpeta.ruta) rutas.push(carpeta.ruta);
    for (const hijo of carpeta.hijos.values()) visitar(hijo);
  }
  visitar(raiz);
  return rutas;
});

/** El numero total de bloques del PLC. */
const totalBloques = computed(() => plc.bloques.length);

/** Cuantos bloques hay marcados. */
const totalSeleccionados = computed(() => seleccionados.value.size);

/** `true` si hay algo que preparar. */
const puedeEditar = computed(() => totalSeleccionados.value > 0 && !ocupado.value);

// ── la seleccion ───────────────────────────────────────────────────────────

/** Marca o desmarca un bloque. */
function alternar(bloque) {
  const nuevos = new Set(seleccionados.value);
  if (nuevos.has(bloque.nombre)) nuevos.delete(bloque.nombre);
  else nuevos.add(bloque.nombre);
  seleccionados.value = nuevos;
}

/** Marca o desmarca todos los bloques. */
function alternarTodos() {
  const todos = bloquesDescendientes(montarArbol(plc.bloques));
  if (!todos.length) return;
  const nuevos = new Set(seleccionados.value);
  const marcados = todos.every((bloque) => nuevos.has(bloque.nombre));
  for (const bloque of todos) {
    if (marcados) nuevos.delete(bloque.nombre);
    else nuevos.add(bloque.nombre);
  }
  seleccionados.value = nuevos;
}

/** Marca o desmarca los bloques de una carpeta. */
function alternarCarpeta(carpeta) {
  if (!carpeta.descendientes.length) return;
  const nuevos = new Set(seleccionados.value);
  const marcados = carpeta.descendientes.every((bloque) => nuevos.has(bloque.nombre));
  for (const bloque of carpeta.descendientes) {
    if (marcados) nuevos.delete(bloque.nombre);
    else nuevos.add(bloque.nombre);
  }
  seleccionados.value = nuevos;
}

/** `true` si una carpeta esta marcada entera. */
function carpetaMarcada(carpeta) {
  return (
    carpeta.descendientes.length > 0 &&
    carpeta.descendientes.every((bloque) => seleccionados.value.has(bloque.nombre))
  );
}

/** `true` si una carpeta esta marcada a medias. */
function carpetaParcial(carpeta) {
  const algunos = carpeta.descendientes.some((bloque) => seleccionados.value.has(bloque.nombre));
  return algunos && !carpetaMarcada(carpeta);
}

/** Despliega o repliega una carpeta. */
function alternarDespliegue(ruta) {
  const nuevos = new Set(desplegadas.value);
  if (nuevos.has(ruta)) nuevos.delete(ruta);
  else nuevos.add(ruta);
  desplegadas.value = nuevos;
}

/** Despliega todas las carpetas. */
function desplegarTodo() {
  desplegadas.value = new Set(rutasCarpetas.value);
}

/** Repliega todas las carpetas. */
function colapsarTodo() {
  desplegadas.value = new Set();
}

/** Quita toda la seleccion. */
function limpiarSeleccion() {
  seleccionados.value = new Set();
}

// ── los cambios ────────────────────────────────────────────────────────────

/** El valor de un campo: el pendiente si lo hay, si no el de TIA. */
function valorPreparado(nombre, campo) {
  const bloque = preparados.value.find((item) => item.nombre === nombre);
  if (!bloque) return "";
  const pendiente = pendientes.value[nombre];
  if (pendiente && Object.prototype.hasOwnProperty.call(pendiente, campo)) {
    return pendiente[campo];
  }
  if (campo === "Name") return bloque.nombre;
  if (campo === "Number") return bloque.numero === null || bloque.numero === undefined ? "" : bloque.numero;
  return "";
}

/** Guarda un cambio pendiente. Si vuelve al valor de TIA, se quita. */
function guardarValor(nombre, campo, valor) {
  const bloque = preparados.value.find((item) => item.nombre === nombre);
  if (!bloque) return;
  const original = campo === "Name" ? bloque.nombre : bloque.numero;
  const iguales =
    campo === "Number"
      ? Number(valor) === Number(original)
      : String(valor) === String(original ?? "");
  const nuevos = { ...pendientes.value };
  if (iguales) {
    if (nuevos[nombre]) {
      const copia = { ...nuevos[nombre] };
      delete copia[campo];
      if (Object.keys(copia).length) nuevos[nombre] = copia;
      else delete nuevos[nombre];
    }
  } else {
    nuevos[nombre] = { ...(nuevos[nombre] || {}) };
    nuevos[nombre][campo] = campo === "Number" ? Number(valor) : String(valor);
  }
  pendientes.value = nuevos;
}

/** Cuantos bloques tienen cambios. */
const numeroCambios = computed(() => Object.keys(pendientes.value).length);

/** Los cambios, listos para mandarlos al backend. */
const cambios = computed(() => {
  const salida = {};
  for (const [nombre, campos] of Object.entries(pendientes.value)) {
    const propias = {};
    if (Object.prototype.hasOwnProperty.call(campos, "Name")) propias.Name = campos.Name;
    if (Object.prototype.hasOwnProperty.call(campos, "Number")) propias.Number = campos.Number;
    if (Object.keys(propias).length) salida[nombre] = propias;
  }
  return salida;
});

// ── los trabajos ───────────────────────────────────────────────────────────

/** Prepara los bloques seleccionados contra TIA. */
async function preparar() {
  if (!puedeEditar.value) return;
  error.value = "";
  modo.value = "preparando";
  if (tia.demo) {
    // En el demo no hay TIA: se prepara con lo que ya hay en el store.
    preparados.value = [...seleccionados.value]
      .map((nombre) => plc.bloques.find((bloque) => bloque.nombre === nombre))
      .filter(Boolean);
    modo.value = "editando";
    return;
  }
  try {
    const respuesta = await prepararBloques(
      plc.seleccionado,
      [...seleccionados.value],
    );
    const job = await trabajos.esperar(respuesta.job_id);
    if (job.estado !== "ok") {
      error.value = job.error || "No se pudieron preparar los bloques.";
      modo.value = "idle";
      return;
    }
    preparados.value = (job.resultado && job.resultado.bloques) || [];
    modo.value = "editando";
  } catch (fallo) {
    error.value = fallo.message;
    modo.value = "idle";
  }
}

/** Aplica los cambios contra TIA Portal. */
async function aplicar() {
  if (!numeroCambios.value || aplicando.value) return;
  error.value = "";
  aplicando.value = true;
  if (tia.demo) {
    aplicando.value = false;
    limpiarSeleccion();
    cancelar();
    return;
  }
  try {
    const respuesta = await editarBloques(plc.seleccionado, cambios.value);
    const job = await trabajos.esperar(respuesta.job_id);
    aplicando.value = false;
    if (job.estado !== "ok") {
      error.value = job.error || "No se pudieron aplicar los cambios.";
      return;
    }
    // El trabajo refresca los bloques: el arbol tiene que ver los nombres
    // nuevos.
    const resultado = job.resultado || {};
    if (Array.isArray(resultado.bloques)) {
      plc.bloques = resultado.bloques;
    }
    limpiarSeleccion();
    cancelar();
  } catch (fallo) {
    error.value = fallo.message;
    aplicando.value = false;
  }
}

/** Cancela la edicion y vuelve al arbol. */
function cancelar() {
  modo.value = "idle";
  preparados.value = [];
  pendientes.value = {};
  error.value = "";
}

// ── el aspecto de la pastilla de tipo ──────────────────────────────────────

/** Los colores de TIA Portal para cada tipo de bloque. */
const COLORES_TIPO = {
  OB: { fondo: "rgb(190, 30, 247)", texto: "rgb(255, 255, 255)" },
  DB: { fondo: "rgb(63, 80, 235)", texto: "rgb(255, 255, 255)" },
  FB: { fondo: "rgb(19, 154, 241)", texto: "rgb(255, 255, 255)" },
  FC: { fondo: "rgb(34, 184, 32)", texto: "rgb(255, 255, 255)" },
  UDT: { fondo: "rgb(224, 237, 243)", texto: "rgb(40, 50, 70)" },
};

const COLOR_POR_DEFECTO = { fondo: "rgb(180, 180, 180)", texto: "rgb(255, 255, 255)" };

/** El estilo de la pastilla de un tipo. */
function estiloTipo(tipo) {
  const color = COLORES_TIPO[String(tipo || "OTHER").toUpperCase()] || COLOR_POR_DEFECTO;
  return {
    backgroundColor: color.fondo,
    color: color.texto,
    display: "inline-block",
    minWidth: "26px",
    height: "16px",
    lineHeight: "16px",
    paddingLeft: "4px",
    paddingRight: "4px",
    textAlign: "center",
    fontSize: "9px",
    fontWeight: "700",
    fontFamily: "ui-monospace, SFMono-Regular, Menlo, Consolas, monospace",
    borderRadius: "2px",
    letterSpacing: "0.5px",
  };
}

/** La etiqueta de un tipo. */
function etiquetaTipo(tipo) {
  const clave = String(tipo || "OTHER").toUpperCase();
  return clave === "OTHER" ? "??" : clave;
}
</script>

<template>
  <section class="flex-1 flex flex-col overflow-hidden gap-4" data-testid="editor-bloques">
    <div
      v-if="!tia.conectado"
      class="flex-1 flex items-center justify-center bg-surface-raised border border-dashed border-line rounded p-10 text-center text-ink-muted"
      data-testid="editor-sin-conexion"
    >
      <div>
        <div class="text-5xl mb-3 opacity-40">🔌</div>
        <p class="mb-2 font-semibold text-ink">Conecta a TIA Portal</p>
        <p class="text-xs">Desde la pestaña PLC pulsa 'Conectar' para empezar.</p>
      </div>
    </div>

    <div v-else-if="!plc.seleccionado" class="flex-1 flex items-center justify-center bg-surface-raised border border-dashed border-line rounded p-10 text-center text-ink-muted">
      <div>
        <div class="text-5xl mb-3 opacity-40">📋</div>
        <p class="mb-2 font-semibold text-ink">Selecciona un PLC</p>
        <p class="text-xs">En la pestaña PLC elige uno de los PLCs disponibles.</p>
      </div>
    </div>

    <div v-else-if="!plc.escaneado" class="flex-1 flex items-center justify-center bg-surface-raised border border-dashed border-line rounded p-10 text-center text-ink-muted">
      <div>
        <div class="text-5xl mb-3 opacity-40">⚠️</div>
        <p class="mb-2 font-semibold text-ink">Contenido del PLC no disponible</p>
        <p class="text-xs">Pulsa 'Actualizar' en la pestaña PLC para escanearlo.</p>
      </div>
    </div>

    <div v-else class="flex-1 min-h-0 grid grid-cols-3 gap-4">
      <div
        class="col-span-1 flex flex-col bg-surface-raised border border-line rounded p-5 gap-3 min-h-0"
        :class="ocupado ? 'pointer-events-none opacity-50' : ''"
        data-testid="editor-arbol"
      >
        <div class="flex items-start justify-between gap-3">
          <div>
            <h3 class="text-sm font-bold text-ink">Selección de bloques</h3>
            <p class="text-xs text-ink-muted mt-1">Selección read-only.</p>
          </div>
          <div class="flex items-center gap-3 text-xs shrink-0">
            <span class="text-ink-muted">{{ totalSeleccionados }} seleccionados</span>
            <button
              v-if="totalSeleccionados > 0"
              type="button"
              class="text-ink-muted hover:text-ink underline"
              @click="limpiarSeleccion"
            >
              Limpiar
            </button>
          </div>
        </div>

        <div class="flex items-center gap-3 text-xs flex-wrap">
          <label class="flex items-center gap-2">
            <input
              type="checkbox"
              :checked="totalSeleccionados === totalBloques && totalBloques > 0"
              :indeterminate.prop="totalSeleccionados > 0 && totalSeleccionados < totalBloques"
              data-testid="editor-seleccionar-todos"
              @change="alternarTodos"
            />
            <span>Seleccionar todos ({{ totalBloques }} bloques)</span>
          </label>
          <button type="button" class="text-xs text-ink-muted hover:text-ink underline" @click="desplegarTodo">
            Expandir todo
          </button>
          <button type="button" class="text-xs text-ink-muted hover:text-ink underline" @click="colapsarTodo">
            Colapsar todo
          </button>
        </div>

        <div
          class="flex-1 min-h-0 overflow-y-auto bg-surface-raised border border-line rounded text-xs"
          data-testid="editor-arbol-lista"
        >
          <div
            v-for="nodo in nodos"
            :key="nodo.id"
            class="flex items-center gap-2 px-2 py-0.5 hover:bg-surface-sunken"
            :style="{ paddingLeft: nodo.profundidad * 16 + 4 + 'px' }"
          >
            <span
              v-if="nodo.tipo === 'carpeta' && nodo.tieneHijos"
              class="cursor-pointer select-none w-4 inline-flex items-center justify-center text-gray-500 hover:text-gray-700"
              @click="alternarDespliegue(nodo.ruta)"
              >{{ nodo.abierto ? "▼" : "▶" }}</span
            >
            <span v-else class="w-4"></span>

            <input
              v-if="nodo.tipo === 'carpeta'"
              type="checkbox"
              :checked="carpetaMarcada(nodo)"
              :indeterminate.prop="carpetaParcial(nodo)"
              class="shrink-0"
              @change="alternarCarpeta(nodo)"
            />
            <input
              v-else
              type="checkbox"
              :checked="seleccionados.has(nodo.bloque.nombre)"
              class="shrink-0"
              @change="alternar(nodo.bloque)"
            />

            <span
              v-if="nodo.tipo === 'bloque'"
              :style="estiloTipo(nodo.bloque.tipo)"
              class="shrink-0"
              :title="nodo.bloque.tipo"
              >{{ etiquetaTipo(nodo.bloque.tipo) }}</span
            >
            <span v-else class="w-4 text-center shrink-0" aria-hidden="true">
              {{ nodo.abierto ? "📂" : "📁" }}
            </span>

            <span
              :class="nodo.tipo === 'carpeta' ? 'font-semibold text-ink' : 'font-mono text-ink'"
              class="truncate"
            >
              {{ nodo.tipo === 'carpeta' ? nodo.nombre : nodo.bloque.nombre }}
            </span>
            <span v-if="nodo.tipo === 'carpeta' && nodo.tieneHijos" class="text-ink-muted">
              ({{ nodo.total }} bloques)
            </span>
          </div>
        </div>

        <div class="flex justify-end pt-3 border-t border-line">
          <button
            type="button"
            :disabled="!puedeEditar"
            :class="puedeEditar ? 'bg-accent text-ink-inverse hover:bg-accent-hover cursor-pointer' : 'bg-surface-sunken text-ink-muted cursor-not-allowed'"
            class="px-4 py-2 rounded text-sm font-semibold"
            data-testid="editor-editar"
            @click="preparar"
          >
            Editar
          </button>
        </div>
      </div>

      <div
        class="col-span-2 flex flex-col bg-surface-raised border border-line rounded p-5 gap-3 min-h-0"
        data-testid="editor-propiedades"
      >
        <div v-if="modo === 'idle'" class="flex-1 min-h-0 flex flex-col">
          <div>
            <h3 class="text-sm font-bold text-ink">Edición de propiedades</h3>
            <p class="text-xs text-ink-muted mt-1">Edición transaccional de Name / Number.</p>
          </div>
          <div
            class="flex-1 min-h-0 flex flex-col items-center justify-center border border-dashed border-line rounded bg-surface-sunken text-xs text-ink-muted gap-2 p-6 text-center"
          >
            <span class="text-3xl opacity-40">🛠️</span>
            <p>
              <span v-if="totalSeleccionados > 0"
                >{{ totalSeleccionados }} bloques seleccionados. Pulsa "Editar" para preparar los
                datos contra TIA.</span
              >
              <span v-else>Selecciona bloques en el árbol para empezar.</span>
            </p>
          </div>
          <div class="flex justify-end pt-3 border-t border-line">
            <button
              type="button"
              disabled
              class="px-4 py-2 rounded text-sm font-semibold bg-surface-sunken text-ink-muted cursor-not-allowed"
              data-testid="editor-aplicar"
            >
              Aplicar
            </button>
          </div>
        </div>

        <div
          v-else-if="modo === 'preparando'"
          class="flex-1 min-h-0 flex flex-col items-center justify-center gap-3 text-xs text-ink-muted"
          data-testid="editor-preparando"
        >
          <span class="inline-block animate-spin text-3xl text-accent">↻</span>
          <p>Preparando {{ totalSeleccionados }} bloques contra TIA Portal…</p>
        </div>

        <div v-else class="flex-1 min-h-0 flex flex-col gap-3" data-testid="editor-tabla">
          <div>
            <h3 class="text-sm font-bold text-ink">Edición de propiedades</h3>
            <p class="text-xs text-ink-muted mt-1">
              <strong class="text-ink">Name</strong> y <strong class="text-ink">Number</strong> son
              editables y se aplican contra TIA Portal.
              <strong class="text-ink">Title</strong>, <strong class="text-ink">Comment</strong>,
              <strong class="text-ink">Author</strong> y
              <strong class="text-ink">Version</strong> son solo lectura por ahora. El comentario
              solo se puede leer del XML exportado (SimaticSD), que necesita TIA V21.
            </p>
            <p
              v-if="aplicando"
              class="text-xs text-accent mt-1"
              data-testid="editor-aplicando"
            >
              <span class="inline-block animate-spin mr-1">↻</span>
              Aplicando cambios en TIA Portal (transacción atómica, puede tardar minutos)…
            </p>
            <p v-if="error" class="text-xs text-red-600 mt-1" data-testid="editor-error">
              ✗ {{ error }}
            </p>
          </div>

          <div class="flex-1 min-h-0 overflow-auto border border-line rounded">
            <table class="min-w-full text-xs">
              <thead class="sticky top-0 bg-surface-raised text-ink-muted">
                <tr>
                  <th class="px-2 py-1 text-left whitespace-nowrap">Tipo</th>
                  <th class="px-2 py-1 text-left whitespace-nowrap">Name*</th>
                  <th class="px-2 py-1 text-right whitespace-nowrap">Number*</th>
                  <th class="px-2 py-1 text-left whitespace-nowrap">Title</th>
                  <th class="px-2 py-1 text-left whitespace-nowrap">Comment</th>
                  <th class="px-2 py-1 text-left whitespace-nowrap">Author</th>
                  <th class="px-2 py-1 text-left whitespace-nowrap">Version</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="bloque in preparados" :key="bloque.nombre" class="border-t border-line">
                  <td class="px-2 py-1 whitespace-nowrap">
                    <span :style="estiloTipo(bloque.tipo)" class="shrink-0" :title="bloque.tipo">
                      {{ etiquetaTipo(bloque.tipo) }}
                    </span>
                  </td>
                  <td class="px-2 py-1">
                    <input
                      type="text"
                      :value="valorPreparado(bloque.nombre, 'Name')"
                      :disabled="aplicando"
                      class="font-mono px-1 py-0.5 rounded w-full border border-line bg-surface-raised text-ink focus:outline-none focus:border-line-strong"
                      :data-testid="'editor-nombre-' + bloque.nombre"
                      @input="guardarValor(bloque.nombre, 'Name', $event.target.value)"
                    />
                  </td>
                  <td class="px-2 py-1">
                    <input
                      type="number"
                      :value="valorPreparado(bloque.nombre, 'Number')"
                      :disabled="aplicando"
                      class="font-mono px-1 py-0.5 rounded w-full text-right border border-line bg-surface-raised text-ink focus:outline-none focus:border-line-strong"
                      :data-testid="'editor-numero-' + bloque.nombre"
                      @input="guardarValor(bloque.nombre, 'Number', $event.target.value)"
                    />
                  </td>
                  <td class="px-2 py-1">
                    <input
                      type="text"
                      :value="bloque.extended.title || ''"
                      disabled
                      title="Title: solo lectura"
                      class="font-mono px-1 py-0.5 rounded w-full border border-line bg-surface-sunken text-ink-muted cursor-not-allowed"
                      :data-testid="'editor-titulo-' + bloque.nombre"
                    />
                  </td>
                  <td class="px-2 py-1">
                    <textarea
                      :value="bloque.extended.comment || ''"
                      readonly
                      title="Comment: solo lectura. Solo se puede leer del XML exportado (SimaticSD, V21+)."
                      style="min-height: 24px; min-width: 160px;"
                      class="font-mono px-1 py-0.5 rounded w-full border border-line bg-surface-sunken text-ink-muted"
                      :data-testid="'editor-comentario-' + bloque.nombre"
                    ></textarea>
                  </td>
                  <td class="px-2 py-1">
                    <input
                      type="text"
                      :value="bloque.extended.author || ''"
                      disabled
                      title="Author: solo lectura"
                      class="px-1 py-0.5 rounded w-full border border-line bg-surface-sunken text-ink-muted cursor-not-allowed"
                      :data-testid="'editor-autor-' + bloque.nombre"
                    />
                  </td>
                  <td class="px-2 py-1">
                    <input
                      type="text"
                      :value="bloque.extended.version || ''"
                      disabled
                      title="Version: solo lectura"
                      class="font-mono px-1 py-0.5 rounded w-full border border-line bg-surface-sunken text-ink-muted cursor-not-allowed"
                      :data-testid="'editor-version-' + bloque.nombre"
                    />
                  </td>
                </tr>
              </tbody>
            </table>
          </div>

          <div class="flex justify-between pt-3 border-t border-line">
            <button
              type="button"
              :disabled="aplicando"
              :class="aplicando ? 'text-ink-muted cursor-not-allowed' : 'text-ink-muted hover:text-ink underline'"
              class="text-sm"
              data-testid="editor-cancelar"
              @click="cancelar"
            >
              Cancelar
            </button>
            <button
              type="button"
              :disabled="!numeroCambios || aplicando"
              :class="!numeroCambios || aplicando ? 'bg-surface-sunken text-ink-muted cursor-not-allowed' : 'bg-accent text-ink-inverse hover:bg-accent-hover cursor-pointer'"
              class="px-4 py-2 rounded text-sm font-semibold"
              data-testid="editor-aplicar-cambios"
              @click="aplicar"
            >
              Aplicar ({{ numeroCambios }})
            </button>
          </div>
        </div>
      </div>
    </div>
  </section>
</template>
