r"""Smoke de los bloques del PLC.

Modos:

- ``--leer`` lista los bloques del PLC con sus propiedades. No escribe nada.
- ``--escribir`` cambia UNA propiedad de UN bloque, dentro de una transaccion.
  Por defecto deshace el cambio (rollback), de modo que el proyecto queda
  como estaba; con ``--no-deshacer`` hace commit.

Este smoke **ESCRIBE en el proyecto de TIA** en el modo ``--escribir``. Solo
contra un proyecto de PRUEBA. Lo lanza el operario.

No forma parte de la suite de pytest: vive fuera de la recogida, en
``tests/smoke/``.

Uso (PowerShell, desde la raiz del repo):

    # Listar los bloques del PLC (no escribe nada).
    python tests\smoke\smoke_bloques.py --leer --plc ZC_PLC_STD

    # Renombrar un bloque y deshacerlo.
    python tests\smoke\smoke_bloques.py --escribir --plc ZC_PLC_STD `
        --bloque OB1_MAIN --propiedad Name --valor OB1_MAIN_SMOKE

    # Cambiar el numero de un bloque y deshacerlo.
    python tests\smoke\smoke_bloques.py --escribir --plc ZC_PLC_STD `
        --bloque DB10 --propiedad Number --valor 99

    # Con commit de verdad (deja el cambio en el proyecto):
    python tests\smoke\smoke_bloques.py --escribir --plc ZC_PLC_STD `
        --bloque OB1_MAIN --propiedad Name --valor OB1_MAIN_SMOKE --no-deshacer
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
from zc_suite.tia_ops.bloques import (  # noqa: E402
    PROPIEDADES_EDITABLES,
    aplicar_cambios,
    escanear_bloques,
    escanear_tipos_de_usuario,
)


class DeshacerError(Exception):
    """Excepcion controlada para provocar el rollback de la transaccion."""


def _argumentos() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Smoke de bloques del PLC (en --escribir, escribe)."
    )
    modo = parser.add_mutually_exclusive_group(required=True)
    modo.add_argument("--leer", action="store_true", help="Lista los bloques.")
    modo.add_argument("--escribir", action="store_true", help="Cambia UNA propiedad.")
    parser.add_argument("--plc", required=True, help="Nombre del PLC.")
    parser.add_argument("--bloque", default="", help="Nombre del bloque.")
    parser.add_argument(
        "--propiedad",
        default="Name",
        help=f"Propiedad a cambiar: {sorted(PROPIEDADES_EDITABLES)}.",
    )
    parser.add_argument("--valor", default="", help="Valor nuevo.")
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


def _esperar(bus: BusEventos, job_id: str, timeout: float = 180.0) -> dict[str, Any]:
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


def _trabajo_leer(job: Any, plc: str) -> dict[str, Any]:
    """Trabajo de smoke: lista los bloques del PLC."""
    job.empezar("Smoke de bloques", [("leer", "Listar los bloques")])
    with job.paso("leer") as paso:
        bloques = escanear_bloques(job.tia.portal, plc)
        tipos = escanear_tipos_de_usuario(job.tia.portal, plc)
        paso["detail"] = f"{len(bloques)} bloques y {len(tipos)} tipos de usuario"
    return {"bloques": bloques, "tipos": tipos}


def _trabajo_escribir(
    job: Any,
    plc: str,
    bloque: str,
    propiedad: str,
    valor: str,
    deshacer: bool,
) -> dict[str, Any]:
    """Trabajo de smoke: cambia UNA propiedad de un bloque."""
    job.empezar("Smoke de bloques", [("escribir", "Cambiar la propiedad")])
    resultado: dict[str, Any] = {}
    rollback = False

    with job.paso("escribir") as paso:
        try:
            with transaccion(job, "Smoke bloques"):
                resultado = aplicar_cambios(
                    job.tia.portal,
                    plc,
                    bloque,
                    {propiedad: valor},
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


def _imprimir_bloques(bloques: list[dict[str, Any]]) -> None:
    """Lista los bloques con sus propiedades."""
    for bloque in bloques:
        extendidas = bloque["extended"]
        numero = "-" if bloque["numero"] is None else str(bloque["numero"])
        print(
            f"  {bloque['nombre']:<28} {bloque['tipo']:<6} num {numero:<6}"
            f" ruta {bloque['ruta'] or '-'}"
        )
        print(
            f"      titulo={extendidas['title'] or '-'}  "
            f"autor={extendidas['author'] or '-'}  "
            f"version={extendidas['version'] or '-'}"
        )
        print(
            f"      lenguaje={extendidas['programming_language'] or '-'}  "
            f"memoria={extendidas['memory_layout'] or '-'}"
        )


def main() -> int:
    """Conecta y lee o cambia un bloque."""
    argumentos = _argumentos()
    if argumentos.escribir:
        if not argumentos.bloque:
            print("En --escribir hace falta --bloque.")
            return 1
        if not argumentos.valor:
            print("En --escribir hace falta --valor.")
            return 1
        if argumentos.propiedad not in PROPIEDADES_EDITABLES:
            print(
                f"Propiedad '{argumentos.propiedad}' no editable. "
                f"Editables: {sorted(PROPIEDADES_EDITABLES)}."
            )
            return 1

    bus = BusEventos()
    servicio = ServicioTIA(publicador=bus.publicar)
    servicio.arrancar()

    try:
        print(f"PLC: {argumentos.plc}")
        print("Conectando con TIA Portal (attach)...")
        job_id = servicio.lanzar(tia.conectar)
        conexion = _esperar(bus, job_id)
        print(f"  conexion: {conexion['estado']}  {conexion.get('error') or ''}")
        if conexion["estado"] != "ok":
            print("\nNo hay conexion. Abre TIA Portal con el proyecto de prueba.")
            return 1

        if argumentos.leer:
            job_id = servicio.lanzar(_trabajo_leer, plc=argumentos.plc)
            lectura = _esperar(bus, job_id)
            if lectura["estado"] != "ok":
                print(f"\n  ERROR: {lectura.get('error')}")
                return 1
            resultado = lectura["resultado"]
            print("\n--- bloques ---")
            _imprimir_bloques(resultado["bloques"])
            print("\n--- tipos de datos de usuario ---")
            _imprimir_bloques(resultado["tipos"])
            return 0

        print(
            f"Deshacer: {'SI (rollback)' if argumentos.deshacer else 'NO (commit)'}"
        )
        job_id = servicio.lanzar(
            _trabajo_escribir,
            plc=argumentos.plc,
            bloque=argumentos.bloque,
            propiedad=argumentos.propiedad,
            valor=argumentos.valor,
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
