---
description: "Preferencias durables del operario: idioma, trazabilidad obligatoria, prefijos de dominio, modelo mental PLC, simplicidad, delegacion en pasos pequenos, convenciones de commits y estilo de colaboracion."
read_if: "Proponer refactors o disenos, escribir commits, o decidir entre alternativas cuando el estilo del operario influye en la eleccion."
---

# Perfil del operario

Resumen del perfil operativo del operario. Tratar como preferencias estables
del usuario; aplicar al proponer refactors, auditorias y diseno de flujos. La
duplicacion con las instrucciones privadas es intencionada: alli va la regla
autoritativa, aqui el motivo de cada una.

## Perfil profesional

- Automatizacion industrial a tiempo completo.
- Trabaja con **Siemens TIA Portal** (V15.1+) usando el SDK oficial
  **TIA Scripting Python** (`siemens_tia_scripting`) via COM/.NET.
- Stack familiar: Python 3.12-3.14, Flask, Vue 3 (SFC con build step),
  Pinia, PyInstaller, Openness API.

## Preferencias durables

1. **Idioma.** Habla en espanol. Respuestas en espanol.
2. **Pragmatico.** Prefiere la opcion simple y robusta: p. ej. "panel fijo en
   sidebar" en lugar de "overlay dinamico" cuando la segunda opcion da
   problemas de UI.
3. **La trazabilidad es obligatoria.** El operario necesita ver que esta
   haciendo la app en operaciones largas contra TIA Portal: `job.paso()`
   declara y marca cada paso, y el faceplate de progreso de la SPA lo
   refleja. Un trabajo largo sin pasos declarados es un defecto, no una
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
   secuenciales (task runner / "SFC en JS") a `if/else` con awaits
   encadenados. Cuando se proponga un refactor, mostrar el equivalente en SCL
   o diagrama de escalera para que valide.
8. **Simplicidad por delante del paralelismo.** Prefiere sync + cola sobre
   async + event loop + subprocess cuando sea viable. Trade-off aceptado:
   pierde paralelismo I/O pero gana simplicidad.
9. **Greenfield por rama, no por repo.** Para grandes refactors prefiere crear
   una rama en el repo actual y borrar todo y empezar de cero ahi, no un repo
   nuevo. Mantiene legacy operativo en main mientras construye el nuevo.
10. **Delegar en pasos pequenos.** Cuando se delega, dividir en 1-2 archivos
    por paso, < 200 lineas, commiteable solo. Tareas grandes = alucinaciones.
    Si un paso se complica, se subdivide.
11. **Alcance antes de construir.** Quiere un documento de alcance pequeno
    antes de seguir anadiendo funciones: roles, ambito de cada uno y lista de
    lo que NO entra. Decisiones abiertas numeradas y con propuesta.
12. **Tags YAML en Obsidian: SIEMPRE lista, NUNCA inline.** Rechaza el
    formato `tags: [a, b, c]` y exige lista YAML con 2 espacios de
    indentacion.
13. **Separadores de tabla markdown: SIN espacios.** En tablas markdown, el
    separator debe ser `|---|---|---|` sin espacios. NO acepta
    `| --- | --- | --- |`.

## Estilo de colaboracion

- Resolver el problema, no extender el scope.
- Si hay un bug dificil de diagnosticar, prefiere cambiar de enfoque antes que
  quemarse depurando.
- Le gusta ver el resultado funcionando: tests verdes + commit al final.
- "Me la tenias que haber avisado": cuando reporte un bug, hacer un escaneo
  exhaustivo y reportar TODAS las inconsistencias, no solo la que pregunta.
- Si el diseno tiene dos lecturas razonables, parar y proponer una opcion con
  ejemplos del codigo. No improvisar una capa de compatibilidad.

## Convenciones de commits

- 1-2 archivos por commit.
- Mensaje en archivo (`git commit -F <archivo>`).
- Borrar el archivo temp tras el commit con la herramienta de basura, nunca
  `rm` directo.
- Nombre del commit: scope entre parentesis, descripcion corta imperativa.
  Sin planes ni "Migrado de" / "antes X ahora Y" en el cuerpo.
