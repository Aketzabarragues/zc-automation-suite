/**
 * Componente ``blockpropertieseditor``.
 *
 * Vista shell transversal sobre la cache
 * ``store.appCache.plc_blocks[<plc>]``. Muestra el arbol jerarquico
 * MULTI-NIVEL estilo TIA Portal: un unico arbol con indentacion
 * progresiva, expansion/colapso por categoria, seleccion multiple
 * por bloque y por carpeta (recursivo sobre descendientes).
 *
 * Al pulsar "Editar" llama a ``apiBlockEditPrepare``
 * (FB ``block_edit_prepare``), que re-lee TIA + exporta SD +
 * parsea SCL y rellena
 * ``app_cache.block_edit_prepared[plc_name]`` con DTOs de 10
 * campos. Tras el OK, ``apiGetPreparedBlocks`` devuelve el cache
 * y la SPA pinta la tabla editable inline para Name + Number.
 * El boton "Aplicar" envia ``apiBlockEditApply`` (FB
 * ``block_edit_apply``, transaccion atomica con rollback). El FB
 * refresca el snapshot del PLC en su ultimo step y limpia
 * ``block_edit_prepared[plc]``; tras el OK la SPA vuelve a ``idle``
 * y el operario pulsa "Editar" de nuevo para un prepare fresco.
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
 * Convencion de paths (sept-2026):
 *   - Tree blocks (``b.ruta``) pueden llegar con ``\``, ``/`` o
 *     mezcla (TIA SDK inconsistente entre jerarquias).
 *     ``buildFolderTree`` normaliza a ``/`` antes de splitear.
 *   - Backend FBs ``block_edit_prepare`` / ``block_edit_apply``
 *     usan separador ``/`` (param ``selected_block_paths`` y
 *     keys del dict ``edits``).
 *   - El helper ``toBackendPath(ruta)`` hace la conversion
 *     defensiva en una sola direccion al cruzar la frontera IT/OT.
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
    reactive,
    ref,
} from "/js/vendor/vue.esm-browser.prod.js";
import { store } from "/js/store.js";
import {
    apiBlockEditApply,
    apiBlockEditPrepare,
    apiGetPreparedBlocks,
} from "../api.js";

const STALE_AFTER_MS = 5 * 60 * 1000;
const _TIPO_ORDER = ["OB", "FC", "FB", "DB", "UDT", "OTHER"];
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
                // Normaliza el separador: TIA SDK puede devolver paths
                // con ``/`` o ``\`` segun la jerarquia. Sin esto,
                // ``split("\\")`` deja ``"ZC_Estandar_Alimentacion/000..."``
                // como un solo segmento y el arbol no anida (se ve como
                // carpeta con ``/`` literal en el nombre).
                const ruta = String(b.ruta || "")
                    .replace(/\\/g, "/")
                    .replace(/^\/+|\/+$/g, "")
                    .trim();
                if (!ruta) { root.blocks.push(b); continue; }
                const segs = ruta.split("/").filter((s) => s.length > 0);
                let cur = root;
                let curPath = "";
                for (let i = 0; i < segs.length; i++) {
                    const seg = segs[i];
                    curPath = curPath ? curPath + "/" + seg : seg;
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
                    // Raíz visual: NO se renderiza como fila, solo emite bloques sueltos
                    // y carpetas (hijos). Bloques primero (orden OB/FC/FB/DB), carpetas
                    // después, replicando el orden del árbol de TIA Portal.
                    for (const b of folder.blocks) {
                        nodes.push({ kind: "block", id: "block:" + b.nombre, depth, block: b, name: b.nombre });
                    }
                    for (const child of folder.children.values()) visit(child, depth + 1, true);
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
                // Bloques sueltos primero (orden OB/FC/FB/DB), carpetas (hijos) después.
                for (const b of folder.blocks) {
                    nodes.push({ kind: "block", id: "block:" + b.nombre, depth: depth + 1, block: b, name: b.nombre });
                }
                for (const child of folder.children.values()) visit(child, depth + 1, true);
            }
            visit(root, 0, true);
            return nodes;
        }

        const expandedFolders = ref(new Set());
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
            // Arbol colapsado por defecto: el operario pulsa "Expandir
            // todo" o clica cada chevron. ``expandedFolders`` parte
            // vacio; cualquier eleccion manual posterior (chevron click
            // o expandAll) se respeta en renders siguientes.
            const nodes = flattenFolderTree(root, expandedFolders.value);
            return { nodes, totalBlocks: list.length, root };
        });

        const selectedKeys = ref(new Set());
        const totalSelected = computed(() => selectedKeys.value.size);
        const canContinue = computed(() => totalSelected.value > 0);

        // Modo del card derecho: "idle" muestra el placeholder FASE 1;
        // "preparing" muestra spinner mientras /prepare corre;
        // "editing" muestra la tabla editable inline con los 7 campos
        // visibles del DTO (Tipo, Name, Number, Title, Comment, Author,
        // Version). Los otros 3 (``programming_language``,
        // ``memory_layout``, ``ruta``) vienen en el DTO pero no se
        // renderizan en la UI.
        const editMode = ref("idle");
        const canEdit = computed(
            () => totalSelected.value > 0 && editMode.value === "idle"
        );
        // El card del arbol se bloquea en cuanto el operario abandona el
        // modo idle (preparando, editing, applying, error). Asi no
        // puede modificar la seleccion mientras ``preparedBlocks``
        // esta fijado en el FB. Se aplica ``pointer-events-none`` +
        // ``opacity-50`` al card completo (no a controles
        // individuales): un solo sitio, un solo estado, una sola
        // pista visual. El card gris + no-clickable deja claro que
        // la seleccion esta fijada hasta que termine la operacion.
        const treeLocked = computed(() => editMode.value !== "idle");
        const selectedBlocks = computed(() => {
            // Itera sobre TODOS los bloques del cache (``blocks.value``),
            // NO sobre ``tree.value.nodes``. Los nodos visibles son solo
            // un subconjunto (carpetas colapsadas ocultan sus hijos);
            // si el operario selecciona una carpeta colapsada,
            // ``selectedKeys`` contiene los descendientes pero no aparecen
            // en ``tree.nodes``. Filtrar por ``blocks.value`` mantiene
            // coherencia con ``totalSelected`` (``selectedKeys.size``) y
            // permite que ``startEdit`` envie al backend todos los
            // bloques seleccionados.
            const sel = selectedKeys.value;
            const list = blocks.value;
            if (!Array.isArray(list) || list.length === 0) return [];
            const out = [];
            for (const b of list) {
                if (b && sel.has(b.nombre)) {
                    out.push(b);
                }
            }
            return out;
        });

        // Conversion de paths IT (separador "\\") a paths del backend FB
        // (separador "/"). El FB ``block_edit_prepare`` parsea con
        // ``path.split("/")``: el ultimo segmento es el nombre del bloque
        // y el resto es la jerarquia de grupos. Si le llega "\\" se queda
        // como un solo segmento y la busqueda en TIA falla.
        function toBackendPath(ruta, nombre) {
            // El FB ``block_edit_prepare`` parsea el path con
            // ``split("/")``: el ultimo segmento es el nombre del bloque y
            // el resto es la jerarquia de grupos. ``b.ruta`` del arbol
            // solo contiene la jerarquia (vacia para bloques en raiz); si
            // no concatenamos el nombre, el parser se queda con parts=[""]
            // y ``_find_block_in_plc`` falla con name="" y path="".
            const normRuta = String(ruta || "")
                .replace(/\\/g, "/")
                .replace(/^\/+|\/+$/g, "");
            const nombreNorm = String(nombre || "").trim();
            if (!nombreNorm) return normRuta;
            return normRuta ? `${normRuta}/${nombreNorm}` : nombreNorm;
        }

        // DTOs recibidos del endpoint GET /prepared, en el mismo orden
        // que ``selectedBlocks``. Cada entrada tiene los 10 campos del
        // ``DataBloquePLC`` (``nombre``, ``numero``, ``tipo``, ``ruta``,
        // ``title``, ``comment``, ``author``, ``version``,
        // ``programming_language``, ``memory_layout``) + ``path``
        // (key del dict backend, separador "/"). La UI renderiza 7
        // columnas (Tipo, Name*, Number*, Title, Comment, Author,
        // Version); los otros 3 (``ruta``, ``programming_language``,
        // ``memory_layout``) quedan en el dict para uso interno /
        // debug y no se muestran.
        const preparedBlocks = ref([]);
        const preparedBlocksByPath = computed(() => {
            const map = {};
            for (const b of preparedBlocks.value) {
                if (b && b.path) map[b.path] = b;
            }
            return map;
        });

        // Pendientes de Name/Number keyed por path backend ("/").
        // Estructura: ``{ "<path>": { name?: str, number?: int } }``.
        // Solo se anade una key cuando el operario edita; los inputs
        // que coinciden con el original NO contaminan el dict, asi
        // el apply solo envia diffs reales. Las keys coinciden con
        // la whitelist del FB ``block_edit_apply`` (name/number),
        // por lo que ``pendingEdits`` se envia tal cual al endpoint.
        const pendingEdits = reactive({});

        const pendingChangesCount = computed(
            () => Object.keys(pendingEdits).length
        );
        const hasChanges = computed(
            () => pendingChangesCount.value > 0
        );

        // Estado de las llamadas async contra los 2 FBs.
        // ``operationStatus`` separa preparing/applying del resto para
        // que el template pueda mostrar spinners / deshabilitar botones
        // independientes en cada fase.
        const operationStatus = ref("idle");  // "idle" | "preparing" | "applying" | "error"
        const operationError = ref("");

        function resetEditState() {
            preparedBlocks.value = [];
            // ``pendingEdits`` es reactive: borramos keys explicitamente
            // (no se puede reasignar ``pendingEdits = {}`` sin perder
            // la reactividad).
            for (const k of Object.keys(pendingEdits)) delete pendingEdits[k];
            operationStatus.value = "idle";
            operationError.value = "";
        }

        async function startEdit() {
            const blocks = selectedBlocks.value;
            if (!blocks || blocks.length === 0) return;
            const plc = selectedPlc.value;
            if (!plc) return;
            // Conversion IT ("\\") -> backend ("/") una sola vez.
            const paths = blocks.map((b) => toBackendPath(b.ruta, b.nombre));

            editMode.value = "editing";
            operationStatus.value = "preparing";
            operationError.value = "";
            preparedBlocks.value = [];

            const resp = await apiBlockEditPrepare(plc, paths);
            if (!resp.ok || !resp.data || !resp.data.ok) {
                operationStatus.value = "error";
                operationError.value =
                    (resp.data && resp.data.error) ||
                    `HTTP ${resp.status} en /prepare`;
                return;
            }

            // Pull del cache ``block_edit_prepared[plc]`` (NO viene en
            // el body de /prepare: solo trae resumenes).
            const preparedResp = await apiGetPreparedBlocks(plc);
            if (!preparedResp.ok || !preparedResp.data || !preparedResp.data.ok) {
                operationStatus.value = "error";
                operationError.value =
                    (preparedResp.data && preparedResp.data.error) ||
                    `HTTP ${preparedResp.status} en /prepared`;
                return;
            }
            const preparedMap = preparedResp.data.prepared || {};
            // Convertir dict (keyed por path) a array con ``path`` inyectado
            // como campo (necesario para iterar en la tabla y para usarlo
            // como key de ``pendingEdits``).
            const arr = [];
            for (const path of Object.keys(preparedMap)) {
                const dto = preparedMap[path] || {};
                arr.push({ path, ...dto });
            }
            preparedBlocks.value = arr;
            operationStatus.value = "idle";
        }

        function cancelEdit() {
            editMode.value = "idle";
            resetEditState();
        }

        /**
         * Getter/setter virtual sobre ``pendingEdits[path][field]``.
         *
         * Reglas:
         *   - Si ``value`` coincide con el original del DTO preparado
         *     -> borra la key del dict (no es un cambio real).
         *   - Si difiere -> guarda ``{name|number: value}``.
         *   - Si tras borrar el campo el dict de la path queda vacio
         *     -> borra tambien la entrada ``pendingEdits[path]``.
         *
         * Usado por los ``:value`` / ``@input`` de los inputs Name/Number
         * para que el ``pendingChangesCount`` y ``hasChanges`` reflejen
         * solo diffs reales (no "edite y volvi al mismo valor").
         */
        function getPendingValue(path, field) {
            const original = preparedBlocksByPath.value[path];
            if (!original) return "";
            const pending = pendingEdits[path];
            if (pending && Object.prototype.hasOwnProperty.call(pending, field)) {
                return pending[field];
            }
            return original[field] ?? "";
        }
        function setPendingValue(path, field, value) {
            const original = preparedBlocksByPath.value[path];
            if (!original) return;
            const origVal = original[field];
            // Comparar normalizando: number puede venir como int vs string
            // desde el input HTML (los ``<input type="number">`` siempre
            // emiten string, hay que convertir).
            const isSame = field === "numero"
                ? Number(value) === Number(origVal)
                : String(value) === String(origVal ?? "");
            if (isSame) {
                if (pendingEdits[path]) {
                    delete pendingEdits[path][field];
                    if (Object.keys(pendingEdits[path]).length === 0) {
                        delete pendingEdits[path];
                    }
                }
                return;
            }
            if (!pendingEdits[path]) pendingEdits[path] = {};
            pendingEdits[path][field] = field === "numero" ? Number(value) : String(value);
        }

        async function applyEdits() {
            const plc = selectedPlc.value;
            if (!plc) return;
            if (!hasChanges.value) return;
            // Snapshot del dict reactivo (las keys se borran en
            // cancelEdit / startEdit, copiamos para que el await no
            // vea mutaciones).
            //
            // Traduccion DTO -> contrato de edicion: los inputs usan los
            // nombres de campo del DTO (``nombre``/``numero``, español,
            // ver ``DataBloquePLC``), pero el endpoint ``POST /apply``
            // espera las keys del contrato de edicion (``name``/``number``,
            // inglés, que es lo que valida el FB contra
            // ``_ALLOWED_EDIT_KEYS``). Sin esta traduccion el FB rechaza
            // el payload con ``ValueError: key 'nombre' no permitida``.
            // El mapeo field->property vive aqui (borde IT/OT), no en
            // el backend: asi el API habla un solo vocabulario.
            const edits = {};
            for (const path of Object.keys(pendingEdits)) {
                const src = pendingEdits[path];
                const dst = {};
                if (Object.prototype.hasOwnProperty.call(src, "nombre")) {
                    dst.name = src.nombre;
                }
                if (Object.prototype.hasOwnProperty.call(src, "numero")) {
                    dst.number = src.numero;
                }
                if (Object.keys(dst).length > 0) {
                    edits[path] = dst;
                }
            }

            operationStatus.value = "applying";
            operationError.value = "";

            const resp = await apiBlockEditApply(plc, edits);
            if (!resp.ok || !resp.data || !resp.data.ok) {
                operationStatus.value = "error";
                operationError.value =
                    (resp.data && resp.data.error) ||
                    `HTTP ${resp.status} en /apply`;
                return;
            }

            // No hay que re-escanear aqui: el ultimo step del FB
            // (``Refrescar cache``) ya llama a
            // ``scan_plc_blocks(force_refresh=True)`` y ademas limpia
            // ``block_edit_prepared[plc]``. Repetirlo desde la SPA
            // costaba un segundo scan completo de 15-26s sobre el PLC
            // (173 bloques) por cada apply.
            //
            // Tras un apply el estado en TIA cambio (nombres/numeros
            // nuevos), asi que la seleccion del arbol y los
            // ``pendingEdits`` keyed por ``path`` (que codifica el
            // nombre viejo) quedaron invalidos. Se vuelve a ``idle``
            // y el operario tiene que pulsar "Editar" de nuevo para
            // un ``prepare`` fresco contra el estado real de TIA.
            //
            // ``clearSelection`` es obligatorio, no cosmetico:
            // ``selectedKeys`` guarda NOMBRES de bloque. Si el apply
            // renombro ``test`` -> ``FC11_TEST``, la cache ya tiene el
            // nombre nuevo pero ``selectedKeys`` sigue teniendo
            // ``test``. El siguiente ``startEdit`` calcula
            // ``selectedBlocks`` filtrando ``blocks.value`` por
            // ``selectedKeys``, no encuentra match y aborta en
            // silencio ("no hace nada"). En vivo:
            //   _find_block_in_plc: no se encontro bloque 'test'
            // tras haberlo renombrado en el apply anterior.
            clearSelection();
            editMode.value = "idle";
            resetEditState();
        }

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
            editMode,
            canEdit,
            treeLocked,
            selectedBlocks,
            preparedBlocks,
            preparedBlocksByPath,
            pendingEdits,
            pendingChangesCount,
            hasChanges,
            operationStatus,
            operationError,
            startEdit,
            cancelEdit,
            applyEdits,
            getPendingValue,
            setPendingValue,
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
        <section class="flex-1 flex flex-col overflow-hidden gap-4" data-testid="block-editor-root">
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
                <div class="col-span-1 flex flex-col bg-surface-raised border border-line rounded p-5 gap-3 min-h-0" :class="treeLocked ? 'pointer-events-none opacity-50' : ''" data-testid="block-editor-tree-card">
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
                            <!-- Chevron para carpetas con hijos.
                                \uFE0E = variation selector 15 (text presentation):
                                fuerza al navegador a pintar el glifo como
                                texto plano (gris/negro, sin fondo). Sin el
                                VS-15, U+25B6 lo renderiza como emoji con
                                fondo cuadrado azul + flecha blanca en
                                algunos fonts del sistema. -->
                            <span v-if="node.kind === 'folder' && node.hasChildren" class="cursor-pointer select-none w-4 inline-flex items-center justify-center text-gray-500 hover:text-gray-700" @click="toggleFolder(node.fullPath)">{{ node.expanded ? '\u25BC\uFE0E' : '\u25B6\uFE0E' }}</span>
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
                    <!-- Footer: botón "Editar" (placeholder FASE 2, simétrico con "Aplicar" der) -->
                    <div class="flex justify-end pt-3 border-t border-line">
                        <button :disabled="!canEdit" @click="startEdit" :class="canEdit ? 'bg-accent text-ink-inverse hover:bg-accent-hover cursor-pointer' : 'bg-surface-sunken text-ink-muted cursor-not-allowed'" class="px-4 py-2 rounded text-sm font-semibold" data-testid="block-editor-edit">Editar (FASE 2)</button>
                    </div>
                </div>
                <!-- Columna derecha 2/3: card edición (idle: placeholder; preparing: spinner; editing: tabla editable) -->
                <div class="col-span-2 flex flex-col bg-surface-raised border border-line rounded p-5 gap-3 min-h-0" data-testid="block-editor-edit-card">
                    <!-- Modo idle: placeholder -->
                    <div v-if="editMode === 'idle'" class="flex-1 min-h-0 flex flex-col" data-testid="block-editor-edit-placeholder">
                        <div>
                            <h3 class="text-sm font-bold text-ink">Edición de propiedades</h3>
                            <p class="text-xs text-ink-muted mt-1">FASE 2 — edición transaccional de Name / Number.</p>
                        </div>
                        <div class="flex-1 min-h-0 flex flex-col items-center justify-center border border-dashed border-line rounded bg-surface-sunken text-xs text-ink-muted gap-2 p-6 text-center">
                            <span class="text-3xl opacity-40">🛠️</span>
                            <p>
                                <span v-if="totalSelected > 0">{{ totalSelected }} bloques seleccionados. Pulsa &quot;Editar&quot; para preparar los datos contra TIA.</span>
                                <span v-else>Selecciona bloques en el árbol para empezar.</span>
                            </p>
                        </div>
                        <div class="flex justify-end pt-3 border-t border-line">
                            <button disabled class="px-4 py-2 rounded text-sm font-semibold bg-surface-sunken text-ink-muted cursor-not-allowed" data-testid="block-editor-apply">Aplicar</button>
                        </div>
                    </div>
                    <!-- Modo preparing: spinner mientras /prepare corre -->
                    <div v-else-if="editMode === 'editing' && operationStatus === 'preparing'" class="flex-1 min-h-0 flex flex-col items-center justify-center gap-3 text-xs text-ink-muted" data-testid="block-editor-preparing">
                        <span class="inline-block animate-spin text-3xl text-accent">↻</span>
                        <p>Preparando {{ selectedBlocks.length }} bloques contra TIA Portal…</p>
                        <p class="text-[10px]">Exporta SD + parsea SCL + cachea DTOs. Puede tardar 30-90s.</p>
                    </div>
                    <!-- Modo editing: tabla editable inline con 7 columnas (Tipo, Name,
                         Number, Title, Comment, Author, Version). -->
                    <div v-else class="flex-1 min-h-0 flex flex-col gap-3" data-testid="block-editor-edit-table">
                        <div>
                            <h3 class="text-sm font-bold text-ink">Edición de propiedades</h3>
                            <p class="text-xs text-ink-muted mt-1">
                                <strong class="text-ink">Name</strong> y <strong class="text-ink">Number</strong> son editables y se aplican contra TIA Portal. <strong class="text-ink">Title</strong>, <strong class="text-ink">Comment</strong>, <strong class="text-ink">Author</strong> y <strong class="text-ink">Version</strong> son solo lectura por ahora (backend pendiente de ampliar whitelist).
                            </p>
                            <p v-if="operationStatus === 'applying'" class="text-xs text-accent mt-1" data-testid="block-editor-applying">
                                <span class="inline-block animate-spin mr-1">↻</span>
                                Aplicando cambios en TIA Portal (transacción atómica, puede tardar minutos)…
                            </p>
                            <p v-if="operationStatus === 'error'" class="text-xs text-red-600 mt-1" data-testid="block-editor-error">
                                ✗ {{ operationError }}
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
                                    <tr v-for="block in preparedBlocks" :key="block.path" class="border-t border-line" :data-testid="'block-editor-edit-row-' + block.nombre">
                                        <!-- Tipo: badge compacto. No se expande. -->
                                        <td class="px-2 py-1 whitespace-nowrap">
                                            <span :style="typeStyle(block.tipo)" class="shrink-0" :data-tipo="block.tipo" :title="block.tipo">{{ tipoLabel(block.tipo) }}</span>
                                        </td>
                                        <!-- Name / Number: editables (backend los aplica via whitelist). -->
                                        <td class="px-2 py-1">
                                            <input type="text"
                                                :value="getPendingValue(block.path, 'nombre')"
                                                @input="setPendingValue(block.path, 'nombre', $event.target.value)"
                                                :disabled="operationStatus === 'applying'"
                                                class="font-mono px-1 py-0.5 rounded w-full border border-line bg-surface-raised text-ink focus:outline-none focus:border-line-strong"
                                                :data-testid="'block-editor-input-name-' + block.nombre" />
                                        </td>
                                        <td class="px-2 py-1">
                                            <input type="number"
                                                :value="getPendingValue(block.path, 'numero')"
                                                @input="setPendingValue(block.path, 'numero', $event.target.value)"
                                                :disabled="operationStatus === 'applying'"
                                                class="font-mono px-1 py-0.5 rounded w-full text-right border border-line bg-surface-raised text-ink focus:outline-none focus:border-line-strong"
                                                :data-testid="'block-editor-input-number-' + block.nombre" />
                                        </td>
                                        <!-- Title: input preparado. disabled: backend solo soporta name/number. -->
                                        <td class="px-2 py-1">
                                            <input type="text"
                                                :value="block.title ?? ''"
                                                disabled
                                                title="Title: pendiente de soporte backend (whitelist actual: name, number)"
                                                class="font-mono px-1 py-0.5 rounded w-full border border-line bg-surface-sunken text-ink-muted cursor-not-allowed"
                                                :data-testid="'block-editor-input-title-' + block.nombre" />
                                        </td>
                                        <!-- Comment: textarea readonly con resize vertical.
                                             El handle de la esquina inferior derecha sigue
                                             funcional pese al readonly. -->
                                        <td class="px-2 py-1">
                                            <textarea
                                                :value="block.comment ?? ''"
                                                readonly
                                                title="Comment: pendiente de soporte backend (whitelist actual: name, number)"
                                                style="min-height: 24px; min-width: 160px;"
                                                class="font-mono px-1 py-0.5 rounded w-full border border-line bg-surface-sunken text-ink-muted"
                                                :data-testid="'block-editor-input-comment-' + block.nombre"></textarea>
                                        </td>
                                        <!-- Author / Version: inputs preparados. disabled: idem Title. -->
                                        <td class="px-2 py-1">
                                            <input type="text"
                                                :value="block.author ?? ''"
                                                disabled
                                                title="Author: pendiente de soporte backend (whitelist actual: name, number)"
                                                class="px-1 py-0.5 rounded w-full border border-line bg-surface-sunken text-ink-muted cursor-not-allowed"
                                                :data-testid="'block-editor-input-author-' + block.nombre" />
                                        </td>
                                        <td class="px-2 py-1">
                                            <input type="text"
                                                :value="block.version ?? ''"
                                                disabled
                                                title="Version: pendiente de soporte backend (whitelist actual: name, number)"
                                                class="font-mono px-1 py-0.5 rounded w-full border border-line bg-surface-sunken text-ink-muted cursor-not-allowed"
                                                :data-testid="'block-editor-input-version-' + block.nombre" />
                                        </td>
                                    </tr>
                                </tbody>
                            </table>
                        </div>
                        <div class="flex justify-between pt-3 border-t border-line">
                            <button @click="cancelEdit"
                                :disabled="operationStatus === 'applying'"
                                :class="operationStatus === 'applying' ? 'text-ink-muted cursor-not-allowed' : 'text-ink-muted hover:text-ink underline'"
                                class="text-sm"
                                data-testid="block-editor-edit-cancel">Cancelar</button>
                            <button @click="applyEdits"
                                :disabled="!hasChanges || operationStatus === 'applying'"
                                :class="(!hasChanges || operationStatus === 'applying') ? 'bg-surface-sunken text-ink-muted cursor-not-allowed' : 'bg-accent text-ink-inverse hover:bg-accent-hover cursor-pointer'"
                                class="px-4 py-2 rounded text-sm font-semibold"
                                data-testid="block-editor-edit-apply">Aplicar ({{ pendingChangesCount }})</button>
                        </div>
                    </div>
                </div>
            </div>
        </section>
    `,
};
