---
name: user-profile
description: Perfil operativo del operario (Aketza) para zc-automation-suite — idioma, trazabilidad obligatoria, prefijos de dominio, modelo mental PLC, comentarios limpios, rama greenfield, pasos pequenos, convenciones Obsidian. Carga esta skill cuando el prompt mencione preferencias del operario, estilo de trabajo, o haya que decidir entre alternativas de diseno.
---

# Perfil del operario (Aketza) — zc-automation-suite

Resumen del perfil operativo del operario. Tratar como preferencias estables
del usuario; aplicar al proponer refactors, auditorias y diseno de flujos.

## Perfil profesional

- Automatizacion industrial a tiempo completo.
- Trabaja con **Siemens TIA Portal** (V15.1+) usando el SDK oficial
  **TIA Scripting Python** (`siemens_tia_scripting`) via COM/.NET.
- Stack familiar: Python 3.12-3.14, Flask, Vue 3 (SFC con build step),
  Pinia, PyInstaller, Openness API.

## Proyecto principal

**zc-automation-suite** — Herramienta de integracion IT/OT para automatizacion
e inspeccion de proyectos TIA Portal.

- Nucleo simple: **un unico hilo** dueno del portal de TIA. Los trabajos se
  ejecutan **enteros** dentro de ese hilo; no hay cola de comandos ni hilos
  por paso.
- Contrato de trabajo: `job.empezar(titulo, pasos)` + `with job.paso(nombre)`
  + `with transaccion(job, texto)`.
- Una sola funcion por operacion, con modo `aplicar=False` (preview) y
  `aplicar=True`. No hay pares preview/operar.
- Fallos siempre como excepciones. Nunca un `{"ok": False}` que alguien
  tenga que comprobar.
- Eventos SSE (`progress`, `job`, `log`, `tia`) como unico canal de la SPA
  hacia el backend.
- Areas registradas en una lista explicita `AREAS` en `main.py`.
- Repo local: `D:/Zeus Control/Proyectos/GitHub/zc-automation-suite`.
- Puerto dev: `127.0.0.1:9484` (backend), `5173` (Vite).

## Preferencias durables

1. **Idioma:** habla en espanol. Respuestas en espanol.
2. **Pragmatico:** prefiere la opcion simple y robusta. Ejemplo:
   "panel fijo en sidebar" en lugar de "overlay dinamico" cuando la segunda
   opcion da problemas de UI.
3. **La trazabilidad es obligatoria.** El operario necesita ver que esta
   haciendo la app en operaciones largas contra TIA Portal. Concretamente:
   `job.paso()` declara y marca cada paso, y el faceplate de progreso de la
   SPA lo refleja. Un trabajo largo sin pasos declarados es un defecto, no una
   decision de diseno. Los logs tampoco son opcionales.
4. **Windows + PowerShell + Python venvs.**
5. **Prefijos de dominio primero.** `disp_*` (dispositivos), `proc_*`
   (procesos) y `ent_*` (entidades) van SIEMPRE primero en
   archivos/clases/funciones. Patron `<prefijo>_<verbo>_<concepto>`, NO al
   reves. No mezclar `disp_*` con `proc_*` en el mismo archivo.
6. **Comentarios limpios.** NO en comentarios: planes (Fase X, Paso Y),
   fechas explicitas, estilo IA ("absorbe logica de", "Migrado de"),
   narrador refactor ("antes X ahora Y"). SI: contrato API, restricciones,
   naming no obvio. Archivo reescrito = borrar historial del docstring.
7. **Modelo mental PLC.** Su cabeza procesa como IEC 61131-3 (SFC, CASE,
   nStep, marcas de bit). Le cuesta REST asincrono + reactividad Vue 3.
   Prefiere state machines discretas a flags booleanos; prefiere orquestadores
   secuenciales (task runner / "SFC en JS") a `if/else` con awaits encadenados.
   Cuando propongas refactors, mostrar el equivalente en SCL o diagrama de
   escalera para que valide.
8. **Simplicidad por delante del paralelismo.** Prefiere sync + cola sobre
   async + event loop + subprocess cuando sea viable. Trade-off aceptado:
   pierde paralelismo I/O pero gana simplicidad.
9. **Greenfield por rama, no por repo.** Para grandes refactors prefiere crear
   una rama en el repo actual y "borrar todo y empezar de cero" ahi, no un
   repo nuevo. Mantiene legacy operativo en main mientras construye el nuevo.
10. **Delegar en pasos pequenos.** Cuando se delega, dividir en 1-2 archivos
    por paso, < 200 lineas, commiteable solo. Tareas grandes = alucinaciones.
    Si un paso se complica, se subdivide.
11. **Alcance antes de construir.** Quiere un documento de alcance pequeno
    antes de seguir anadiendo funciones: roles, ambito de cada uno y lista de
    lo que NO entra. Decisiones abiertas numeradas y con propuesta.
12. **Tags YAML en Obsidian: SIEMPRE lista, NUNCA inline.** Para frontmatter
    de Obsidian, rechaza el formato `tags: [a, b, c]` y exige lista YAML con
    2 espacios de indentacion.
13. **Separators tabla markdown: SIN espacios.** En tablas markdown para sus
    vaults, el separator debe ser `|---|---|---|` sin espacios. NO acepta
    `| --- | --- | --- |`.

## Estilo de colaboracion

- Resolver el problema, no extender el scope.
- Si hay un bug dificil de diagnosticar, prefiere cambiar de enfoque antes de
  quemarse depurando.
- Le gusta ver el resultado funcionando: tests verdes + commit al final.
- "Me la tenias que haber avisado": cuando reporte un bug, hacer un escaneo
  exhaustivo y reportar TODAS las inconsistencias, no solo la que pregunta.
- Si el diseno tiene dos lecturas razonables, para y propón una opcion con
  ejemplos del codigo. No improvises una capa de compatibilidad.

## Convenciones de commits

- 1-2 archivos por commit.
- Mensaje en archivo (`git commit -F <archivo>`).
- Borrar el archivo temp tras commit con `mavis-trash` (nunca `rm` directo).
- Nombre del commit: scope entre parentesis, descripcion corta imperativa. Sin
  planes ni "Migrado de" / "antes X ahora Y" en el cuerpo.
