r"""Smoke de la compilacion del software del PLC.

Este smoke **solo compila**: no exporta, no importa y no cambia el proyecto.
Compilar no altera la logica del PLC, solo su estado compilado.

No forma parte de la suite de pytest: vive fuera de la recogida, en
``scripts/smoke/``. Lo lanza el operario.

Uso (PowerShell, desde la raiz del repo):

    # Compilar todo el software del PLC.
    python scripts\smoke\compilar.py --plc <PLC>

    # Compilar solo algunos bloques (los que ya estan consistentes se saltan).
    python scripts\smoke\compilar.py --plc <PLC> --bloques OB1_MAIN DB2000_ED

Las tablas de tags no se compilan: no son codigo.
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path
from typing import Any

RAIZ = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(RAIZ / "backend"))

from zc_suite.nucleo.tia import servicio as tia  # noqa: E402
from zc_suite.nucleo.tia.eventos import BusEventos  # noqa: E402
from zc_suite.nucleo.tia.servicio import ServicioTIA  # noqa: E402
from zc_suite.tia_ops.compilar import compilar_bloques, compilar_plc  # noqa: E402


def _argumentos() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Smoke de compilacion del PLC (solo compila, no escribe nada)."
    )
    parser.add_argument("--plc", required=True, help="Nombre del PLC.")
    parser.add_argument(
        "--bloques",
        nargs="+",
        default=[],
        help=(
            "Bloques a compilar. Opcional: sin este argumento se compila "
            "todo el software del PLC."
        ),
    )
    return parser.parse_args()


def _esperar(bus: BusEventos, job_id: str, timeout: float = 300.0) -> dict[str, Any]:
    """Espera al evento de fin del trabajo indicado."""
    suscriptor = bus.suscribir()
    try:
        limite = time.monotonic() + timeout
        while time.monotonic() < limite:
            evento = suscriptor.siguiente(timeout=1.0)
            if evento is None or evento.get("type") != "job":
                continue
            if evento.get("job") == job_id:
                return evento
        raise TimeoutError(f"El trabajo {job_id} no ha terminado en {timeout} s.")
    finally:
        suscriptor.cerrar()


def _trabajo_compilar(
    job: Any,
    plc: str,
    bloques: list[str],
) -> dict[str, Any]:
    """Trabajo de smoke: se ejecuta entero dentro del hilo de TIA."""
    if bloques:
        job.empezar("Smoke de compilacion", [("compilar", "Compilar bloques")])
        with job.paso("compilar") as paso:
            resultado = compilar_bloques(job.tia.portal, plc, bloques)
            paso["detail"] = (
                f"{resultado['n_compilados_ok']} ok, "
                f"{resultado['n_compilados_error']} con error, "
                f"{resultado['n_sin_cambios']} sin cambios, "
                f"{resultado['n_no_encontrados']} no encontrados"
            )
        return resultado

    job.empezar("Smoke de compilacion", [("compilar", "Compilar el PLC")])
    with job.paso("compilar") as paso:
        resultado = compilar_plc(job.tia.portal, plc)
        paso["detail"] = (
            f"con errores: {'; '.join(resultado['errores'])}"
            if resultado["tiene_errores"]
            else "sin errores"
        )
    return resultado


def main() -> int:
    """Conecta, compila y muestra el resultado."""
    argumentos = _argumentos()

    bus = BusEventos()
    servicio = ServicioTIA(publicador=bus.publicar)
    servicio.arrancar()

    try:
        modo = "bloques" if argumentos.bloques else "todo el software del PLC"
        print(f"PLC: {argumentos.plc}   Compilando: {modo}")
        print("Conectando con TIA Portal (attach)...")
        job_id = servicio.lanzar(tia.conectar)
        conexion = _esperar(bus, job_id)
        print(f"  conexion: {conexion['estado']}  {conexion.get('error') or ''}")
        if conexion["estado"] != "ok":
            print("\nNo hay conexion. Abre TIA Portal con el proyecto de prueba.")
            return 1

        version = conexion["resultado"].get("version_tia", "")
        print(f"  version de TIA: {version or '(desconocida)'}")

        job_id = servicio.lanzar(
            _trabajo_compilar,
            plc=argumentos.plc,
            bloques=argumentos.bloques,
        )
        compilacion = _esperar(bus, job_id)
        if compilacion["estado"] != "ok":
            print(f"\n  ERROR: {compilacion.get('error')}")
            return 1

        resultado = compilacion["resultado"]
        print("\n--- resultado ---")
        for clave, valor in resultado.items():
            print(f"  {clave}: {valor}")
        return 0
    finally:
        servicio.parar()


if __name__ == "__main__":
    raise SystemExit(main())
