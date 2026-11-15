r"""Smoke de crear un proceso desde una plantilla contra un TIA Portal real.

No forma parte de la suite de pytest. Se lanza a mano contra un TIA Portal
abierto con un proyecto de **PRUEBA**.

Uso (PowerShell, desde la raiz del repo):

    python scripts\smoke\procesos_crear.py --plc <PLC> --excel <excel.xlsx> ^
        --uid <N> --plantilla <subcarpeta> --confirmar

Que hace:

1. Conecta con el TIA Portal abierto (solo ``attach``: no abre nada).
2. Lanza el mismo trabajo que la SPA: lee el manifest de la plantilla,
   renombra los bloques del proceso, los importa al PLC en UNA transaccion
   (tablas y bloques juntos) y compila.
3. Saca por pantalla el resultado de cada paso y las transacciones.

**Este script ESCRIBE en el PLC**: por eso pide ``--confirmar``. Sin esa
opcion solo se lanza la prevision (lo que haria el apply) y no se escribe
nada.

**Solo vale con TIA V21 o superior** (la importacion y la compilacion).
Conviene usar un **uid libre**: la prevision lista las colisiones, pero
importar sobre un proceso ya creado lo estropea. Nunca lo lances contra el
PLC de produccion.
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
from zc_suite.areas.alimentacion.funciones.procesos import (  # noqa: E402
    crear as modulo_crear,
)
from zc_suite.areas.alimentacion.funciones.procesos import (  # noqa: E402
    generar_prevision_crear as modulo_prevision_crear,
)
from zc_suite.nucleo.tia import servicio as tia  # noqa: E402
from zc_suite.nucleo.tia.eventos import BusEventos  # noqa: E402
from zc_suite.nucleo.tia.servicio import ServicioTIA  # noqa: E402


def _argumentos() -> argparse.Namespace:
    """Los argumentos de la linea de ordenes."""
    parser = argparse.ArgumentParser(
        description="Smoke de crear un proceso desde una plantilla."
    )
    parser.add_argument("--plc", required=True, help="Nombre del PLC.")
    parser.add_argument(
        "--excel",
        required=True,
        help="Excel maestro del area (el .xlsx o .xlsm del operario).",
    )
    parser.add_argument(
        "--uid",
        required=True,
        type=int,
        help="El uid del proceso nuevo (su base numerica).",
    )
    parser.add_argument(
        "--plantilla",
        required=True,
        help="El nombre de la subcarpeta de la plantilla, dentro de la carpeta de plantillas.",
    )
    parser.add_argument(
        "--plantillas-dir",
        default=None,
        help="Carpeta con las plantillas. Si no viene, se usa la ruta del config.",
    )
    parser.add_argument(
        "--confirmar",
        action="store_true",
        help="Escribir el proceso en el PLC. Sin esta opcion solo se previsualiza.",
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


def _pintar_prevision(resultado: dict[str, Any], uid: int) -> None:
    """Saca por pantalla lo que haria el apply."""
    manifest = resultado["manifest_plantilla"]
    print("\n--- proceso ---")
    print(f"  uid: {uid}")
    if manifest:
        print(f"  plantilla: base={manifest['base']} codigo={manifest['codigo']}")

    if not resultado["precondiciones_ok"]:
        print("\n--- precondiciones ---")
        for bloque in resultado["missing_blocks"]:
            print(f"  {bloque}")
        for colision in resultado["colisiones"]:
            print(f"  colision: {colision} (ya existe en el PLC)")
        print("\nNo se lanzara el apply: arregla las precondiciones primero.")
        return

    print("\n--- archivos previstos ---")
    for archivo in resultado["archivos_previstos"]:
        print(f"  {archivo}")

    print("\n--- avisos ---")
    for aviso in resultado["warnings"]:
        print(f"  {aviso}")


def _pintar(resultado: dict[str, Any]) -> None:
    """Saca por pantalla lo que se ha aplicado y como ha quedado cada transaccion."""
    print("\n--- proceso ---")
    print(f"  {resultado['process_label']} en {resultado['plc']}")
    print(f"  archivos generados: {len(resultado['archivos_generados'])}")

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

    print("\n--- escaneo ---")
    estado_escaneo = "actualizado" if resultado["escaneo_actualizado"] else "no actualizado"
    print(f"  escaneo del PLC: {estado_escaneo}")


def main() -> int:
    """Conecta y crea el proceso desde la plantilla."""
    argumentos = _argumentos()
    modelo = _modelo()

    almacen = AlmacenExcel()
    almacen.config = modelo
    almacen.volcar(Path(argumentos.excel))
    for aviso in almacen.estado()["avisos"]:
        print(f"Aviso del Excel: {aviso}")

    plantillas_dir = Path(argumentos.plantillas_dir) if argumentos.plantillas_dir else None

    if not argumentos.confirmar:
        print(
            "\nSin --confirmar no se escribe nada: el apply no llega a lanzarse.\n"
            "Esta es la prevision (lo que haria el apply):\n"
        )
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

            print(
                f"Previsualizando la creacion del proceso {argumentos.uid} "
                f"desde la plantilla {argumentos.plantilla} del PLC {argumentos.plc}..."
            )
            job_id = servicio.lanzar(
                modulo_prevision_crear.generar_prevision_crear,
                proc_uid=argumentos.uid,
                plc=argumentos.plc,
                dir_plantilla_nombre=argumentos.plantilla,
                almacen=almacen,
                config=modelo,
                plantillas_dir=plantillas_dir,
            )
            exportacion = _esperar(bus, job_id)
            if exportacion["estado"] != "ok":
                print(f"\n  ERROR: {exportacion.get('error')}")
                return 1

            _pintar_prevision(exportacion["resultado"], argumentos.uid)
            print(
                "\nRelanzalo con --confirmar contra un proyecto de PRUEBA."
            )
            return 2
        finally:
            servicio.parar()

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

        print(
            f"Creando el proceso {argumentos.uid} desde la plantilla "
            f"{argumentos.plantilla} en el PLC {argumentos.plc}..."
        )
        job_id = servicio.lanzar(
            modulo_crear.crear,
            proc_uid=argumentos.uid,
            plc=argumentos.plc,
            dir_plantilla_nombre=argumentos.plantilla,
            almacen=almacen,
            config=modelo,
            plantillas_dir=plantillas_dir,
        )
        creacion = _esperar(bus, job_id)
        if creacion["estado"] != "ok":
            print(f"\n  ERROR: {creacion.get('error')}")
            return 1

        _pintar(creacion["resultado"])
        print("\nEl proyecto NO se ha guardado: revisa el PLC en TIA Portal.")
        return 0
    finally:
        servicio.parar()


if __name__ == "__main__":
    raise SystemExit(main())
