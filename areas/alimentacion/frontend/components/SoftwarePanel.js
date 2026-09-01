/**
 * Componente SoftwarePanel.
 *
 * Panel que se muestra cuando ``store.activeMainTab === 'software'``.
 * Contiene los 4 dominios de software del proyecto (Fase 6) en
 * sub-tabs, con la misma estética que ``DispositivosPanel``:
 *
 *   - Procesos             → ``store.memoryState.procesos``
 *   - Parámetros Enteros   → ``store.memoryState.parametros_int``
 *   - Parámetros Reales    → ``store.memoryState.parametros_real``
 *   - Alarmas              → ``store.memoryState.alarmas``
 *
 * Si el flag ``software_parsers_implemented`` es ``false`` (modo
 * degradado: backend aún no expone los 4 campos o Excel sin hojas
 * de software), pinta arriba un banner ámbar con la indicación al
 * operario.
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
import { computed, ref } from "https://unpkg.com/vue@3/dist/vue.esm-browser.prod.js";
import { store } from "/js/store.js";

export default {
    name: "SoftwarePanel",
    setup() {
        /**
         * Flag del backend: ``true`` si los 4 parsers de software
         * están integrados. Si es ``false`` (versión antigua del
         * backend o Excel sin las 4 hojas de software) mostramos
         * banner ámbar.
         */
        const softwareImplemented = computed(
            () => !!(store.memoryState
                     && store.memoryState.software_parsers_implemented)
        );

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
         * 4 dominios de software tiene datos. Es la condición para
         * mostrar las tablas (en lugar del "Inspector vacío" idéntico
         * al de ``DispositivosPanel``). Coherencia visual entre los
         * 2 tabs: sin Excel → mismo cuadro vacío con emoji.
         *
         * NO confundir con ``softwareImplemented``: ese flag es del
         * backend y vale ``false`` también cuando el Excel existe pero
         * no tiene las 4 hojas de software (caso "Excel de solo
         * dispositivos" o backend antiguo). En ese caso, este
         * ``hasMemory`` vale ``true`` y se muestra el banner ámbar
         * con la indicación de qué hojas faltan.
         */
        const hasMemory = computed(
            () => !!(store.memoryState
                     && (procesos.value.length > 0
                         || parametrosInt.value.length > 0
                         || parametrosReal.value.length > 0
                         || alarmas.value.length > 0))
        );

        /**
         * Sub-tab activo. Una de
         * ``'procesos' | 'parametros_int' | 'parametros_real' | 'alarmas'``.
         * Default: ``'procesos'`` (suele ser la lista más corta y
         * cabecera del resto).
         */
        const activeSoftwareTab = ref("procesos");

        return {
            softwareImplemented,
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

            <!-- Bloque principal: solo visible si hay Excel cargado
                 con datos de software (hasMemory). Coherencia con
                 DispositivosPanel: si NO hay Excel, se muestra el
                 "Inspector vacío" idéntico al del otro tab. -->
            <template v-if="hasMemory">

                <!-- Banner ámbar: visible si el flag software_parsers_implemented
                     es false (modo degradado: backend aún no expone los 4
                     campos nuevos o Excel sin hojas de software). -->
                <div v-if="!softwareImplemented"
                     class="mb-3 bg-amber-100 border-l-4 border-amber-500 text-amber-900 p-3 rounded text-xs">
                    ⚠️ Datos de software pendientes. Sube un Excel con hojas
                    CONFIGURACION / P_REAL / P_INT / ALARMAS para verlos aquí.
                </div>

                <!-- Sub-tabs de software (Procesos | PInt | PReal | Alarmas) -->
                <div class="flex border-b border-line bg-surface-sunken overflow-x-auto">
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

                <!-- Tabla del sub-tab activo -->
                <div class="flex-1 overflow-auto table-scroll-x mt-2 bg-surface-raised border border-line rounded">

                <!-- Procesos -->
                <table v-if="activeSoftwareTab === 'procesos'" class="w-full text-xs">
                    <thead class="sticky top-0 bg-surface-sunken text-[10px] uppercase">
                        <tr>
                            <th class="px-3 py-2 text-left text-ink-muted">UID</th>
                            <th class="px-3 py-2 text-left text-ink-muted">Código</th>
                            <th class="px-3 py-2 text-left text-ink-muted">Nombre</th>
                            <th class="px-3 py-2 text-left text-ink-muted">PReal</th>
                            <th class="px-3 py-2 text-left text-ink-muted">PInt</th>
                            <th class="px-3 py-2 text-left text-ink-muted">Alarmas</th>
                            <th class="px-3 py-2 text-left text-ink-muted">DB PREAL</th>
                            <th class="px-3 py-2 text-left text-ink-muted">DB ALM</th>
                            <th class="px-3 py-2 text-left text-ink-muted">ALM HMI</th>
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
                            <td class="px-3 py-1.5 font-mono">DB{{ 3000 + p.uid }}</td>
                            <td class="px-3 py-1.5 font-mono">DB{{ 5000 + p.uid }}</td>
                            <td class="px-3 py-1.5">{{ Math.max(0, Math.floor(p.alarmas / 16) - 1) }}</td>
                        </tr>
                        <tr v-if="procesos.length === 0">
                            <td colspan="9" class="px-3 py-6 text-center text-ink-muted italic">
                                ⚠️ Sin procesos definidos.
                            </td>
                        </tr>
                    </tbody>
                </table>

                <!-- Parámetros Enteros -->
                <table v-else-if="activeSoftwareTab === 'parametros_int'" class="w-full text-xs">
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
                <table v-else-if="activeSoftwareTab === 'parametros_real'" class="w-full text-xs">
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
                <table v-else-if="activeSoftwareTab === 'alarmas'" class="w-full text-xs">
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

                </div>
            </template>

            <!-- "Inspector vacío" idéntico al de DispositivosPanel.
                 Solo se ve si NO hay Excel cargado (o el Excel no
                 tiene ninguna de las 4 hojas de software). Coherencia
                 visual: sin datos, mismo cuadro centrado con emoji. -->
            <div v-else class="flex-1 flex items-center justify-center bg-surface-raised border border-dashed border-line rounded mt-2 p-10 text-center text-ink-muted">
                <div>
                    <div class="text-5xl mb-3 opacity-40">⚙️</div>
                    <p class="mb-2">El Inspector de Software está vacío.</p>
                    <p class="text-xs">Sube un Excel con las hojas de software
                        (CONFIGURACION / P_REAL / P_INT / ALARMAS) y pulsa
                        <strong class="text-accent">"Refrescar Memoria"</strong>.</p>
                </div>
            </div>

        </div>
    `,
};
