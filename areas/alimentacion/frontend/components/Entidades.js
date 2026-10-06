/**
 * Componente Entidades.
 *
 * Sub-vista de primer nivel del area "alimentacion" que se muestra
 * cuando ``store.currentView === 'entidades'``. Es el boton gemelo
 * de Dispositivos / Procesos en el sidebar del shell SPA.
 *
 * En esta primera iteracion (commit B.0) solo monta
 * ``<entidades-panel />`` directamente. El panel vive tambien dentro
 * del tab "Entidades" de ``DefinicionProgramacion`` (UX gemela de
 * Dispositivos/Software/Configuracion); esta sub-vista top-level
 * existe solo para que el operario tenga acceso directo desde el
 * sidebar sin pasar por "Definicion programacion".
 *
 * En el commit D se anadiran las cards de accion (selector de
 * dimensionado, previsualizacion del DB6_ENT, sync, etc) siguiendo
 * el patron de ``Procesos.js``.
 *
 * Tema: Industrial Claro. Solo tokens semanticos
 * (``bg-surface*``, ``border-line*``, ``text-ink*``).
 */
export default {
    name: "Entidades",
    template: /* html */ `
        <section class="flex-1 flex flex-col overflow-hidden">
            <entidades-panel />
        </section>
    `,
};