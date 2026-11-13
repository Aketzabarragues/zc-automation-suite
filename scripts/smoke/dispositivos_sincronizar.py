r"""Smoke de la sincronizacion de dispositivos contra un TIA Portal real.

No forma parte de la suite de pytest. Se lanza a mano contra un TIA Portal
abierto con un proyecto de **PRUEBA**.

Uso (PowerShell, desde la raiz del repo):

    python scripts\smoke\dispositivos_sincronizar.py --plc <PLC> --excel <excel.xlsx> --confirmar

Que hace:

1. Conecta con el TIA Portal abierto (solo ``attach``: no abre nada).
2. Lanza el mismo trabajo que la SPA: exporta las tablas de dispositivos con
   la estructura de TIA, aplica los N_MAX y los renombres en linea, importa
   las tablas editadas, compila los DBs afectados y aplica los comentarios por
   instancia.
3. Saca por pantalla el estado de cada transaccion.

**Este script ESCRIBE en el PLC**: por eso pide ``--confirmar``. Sin esa
opcion solo lee (exporta y enseña el diff).

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
from zc_suite.areas.alimentacion.funciones.dispositivos import (  # noqa: E402
    sincronizar as modulo_sync,
)
from zc_suite.nucleo.tia import servicio as tia  # noqa: E402
from zc_suite.nucleo.tia.eventos import BusEventos  # noqa: E402
from zc_suite.nucleo.tia.servicio import ServicioTIA  # noqa: E402


def _argumentos() -> argparse.Namespace:
    """Los argumentos de la linea de ordenes."""
    parser = argparse.ArgumentParser(
        description="Smoke de la sincronizacion de dispositivos."
    )
    parser.add_argument("--plc", required=True, help="Nombre del PLC.")
    parser.add_argument(
        "--excel",
        required=True,
        help="Excel maestro del area (el .xlsx o .xlsm del operario).",
    )
    parser.add_argument(
        "--confirmar",
        action="store_true",
        help="Escribir los cambios en el PLC. Sin esta opcion no se escribe.",
    )
    return parser.parse_args()


def _esperar(bus: BusEventos, job_id: str, timeout: float = 1800.0) -> dict[str, Any]:
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
    """Saca por pantalla lo que se ha aplicado y como ha quedado cada transaccion."""
    print("\n--- resumen ---")
    print(f"  operaciones aplicadas: {resultado['operaciones']}")
    print(f"  N_MAX actualizados: {resultado['n_max']['actualizados']}")
    print(f"  renombres: {resultado['n_max']['renombres']}")
    print(f"  tablas con cambios: {resultado['dispositivos']['tablas']}")
    print(f"  agregados: {resultado['dispositivos']['agregados']}")
    print(f"  eliminados: {resultado['dispositivos']['eliminados']}")

    print("\n--- transacciones ---")
    for transaccion in resultado["transacciones"]:
        print(f"  {transaccion['nombre']}: {transaccion['estado']}")
        if transaccion["detalle"]:
            print(f"    {transaccion['detalle']}")

    print("\n--- compilacion ---")
    compilacion = resultado["compilacion"]
    print(f"  {compilacion['detalle']}")
    if compilacion["error"]:
        print(f"  {compilacion['error']}")


def main() -> int:
    """Conecta y sincroniza los dispositivos."""
    argumentos = _argumentos()
    modelo = _modelo()

    almacen = AlmacenExcel()
    almacen.config = modelo
    almacen.volcar(Path(argumentos.excel))
    for aviso in almacen.estado()["avisos"]:
        print(f"Aviso del Excel: {aviso}")

    if not argumentos.confirmar:
        print(
            "\nSin --confirmar no se escribe nada: el sync no llega a lanzarse.\n"
            "Relanzalo con --confirmar contra un proyecto de PRUEBA."
        )
        return 2

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

        print(f"Sincronizando los dispositivos del PLC {argumentos.plc}...")
        job_id = servicio.lanzar(
            modulo_sync.sincronizar,
            plc=argumentos.plc,
            almacen=almacen,
            config=modelo,
        )
        sincronizacion = _esperar(bus, job_id)
        if sincronizacion["estado"] != "ok":
            print(f"\n  ERROR: {sincronizacion.get('error')}")
            return 1

        _pintar(sincronizacion["resultado"])
        print("\nEl proyecto NO se ha guardado: revisa el PLC en TIA Portal.")
        return 0
    finally:
        servicio.parar()


if __name__ == "__main__":
    raise SystemExit(main())
