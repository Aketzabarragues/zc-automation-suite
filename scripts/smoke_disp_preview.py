"""Smoke de la prevision de dispositivos contra un TIA Portal real.

No forma parte de la suite de pytest. Se lanza a mano contra un TIA Portal
abierto con un proyecto de **PRUEBA**.

Uso (PowerShell, desde la raiz del repo):

    python scripts/smoke_disp_preview.py --plc <PLC> --excel <excel.xlsx>

Que hace:

1. Conecta con el TIA Portal abierto (solo ``attach``: no abre ni escribe
   nada).
2. Exporta en plano la tabla de los N_MAX y las tablas de tags de los
   dispositivos a ``.build_cache/alimentacion/disp/preview/``.
3. Compara lo exportado con el Excel y saca el diff por pantalla.

**Prohibido escribir, importar o compilar**: este script solo lee de TIA y
escribe en disco local (la carpeta de preview).

Nunca lo lances contra el PLC de produccion.

Ojo: los comentarios de TIA (SimaticSD) solo se pueden leer en TIA V21. En
V18 se saltan con un aviso y el diff sale igual.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / "backend"))

from zc_suite import tia  # noqa: E402
from zc_suite.areas.alimentacion.dispositivo import (  # noqa: E402
    disp_preview,
    disp_trabajo,
)
from zc_suite.areas.alimentacion.excel import parser as parser_excel  # noqa: E402
from zc_suite.eventos import BusEventos  # noqa: E402
from zc_suite.tia import ServicioTIA  # noqa: E402
from zc_suite.tia_ops.exportar import exportar_tablas  # noqa: E402


def _argumentos() -> argparse.Namespace:
    """Los argumentos de la linea de ordenes."""
    parser = argparse.ArgumentParser(description="Smoke de la prevision de dispositivos.")
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


def _config() -> dict[str, Any]:
    """La seccion del area en el ``config.json``."""
    datos = json.loads((RAIZ / "config" / "config.json").read_text(encoding="utf-8"))
    return datos["areas"]["alimentacion"]


def _smoke(
    job: Any,
    plc: str,
    excel: dict[str, Any],
    config: dict[str, Any],
) -> dict[str, Any]:
    """El trabajo de smoke: exporta y calcula el diff."""
    job.empezar(
        "Smoke de la prevision de dispositivos",
        [
            ("exportar", "Exportar las tablas de tags"),
            ("diff", "Calcular las diferencias"),
            ("componer", "Componer el resultado"),
        ],
    )
    carpeta = disp_trabajo.workdir_dispositivos()
    carpeta.limpiar_preview()
    destino_config = carpeta.preview_de("config")
    destino_disp = carpeta.preview_de("disp")

    tipos = disp_trabajo.tablas_de_dispositivos(config)
    tabla_n_max = str(config.get("global_config_table_name", ""))

    with job.paso("exportar") as paso:
        if tabla_n_max:
            exportar_tablas(
                job.tia.portal,
                plc,
                destino_config,
                [tabla_n_max],
                mantener_estructura=False,
            )
        exportar_tablas(
            job.tia.portal,
            plc,
            destino_disp,
            [tabla for _tipo, tabla, _db in tipos],
            mantener_estructura=False,
        )
        paso["detail"] = f"{len(tipos)} tablas de dispositivos"

    diffs: dict[str, Any] = {}
    with job.paso("diff") as paso:
        for tipo, tabla, _db in tipos:
            dispositivos = [
                fila
                for fila_tabla in excel["dispositivos"]
                if fila_tabla["tipo"] == tipo
                for fila in fila_tabla["filas"]
                if str(fila.get("plc_name", "")) == plc
            ]
            diffs[tabla] = disp_preview.disp_calcular_diff_tabla(
                tabla,
                dispositivos,
                destino_disp / f"{tabla}.xml",
            )
        paso["detail"] = f"{len(diffs)} tablas"

    with job.paso("componer") as paso:
        n_max = disp_preview.disp_calcular_diff_n_max(
            tabla_n_max,
            _n_max_del_excel(excel, plc),
            destino_config / f"{tabla_n_max}.xml",
        )
        resultado = disp_trabajo.componer_respuesta(diffs, n_max, {})
        paso["detail"] = f"{resultado['summary']['total']} entradas"

    return resultado


def _n_max_del_excel(excel: dict[str, Any], plc: str) -> dict[str, int]:
    """Los N_MAX del Excel del PLC elegido."""
    for fila in excel["configuracion"]["filas"]:
        if str(fila.get("PLC", "")) != plc:
            continue
        return {
            nombre: int(valor)
            for nombre, valor in fila.items()
            if nombre.startswith("N_MAX_") and isinstance(valor, (int, float))
        }
    return {}


def _pintar(resultado: dict[str, Any]) -> None:
    """Saca el diff por pantalla."""
    resumen = resultado["summary"]
    print("\n--- resumen ---")
    print(f"  dispositivos analizados: {resumen['total']}")
    print(f"  a agregar:  {resumen['agregar']}")
    print(f"  a renombrar: {resumen['renombrados']}")
    print(f"  a eliminar:  {resumen['eliminar']}")
    print(f"  sin cambios: {resumen['sin_cambios']}")

    print("\n--- N_MAX ---")
    for fila in resultado["nmax"]["todos"]:
        marca = "->" if fila["status"] == "actualizar" else "  "
        print(f"  {marca} {fila['name']}: {fila['actual']} -> {fila['nuevo']}")

    print("\n--- diff por tipo ---")
    for fila in resultado["todos"]:
        print(
            f"  [{fila['type']}] {fila['numero']:>4}  "
            f"{fila['actual'] or '-'!s:<16} -> {fila['nuevo'] or '-'!s:<16} "
            f"{fila['status']}"
        )


def main() -> int:
    """Conecta, exporta y saca el diff."""
    argumentos = _argumentos()
    config = _config()
    excel = parser_excel.leer_excel(argumentos.excel, config)

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
            _smoke,
            plc=argumentos.plc,
            excel=excel,
            config=config,
        )
        exportacion = _esperar(bus, job_id)
        if exportacion["estado"] != "ok":
            print(f"\n  ERROR: {exportacion.get('error')}")
            return 1

        _pintar(exportacion["resultado"])
        print(f"\nPreview en: {disp_trabajo.workdir_dispositivos().preview}")
        return 0
    finally:
        servicio.parar()


if __name__ == "__main__":
    raise SystemExit(main())
