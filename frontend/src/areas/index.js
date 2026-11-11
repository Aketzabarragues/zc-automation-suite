/**
 * Las areas de la app.
 *
 * Cada area vive en su carpeta y exporta su definicion. El shell las
 * recoge con el glob: anadir un area es anadir una carpeta, sin tocar
 * ningun fichero del shell.
 */
const modulos = import.meta.glob("./*/index.js", { eager: true });

export const AREAS = Object.values(modulos)
  .map((modulo) => modulo.default)
  .filter(Boolean)
  .sort((a, b) => String(a.nombre).localeCompare(String(b.nombre)));

/**
 * Las vistas de las areas, indexadas por nombre de componente.
 *
 * Una vista que no esta aqui no se puede abrir: el shell avisa en vez de
 * dejar un hueco en blanco.
 */
const modulosVista = import.meta.glob("./*/vistas/*.vue", { eager: true });

export const VISTAS = Object.fromEntries(
  Object.entries(modulosVista).map(([ruta, modulo]) => [ruta.split("/").pop(), modulo.default]),
);
