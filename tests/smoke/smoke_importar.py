r"""Smoke de la importacion contra un TIA Portal real.

AVISO: este smoke **ESCRIBE en el proyecto de TIA**. Solo contra un proyecto
de PRUEBA. Lo lanza el operario.

No forma parte de la suite de pytest: vive fuera de la recogida, en
``tests/smoke/``.

Modos:

- ``--modo tablas``  importa tablas de tags (XML SimaticML). Funciona en
  cualquier version de TIA Portal.
- ``--modo bloques`` importa bloques (``.s7dcl``). Necesita TIA Portal V21 o
  superior: antes la API no admite SimaticSD.

Uso (PowerShell). ``DIR`` es la carpeta destino que imprimio
smoke_exportar.py.

    cd tests\smoke

    # 1. Exportar primero.
    python smoke_exportar.py --plc ZC_PLC_STD --tabla 2000_Disp_ED

    # 2a. Importar las tablas de vuelta.
    python smoke_importar.py --modo tablas --plc ZC_PLC_STD --origen DIR `
        --carpeta 2000_Dispositivos

    # 2b. Importar los bloques de vuelta (necesita TIA V21+).
    python smoke_importar.py --modo bloques --plc ZC_PLC_STD --origen DIR
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

from zc_suite import tia  # noqa: E402
from zc_suite.eventos import BusEventos  # noqa: E402
from zc_suite.tia import ServicioTIA  # noqa: E402
from zc_suite.tia_ops.importar import importar_bloques, importar_tablas  # noqa: E402

#: Version minima de TIA Portal para importar bloques en SimaticSD.
VERSION_MINIMA_BLOQUES = 21


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
) -> dict[str, Any]:
    """Trabajo de smoke: se ejecuta entero dentro del hilo de TIA."""
    job.empezar("Smoke de importacion", [("importar", f"Importar {modo}")])
    with job.paso("importar") as paso:
        if modo == "bloques":
            resultado = importar_bloques(job.tia.portal, plc, origen, carpeta)
        else:
            resultado = importar_tablas(job.tia.portal, plc, origen, carpeta)
        paso["detail"] = resultado["importado_de"]
    return resultado


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
        )
        importacion = _esperar(bus, job_id)
        if importacion["estado"] != "ok":
            print(f"\n  ERROR: {importacion.get('error')}")
            return 1

        print("\n--- resultado ---")
        print(f"  {importacion['resultado']}")
        return 0
    finally:
        servicio.parar()


if __name__ == "__main__":
    raise SystemExit(main())
