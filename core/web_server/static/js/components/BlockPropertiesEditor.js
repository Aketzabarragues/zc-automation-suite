/**
 * Componente ``blockpropertieseditor``.
 *
 * Vista shell transversal, read-only sobre la cache
 * ``store.appCache.plc_blocks[<plc>]``. Muestra el arbol jerarquico
 * agrupado por el primer segmento de ``b.ruta`` (split por ``\``)
 * con seleccion multiple de bloques (``selectedKeys`` = Set de
 * ``b.nombre``).
 *
 * 4 empty states secuenciales (prioridad estricta):
 *   1. TIA no connected               (icono "🔌")
 *   2. TIA connected sin PLC selected (icono "📋")
 *   3. PLC selected sin cache         (icono "⚠️")
 *   4. cache con ``blocks`` vacio     (icono "📭")
 *
 * Tema: Industrial Claro. Solo tokens semanticos. Sin baktilts
 * dentro del ``template:`` (regla Vue 3 sin build step).
 */

import {
    computed,
    ref,
} from "/js/vendor/vue.esm-browser.prod.js";
import { store } from "/js/store.js";

const STALE_AFTER_MS = 5 * 60 * 1000;
const _TIPO_ORDER = ["OB", "DB", "FB", "FC", "UDT", "OTHER"];
const ROOT_FOLDER = "(raiz)";

