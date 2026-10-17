/**
 * Componente ``blockpropertieseditor``.
 *
 * Vista shell transversal, read-only sobre la cache
 * ``store.appCache.plc_blocks[<plc>]``. Muestra el arbol jerarquico
 * MULTI-NIVEL estilo TIA Portal: un unico arbol con indentacion
 * progresiva, expansion/colapso por categoria, seleccion multiple
 * por bloque y por carpeta (recursivo sobre descendientes).
 *
 * Construccion del arbol:
 *   - Las rutas de los bloques (``b.ruta``) son strings con
 *     separador ``\`` que representan la jerarquia TIA Portal.
 *   - Cada segmento se interpreta como una carpeta. Un bloque con
 *     ``ruta = "0_Sistema\DBs"`` vive dentro de la carpeta
 *     ``0_Sistema\DBs`` (que es hijo de ``0_Sistema``).
 *   - El arbol se aplana a una lista de ``nodes`` (carpetas y
 *     bloques) segun ``expandedFolders``.
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

        function tipoKey(block) {
            const t = String((block && block.tipo) || "OTHER").toUpperCase();
            return _TIPO_ORDER.includes(t) ? t : "OTHER";
        }

        function compareBlocks(a, b) {
            const tc = _TIPO_ORDER.indexOf(tipoKey(a)) - _TIPO_ORDER.indexOf(tipoKey(b));
            if (tc !== 0) return tc;
            const an = String(a.nombre || "");
            const bn = String(b.nombre || "");
            return an.localeCompare(bn, undefined, { sensitivity: "base", numeric: true });
        }

        function buildFolderTree(list) {
            const root = { name: ROOT_FOLDER, fullPath: "", blocks: [], children: new Map() };
            for (const b of list) {
                if (!b) continue;
                const ruta = String(b.ruta || "").trim();
                if (!ruta) { root.blocks.push(b); continue; }
                const segs = ruta.split("\\").filter((s) => s.length > 0);
                let cur = root;
                let curPath = "";
                for (let i = 0; i < segs.length; i++) {
                    const seg = segs[i];
                    curPath = curPath ? curPath + "\\" + seg : seg;
                    if (!cur.children.has(seg)) {
                        cur.children.set(seg, {
                            name: seg,
                            fullPath: curPath,
                            blocks: [],
                            children: new Map(),
                        });
                    }
                    cur = cur.children.get(seg);
                }
                cur.blocks.push(b);
            }
            function sortFolder(folder) {
                const sortedChildren = [...folder.children.entries()].sort(([a], [b]) =>
                    a.localeCompare(b, undefined, { sensitivity: "base", numeric: true })
                );
                folder.children = new Map(sortedChildren);
                for (const child of folder.children.values()) sortFolder(child);
                folder.blocks.sort(compareBlocks);
            }
            sortFolder(root);
            return root;
        }

        function collectDescendantBlocks(folder) {
            let arr = [...folder.blocks];
            for (const child of folder.children.values()) {
                arr = arr.concat(collectDescendantBlocks(child));
            }
            return arr;
        }

        function countDescendantBlocks(folder) {
            let n = folder.blocks.length;
            for (const child of folder.children.values()) n += countDescendantBlocks(child);
            return n;
        }

        function flattenFolderTree(root, expandedSet) {
            const nodes = [];
            const rootPath = root.fullPath;
            function visit(folder, depth, parentExpanded) {
                if (depth === 0) {
                    // Raiz visual: NO se renderiza como fila, solo emite sus hijos.
                    for (const child of folder.children.values()) visit(child, depth + 1, true);
                    for (const b of folder.blocks) {
                        nodes.push({ kind: "block", id: "block:" + b.nombre, depth, block: b, name: b.nombre });
                    }
                    return;
                }
                const isExpanded = parentExpanded && expandedSet.has(folder.fullPath);
                const descendantCount = countDescendantBlocks(folder);
                const descendantBlocks = collectDescendantBlocks(folder);
                nodes.push({
                    kind: "folder",
                    id: "folder:" + folder.fullPath,
                    name: folder.name,
                    fullPath: folder.fullPath,
                    depth,
                    hasChildren: folder.children.size > 0 || folder.blocks.length > 0,
                    expanded: isExpanded,
                    descendantCount,
                    descendantBlocks,
                });
                if (!isExpanded) return;
                for (const child of folder.children.values()) visit(child, depth + 1, true);
                for (const b of folder.blocks) {
                    nodes.push({ kind: "block", id: "block:" + b.nombre, depth: depth + 1, block: b, name: b.nombre });
                }
            }
            visit(root, 0, true);
            return nodes;
        }

        const expandedFolders = ref(new Set());
        const hasInitializedExpansion = ref(false);
        const allFolderPaths = computed(() => {
            const list = Array.isArray(blocks.value) ? blocks.value : [];
            const root = buildFolderTree(list);
            const paths = [];
            function visit(folder) {
                if (folder.fullPath) paths.push(folder.fullPath);
                for (const child of folder.children.values()) visit(child);
            }
            visit(root);
            return paths;
        });
        function expandAll() {
            expandedFolders.value = new Set(allFolderPaths.value);
        }
        function collapseAll() {
            expandedFolders.value = new Set();
        }
        function toggleFolder(fullPath) {
            const next = new Set(expandedFolders.value);
            if (next.has(fullPath)) next.delete(fullPath);
            else next.add(fullPath);
            expandedFolders.value = next;
        }

        const tree = computed(() => {
            const list = Array.isArray(blocks.value) ? blocks.value : [];
            const root = buildFolderTree(list);
            // Auto-expand inicial: en la primera carga con bloques
            // disponibles, expandir TODAS las carpetas. Asi el operario
            // ve el arbol completo de un vistazo (como TIA Portal). Las
            // elecciones manuales posteriores del operario (colapsar /
            // expandir individuales) se respetan en renders siguientes.
            if (!hasInitializedExpansion.value && list.length > 0) {
                const allPaths = [];
                function visit(f) {
                    if (f.fullPath) allPaths.push(f.fullPath);
                    for (const c of f.children.values()) visit(c);
                }
                visit(root);
                expandedFolders.value = new Set(allPaths);
                hasInitializedExpansion.value = true;
            }
            const nodes = flattenFolderTree(root, expandedFolders.value);
            return { nodes, totalBlocks: list.length, root };
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
        function toggleSelectAll() {
            const list = tree.value.root.blocks;
            if (list.length === 0 && tree.value.root.children.size === 0) return;
            const next = new Set(selectedKeys.value);
            const allBlocks = collectDescendantBlocks(tree.value.root);
            if (allBlocks.length === 0) return;
            const allSelected = allBlocks.every((b) => next.has(b.nombre));
            for (const b of allBlocks) {
                if (allSelected) next.delete(b.nombre);
                else next.add(b.nombre);
            }
            selectedKeys.value = next;
        }
        function toggleSelectFolder(folderNode) {
            const blocks = folderNode.descendantBlocks || [];
            if (blocks.length === 0) return;
            const next = new Set(selectedKeys.value);
            const allSelected = blocks.every((b) => next.has(b.nombre));
            for (const b of blocks) {
                if (allSelected) next.delete(b.nombre);
                else next.add(b.nombre);
            }
            selectedKeys.value = next;
        }
        function typeIcon(tipo) {
            // Mantenido por retro-compat con cualquier consumidor externo;
            // el render del template usa typeStyle + tipoLabel.
            switch (String(tipo || "OTHER").toUpperCase()) {
                case "OB": return "OB";
                case "DB": return "DB";
                case "FB": return "FB";
                case "FC": return "FC";
                case "UDT": return "UDT";
                default: return "??";
            }
        }

        // Colores oficiales TIA Portal para el icono-pastilla de cada tipo.
        // Documentados como constantes para que cualquier ajuste futuro
        // (cambio de tonalidad entre versiones TIA) sea de un solo punto.
        const TIA_TYPE_COLORS = Object.freeze({
            OB:    { bg: "rgb(190, 30, 247)", fg: "rgb(255, 255, 255)" },
            DB:    { bg: "rgb(63, 80, 235)",  fg: "rgb(255, 255, 255)" },
            FB:    { bg: "rgb(19, 154, 241)", fg: "rgb(255, 255, 255)" },
            FC:    { bg: "rgb(34, 184, 32)",  fg: "rgb(255, 255, 255)" },
            UDT:   { bg: "rgb(224, 237, 243)", fg: "rgb(40, 50, 70)"   },
        });
        const TIA_DEFAULT_COLOR = Object.freeze({ bg: "rgb(180, 180, 180)", fg: "rgb(255, 255, 255)" });

        function typeStyle(tipo) {
            const key = String(tipo || "OTHER").toUpperCase();
            const c = TIA_TYPE_COLORS[key] || TIA_DEFAULT_COLOR;
            return {
                backgroundColor: c.bg,
                color: c.fg,
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
        function tipoLabel(tipo) {
            const key = String(tipo || "OTHER").toUpperCase();
            if (key === "OTHER") return "??";
            return key;
        }
        function isFolderFullySelected(folderNode) {
            const blocks = folderNode.descendantBlocks || [];
            return blocks.length > 0 && blocks.every((b) => selectedKeys.value.has(b.nombre));
        }
        function isFolderPartiallySelected(folderNode) {
            const blocks = folderNode.descendantBlocks || [];
            const some = blocks.some((b) => selectedKeys.value.has(b.nombre));
            const all = blocks.every((b) => selectedKeys.value.has(b.nombre));
            return some && !all;
        }

        return {
            selectedPlc,
            cache,
            blocks,
            scannedAt,
            isStale,
            emptyState,
            tree,
            expandedFolders,
            selectedKeys,
            totalSelected,
            canContinue,
            toggleSelect,
            toggleSelectAll,
            toggleSelectFolder,
            toggleFolder,
            expandAll,
            collapseAll,
            clearSelection,
            typeIcon,
            typeStyle,
            tipoLabel,
            isFolderFullySelected,
            isFolderPartiallySelected,
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
            <!-- Árbol + card edición: layout 2 columnas (1/3 + 2/3) -->
            <div v-else class="flex-1 min-h-0 grid grid-cols-3 gap-4">
                <!-- Columna izquierda 1/3: árbol compacto (sin columnas de metadata) -->
                <div class="col-span-1 flex flex-col bg-surface-raised border border-line rounded p-5 gap-3 min-h-0" data-testid="block-editor-tree-card">
                    <!-- Header: titulo+subtitulo (izq) | contador+limpiar (der) -->
                    <div class="flex items-start justify-between gap-3">
                        <div>
                            <h3 class="text-sm font-bold text-ink">Selección de bloques</h3>
                            <p class="text-xs text-ink-muted mt-1">FASE 1 — selección read-only.</p>
                        </div>
                        <div class="flex items-center gap-3 text-xs shrink-0">
                            <span class="text-ink-muted">{{ totalSelected }} seleccionados</span>
                            <button v-if="totalSelected > 0" @click="clearSelection" class="text-ink-muted hover:text-ink underline">Limpiar</button>
                        </div>
                    </div>
                    <!-- Strip de acciones: maestro + expand/collapse -->
                    <div class="flex items-center gap-3 text-xs flex-wrap">
                        <label class="flex items-center gap-2">
                            <input type="checkbox" :checked="totalSelected === tree.totalBlocks" :indeterminate.prop="totalSelected > 0 && totalSelected < tree.totalBlocks" @change="toggleSelectAll" data-testid="block-editor-select-all" />
                            <span>Seleccionar todos ({{ tree.totalBlocks }} bloques)</span>
                        </label>
                        <button @click="expandAll" class="text-xs text-ink-muted hover:text-ink underline" data-testid="block-editor-expand-all">Expandir todo</button>
                        <button @click="collapseAll" class="text-xs text-ink-muted hover:text-ink underline" data-testid="block-editor-collapse-all">Colapsar todo</button>
                    </div>
                    <!-- Árbol único vertical estilo TIA Portal (compactado: solo pastilla + nombre) -->
                    <div class="flex-1 min-h-0 overflow-y-auto bg-surface-raised border border-line rounded text-xs" data-testid="block-editor-tree">
                        <div v-for="node in tree.nodes" :key="node.id" class="flex items-center gap-2 px-2 py-0.5 hover:bg-surface-sunken" :style="{ paddingLeft: (node.depth * 16 + 4) + 'px' }" :data-testid="'block-editor-' + node.kind + '-' + (node.kind === 'folder' ? node.fullPath : node.block.nombre)">
                            <!-- Chevron para carpetas con hijos -->
                            <span v-if="node.kind === 'folder' && node.hasChildren" class="cursor-pointer select-none w-4 inline-flex items-center justify-center text-gray-500 hover:text-gray-700" @click="toggleFolder(node.fullPath)">{{ node.expanded ? '▼' : '▶' }}</span>
                            <span v-else-if="node.kind === 'folder'" class="w-4"></span>
                            <span v-else class="w-4"></span>
                            <!-- Checkbox -->
                            <input v-if="node.kind === 'folder'" type="checkbox" :checked="isFolderFullySelected(node)" :indeterminate.prop="isFolderPartiallySelected(node)" @change="toggleSelectFolder(node)" :data-testid="'block-editor-folder-select-' + node.fullPath" class="shrink-0" />
                            <input v-else type="checkbox" :checked="selectedKeys.has(node.block.nombre)" @change="toggleSelect(node.block.nombre)" :data-testid="'block-editor-row-' + node.block.nombre" class="shrink-0" />
                            <!-- Icono pastilla + nombre (sin columnas de numero/tipo/ruta) -->
                            <span v-if="node.kind === 'block'" :style="typeStyle(node.block.tipo)" class="shrink-0" :data-tipo="node.block.tipo" :title="node.block.tipo">{{ tipoLabel(node.block.tipo) }}</span>
                            <span v-else class="w-4 text-center shrink-0" aria-hidden="true">{{ node.expanded ? '📂' : '📁' }}</span>
                            <span :class="node.kind === 'folder' ? 'font-semibold text-ink' : 'font-mono text-ink'" class="truncate">{{ node.name }}</span>
                            <span v-if="node.kind === 'folder' && node.hasChildren" class="text-ink-muted">({{ node.descendantCount }} bloques)</span>
                        </div>
                    </div>
                </div>
                <!-- Columna derecha 2/3: card edición (placeholder FASE 2) -->
                <div class="col-span-2 flex flex-col bg-surface-raised border border-line rounded p-5 gap-3 min-h-0" data-testid="block-editor-edit-card">
                    <div>
                        <h3 class="text-sm font-bold text-ink">Edición de propiedades</h3>
                        <p class="text-xs text-ink-muted mt-1">FASE 2 — edición transaccional pendiente.</p>
                    </div>
                    <div class="flex-1 min-h-0 flex flex-col items-center justify-center border border-dashed border-line rounded bg-surface-sunken text-xs text-ink-muted gap-2 p-6 text-center">
                        <span class="text-3xl opacity-40">🛠️</span>
                        <p>
                            <span v-if="totalSelected > 0">{{ totalSelected }} bloques seleccionados. La edición transaccional se implementará en FASE 2.</span>
                            <span v-else>Selecciona bloques en el árbol para empezar.</span>
                        </p>
                    </div>
                    <div class="flex justify-end pt-3 border-t border-line">
                        <button disabled class="px-4 py-2 rounded text-sm font-semibold bg-surface-sunken text-ink-muted cursor-not-allowed" data-testid="block-editor-apply">Aplicar (FASE 2)</button>
                    </div>
                </div>
            </div>
        </section>
    `,
};
