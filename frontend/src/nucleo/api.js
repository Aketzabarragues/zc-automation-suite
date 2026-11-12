/**
 * Llamadas HTTP al backend.
 *
 * El resultado de un trabajo NO vuelve en el body del POST: el POST responde
 * 202 con el `job_id` y el resultado llega por el stream de eventos.
 */

const CABECERAS = { "Content-Type": "application/json" };

/**
 * Hace una peticion y devuelve su cuerpo en JSON.
 *
 * @param {string} ruta ruta del endpoint.
 * @param {object} opciones opciones de `fetch`.
 * @returns {Promise<object>} el cuerpo de la respuesta.
 * @throws {Error} si la respuesta no es un 2xx. El mensaje es el que manda
 *   el backend en el campo `error`.
 */
export async function pedir(ruta, opciones = {}) {
  const respuesta = await fetch(ruta, { credentials: "same-origin", ...opciones });
  const cuerpo = await respuesta.json().catch(() => ({}));
  if (!respuesta.ok) {
    throw new Error(cuerpo.error || `Error ${respuesta.status}`);
  }
  return cuerpo;
}

/** Encola la conexion con TIA Portal. */
export function conectar() {
  return pedir("/api/v1/tia/conectar", { method: "POST", headers: CABECERAS });
}

/** Encola la desconexion de TIA Portal. */
export function desconectar() {
  return pedir("/api/v1/tia/desconectar", { method: "POST", headers: CABECERAS });
}

/** Estado de la conexion: conectado, trabajo en curso y ultimo error. */
export function estado() {
  return pedir("/api/v1/tia/estado");
}

/** Encola la busqueda de los PLCs del proyecto abierto. */
export function buscarPlcs() {
  return pedir("/api/v1/tia/plcs/listar", { method: "POST", headers: CABECERAS });
}

/** Encola el escaneo de un PLC: bloques, tablas de tags y tipos de usuario. */
export function escanearPlc(plc) {
  return pedir(`/api/v1/tia/plcs/${encodeURIComponent(plc)}/escanear`, {
    method: "POST",
    headers: CABECERAS,
  });
}

/** Encola la lectura de las propiedades de los bloques indicados. */
export function prepararBloques(plc, bloques) {
  return pedir(`/api/v1/tia/plcs/${encodeURIComponent(plc)}/bloques/preparar`, {
    method: "POST",
    headers: CABECERAS,
    body: JSON.stringify({ bloques }),
  });
}

/** Encola la aplicacion de los cambios de nombre y numero. */
export function editarBloques(plc, cambios) {
  return pedir(`/api/v1/tia/plcs/${encodeURIComponent(plc)}/bloques/editar`, {
    method: "POST",
    headers: CABECERAS,
    body: JSON.stringify({ cambios }),
  });
}
