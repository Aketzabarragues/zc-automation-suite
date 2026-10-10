/**
 * ConfiguracionPanel — Tab "Configuracion" dentro de "Definicion programacion".
 *
 * Sept-2026 (multi-PLC, propuesta del operario): muestra la
 * ``Tabla_Dispositivos`` del Excel como tabla cruda (no como cards
 * de N_MAX). Cada fila es un PLC con sus N_MAX_DISP_* en columnas.
 *
 * Sustituye a las N_MAX cards que vivían en ``DispositivosPanel``
 * (multi-PLC rompe la utilidad de cards mezcladas por PLC: la info
 * por PLC vive en el preview del PLC concreto, en ``Dispositivos.js``).
 *
 * Shape del backend (en el slot ``excel_full`` del AppCache):
 *   store.appCache.areas["alimentacion"].excel_full.dimensiones = {
 *       "ZC_PLC_STD": { "N_MAX_DISP_ED": 50, "N_MAX_DISP_EA": 30, ... },
 *       "PLC_CPR":    { "N_MAX_DISP_ED": 200, ... }
 *   }
 *
 * Columnas derivadas dinámicamente del primer PLC (orden estable).
 * Si el Excel no tiene ``Tabla_Dispositivos``, el contenedor viene
 * vacio y mostramos un empty state claro.
 */
import { computed } from "/js/vendor/vue.esm-browser.prod.js";
import { store } from "/js/store.js";

export default {
    name: "ConfiguracionPanel",
    setup() {
        // ``excel_full`` reactivo desde el AppCache del area activa.
        const excelFull = computed(
            () => store.appCache?.areas?.alimentacion?.excel_full || null
        );

        /**
         * True solo cuando hay Excel cargado (``excel_full`` no nulo).
         * Mismo patron que ``DispositivosPanel`` y ``ProcesosPanel``:
         * cuando NO hay Excel, este panel pinta el "Inspector vacio"
         * identico al resto de tabs (coherencia visual).
         */
        const hasMemory = computed(() => excelFull.value != null);

        /**
         * Lista de PLCs (filas). Cada item: ``{ plc_name, extras: {...} }``.
         * Viene de ``excel_full.dimensiones`` (dict
         * ``{plc_name: {nmax_name: int}}``). Lo pasamos a una lista
         * ordenada para iterar en el template.
         */
        const plcRows = computed(() => {
            const d = excelFull.value && excelFull.value.dimensiones;
            if (!d || typeof d !== "object") return [];
            return Object.entries(d).map(([plc_name, extras]) => ({
                plc_name,
                extras: extras || {},
            }));
        });

        /**
         * Columnas de N_MAX derivadas del primer PLC (orden estable:
         * keys de extras en el orden que devuelve el backend).
         * Si no hay PLCs, devuelve lista vacia.
         */
        const nmaxColumns = computed(() => {
            const rows = plcRows.value;
            if (rows.length === 0) return [];
            return Object.keys(rows[0].extras);
        });

        const hasDimensiones = computed(() => plcRows.value.length > 0);

        return {
            plcRows,
            nmaxColumns,
            hasMemory,
            hasDimensiones,
        };
    },
    template: /* html */ `
        <div class="flex-1 overflow-auto bg-surface-raised border border-line rounded">
            <div v-if="!hasMemory" class="px-6 py-12 text-center text-ink-muted">
                <div class="text-5xl mb-3 opacity-40">📊</div>
                <p class="mb-2">La cache del excel está vacía.</p>
                <p class="text-xs">Sube un Excel y pulsa <strong class="text-accent">"Actualizar"</strong>.</p>
            </div>
            <div v-else-if="!hasDimensiones" class="px-6 py-12 text-center text-ink-muted">
                <div class="text-base mb-2">
                    No hay <span class="font-mono">Tabla_Dispositivos</span> en el Excel cargado.
                </div>
                <div class="text-xs">
                    Anade una hoja con la tabla de N_MAX (columnas
                    <span class="font-mono">PLC, N_Max_ED, N_Max_EA, N_Max_SA, ...</span>)
                    y vuelve a subir el archivo para ver aqui las dimensiones por PLC.
                </div>
            </div>
            <table v-else class="w-full text-xs">
                <thead class="sticky top-0 bg-surface-sunken text-[10px] uppercase">
                    <tr>
                        <th class="px-3 py-2 text-left text-ink-muted whitespace-nowrap border-b border-line">
                            PLC
                        </th>
                        <th v-for="col in nmaxColumns" :key="col"
                            class="px-3 py-2 text-left text-ink-muted whitespace-nowrap border-b border-line font-mono">
                            {{ col }}
                        </th>
                    </tr>
                </thead>
                <tbody>
                    <tr v-for="row in plcRows" :key="row.plc_name"
                        class="border-b border-line hover:bg-surface-sunken">
                        <td class="px-3 py-1.5 align-top text-ink font-mono whitespace-nowrap">
                            {{ row.plc_name }}
                        </td>
                        <td v-for="col in nmaxColumns" :key="col"
                            class="px-3 py-1.5 align-top text-ink font-mono whitespace-nowrap">
                            {{ row.extras[col] ?? 0 }}
                        </td>
                    </tr>
                </tbody>
            </table>
        </div>
    `,
};
