/**
 * Componente ProcesosPanel.
 *
 * Panel que se muestra cuando ``store.activeMainTab === 'procesos'``.
 * Contiene los 4 dominios del Excel corporativo (Fase 6) en
 * sub-tabs, con la misma estética que ``DispositivosPanel``:
 *
 *   - Procesos             → ``store.memoryState.procesos``
 *   - Parámetros Enteros   → ``store.memoryState.parametros_int``
 *   - Parámetros Reales    → ``store.memoryState.parametros_real``
 *   - Alarmas              → ``store.memoryState.alarmas``
 *
 * Sin banner ámbar. El "Inspector vacío" idéntico al de
 * ``DispositivosPanel`` (mismo emoji, mismo copy, mismas
 * clases) se muestra cuando ``!hasMemory``: no hay Excel
 * cargado, o los 4 dominios de software están vacíos (caso del
 * "Refrescar Memoria" sin Excel o Excel de solo dispositivos).
 * Estructura idéntica a ``DispositivosPanel``: sub-tabs y
 * "Inspector vacío" protegidos por el mismo ``v-if="hasMemory"``
 * del computed, tablas con ``v-if="hasMemory && activeSoftwareTab"``.
 *
 * Reemplaza los 4 ``<details>`` que tenía ``DefinicionProgramacion``
 * (líneas 292-433). Misma forma de tabla, mismas columnas; solo
 * cambia el contenedor (sub-tab activo en lugar de ``<details>``
 * plegable). Esto da simetría visual con ``DispositivosPanel`` y
 * elimina la sensación de "anexo".
 *
 * Tema: Industrial Claro. Solo tokens semánticos
 * (``bg-surface*``, ``border-line*``, ``text-ink*``, ``text-accent``,
 * ``bg-amber-*``, ``text-amber-*``).
 *
 * IMPORTANTE sobre templates Vue: el compilador en runtime de
 * `vue.esm-browser.prod.js` NO acepta string literals multi-línea
 * dentro de arrays de `:class`. Cada literal va en una sola línea.
 */
import { computed, ref } from "/js/vendor/vue.esm-browser.prod.js";
import { store } from "/js/store.js";

