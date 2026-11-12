"""Smoke de la exportacion contra un TIA Portal real.

No forma parte de la suite de pytest: vive fuera de la recogida, en
``tests/smoke/``. Se lanza a mano contra un TIA Portal abierto con un
proyecto de **PRUEBA**.

Uso (PowerShell, desde la raiz del repo):

    python tests/smoke/smoke_exportar.py --plc <PLC> --bloques DB2000_ED FB2017 --tabla 2000_Disp_ED

La carpeta destino que imprime es la que despues toma
``smoke_importar.py --origen``.

Que hace:

1. Arranca el hilo de TIA y se engancha al TIA Portal abierto.
2. Exporta los bloques y la tabla que se le pidan a una carpeta temporal.
3. Imprime el resultado de cada operacion y los ficheros generados con su
   tamano.
4. Impara, para el primer bloque, lo que devuelve
   ``get_supported_export_format()`` tal cual (``repr``): sirve para saber
   que tipo devuelve el SDK de verdad.

Nunca lo lances contra el PLC de produccion.

Ojo: el export de bloques en SimaticSD solo funciona en las versiones de TIA
que lo admiten (con TIA V21, el entorno de produccion, si; con TIA V18, no).
Si sale "NotSupportedException", el proyecto abierto es de una version de TIA
distinta. Las tablas de tags se exportan igual en cualquier version.
"""

from __future__ import annotations

import argparse
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

RAIZ = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(RAIZ / "backend"))

from zc_suite.nucleo.tia import servicio as tia  # noqa: E402
from zc_suite.nucleo.tia.eventos import BusEventos  # noqa: E402
from zc_suite.nucleo.tia.servicio import ServicioTIA  # noqa: E402
from zc_suite.nucleo.tia.transaccion import proyecto_activo  # noqa: E402
from zc_suite.tia_ops._resolver import buscar_plc, nombre_bloque, nombre_plc  # noqa: E402
from zc_suite.tia_ops.exportar import exportar_bloques, exportar_tablas  # noqa: E402


