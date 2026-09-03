/**
 * Componente Sidebar — wrapper fino del ShellSidebar genérico
 * para el área Alimentación.
 *
 * Este archivo SOLO aporta los ``NAV_ITEMS`` del área y resuelve
 * ``areaInfo`` del catálogo. Todo el chrome corporativo (cabecera
 * blanca con logo, sección PLC, ProgressIndicator dark, footer
 * con "Volver al inicio") vive en ``ShellSidebar`` y se
 * reutilizará tal cual cuando lleguen más áreas.
 *
 * Cuando un segundo área necesite un sidebar, su ``Sidebar.js``
 * será un wrapper equivalente: importa ``ShellSidebar``, declara
 * sus propios ``NAV_ITEMS`` y mapea ``@navigate`` / ``@back`` a
 * los handlers del área.
 *
 * Import absoluto: ver nota histórica. Los cross-cutting
 * (``store.js``, ``ShellSidebar``) viven en ``/js/``, no se
 * mueven.
 */
import { computed } from "/js/vendor/vue.esm-browser.prod.js";
import { store, goToWelcome, goToSubview } from "/js/store.js";
import ShellSidebar from "/js/components/ShellSidebar.js";

/**
 * Items de navegación del área Alimentación. Las ``key`` deben
 * coincidir con las declaradas en el ``manifest.js`` del área
 * (``views``) — el shell SPA las valida contra el manifest al
 * transicionar.
 */
const NAV_ITEMS = [
    { key: "landing", icon: "🏠", label: "Inicio" },
    { key: "def",     icon: "📊", label: "Definición programación" },
    { key: "cache",   icon: "🗃️", label: "Cache del PLC" },
    { key: "disp",    icon: "⚡", label: "Dispositivos" },
    { key: "proc",    icon: "⚙️", label: "Procesos" },
];

export default {
    name: "AlimentacionSidebar",
    components: { ShellSidebar },
    setup() {
        /**
         * ``areaInfo`` (objeto ``{ key, label, subtitle, icon }``)
         * se computa del catálogo ``store.availableAreas`` con la
         * key ``store.selectedArea``. Modo degradado: si el área
         * no está en el catálogo (todavía no se cargó el
         * ``/api/v1/areas`` o el área es nueva sin catálogo),
         * cae a ``{ key, label: <key>, icon: '📁' }`` para que
         * el ShellSidebar siempre tenga algo que pintar.
         *
         * El campo ``subtitle`` es la forma corta del nombre del
         * área (p. ej. ``"Alimentación"``) que el ShellSidebar
         * muestra debajo del caption fijo "Área" para evitar la
         * redundancia "Área" / "Área de alimentación". Si el
         * catálogo trae un ``subtitle`` (futuro), se respeta;
         * si no, se usa el constante local de este área.
         */
        const AREA_SUBTITLE = "Alimentación";
        const areaInfo = computed(() => {
            if (!store.selectedArea) {
                return { key: "", label: "—", subtitle: "—", icon: "" };
            }
            const a = store.availableAreas.find(
                (x) => x.key === store.selectedArea
            );
            if (a) return { ...a, subtitle: a.subtitle || AREA_SUBTITLE };
            return {
                key: store.selectedArea,
                label: store.selectedArea,
                subtitle: AREA_SUBTITLE,
                icon: "",
            };
        });

        return {
            areaInfo,
            navItems: NAV_ITEMS,
            goToWelcome,
            goToSubview,
        };
    },
    template: /* html */ `
        <ShellSidebar
            :area="areaInfo"
            :navItems="navItems"
            @navigate="goToSubview"
            @back="goToWelcome" />
    `,
};
