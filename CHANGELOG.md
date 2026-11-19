# Changelog

Formato Keep a Changelog. Fechas en `YYYY-MM-DD`.

## [No publicado]

### Added

- 2026-11-17 — Módulo común de sincronización en `areas/alimentacion/sincronizacion_comun.py`: estado de transacciones, `compilar_con_aviso`, `datos_compilacion`, `mensaje_corto` y `localizar_xml`, reutilizados por los cuatro FB.

### Changed

- 2026-11-19 — Menú del área de alimentación: Entidades va antes que Procesos. El inicio del área añade la tarjeta de Entidades, que en `main` no tenía.
- 2026-11-17 — Dispositivos, Entidades y Procesos usan el módulo común; el resultado `compilacion` de los tres sync pasa a detalle string y Crear conserva el shape `{ok, error, detalle}`.
- 2026-11-17 — Los cuatro FB se dividen en pasos y helpers con responsabilidad única; ninguna función de los cuatro ficheros supera 100 líneas.
- 2026-11-17 — `ConfigError` hereda de `ZCError`; las respuestas HTTP de la ruta de plantillas (200/400/500) no cambian.
- 2026-11-17 — Textos de la web alineados con `main`: botón y mensaje de éxito de Crear proceso, `Parametros Reales` en Definición, título de la pantalla de inicio y descripción del área.
- 2026-11-17 — Documentación de reescritura actualizada: forma real de `compilacion` y lista de textos nuevos deliberados.

### Fixed

- 2026-11-17 — La tarjeta "Crear proceso" de Procesos hace scroll vertical; el botón de aplicar es alcanzable a 900 y 1080 px y las tablas no se aplastan.
- 2026-11-17 — La compilación de Crear proceso solo se muestra cuando falla; en caso contrario ya no aparece el detalle técnico.
- 2026-11-17 — La nota de TIA V21 solo aparece cuando la versión conectada es anterior a V21.
- 2026-11-17 — El test de unicidad de IDs MLC actualiza el conjunto `used` como exige el contrato de `siguiente_id_mlc`.
