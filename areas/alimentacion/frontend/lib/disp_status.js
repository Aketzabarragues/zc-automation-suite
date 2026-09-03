// ============================================================================
// disp_status.js — STATUS_META compartido por el sync de dispositivos y el
// sync de procesos.
//
// Mantener un solo origen de verdad para los labels y clases CSS de las
// acciones de diff. Los dos flujos (devices y procesos) producen el
// mismo set de acciones (agregar / renombrar / eliminar / sin_cambios),
// así que la SPA muestra los mismos iconos y colores sin duplicar
// constantes.
//
// ``eliminar`` no se computa en el flujo de procesos (no borramos slots
// del array, solo actualizamos comentarios), pero la key se mantiene
// en la tabla para que, si en el futuro se añade esa lógica, la SPA
// ya tenga el label listo.
//
// NOTA: las clases ``action-add``/``action-rename``/``action-remove``/
// ``action-ok`` son las previstas para colorear la fila entera; aún no
// están definidas en ``input.css`` (deuda heredada de Dispositivos.js
// previa a PR 7). Cuando se defina el styles.css semántico, se aplica
// el ``cls`` al ``<tr>`` y el row se colorea entero. Mientras tanto,
// los colores se aplican manualmente celda a celda.
// ============================================================================

export const DISP_STATUS = Object.freeze({
    agregar:     { label: "➕ AGREGAR",    cls: "action-add" },
    renombrar:   { label: "✏️ RENOMBRAR", cls: "action-rename" },
    eliminar:    { label: "🗑️ ELIMINAR",  cls: "action-remove" },
    sin_cambios: { label: "✓ OK",         cls: "action-ok" },
});

// Alias histórico: ``STATUS_META``. Algunos componentes lo importan
// con ese nombre. Se reexporta para no romperlos.
export const STATUS_META = DISP_STATUS;