export default {
    name: "ProcesosPanel",
    setup() {
        // 4 dominios de software. Defensivos: si el operario aún
        // no ha subido Excel o el backend aún no expone los 4
        // campos nuevos, todos devuelven ``[]``.
        const procesos = computed(
            () => (store.memoryState && store.memoryState.procesos) || []
        );
        const parametrosInt = computed(
            () => (store.memoryState && store.memoryState.parametros_int) || []
        );
        const parametrosReal = computed(
            () => (store.memoryState && store.memoryState.parametros_real) || []
        );
        const alarmas = computed(
            () => (store.memoryState && store.memoryState.alarmas) || []
        );

        /**
         * ``true`` solo cuando hay Excel cargado Y al menos uno de los
         * 4 dominios de software tiene datos. Es la condición que
         * alterna entre las 4 tablas y el "Inspector vacío" idéntico
         * al de ``DispositivosPanel``. Coherencia total entre los 2
         * tabs: sin Excel → mismo cuadro centrado con emoji.
         */
        const hasMemory = computed(
            () => {
                // ``hasMemory`` distingue 2 estados visuales (mismo
                // patron que ``DispositivosPanel`` para coherencia
                // total entre los 2 tabs):
                //   1. ``store.memoryState === null``: operario no ha
                //      hecho nunca un fetch (estado "virgen"). Se
                //      muestra el "Inspector vacío" centrado.
                //   2. ``store.memoryState`` es un objeto (incluso con
                //      arrays vacios, p.ej. tras "Refrescar" sin
                //      Excel): se muestran las tablas. Cada tabla
                //      pinta su propio mensaje "Sin X definidos" si
                //      su lista esta vacia (eso lo hace el
                //      ``<tr v-if="...">``).
                return store.memoryState !== null
                    && store.memoryState !== undefined;
            }
        );

        /**
         * Sub-tab activo. Una de
         * ``'procesos' | 'parametros_int' | 'parametros_real' | 'alarmas'``.
         * Default: ``'procesos'`` (suele ser la lista más corta y
         * cabecera del resto).
         */
        const activeSoftwareTab = ref("procesos");

        return {
            procesos,
            parametrosInt,
            parametrosReal,
            alarmas,
            hasMemory,
            activeSoftwareTab,
        };
    },
    template: /* html */ `
        <div class="flex-1 flex flex-col overflow-hidden">

            <!-- Sub-tabs de software (Procesos | PInt | PReal | Alarmas).
                 Solo visibles si hay datos (mismo patron que
                 DispositivosPanel, que oculta los sub-tabs cuando
                 !hasMemory). -->
            <div v-if="hasMemory" class="flex border-b border-line bg-surface-sunken overflow-x-auto">
                <button @click="activeSoftwareTab = 'procesos'"
                    :class="['tab-btn px-4 py-2 text-xs font-medium border-r border-line whitespace-nowrap',
                             activeSoftwareTab === 'procesos' ? 'active' : 'bg-surface-raised text-ink-muted hover:bg-surface-sunken']">
                    Procesos
                    <span class="ml-1 text-[10px] opacity-70">({{ procesos.length }})</span>
                </button>
                <button @click="activeSoftwareTab = 'parametros_int'"
                    :class="['tab-btn px-4 py-2 text-xs font-medium border-r border-line whitespace-nowrap',
                             activeSoftwareTab === 'parametros_int' ? 'active' : 'bg-surface-raised text-ink-muted hover:bg-surface-sunken']">
                    Parámetros Enteros
                    <span class="ml-1 text-[10px] opacity-70">({{ parametrosInt.length }})</span>
                </button>
                <button @click="activeSoftwareTab = 'parametros_real'"
                    :class="['tab-btn px-4 py-2 text-xs font-medium border-r border-line whitespace-nowrap',
                             activeSoftwareTab === 'parametros_real' ? 'active' : 'bg-surface-raised text-ink-muted hover:bg-surface-sunken']">
                    Parámetros Reales
                    <span class="ml-1 text-[10px] opacity-70">({{ parametrosReal.length }})</span>
                </button>
                <button @click="activeSoftwareTab = 'alarmas'"
                    :class="['tab-btn px-4 py-2 text-xs font-medium border-r border-line whitespace-nowrap',
                             activeSoftwareTab === 'alarmas' ? 'active' : 'bg-surface-raised text-ink-muted hover:bg-surface-sunken']">
                    Alarmas
                    <span class="ml-1 text-[10px] opacity-70">({{ alarmas.length }})</span>
                </button>
            </div>

            <!-- Contenedor SIEMPRE presente (estructura idéntica a
                 DispositivosPanel). Dentro: si hay Excel, la tabla
                 del sub-tab activo; si NO hay Excel, el "Inspector
                 vacío" centrado heredando el background del
                 contenedor. -->
            <div class="flex-1 overflow-auto table-scroll-x mt-2 bg-surface-raised border border-line rounded">

                <!-- Procesos -->
                <table v-if="hasMemory && activeSoftwareTab === 'procesos'" class="w-full text-xs">
                    <thead class="sticky top-0 bg-surface-sunken text-[10px] uppercase">
                        <tr>
                            <th class="px-3 py-2 text-left text-ink-muted">UID</th>
                            <th class="px-3 py-2 text-left text-ink-muted">Código</th>
                            <th class="px-3 py-2 text-left text-ink-muted">Nombre</th>
                            <th class="px-3 py-2 text-left text-ink-muted">PReal</th>
                            <th class="px-3 py-2 text-left text-ink-muted">PInt</th>
                            <th class="px-3 py-2 text-left text-ink-muted">Alarmas</th>
                        </tr>
                    </thead>
                    <tbody>
                        <tr v-for="p in procesos" :key="p.uid" class="border-b border-line">
                            <td class="px-3 py-1.5 font-mono">{{ p.uid }}</td>
                            <td class="px-3 py-1.5 font-mono">{{ p.codigo }}</td>
                            <td class="px-3 py-1.5">{{ p.nombre }}</td>
                            <td class="px-3 py-1.5">{{ p.preal }}</td>
                            <td class="px-3 py-1.5">{{ p.pint }}</td>
                            <td class="px-3 py-1.5">{{ p.alarmas }}</td>
                        </tr>
                        <tr v-if="procesos.length === 0">
                            <td colspan="6" class="px-3 py-6 text-center text-ink-muted italic">
                                ⚠️ Sin procesos definidos.
                            </td>
                        </tr>
                    </tbody>
                </table>

                <!-- Parámetros Enteros -->
                <table v-else-if="hasMemory && activeSoftwareTab === 'parametros_int'" class="w-full text-xs">
                    <thead class="sticky top-0 bg-surface-sunken text-[10px] uppercase">
                        <tr>
                            <th class="px-3 py-2 text-left text-ink-muted">UID</th>
                            <th class="px-3 py-2 text-left text-ink-muted">Nº</th>
                            <th class="px-3 py-2 text-left text-ink-muted">Código</th>
                            <th class="px-3 py-2 text-left text-ink-muted">Num.DB</th>
                            <th class="px-3 py-2 text-left text-ink-muted">Num.Lista</th>
                            <th class="px-3 py-2 text-left text-ink-muted">Txt.Lista</th>
                            <th class="px-3 py-2 text-left text-ink-muted">Descripción</th>
                        </tr>
                    </thead>
                    <tbody>
                        <tr v-for="p in parametrosInt" :key="p.uid" class="border-b border-line">
                            <td class="px-3 py-1.5 font-mono">{{ p.uid }}</td>
                            <td class="px-3 py-1.5 font-mono">{{ p.numero }}</td>
                            <td class="px-3 py-1.5 font-mono">{{ p.codigo }}</td>
                            <td class="px-3 py-1.5 font-mono">{{ p.num_db }}</td>
                            <td class="px-3 py-1.5 font-mono">{{ p.num_lista }}</td>
                            <td class="px-3 py-1.5">{{ p.txt_lista }}</td>
                            <td class="px-3 py-1.5">{{ p.descripcion }}</td>
                        </tr>
                        <tr v-if="parametrosInt.length === 0">
                            <td colspan="7" class="px-3 py-6 text-center text-ink-muted italic">
                                ⚠️ Sin parámetros enteros definidos.
                            </td>
                        </tr>
                    </tbody>
                </table>

                <!-- Parámetros Reales -->
                <table v-else-if="hasMemory && activeSoftwareTab === 'parametros_real'" class="w-full text-xs">
                    <thead class="sticky top-0 bg-surface-sunken text-[10px] uppercase">
                        <tr>
                            <th class="px-3 py-2 text-left text-ink-muted">UID</th>
                            <th class="px-3 py-2 text-left text-ink-muted">Nº</th>
                            <th class="px-3 py-2 text-left text-ink-muted">Código</th>
                            <th class="px-3 py-2 text-left text-ink-muted">Num.DB</th>
                            <th class="px-3 py-2 text-left text-ink-muted">Num.Lista</th>
                            <th class="px-3 py-2 text-left text-ink-muted">Txt.Lista</th>
                            <th class="px-3 py-2 text-left text-ink-muted">Descripción</th>
                        </tr>
                    </thead>
                    <tbody>
                        <tr v-for="p in parametrosReal" :key="p.uid" class="border-b border-line">
                            <td class="px-3 py-1.5 font-mono">{{ p.uid }}</td>
                            <td class="px-3 py-1.5 font-mono">{{ p.numero }}</td>
                            <td class="px-3 py-1.5 font-mono">{{ p.codigo }}</td>
                            <td class="px-3 py-1.5 font-mono">{{ p.num_db }}</td>
                            <td class="px-3 py-1.5 font-mono">{{ p.num_lista }}</td>
                            <td class="px-3 py-1.5">{{ p.txt_lista }}</td>
                            <td class="px-3 py-1.5">{{ p.descripcion }}</td>
                        </tr>
                        <tr v-if="parametrosReal.length === 0">
                            <td colspan="7" class="px-3 py-6 text-center text-ink-muted italic">
                                ⚠️ Sin parámetros reales definidos.
                            </td>
                        </tr>
                    </tbody>
                </table>

                <!-- Alarmas -->
                <table v-else-if="hasMemory && activeSoftwareTab === 'alarmas'" class="w-full text-xs">
                    <thead class="sticky top-0 bg-surface-sunken text-[10px] uppercase">
                        <tr>
                            <th class="px-3 py-2 text-left text-ink-muted">UID</th>
                            <th class="px-3 py-2 text-left text-ink-muted">Nº</th>
                            <th class="px-3 py-2 text-left text-ink-muted">Proceso</th>
                            <th class="px-3 py-2 text-left text-ink-muted">Num.DB</th>
                            <th class="px-3 py-2 text-left text-ink-muted">Descripción</th>
                        </tr>
                    </thead>
                    <tbody>
                        <tr v-for="a in alarmas" :key="a.uid" class="border-b border-line">
                            <td class="px-3 py-1.5 font-mono">{{ a.uid }}</td>
                            <td class="px-3 py-1.5 font-mono">{{ a.numero }}</td>
                            <td class="px-3 py-1.5">{{ a.proceso }}</td>
                            <td class="px-3 py-1.5 font-mono">{{ a.num_db }}</td>
                            <td class="px-3 py-1.5">{{ a.descripcion }}</td>
                        </tr>
                        <tr v-if="alarmas.length === 0">
                            <td colspan="5" class="px-3 py-6 text-center text-ink-muted italic">
                                ⚠️ Sin alarmas definidas.
                            </td>
                        </tr>
                    </tbody>
                </table>

                <!-- "Inspector vacío" idéntico al de DispositivosPanel:
                     mismo copy, mismo emoji, mismas clases (heredadas
                     del contenedor padre). Se muestra cuando !hasMemory
                     (no hay Excel cargado o ningún dominio tiene datos). -->
                <div v-else class="flex-1 flex items-center justify-center p-10 text-center text-ink-muted">
                    <div>
                        <div class="text-5xl mb-3 opacity-40">📊</div>
                        <p class="mb-2">La cache del excel está vacía.</p>
                        <p class="text-xs">Sube un Excel y pulsa <strong class="text-accent">"Actualizar"</strong>.</p>
                    </div>
                </div>

            </div>

        </div>
    `,
};
