r"""Smoke de la prevision de crear un proceso desde una plantilla.

No forma parte de la suite de pytest. Se lanza a mano contra un TIA Portal
abierto con un proyecto de **PRUEBA**.

Uso (PowerShell, desde la raiz del repo):

    python scripts\smoke\procesos_crear_prevision.py --plc <PLC> --excel <excel.xlsx> ^
        --uid <N> --plantilla <subcarpeta>

Que hace:

1. Conecta con el TIA Portal abierto (solo ``attach``: no abre ni escribe
   nada).
2. Lanza el mismo trabajo que la SPA: lee el manifest de la plantilla
   (la subcarpeta indicada dentro de la carpeta de plantillas del config),
   la copia al workdir de preview y cruza sus bloques con el escaneo del
   PLC.
3. Saca por pantalla que bloques se crearian, que colisionan y que
   dependencias externas faltan.

**Prohibido escribir, importar o compilar**: este script solo lee de TIA y
escribe en disco local (el workdir del flujo).

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
from zc_suite.areas.alimentacion.funciones.procesos import (  # noqa: E402
    generar_prevision_crear as modulo_crear,
)
from zc_suite.nucleo.tia import servicio as tia  # noqa: E402
from zc_suite.nucleo.tia.eventos import BusEventos  # noqa: E402
from zc_suite.nucleo.tia.servicio import ServicioTIA  # noqa: E402


def _argumentos() -> argparse.Namespace:
    """Los argumentos de la linea de ordenes."""
    parser = argparse.ArgumentParser(
        description="Smoke de la prevision de crear un proceso desde una plantilla."
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


def _pintar(resultado: dict[str, Any], uid: int) -> None:
    """Saca por pantalla lo que haria el apply."""
    manifest = resultado["manifest_plantilla"]
    print("\n--- proceso ---")
    print(f"  uid: {uid}")
    if manifest:
        print(f"  plantilla: base={manifest['base']} codigo={manifest['codigo']}")
    if resultado["descripcion"]:
        print(f"  descripcion: {resultado['descripcion']}")

    if not resultado["precondiciones_ok"]:
        print("\n--- precondiciones ---")
        for bloque in resultado["missing_blocks"]:
            print(f"  {bloque}")
        for colision in resultado["colisiones"]:
            print(f"  colision: {colision} (ya existe en el PLC)")

    print("\n--- dependencias ---")
    for bloque in resultado["dependencias_ok"]:
        print(f"  ok: {bloque}")
    for bloque in resultado["dependencias_faltantes"]:
        print(f"  FALTA: {bloque}")

    print("\n--- archivos previstos ---")
    if not resultado["archivos_previstos"]:
        print("  (ninguno)")
    for archivo in resultado["archivos_previstos"]:
        print(f"  {archivo}")

    print("\n--- colisiones ---")
    if not resultado["colisiones"]:
        print("  (ninguna)")
    for colision, existente in zip(
        resultado["colisiones"],
        resultado["colisiones_con"].values(),
        strict=False,
    ):
        print(f"  {colision} -> ya existe: {existente}")

    print("\n--- avisos ---")
    for aviso in resultado["warnings"]:
        print(f"  {aviso}")


def main() -> int:
    """Conecta y saca el preview de la creacion."""
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

        print(
            f"Previsualizando la creacion del proceso {argumentos.uid} "
            f"desde la plantilla {argumentos.plantilla} del PLC {argumentos.plc}..."
        )
        plantillas_dir = (
            Path(argumentos.plantillas_dir) if argumentos.plantillas_dir else None
        )
        job_id = servicio.lanzar(
            modulo_crear.generar_prevision_crear,
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

        _pintar(exportacion["resultado"], argumentos.uid)
        print(
            f"\nPreview en: {modulo_crear.workdir_crear().carpeta('Plantilla')} "
            "(el apply lo renombra dentro del PLC)."
        )
        return 0
    finally:
        servicio.parar()


if __name__ == "__main__":
    raise SystemExit(main())
