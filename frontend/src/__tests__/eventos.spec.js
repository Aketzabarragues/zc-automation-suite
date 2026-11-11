import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { crearClienteEventos } from "../eventos.js";

/** Fuente de eventos falsa, con la misma interfaz que un EventSource. */
function fuenteFalsa() {
  return {
    onopen: null,
    onmessage: null,
    onerror: null,
    cerrada: false,
    close() {
      this.cerrada = true;
    },
  };
}

describe("cliente de eventos", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("entrega los eventos que llegan", () => {
    const fuentes = [];
    const eventos = [];
    const cliente = crearClienteEventos({
      crearFuente: () => {
        const fuente = fuenteFalsa();
        fuentes.push(fuente);
        return fuente;
      },
      onEvento: (evento) => eventos.push(evento),
    });

    cliente.abrir();
    expect(fuentes).toHaveLength(1);

    fuentes[0].onmessage({
      data: JSON.stringify({ type: "log", nivel: "info", mensaje: "hola" }),
    });
    expect(eventos).toHaveLength(1);
    expect(eventos[0].mensaje).toBe("hola");
  });

  it("ignora lo que no es JSON", () => {
    const fuentes = [];
    const eventos = [];
    const cliente = crearClienteEventos({
      crearFuente: () => {
        const fuente = fuenteFalsa();
        fuentes.push(fuente);
        return fuente;
      },
      onEvento: (evento) => eventos.push(evento),
    });

    cliente.abrir();
    fuentes[0].onmessage({ data: "esto no es json" });
    expect(eventos).toHaveLength(0);
  });

  it("avisa del estado de la conexion", () => {
    const fuentes = [];
    const estados = [];
    const cliente = crearClienteEventos({
      crearFuente: () => {
        const fuente = fuenteFalsa();
        fuentes.push(fuente);
        return fuente;
      },
      onEstado: (estado) => estados.push(estado.estado),
    });

    cliente.abrir();
    fuentes[0].onopen();
    expect(estados).toContain("conectado");
  });

  it("reconecta solo cuando se cae", () => {
    const fuentes = [];
    const estados = [];
    const cliente = crearClienteEventos({
      crearFuente: () => {
        const fuente = fuenteFalsa();
        fuentes.push(fuente);
        return fuente;
      },
      onEstado: (estado) => estados.push(estado.estado),
      esperaMinima: 1000,
      esperaMaxima: 4000,
    });

    cliente.abrir();
    fuentes[0].onerror(new Error("se ha caido"));
    expect(estados).toContain("reconectando");
    expect(fuentes[0].cerrada).toBe(true);
    expect(fuentes).toHaveLength(1);

    vi.advanceTimersByTime(1000);
    expect(fuentes).toHaveLength(2);
  });

  it("espera cada vez mas entre reintentos", () => {
    const fuentes = [];
    const cliente = crearClienteEventos({
      crearFuente: () => {
        const fuente = fuenteFalsa();
        fuentes.push(fuente);
        return fuente;
      },
      esperaMinima: 1000,
      esperaMaxima: 4000,
    });

    cliente.abrir();
    fuentes[0].onerror();
    vi.advanceTimersByTime(1000);
    expect(fuentes).toHaveLength(2);

    fuentes[1].onerror();
    vi.advanceTimersByTime(1000);
    expect(fuentes).toHaveLength(2);

    vi.advanceTimersByTime(1000);
    expect(fuentes).toHaveLength(3);
  });

  it("cerrar deja de reconectar", () => {
    const fuentes = [];
    const cliente = crearClienteEventos({
      crearFuente: () => {
        const fuente = fuenteFalsa();
        fuentes.push(fuente);
        return fuente;
      },
    });

    cliente.abrir();
    cliente.cerrar();
    vi.advanceTimersByTime(10000);
    expect(fuentes).toHaveLength(1);
  });
});
