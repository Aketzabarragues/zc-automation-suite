---
name: user-profile
description: Perfil operativo del operario (Aketza) para zc-automation-suite — idioma, OB1, prefijos disp_*/proc_*, modelo mental PLC, comentarios limpios, convenciones Obsidian. Carga esta skill cuando el prompt mencione preferencias del operario, estilo de trabajo, o haya que decidir entre alternativas de diseño.
---

# Perfil del operario (Aketza) — zc-automation-suite

Resumen del perfil operativo del operario. Tratar como preferencias
estables del usuario; aplicar al proponer refactors, auditorías y
diseño de flujos.

## Perfil profesional

- Automatización industrial a tiempo completo.
- Trabaja con **Siemens TIA Portal** (V15.1+) usando el SDK oficial
  **TIA Scripting Python** (`siemens_tia_scripting`) vía COM/.NET.
- Stack familiar: Python 3.12-3.14, Flask, Vue 3 (ESM sin build
  step), PyInstaller, asyncio, Openness API.

## Proyecto principal

**zc-automation-suite** — Herramienta de integración IT/OT para
automatización e inspección de proyectos TIA Portal.

- Arquitectura Clean (core / infrastructure / application / interfaces).
- Patrón OB1: hilo TIA persistente con `SyncTIAClient` + cola FIFO +
  state machine de 6 estados. Flask sync daemonizado por supervisor.
- Despacho por bandeja (system tray) con `pystray` + supervisor web.
- Repo local: `D:/Zeus Control/Proyectos/GitHub/zc-automation-suite`.
- Puerto dev: `127.0.0.1:9484`.

## Preferencias durables

1. **Idioma:** habla en español. Respuestas en español.
2. **Pragmático:** prefiere la opción simple y robusta. Ejemplo:
   "panel fijo en sidebar" en lugar de "overlay dinámico" cuando la
   segunda opción da problemas de UI.
3. **Trazabilidad:** el operario necesita ver qué está haciendo la
   app en operaciones largas contra TIA Portal. Los logs y el
   `ProgressTracker` no son opcionales.
4. **Windows + PowerShell + Python venvs.**
5. **Prefijos `disp_*` / `proc_*` primero.** Convención arquitectónica
   estricta: `disp_*` (dispositivos) y `proc_*` (procesos) van
   SIEMPRE primero en archivos/clases/funciones. Patrón
   `<prefijo>_<verbo>_<concepto>`, NO al revés. Excepciones:
   `mlc_registry.py`, `excel_cache.py`, cross-cutting, mcp/tools.py.
6. **Comentarios limpios.** NO en comentarios: planes (Fase X, Paso
   Y), fechas explícitas, estilo IA ("absorbe logica de", "Migrado
   de"), narrador refactor ("antes X ahora Y"). SI: contrato API,
   restricciones, naming no obvio. Archivo reescrito = borrar
   historial del docstring.
7. **Modelo mental PLC.** Su cabeza procesa como IEC 61131-3 (SFC,
   CASE, nStep, marcas de bit). Le cuesta REST asíncrono + reactividad
   Vue 3. Prefiere state machines discretas a flags booleanos;
   prefiere orquestadores secuenciales (task runner / "SFC en JS") a
   `if/else` con awaits encadenados. Cuando proponga refactors,
   mostrar el equivalente en SCL o diagrama de escalera para que
   valide.
8. **OB1 single-threaded cyclic a nivel de app.** Prefiere
   arquitectura OB1 (single-threaded cyclic main loop + Flask sync en
   hilo + TIA wrapper llamado directamente) sobre async+event-loop+
   subprocess. Trade-off aceptado: pierde paralelismo I/O pero gana
   simplicidad 5x.
9. **Greenfield por rama, no por repo.** Para grandes refactors
   prefiere crear una rama en el repo actual y "borrar todo y
   empezar de cero" ahí, no un repo nuevo. Mantiene legacy
   operativo en main mientras construye el nuevo.
10. **Delegar en pasos pequeños.** Cuando se delega, dividir en 1-2
    archivos por paso, < 200 líneas, commiteable solo. Tareas grandes
    = alucinaciones. Si un paso se complica, se subdivide.
11. **Tags YAML en Obsidian: SIEMPRE lista, NUNCA inline.** Para
    frontmatter de Obsidian, rechaza el formato `tags: [a, b, c]` y
    exige lista YAML con 2 espacios de indentación.
12. **Separators tabla markdown: SIN espacios.** En tablas markdown
    para sus vaults, el separator debe ser `|---|---|---|` sin
    espacios. NO acepta `| --- | --- | --- |`.

## Estilo de colaboración

- Resolver el problema, no extender el scope.
- Si hay un bug difícil de diagnosticar, prefiere cambiar de enfoque
  antes que quemarse depurando.
- Le gusta ver el resultado funcionando: tests verdes + commit al
  final.
- "Me la tenías que haber avisado": cuando reporte un bug, hacer un
  escaneo exhaustivo y reportar TODAS las inconsistencias, no solo la
  que pregunta.

## Convenciones de commits

- 1-2 archivos por commit.
- Mensaje en archivo (`git commit -F <archivo>`).
- Borrar el archivo temp tras commit con `mavis-trash` (nunca `rm`
  directo).
- Nombre del commit: scope entre paréntesis, descripción corta
  imperativa. Sin planes ni "Migrado de" / "antes X ahora Y" en el
  cuerpo.