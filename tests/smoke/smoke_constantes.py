r"""Smoke de las constantes de usuario del PLC.

Modos:

- ``--leer`` lista las constantes de una tabla de tags. No escribe nada.
- ``--escribir`` cambia el valor o el nombre de UNA constante, dentro de una
  transaccion. Por defecto deshace el cambio (rollback), de modo que el
  proyecto queda como estaba; con ``--no-deshacer`` hace commit.

Este smoke **ESCRIBE en el proyecto de TIA** en el modo ``--escribir``. Solo
contra un proyecto de PRUEBA. Lo lanza el operario.

No forma parte de la suite de pytest: vive fuera de la recogida, en
``tests/smoke/``.

Uso (PowerShell, desde la raiz del repo):

    # Listar las constantes de una tabla (no escribe nada).
    python tests\smoke\smoke_constantes.py --leer --plc <PLC> --tabla <TABLA>

    # Cambiar el valor de una constante y deshacerlo.
    python tests\smoke\smoke_constantes.py --escribir --plc <PLC> --tabla <TABLA> `
        --constante <NOMBRE> --valor <VALOR>

    # Renombrar una constante y deshacerlo.
    python tests\smoke\smoke_constantes.py --escribir --plc <PLC> --tabla <TABLA> `
        --constante <NOMBRE> --nombre <NUEVO>

    # Con commit de verdad (deja el cambio en el proyecto):
    python tests\smoke\smoke_constantes.py --escribir --plc <PLC> --tabla <TABLA> `
        --constante <NOMBRE> --valor <VALOR> --no-deshacer
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path
from typing import Any

RAIZ = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(RAIZ / "backend"))

from zc_suite import tia  # noqa: E402
from zc_suite.eventos import BusEventos  # noqa: E402
from zc_suite.tia import ServicioTIA, transaccion  # noqa: E402
from zc_suite.tia_ops.constantes import (  # noqa: E402
    cambiar_valor,
    leer_constantes,
    renombrar,
)


class DeshacerError(Exception):
    """Excepcion controlada para provocar el rollback de la transaccion."""


def _argumentos() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Smoke de constantes de usuario (en --escribir, escribe)."
    )
    modo = parser.add_mutually_exclusive_group(required=True)
    modo.add_argument("--leer", action="store_true", help="Lista las constantes.")
    modo.add_argument("--escribir", action="store_true", help="Cambia UNA constante.")
    parser.add_argument("--plc", required=True, help="Nombre del PLC.")
    parser.add_argument("--tabla", required=True, help="Nombre de la tabla de tags.")
    parser.add_argument("--constante", default="", help="Nombre de la constante.")
    parser.add_argument("--valor", default="", help="Valor nuevo.")
    parser.add_argument("--nombre", default="", help="Nombre nuevo (renombrar).")
    parser.add_argument(
        "--deshacer",
        dest="deshacer",
        action="store_true",
        default=True,
        help="Deshace el cambio con un rollback. Es lo de por defecto.",
    )
    parser.add_argument(
        "--no-deshacer",
        dest="deshacer",
        action="store_false",
        help="Confirma el cambio: hace commit.",
    )
    return parser.parse_args()


def _esperar(bus: BusEventos, job_id: str, timeout: float = 120.0) -> dict[str, Any]:
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


def _trabajo_leer(job: Any, plc: str, tabla: str) -> dict[str, Any]:
    """Trabajo de smoke: lee las constantes de una tabla."""
    job.empezar("Smoke de constantes", [("leer", "Leer las constantes")])
    with job.paso("leer") as paso:
        constantes = leer_constantes(job.tia.portal, plc, tabla)
        paso["detail"] = f"{len(constantes)} constantes"
    return {"constantes": constantes}


def _trabajo_escribir(
    job: Any,
    plc: str,
    tabla: str,
    constante: str,
    valor: str,
    nombre: str,
    deshacer: bool,
) -> dict[str, Any]:
    """Trabajo de smoke: cambia UNA constante dentro de una transaccion."""
    job.empezar("Smoke de constantes", [("escribir", "Cambiar la constante")])
    resultado: dict[str, Any] = {}
    rollback = False

    with job.paso("escribir") as paso:
        try:
            with transaccion(job, "Smoke constantes"):
                if nombre:
                    resultado["renombrar"] = renombrar(
                        job.tia.portal, plc, tabla, constante, nombre
                    )
                else:
                    resultado["cambiar_valor"] = cambiar_valor(
                        job.tia.portal, plc, tabla, constante, valor
                    )
                if deshacer:
                    raise DeshacerError("Rollback pedido por --deshacer.")
        except DeshacerError:
            rollback = True
            paso["detail"] = "cambiado y deshecho"
        except Exception:
            paso["detail"] = "ha fallado"
            raise
        else:
            paso["detail"] = "cambiado y confirmado"

    return {"cambio": resultado, "rollback": rollback}


def main() -> int:
    """Conecta y lee o cambia una constante."""
    argumentos = _argumentos()
    if argumentos.escribir and not argumentos.constante:
        print("En --escribir hace falta --constante.")
        return 1

    bus = BusEventos()
    servicio = ServicioTIA(publicador=bus.publicar)
    servicio.arrancar()

    try:
        print(f"PLC: {argumentos.plc}   Tabla: {argumentos.tabla}")
        print("Conectando con TIA Portal (attach)...")
        job_id = servicio.lanzar(tia.conectar)
        conexion = _esperar(bus, job_id)
        print(f"  conexion: {conexion['estado']}  {conexion.get('error') or ''}")
        if conexion["estado"] != "ok":
            print("\nNo hay conexion. Abre TIA Portal con el proyecto de prueba.")
            return 1

        if argumentos.leer:
            job_id = servicio.lanzar(
                _trabajo_leer,
                plc=argumentos.plc,
                tabla=argumentos.tabla,
            )
            lectura = _esperar(bus, job_id)
            if lectura["estado"] != "ok":
                print(f"\n  ERROR: {lectura.get('error')}")
                return 1
            print("\n--- constantes ---")
            for constante in lectura["resultado"]["constantes"]:
                print(f"  {constante['nombre']} = {constante['valor']}")
            return 0

        print(
            f"Deshacer: {'SI (rollback)' if argumentos.deshacer else 'NO (commit)'}"
        )
        job_id = servicio.lanzar(
            _trabajo_escribir,
            plc=argumentos.plc,
            tabla=argumentos.tabla,
            constante=argumentos.constante,
            valor=argumentos.valor,
            nombre=argumentos.nombre,
            deshacer=argumentos.deshacer,
        )
        cambio = _esperar(bus, job_id)
        if cambio["estado"] != "ok":
            print(f"\n  ERROR: {cambio.get('error')}")
            return 1

        resultado = cambio["resultado"]
        print("\n--- resultado ---")
        print(f"  {resultado['cambio']}")
        if resultado["rollback"]:
            print("  rollback: SI (la transaccion se ha deshecho)")
        else:
            print("  rollback: NO (se ha hecho commit)")
        print("  todo bien: SI")
        return 0
    finally:
        servicio.parar()


if __name__ == "__main__":
    raise SystemExit(main())