export default {
    name: "blockpropertieseditor",
    setup() {
        const selectedPlc = computed(() => store.appCache?.selected_plc || "");
        const cache = computed(() => {
            const plc = selectedPlc.value;
            if (!plc) return null;
            return store.appCache?.plc_blocks?.[plc] || null;
        });
        const blocks = computed(() => {
            const c = cache.value;
            return c && Array.isArray(c.blocks) ? c.blocks : [];
        });
        const scannedAt = computed(() =>
            cache.value && cache.value.scanned_at ? cache.value.scanned_at : null
        );
        const isStale = computed(() => {
            if (!scannedAt.value) return false;
            const t = Date.parse(scannedAt.value);
            return !Number.isNaN(t) && Date.now() - t > STALE_AFTER_MS;
        });

        const emptyState = computed(() => {
            const tia = store.tiaConnection;
            const plcSelected = !!selectedPlc.value;
            const empty = (icon, title, hint) => ({ show: true, icon, title, hint });
            if (!tia || tia.state !== "connected") {
                return empty("🔌", "Conecta a TIA Portal", "Desde la pestaña PLC pulsa 'Conectar' para empezar.");
            }
            if (!plcSelected) {
                return empty("📋", "Selecciona un PLC", "En la pestaña PLC elige uno de los PLCs disponibles.");
            }
            if (!cache.value) {
                return empty("⚠️", "Cache no disponible", "Pulsa 'Refrescar' en la pestaña PLC para cargarla.");
            }
            if (!Array.isArray(blocks.value) || blocks.value.length === 0) {
                return empty("📭", "No hay bloques en la cache", "Pulsa 'Refrescar' en la pestaña PLC.");
            }
            return { show: false, icon: "", title: "", hint: "" };
        });

        function folderOf(block) {
            const ruta = (block && block.ruta) || "";
            if (!ruta) return ROOT_FOLDER;
            const head = ruta.split("\\")[0];
            return head || ROOT_FOLDER;
        }

        function tipoKey(block) {
            const t = String((block && block.tipo) || "OTHER").toUpperCase();
            return _TIPO_ORDER.includes(t) ? t : "OTHER";
        }

        const tree = computed(() => {
            const list = Array.isArray(blocks.value) ? blocks.value : [];
            const buckets = new Map();
            for (const b of list) {
                if (!b) continue;
                const folder = folderOf(b);
                if (!buckets.has(folder)) buckets.set(folder, []);
                buckets.get(folder).push(b);
            }
            for (const arr of buckets.values()) {
                arr.sort((a, b) => {
                    const tc = _TIPO_ORDER.indexOf(tipoKey(a)) - _TIPO_ORDER.indexOf(tipoKey(b));
                    if (tc !== 0) return tc;
                    const an = String(a.nombre || a.name || "");
                    const bn = String(b.nombre || b.name || "");
                    const cmp = an.localeCompare(bn, undefined, { sensitivity: "base", numeric: true });
                    if (cmp !== 0) return cmp;
                    return String(a.ruta || "").localeCompare(String(b.ruta || ""));
                });
            }
            const folderNames = Array.from(buckets.keys()).sort((a, b) =>
                a.localeCompare(b, undefined, { sensitivity: "base", numeric: true })
            );
            return {
                folders: folderNames.map((name) => ({ name, blocks: buckets.get(name) })),
                totalBlocks: list.length,
            };
        });

        const selectedKeys = ref(new Set());
        const totalSelected = computed(() => selectedKeys.value.size);
        const canContinue = computed(() => totalSelected.value > 0);

        function toggleSelect(key) {
            const next = new Set(selectedKeys.value);
            if (next.has(key)) next.delete(key);
            else next.add(key);
            selectedKeys.value = next;
        }
        function clearSelection() {
            selectedKeys.value = new Set();
        }
        function toggleSelectAllInFolder(folderName) {
            const folder = tree.value.folders.find((f) => f.name === folderName);
            if (!folder) return;
            const next = new Set(selectedKeys.value);
            const allSelected = folder.blocks.every((b) => next.has(b.nombre));
            for (const b of folder.blocks) {
                if (allSelected) next.delete(b.nombre);
                else next.add(b.nombre);
            }
            selectedKeys.value = next;
        }
        function toggleSelectAll() {
            const all = tree.value.folders.flatMap((f) => f.blocks);
            if (all.length === 0) return;
            const next = new Set(selectedKeys.value);
            const allSelected = all.every((b) => next.has(b.nombre));
            for (const b of all) {
                if (allSelected) next.delete(b.nombre);
                else next.add(b.nombre);
            }
            selectedKeys.value = next;
        }

        return {
            selectedPlc,
            cache,
            blocks,
            scannedAt,
            isStale,
            emptyState,
            tree,
            selectedKeys,
            totalSelected,
            canContinue,
            toggleSelect,
            toggleSelectAllInFolder,
            toggleSelectAll,
            clearSelection,
        };
    },
    template: /* html */ `
        <section class="flex-1 flex flex-col p-5 gap-4" data-testid="block-editor-root">
            <!-- Cabecera -->
            <header class="flex items-center gap-3">
                <h2 class="text-lg font-bold text-ink">Editor de bloques</h2>
                <span class="text-xs text-ink-muted">PLC: <strong class="text-ink">{{ selectedPlc || "—" }}</strong></span>
                <span class="ml-auto text-xs text-ink-muted">{{ totalSelected }} seleccionados</span>
                <span v-if="isStale" class="text-xs px-2 py-1 rounded bg-amber-100 text-amber-800 border border-amber-300">Cache obsoleta</span>
            </header>
            <!-- Empty state (cualquiera de los 4 casos) -->
            <div v-if="emptyState.show" class="flex-1 flex items-center justify-center bg-surface-raised border border-dashed border-line rounded p-10 text-center text-ink-muted">
                <div>
                    <div class="text-5xl mb-3 opacity-40">{{ emptyState.icon }}</div>
                    <p class="mb-2 font-semibold text-ink">{{ emptyState.title }}</p>
                    <p class="text-xs">{{ emptyState.hint }}</p>
                </div>
            </div>
            <!-- Árbol de carpetas + bloques (solo si NO empty state) -->
            <div v-else class="flex-1 min-h-0 flex flex-col gap-3">
                <!-- Strip de acciones: maestro + clear -->
                <div class="flex items-center gap-3 text-xs">
                    <label class="flex items-center gap-2">
                        <input type="checkbox" :checked="totalSelected === tree.totalBlocks" :indeterminate.prop="totalSelected > 0 && totalSelected < tree.totalBlocks" @change="toggleSelectAll" data-testid="block-editor-select-all" />
                        <span>Seleccionar todos ({{ tree.totalBlocks }} bloques)</span>
                    </label>
                    <button v-if="totalSelected > 0" @click="clearSelection" class="text-xs text-ink-muted hover:text-ink underline">Limpiar selección</button>
                </div>
                <!-- Una card por carpeta -->
                <div v-for="folder in tree.folders" :key="folder.name" class="bg-surface-raised border border-line rounded p-3" :data-testid="'block-editor-folder-' + folder.name">
                    <header class="flex items-center gap-2 mb-2">
                        <input type="checkbox" :checked="folder.blocks.every(b =&gt; selectedKeys.has(b.nombre))" :indeterminate.prop="folder.blocks.some(b =&gt; selectedKeys.has(b.nombre)) &amp;&amp; !folder.blocks.every(b =&gt; selectedKeys.has(b.nombre))" @change="toggleSelectAllInFolder(folder.name)" :data-testid="'block-editor-folder-select-' + folder.name" />
                        <h3 class="text-sm font-bold text-ink">{{ folder.name }}</h3>
                        <span class="text-xs text-ink-muted">({{ folder.blocks.length }} bloques)</span>
                    </header>
                    <table class="w-full text-xs">
                        <thead class="text-ink-muted">
                            <tr>
                                <th class="w-8"></th>
                                <th class="text-left px-2 py-1">Nombre</th>
                                <th class="text-right px-2 py-1 w-20">Número</th>
                                <th class="text-left px-2 py-1 w-16">Tipo</th>
                                <th class="text-left px-2 py-1">Ruta completa</th>
                            </tr>
                        </thead>
                        <tbody>
                            <tr v-for="b in folder.blocks" :key="b.nombre" :data-testid="'block-editor-row-' + b.nombre" class="border-t border-line">
                                <td class="px-2 py-1"><input type="checkbox" :checked="selectedKeys.has(b.nombre)" @change="toggleSelect(b.nombre)" /></td>
                                <td class="px-2 py-1 font-mono text-ink">{{ b.nombre }}</td>
                                <td class="px-2 py-1 text-right text-ink-muted">{{ b.numero || "—" }}</td>
                                <td class="px-2 py-1 text-ink-muted">{{ b.tipo }}</td>
                                <td class="px-2 py-1 text-ink-muted font-mono">{{ b.ruta || "—" }}</td>
                            </tr>
                        </tbody>
                    </table>
                </div>
                <!-- Footer: botón "Continuar a edición" -->
                <footer class="flex justify-end pt-3 border-t border-line">
                    <button :disabled="!canContinue" class="px-4 py-2 rounded text-sm font-semibold transition-colors" :class="canContinue ? 'bg-accent text-ink-inverse hover:bg-accent-hover' : 'bg-surface-sunken text-ink-muted cursor-not-allowed'" data-testid="block-editor-continue">Continuar a edición ({{ totalSelected }})</button>
                </footer>
            </div>
        </section>
    `,
};