def _argumentos() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Smoke de exportacion contra TIA Portal.")
    parser.add_argument("--plc", required=True, help="Nombre del PLC.")
    parser.add_argument(
        "--bloques",
        nargs="+",
        default=[],
        help=(
            "Nombres de los bloques a exportar. Opcional: si se omite, solo "
            "se exporta la tabla."
        ),
    )
    parser.add_argument("--tabla", required=True, help="Nombre de la tabla de tags a exportar.")
    parser.add_argument(
        "--destino",
        default="",
        help="Carpeta destino. Por defecto, una temporal.",
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


def _formatos_del_primer_bloque(job: Any, plc: str) -> dict[str, Any]:
    """Lo que devuelve ``get_supported_export_format()`` en el SDK real."""
    try:
        objetivo = buscar_plc(job.tia.portal, plc)
    except Exception as exc:
        return {"error": f"{type(exc).__name__}: {exc}"}
    for bloque in objetivo.get_program_blocks():
        getter = getattr(bloque, "get_supported_export_format", None)
        if getter is None:
            return {"error": "el bloque no expone get_supported_export_format()"}
        try:
            formatos = getter()
        except Exception as exc:
            return {"error": f"{type(exc).__name__}: {exc}"}
        elementos = list(formatos or [])
        return {
            "bloque": nombre_bloque(bloque),
            "repr": repr(formatos),
            "tipo": type(formatos).__name__,
            "elementos": [repr(formato) for formato in elementos],
            "tipos_elementos": [type(formato).__name__ for formato in elementos],
        }
    return {"error": "el PLC no tiene bloques de programa"}


def _plcs_del_proyecto(job: Any) -> list[str]:
    """Los PLC del proyecto abierto, para saber que nombre usar."""
    try:
        proyecto = proyecto_activo(job.tia.portal)
    except Exception as exc:
        return [f"<no se pudo leer el proyecto: {exc}>"]
    return [str(nombre_plc(plc)) for plc in proyecto.get_plcs()]


def _smoke(job: Any, plc: str, bloques: list[str], tabla: str, destino: Path) -> dict[str, Any]:
    """Trabajo de smoke: se ejecuta entero dentro del hilo de TIA."""
    resultado: dict[str, Any] = {"formatos": None, "plcs": None, "bloques": None, "tabla": None}
    pasos = [("formatos", "Ver los formatos que admite el SDK")]
    if bloques:
        pasos.append(("exportar_bloques", "Exportar bloques"))
    pasos.append(("exportar_tablas", "Exportar una tabla"))
    job.empezar("Smoke de exportacion", pasos)
    with job.paso("formatos") as paso:
        resultado["plcs"] = _plcs_del_proyecto(job)
        resultado["formatos"] = _formatos_del_primer_bloque(job, plc)
        paso["detail"] = str(resultado["formatos"].get("tipo"))

    if bloques:
        with job.paso("exportar_bloques") as paso:
            try:
                resultado["bloques"] = exportar_bloques(
                    job.tia.portal,
                    plc,
                    destino / "bloques",
                    bloques,
                    mantener_estructura=False,
                    version_tia=job.tia.version_tia,
                )
                paso["detail"] = f"{resultado['bloques']['cantidad']} bloques"
            except Exception as exc:
                resultado["bloques"] = {"error": f"{type(exc).__name__}: {exc}"}
                paso["detail"] = "ha fallado"

    with job.paso("exportar_tablas") as paso:
        try:
            resultado["tabla"] = exportar_tablas(
                job.tia.portal,
                plc,
                destino / "tablas",
                [tabla],
                mantener_estructura=True,
            )
            paso["detail"] = f"{resultado['tabla']['cantidad']} tablas"
        except Exception as exc:
            resultado["tabla"] = {"error": f"{type(exc).__name__}: {exc}"}
            paso["detail"] = "ha fallado"

    return resultado


def _listar(carpeta: Path) -> None:
    """Imprime los ficheros generados con su tamano."""
    print("\n--- ficheros generados ---")
    if not carpeta.is_dir():
        print(f"(no existe: {carpeta})")
        return
    encontrados = sorted(p for p in carpeta.rglob("*") if p.is_file())
    if not encontrados:
        print("(ninguno)")
        return
    for fichero in encontrados:
        print(f"  {fichero.relative_to(carpeta)}  ({fichero.stat().st_size} bytes)")


def main() -> int:
    """Conecta, exporta y muestra el resultado."""
    argumentos = _argumentos()
    destino = (
        Path(argumentos.destino)
        if argumentos.destino
        else Path(tempfile.mkdtemp(prefix="zc_smoke_exportar_"))
    )
    destino.mkdir(parents=True, exist_ok=True)

    bus = BusEventos()
    servicio = ServicioTIA(publicador=bus.publicar)
    servicio.arrancar()

    try:
        print(f"Destino: {destino}")
        print("Conectando con TIA Portal (attach)...")
        job_id = servicio.lanzar(tia.conectar)
        conexion = _esperar(bus, job_id)
        print(f"  conexion: {conexion['estado']}  {conexion.get('error') or ''}")
        if conexion["estado"] != "ok":
            print("\nNo hay conexion. Abre TIA Portal con el proyecto de prueba.")
            return 1

        print(f"Exportando bloques {argumentos.bloques} y la tabla {argumentos.tabla}...")
        job_id = servicio.lanzar(
            _smoke,
            plc=argumentos.plc,
            bloques=argumentos.bloques,
            tabla=argumentos.tabla,
            destino=destino,
        )
        exportacion = _esperar(bus, job_id)
        if exportacion["estado"] != "ok":
            print(f"\n  ERROR: {exportacion.get('error')}")
            _listar(destino)
            return 1

        resultado = exportacion["resultado"]
        print("\n--- resultado ---")
        print(f"  bloques: {resultado['bloques']}")
        print(f"  tabla:   {resultado['tabla']}")

        print("\n--- PLC del proyecto abierto ---")
        for nombre in resultado["plcs"] or []:
            print(f"  {nombre}")

        print("\n--- get_supported_export_format() del primer bloque ---")
        for clave, valor in (resultado["formatos"] or {}).items():
            print(f"  {clave}: {valor}")

        _listar(destino)
        print(f"\nDestino: {destino}")

        fallos = [
            parte
            for parte in ("bloques", "tabla")
            if isinstance(resultado.get(parte), dict) and "error" in resultado[parte]
        ]
        return 1 if fallos else 0
    finally:
        servicio.parar()


if __name__ == "__main__":
    raise SystemExit(main())
