/**
 * Cliente del stream de eventos del backend.
 *
 * El backend publica cuatro tipos de evento por ``GET /api/eventos``:
 * ``tia`` (cambia la conexion), ``progress`` (cambia el avance de un
 * trabajo), ``job`` (termina un trabajo) y ``log`` (linea de log).
 *
 * El stream es la unica fuente de updates: no hay polling. Si se cae, el
 * cliente reconecta solo con espera creciente.
 */
import { useLogsStore } from "./stores/logs.js";
import { useTrabajosStore } from "./stores/trabajos.js";
import { useTiaStore } from "./stores/tia.js";
import { crearFuenteDemo } from "./demo.js";
import { estado } from "./api.js";

/** Ruta del stream de eventos. */
export const RUTA_EVENTOS = "/api/eventos";

/** Espera inicial antes de reconectar, en milisegundos. */
export const ESPERA_MINIMA = 1000;

/** Espera maxima entre reintentos, en milisegundos. */
export const ESPERA_MAXIMA = 15000;

/**
 * Crea un cliente del stream de eventos con reconexion automatica.
 *
 * @param {object} opciones opciones.
 * @param {string} opciones.url ruta del stream.
 * @param {Function} opciones.onEvento recibe cada evento ya parseado.
 * @param {Function} opciones.onEstado recibe los cambios de estado del
 *   stream: `conectado`, `reconectando`, `cerrado` o `error`.
 * @param {Function} opciones.crearFuente fabrica la fuente. Por defecto un
 *   `EventSource`; en el demo, una fuente simulada.
 * @param {number} opciones.esperaMinima espera inicial de reconexion.
 * @param {number} opciones.esperaMaxima espera maxima de reconexion.
 * @returns {object} el cliente, con `abrir()` y `cerrar()`.
 */
export function crearClienteEventos(opciones = {}) {
  const {
    url = RUTA_EVENTOS,
    onEvento = () => {},
    onEstado = () => {},
    crearFuente = (destino) => new EventSource(destino),
    esperaMinima = ESPERA_MINIMA,
    esperaMaxima = ESPERA_MAXIMA,
  } = opciones;

  let fuente = null;
  let temporizador = null;
  let espera = esperaMinima;
  let cerrado = false;

  function soltar() {
    if (!fuente) return;
    fuente.onopen = null;
    fuente.onmessage = null;
    fuente.onerror = null;
    if (typeof fuente.close === "function") fuente.close();
    fuente = null;
  }

  function programar() {
    if (cerrado || temporizador) return;
    temporizador = setTimeout(() => {
      temporizador = null;
      abrir();
    }, espera);
    espera = Math.min(espera * 2, esperaMaxima);
  }

  function abrir() {
    if (cerrado) return;
    try {
      fuente = crearFuente(url);
    } catch (error) {
      onEstado({ estado: "error", error });
      programar();
      return;
    }
    fuente.onopen = () => {
      espera = esperaMinima;
      onEstado({ estado: "conectado" });
    };
    fuente.onmessage = (evento) => {
      let datos;
      try {
        datos = JSON.parse(evento.data);
      } catch {
        return;
      }
      onEvento(datos);
    };
    fuente.onerror = (error) => {
      onEstado({ estado: "reconectando", error });
      soltar();
      programar();
    };
  }

  return {
    abrir,
    cerrar() {
      cerrado = true;
      if (temporizador) {
        clearTimeout(temporizador);
        temporizador = null;
      }
      soltar();
      onEstado({ estado: "cerrado" });
    },
    get esperando() {
      return temporizador !== null;
    },
  };
}

/**
 * Arranca el stream de eventos y reparte lo que llega a los stores.
 *
 * @param {object} opciones opciones.
 * @param {boolean} opciones.demo si es `true` no se abre el stream: se
 *   simulan los eventos.
 * @returns {object} el cliente del stream.
 */
export function arrancarEventos({ demo = false } = {}) {
  const tia = useTiaStore();
  const trabajos = useTrabajosStore();
  const logs = useLogsStore();

  tia.demo = demo;

  const cliente = crearClienteEventos({
    crearFuente: demo ? () => crearFuenteDemo() : (destino) => new EventSource(destino),
    onEvento: (evento) => {
      if (evento.type === "tia") {
        tia.aplicar(evento);
      } else if (evento.type === "progress") {
        trabajos.aplicar(evento);
      } else if (evento.type === "job") {
        // El resultado lo espera quien lo encolo, con
        // ``trabajos.esperar(job_id)``. Aqui solo se guarda.
        // El final del trabajo (terminado, cancelado o fallo) ya llega a la
        // consola como linea de log del backend: aqui no se repite.
        trabajos.aplicar(evento);
      } else if (evento.type === "log") {
        logs.aplicar(evento);
      }
    },
    onEstado: (estado) => {
      tia.estadoStream = estado.estado;
    },
  });

  cliente.abrir();

  // El evento `tia` solo se publica cuando la conexion **cambia**. Al
  // abrir la app hay que preguntar el estado actual, o la vista PLC
  // saldria desconectada aunque el portal este vivo.
  if (!demo) {
    estado()
      .then((datos) => tia.aplicar(datos))
      .catch(() => {});
  }

  return cliente;
}
