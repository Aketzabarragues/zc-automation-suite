/**
 * Componente EntidadesConfiguracion.
 *
 * Sub-vacia de la pestana "Configuracion" dentro de Entidades.
 * Reservada para una iteracion futura en la que el operario edite el
 * Excel desde la SPA (N_MAX_ENTIDAD por PLC y similares).
 *
 * Por ahora muestra un empty state consistente con el resto de la
 * SPA ("La cache del excel esta vacia" / "En desarrollo").
 *
 * Tema: Industrial Claro. Solo tokens semanticos.
 */
export default {
    name: "EntidadesConfiguracion",
    setup() {
        return {};
    },
    template: /* html */ `
        <div class="flex-1 flex items-center justify-center p-10 text-center text-ink-muted">
            <div>
                <div class="text-5xl mb-3 opacity-40">⚙️</div>
                <p class="mb-2">Configuracion de entidades.</p>
                <p class="text-xs">Reservado para una iteracion futura.</p>
            </div>
        </div>
    `,
};