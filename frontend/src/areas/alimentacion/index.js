/**
 * Area de alimentacion.
 *
 * El menu es lo que el area aporta al shell. Las vistas que aun no estan
 * implementadas se declaran igual: el shell las muestra y avisa de que
 * faltan, en vez de esconderlas y dejar el menu a medias.
 */
export default {
  id: "alimentacion",
  nombre: "Área de alimentación",
  descripcion: "Dispositivos, sincronización e inspección de PLCs del área de alimentación.",
  icono: "📁",
  /** Prefijo de las rutas del area en el backend. */
  rutas: "/api/v1/areas/alimentacion",
  menu: [
    { clave: "inicio", etiqueta: "Inicio", icono: "🏠", vista: "AreaInicio.vue" },
    {
      clave: "def",
      etiqueta: "Definición programación",
      icono: "📊",
      vista: "DefinicionProgramacion.vue",
    },
    { clave: "disp", etiqueta: "Dispositivos", icono: "⚡", vista: "Dispositivos.vue" },
    { clave: "proc", etiqueta: "Procesos", icono: "⚙️", vista: null },
    { clave: "ent", etiqueta: "Entidades", icono: "🗂️", vista: null },
  ],
};
