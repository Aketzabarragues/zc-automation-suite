import { createPinia, setActivePinia } from "pinia";
import { beforeEach, describe, expect, it } from "vitest";
import { useTrabajosStore } from "../stores/trabajos.js";

describe("store de trabajos", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
  });

  it("el progreso se guarda en el espejo", () => {
    const trabajos = useTrabajosStore();

    trabajos.aplicar({ type: "progress", active: true, label: "Escanear", percent: 50 });

    expect(trabajos.progreso.label).toBe("Escanear");
    expect(trabajos.progreso.percent).toBe(50);
  });

  it("un trabajo terminado se guarda por su id", () => {
    const trabajos = useTrabajosStore();

    trabajos.aplicar({
      type: "job",
      job: "j1",
      estado: "ok",
      resultado: { bloques: [1, 2] },
      error: null,
    });

    expect(trabajos.terminados.j1.estado).toBe("ok");
    expect(trabajos.terminados.j1.resultado).toEqual({ bloques: [1, 2] });
  });

  it("esperar resuelve en el momento si el trabajo ya termino", async () => {
    const trabajos = useTrabajosStore();
    trabajos.aplicar({ type: "job", job: "j1", estado: "ok", resultado: { ok: 1 }, error: null });

    const job = await trabajos.esperar("j1");

    expect(job.resultado).toEqual({ ok: 1 });
  });

  it("esperar resuelve cuando llega el evento", async () => {
    const trabajos = useTrabajosStore();
    const espera = trabajos.esperar("j1");

    trabajos.aplicar({ type: "job", job: "j1", estado: "ok", resultado: { ok: 2 }, error: null });

    const job = await espera;
    expect(job.resultado).toEqual({ ok: 2 });
  });

  it("el evento puede llegar antes de que se espere", async () => {
    // El trabajo es rapido: el evento sale antes de la respuesta del POST.
    const trabajos = useTrabajosStore();

    trabajos.aplicar({ type: "job", job: "j1", estado: "ok", resultado: { ok: 3 }, error: null });
    const job = await trabajos.esperar("j1");

    expect(job.resultado).toEqual({ ok: 3 });
  });

  it("dos trabajos que terminan en el mismo tick se resuelven los dos", async () => {
    const trabajos = useTrabajosStore();
    const esperaUno = trabajos.esperar("j1");
    const esperaDos = trabajos.esperar("j2");

    trabajos.aplicar({ type: "job", job: "j1", estado: "ok", resultado: { n: 1 }, error: null });
    trabajos.aplicar({ type: "job", job: "j2", estado: "error", resultado: null, error: "ha fallado" });

    const [uno, dos] = await Promise.all([esperaUno, esperaDos]);
    expect(uno.resultado).toEqual({ n: 1 });
    expect(dos.estado).toBe("error");
    expect(dos.error).toBe("ha fallado");
  });

  it("solo se guardan los ultimos 50 trabajos terminados", () => {
    const trabajos = useTrabajosStore();

    for (let indice = 0; indice < 60; indice += 1) {
      trabajos.aplicar({ type: "job", job: `j${indice}`, estado: "ok", resultado: null, error: null });
    }

    expect(Object.keys(trabajos.terminados)).toHaveLength(50);
    expect(trabajos.terminados.j0).toBeUndefined();
    expect(trabajos.terminados.j59).toBeDefined();
  });
});
