r"""Smoke de la prevision de entidades contra un TIA Portal real.

No forma parte de la suite de pytest. Se lanza a mano contra un TIA Portal
abierto con un proyecto de **PRUEBA**.

Uso (PowerShell, desde la raiz del repo):

    python scripts\smoke\entidades_generar_prevision.py --plc <PLC> --excel <excel.xlsx>

Que hace:

1. Conecta con el TIA Portal abierto (solo ``attach``: no abre ni escribe
   nada).
2. Lanza el mismo trabajo que la SPA: exporta en plano la tabla de los N_MAX
   y la de las entidades y el DB de entidades a
   ``.build_cache/alimentacion/entidades/preview/`` y las compara con el Excel.
3. Saca el diff por pantalla.

**Prohibido escribir, importar o compilar**: este script solo lee de TIA y
escribe en disco local (la carpeta de preview).

Nunca lo lances contra el PLC de produccion.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any

RAIZ = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(RAIZ / "backend"))

from zc_suite.areas.alimentacion import config as config_area  # noqa: E402
from zc_suite.areas.alimentacion.excel.almacen import AlmacenExcel  # noqa: E402
from zc_suite.areas.alimentacion.funciones.entidades import (  # noqa: E402
    generar_prevision as modulo_prevision,
)
from zc_suite.nucleo.tia import servicio as tia  # noqa: E402
from zc_suite.nucleo.tia.eventos import BusEventos  # noqa: E402
from zc_suite.nucleo.tia.servicio import ServicioTIA  # noqa: E402


def _argumentos() -> argparse.Namespace:
    """Los argumentos de la linea de ordenes."""
    parser = argparse.ArgumentParser(description="Smoke de la prevision de entidades.")
    parser.add_argument("--plc", required=True, help="Nombre del PLC.")
    parser.add_argument(
        "--excel",
        required=True,
        help="Excel maestro del area (el .xlsx o .xlsm del operario).",
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


def _modelo() -> Any:
    """El modelo del area, validado a partir del ``config.json``."""
    datos = json.loads((RAIZ / "config" / "config.json").read_text(encoding="utf-8"))
    return config_area.cargar(datos["areas"]["alimentacion"])


def _pintar(resultado: dict[str, Any]) -> None:
    """Saca el diff por pantalla."""
    resumen = resultado["summary"]
    print("\n--- resumen ---")
    print(f"  cambios en la vista: {resumen['total']}")
    print(f"  constantes agregadas: {resumen['constants_agregados']}")
    print(f"  constantes eliminadas: {resumen['constants_eliminados']}")
    print(f"  constantes renombradas: {resumen['constants_renombrados']}")
    print(f"  comentarios actualizados: {resumen['comments_updated']}")

    print("\n--- N_MAX ---")
    if resultado["nmax"].get("nmax_error"):
        print(f"  {resultado['nmax']['nmax_error']}")
    for fila in resultado["nmax"]["todos"]:
        marca = "->" if fila["status"] == "actualizar" else "  "
        print(f"  {marca} {fila['name']}: {fila['actual']} -> {fila['nuevo']}")

    print("\n--- operaciones ---")
    for operacion in resultado["ops"]:
        print(f"  {operacion['kind']:<15} {operacion.get('plc_tag', '')}")

    print("\n--- avisos ---")
    for aviso in resultado["warnings"]:
        print(f"  {aviso}")


def main() -> int:
    """Conecta, exporta y saca el diff."""
    argumentos = _argumentos()
    modelo = _modelo()

    almacen = AlmacenExcel()
    almacen.config = modelo
    almacen.volcar(Path(argumentos.excel))
    for aviso in almacen.estado()["avisos"]:
        print(f"Aviso del Excel: {aviso}")

    bus = BusEventos()
    servicio = ServicioTIA(publicador=bus.publicar)
    servicio.arrancar()
    try:
        print("Conectando con TIA Portal (attach)...")
        job_id = servicio.lanzar(tia.conectar)
        conexion = _esperar(bus, job_id)
        print(f"  conexion: {conexion['estado']}  {conexion.get('error') or ''}")
        if conexion["estado"] != "ok":
            print("\nNo hay conexion. Abre TIA Portal con el proyecto de prueba.")
            return 1

        print(f"Exportando y diffeando el PLC {argumentos.plc}...")
        job_id = servicio.lanzar(
            modulo_prevision.generar_prevision,
            plc=argumentos.plc,
            almacen=almacen,
            config=modelo,
        )
        exportacion = _esperar(bus, job_id)
        if exportacion["estado"] != "ok":
            print(f"\n  ERROR: {exportacion.get('error')}")
            return 1

        _pintar(exportacion["resultado"])
        print(f"\nPreview en: {modulo_prevision.workdir_entidades().preview}")
        return 0
    finally:
        servicio.parar()


if __name__ == "__main__":
    raise SystemExit(main())
