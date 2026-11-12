r"""Smoke de la importacion contra un TIA Portal real.

AVISO: este smoke **ESCRIBE en el proyecto de TIA**. Solo contra un proyecto
de PRUEBA. Lo lanza el operario.

No forma parte de la suite de pytest: vive fuera de la recogida, en
``scripts/smoke/``.

Que hace:

1. Se engancha al TIA Portal abierto.
2. Importa la tabla o los bloques indicados **dentro de una transaccion**.
3. Por defecto (``--deshacer``) **deshace** la importacion: lanza una
   excepcion controlada dentro de la transaccion, de modo que
   ``transaccion()`` ejecuta ``end_transaction(rollback=True)`` y el proyecto
   queda como estaba. Con ``--no-deshacer`` hace commit.

Asi el smoke prueba tambien ``transaccion()`` contra TIA real: el
``start_transaction``, el rollback y el commit no se habian probado nunca en
vivo.

Modos:

- ``--modo tablas``  importa tablas de tags (XML SimaticML). Funciona en
  cualquier version de TIA Portal.
- ``--modo bloques`` importa bloques (``.s7dcl``). Necesita TIA Portal V21 o
  superior: antes la API no admite SimaticSD.

Uso (PowerShell, desde la raiz del repo). ``DIR`` es la carpeta destino que
imprimio ``exportar.py``.

    # 1. Exportar primero.
    python scripts\smoke\exportar.py --plc <PLC> --tabla 2000_Disp_ED

    # 2a. Importar las tablas de vuelta y deshacerlo.
    python scripts\smoke\importar.py --modo tablas --plc <PLC> --origen DIR `
        --carpeta 2000_Dispositivos

    # 2b. Importar los bloques de vuelta y deshacerlo (necesita TIA V21+).
    python scripts\smoke\importar.py --modo bloques --plc <PLC> --origen DIR

    # Sin deshacer (commit de verdad):
    python scripts\smoke\importar.py --modo tablas --plc <PLC> --origen DIR --no-deshacer

Sin ``--carpeta``, no se manda ``target_folder_path`` a TIA: es lo que hace
que TIA haga match UPDATE por nombre en vez de intentar CREATE y fallar.
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
from zc_suite.nucleo.tia.transaccion import transaccion  # noqa: E402
from zc_suite.tia_ops.importar import importar_bloques, importar_tablas  # noqa: E402

#: Version minima de TIA Portal para importar bloques en SimaticSD.
VERSION_MINIMA_BLOQUES = 21


class DeshacerError(Exception):
    """Excepcion controlada para provocar el rollback de la transaccion."""


def _argumentos() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Smoke de importacion contra TIA Portal (escribe en el proyecto)."
    )
    parser.add_argument(
        "--modo",
        choices=("tablas", "bloques"),
        required=True,
        help="Que se importa.",
    )
    parser.add_argument("--plc", required=True, help="Nombre del PLC.")
    parser.add_argument(
        "--origen",
        required=True,
        help="Carpeta con los ficheros a importar.",
    )
    parser.add_argument(
        "--carpeta",
        default="",
        help=(
            "Carpeta del PLC destino. Si se deja vacia, no se manda "
            "target_folder_path a TIA (match UPDATE por nombre)."
        ),
    )
    parser.add_argument(
        "--deshacer",
        dest="deshacer",
        action="store_true",
        default=True,
        help="Deshace la importacion con un rollback. Es lo de por defecto.",
    )
    parser.add_argument(
        "--no-deshacer",
        dest="deshacer",
        action="store_false",
        help="Confirma la importacion: hace commit.",
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


def _version_mayor_igual(version: str, menor: int) -> bool:
    """``True`` si la version (``"V21.1"``) es al menos la indicada."""
    try:
        mayor = int(version.lstrip("V").split(".")[0])
    except (ValueError, IndexError):
        return False
    return mayor >= menor


def _trabajo_importar(
    job: Any,
    modo: str,
    plc: str,
    origen: Path,
    carpeta: str,
    deshacer: bool,
) -> dict[str, Any]:
    """Trabajo de smoke: se ejecuta entero dentro del hilo de TIA."""
    job.empezar("Smoke de importacion", [("importar", f"Importar {modo}")])
    importado: dict[str, Any] = {}
    rollback = False
    error_rollback: str | None = None

    with job.paso("importar") as paso:
        try:
            with transaccion(job, "Smoke importar"):
                if modo == "bloques":
                    importado = importar_bloques(job.tia.portal, plc, origen, carpeta)
                else:
                    importado = importar_tablas(job.tia.portal, plc, origen, carpeta)
                if deshacer:
                    raise DeshacerError("Rollback pedido por --deshacer.")
        except DeshacerError:
            rollback = True
            paso["detail"] = "importado y deshecho"
        except Exception as exc:
            error_rollback = f"{type(exc).__name__}: {exc}"
            paso["detail"] = "ha fallado"
            raise
        else:
            paso["detail"] = "importado y confirmado"

    return {
        "importado": importado,
        "rollback": rollback,
        "error_rollback": error_rollback,
    }


def main() -> int:
    """Conecta, importa y muestra el resultado."""
    argumentos = _argumentos()
    origen = Path(argumentos.origen)
    if not origen.is_dir():
        print(f"No existe la carpeta de origen: {origen}")
        return 1

    bus = BusEventos()
    servicio = ServicioTIA(publicador=bus.publicar)
    servicio.arrancar()

    try:
        print(f"Origen: {origen}")
        print(f"Modo: {argumentos.modo}   PLC: {argumentos.plc}")
        destino = argumentos.carpeta or "(ninguna: no se manda target_folder_path)"
        print(f"Carpeta destino: {destino}")
        print(f"Deshacer: {'SI (rollback)' if argumentos.deshacer else 'NO (commit)'}")
        print("Conectando con TIA Portal (attach)...")
        job_id = servicio.lanzar(tia.conectar)
        conexion = _esperar(bus, job_id)
        print(f"  conexion: {conexion['estado']}  {conexion.get('error') or ''}")
        if conexion["estado"] != "ok":
            print("\nNo hay conexion. Abre TIA Portal con el proyecto de prueba.")
            return 1

        version = conexion["resultado"].get("version_tia", "")
        print(f"  version de TIA: {version or '(desconocida)'}")

        if argumentos.modo == "bloques" and not _version_mayor_igual(
            version, VERSION_MINIMA_BLOQUES
        ):
            print(
                f"\nLa importacion de bloques necesita TIA Portal V{VERSION_MINIMA_BLOQUES} "
                f"o superior. Con TIA {version or '(desconocida)'} la API no admite "
                "SimaticSD. Usa --modo tablas."
            )
            return 1

        print(f"Importando {argumentos.modo}...")
        job_id = servicio.lanzar(
            _trabajo_importar,
            modo=argumentos.modo,
            plc=argumentos.plc,
            origen=origen,
            carpeta=argumentos.carpeta,
            deshacer=argumentos.deshacer,
        )
        importacion = _esperar(bus, job_id)
        if importacion["estado"] != "ok":
            print(f"\n  ERROR: {importacion.get('error')}")
            return 1

        resultado = importacion["resultado"]
        print("\n--- resultado de la importacion ---")
        print(f"  {resultado['importado']}")
        print("\n--- transaccion ---")
        if resultado["rollback"]:
            print("  rollback: SI (la transaccion se ha deshecho)")
        else:
            print("  rollback: NO (se ha hecho commit)")
        print(f"  todo bien: {'SI' if not resultado['error_rollback'] else 'NO'}")
        if resultado["error_rollback"]:
            print(f"  fallo: {resultado['error_rollback']}")
        return 0
    finally:
        servicio.parar()


if __name__ == "__main__":
    raise SystemExit(main())
