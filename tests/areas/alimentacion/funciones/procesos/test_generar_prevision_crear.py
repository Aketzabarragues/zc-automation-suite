"""La prevision de crear un proceso desde una plantilla.

Copia la plantilla al workdir, la renombra y la cruza con el escaneo del PLC.
No escribe nada en TIA: el preview solo lee y calcula.
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

import pytest

from zc_suite.areas.alimentacion.funciones.procesos import (
    generar_prevision_crear as modulo_crear,
)
from zc_suite.areas.alimentacion.funciones.procesos.generar_prevision_crear import (
    HINT_SIN_ESCANEO,
)
from zc_suite.areas.alimentacion.procesos import CLAVE_PREVISION_CREAR
from zc_suite.nucleo.sesion import Sesion
from zc_suite.nucleo.tia.job import ERROR
from zc_suite.nucleo.tia.workdir import Workdir

from .conftest import NOMBRE_PLC, PROC_UID

#: El nombre de la subcarpeta de la plantilla de prueba.
PLANTILLA = "50500_CIP1"


def _sesion_con_escaneo(bloques: list[dict[str, str]]) -> Sesion:
    """Una sesion con un escaneo fresco del PLC y los bloques dados."""
    sesion = Sesion()
    sesion.guardar_escaneo(
        NOMBRE_PLC,
        bloques=bloques,
        tablas=[{"nombre": "100_CPR"}],
        tipos=[],
    )
    return sesion


def _plantilla(
    tmp_path: Path,
    manifest: dict[str, object] | None = None,
) -> Path:
    """Escribe una plantilla de proceso 50500 en ``<tmp>/plantillas``.

    Dos bloques, cada uno en su par ``.s7dcl``/``.s7res`` (mismo stem).
    """
    raiz = tmp_path / "plantillas"
    dir_plantilla = raiz / PLANTILLA
    (dir_plantilla / "Bloques de programa").mkdir(parents=True)
    for bloque in ("DB50500_CIP1_INTERFAZ", "FC50501_CIP1_ORDENES"):
        (dir_plantilla / "Bloques de programa" / f"{bloque}.s7dcl").write_bytes(
            b"END_DATA_BLOCK\r\n"
        )
        (dir_plantilla / "Bloques de programa" / f"{bloque}.s7res").write_bytes(
            b"es-ES\r\n"
        )
    if manifest is None:
        manifest = {
            "base": 50500,
            "codigo": "CIP1",
            "nombre": "Principal",
            "descripcion": "Plantilla de proceso de alimentacion.",
            "dependencias": ["DB1_SYS"],
            "minimos": {"N_MAX_PREAL": 1, "N_MAX_PINT": 1},
        }
    (dir_plantilla / "manifest.json").write_text(
        json.dumps(manifest), encoding="utf-8"
    )
    return dir_plantilla


def _crear(
    entorno: Any,
    sesion: Sesion,
    plantillas: Path | None,
    dir_plantilla: str,
) -> dict[str, Any]:
    """Lanza la prevision de crear y devuelve su evento de fin."""
    job_id = entorno.servicio.lanzar(
        modulo_crear.generar_prevision_crear,
        proc_uid=PROC_UID,
        plc=NOMBRE_PLC,
        dir_plantilla_nombre=dir_plantilla,
        almacen=entorno.almacen,
        config=entorno.modelo,
        sesion=sesion,
        plantillas_dir=plantillas,
    )
    return entorno._esperar(job_id)


def _etapa(entorno: Any, nombre: str) -> dict[str, Any]:
    """El estado final de un paso del trabajo, desde el ultimo ``progress``.

    El evento ``job`` de fin no lleva las etapas: estas viajan en los
    eventos ``progress`` (``job.snapshot()``), el ``progress`` final se
    publica justo despues del ``job`` (de ahi el pequeño wait). El fixture
    es por test y el test lanza un solo trabajo, asi que el ultimo
    ``progress`` inactivo de la operacion es el final del trabajo.
    """
    limite = time.monotonic() + 5.0
    while time.monotonic() < limite:
        for tipo, carga in reversed(list(entorno.eventos)):
            if (
                tipo == "progress"
                and not carga["active"]
                and carga["operation"] == "generar_prevision_crear"
            ):
                for etapa in carga["stages"]:
                    if etapa["id"] == nombre:
                        return etapa
        time.sleep(0.005)
    raise AssertionError(f"No se encontro la etapa {nombre!r}.")


@pytest.fixture
def entorno_crear(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    entorno_prevision: Any,
) -> Any:
    """El fixture de la prevision con el workdir de crear en el tmp_path."""
    workdir_crear = Workdir(
        base=tmp_path / "procesos_crear",
        carpetas_contexto=("Plantilla", "Nuevo"),
    )
    monkeypatch.setattr(modulo_crear, "workdir_crear", lambda: workdir_crear)
    return entorno_prevision


def test_camino_happy(entorno_crear: Any, tmp_path: Path) -> None:
    """El preview completo: previstos, colisiones y dependencias."""
    dir_plantilla = _plantilla(tmp_path)
    sesion = _sesion_con_escaneo(
        [{"nombre": "DB1_SYS"}, {"nombre": "DB999_OTRO"}]
    )

    evento = _crear(entorno_crear, sesion, dir_plantilla.parent, PLANTILLA)

    assert evento["estado"] == "ok", evento.get("error")
    resultado = evento["resultado"]
    assert resultado["precondiciones_ok"] is True
    assert resultado["success"] is True
    assert resultado["missing_blocks"] == []
    assert resultado["manifest_plantilla"]["base"] == 50500
    assert resultado["descripcion"] == "Plantilla de proceso de alimentacion."
    assert resultado["dependencias_ok"] == ["DB1_SYS"]
    assert resultado["dependencias_faltantes"] == []
    assert resultado["colisiones"] == []
    assert resultado["colisiones_con"] == {}
    # 1 entry por bloque (dcl+res agrupados por stem), con el nombre nuevo.
    nombres = [p["nombre_nuevo"] for p in resultado["archivos_previstos"]]
    assert nombres == ["DB100_CPR_INTERFAZ", "FC101_CPR_ORDENES"]
    assert all(p["estado"] == "OK" for p in resultado["archivos_previstos"])
    # La copia de la plantilla queda en el workdir.
    copia = tmp_path / "procesos_crear" / "Plantilla"
    assert (copia / "manifest.json").is_file()
    assert resultado["plantilla_copia_dir"].endswith("Plantilla")
    # Se guardo en la sesion con la clave nueva.
    guardado = sesion.datos_area("alimentacion").get(CLAVE_PREVISION_CREAR)
    assert guardado is not None
    assert guardado["plc"] == NOMBRE_PLC
    assert guardado["proc_uid"] == PROC_UID
    assert guardado["dir_plantilla_nombre"] == PLANTILLA
    assert guardado["resultado"] == resultado


def test_sin_escaneo_fresco(entorno_crear: Any, tmp_path: Path) -> None:
    """Sin escaneo fresco: precondiciones_ok False, sin copiar ni leer nada."""
    dir_plantilla = _plantilla(tmp_path)
    sesion = Sesion()

    evento = _crear(entorno_crear, sesion, dir_plantilla.parent, PLANTILLA)

    assert evento["estado"] == "ok", evento.get("error")
    resultado = evento["resultado"]
    assert resultado["precondiciones_ok"] is False
    assert resultado["success"] is False
    # El hint va en missing_blocks (como la 4.5); colisiones queda vacia.
    assert resultado["missing_blocks"] == [HINT_SIN_ESCANEO]
    assert resultado["colisiones"] == []
    assert resultado["archivos_previstos"] == []
    assert resultado["manifest_plantilla"] is None
    # No se copio nada al workdir.
    assert not (tmp_path / "procesos_crear" / "Plantilla").exists()
    # La prevision se guardo en la sesion, con la plantilla de origen.
    guardado = sesion.datos_area("alimentacion").get(CLAVE_PREVISION_CREAR)
    assert guardado is not None
    assert guardado["plc"] == NOMBRE_PLC
    assert guardado["proc_uid"] == PROC_UID
    assert guardado["dir_plantilla_nombre"] == PLANTILLA
    assert guardado["resultado"] == resultado


def test_manifest_invalido(entorno_crear: Any, tmp_path: Path) -> None:
    """Un manifest sin 'base' aborta el trabajo (como main): el paso
    "manifest" queda en error con el mensaje."""
    dir_plantilla = _plantilla(
        tmp_path, manifest={"codigo": "CIP1", "dependencias": []}
    )
    sesion = _sesion_con_escaneo([{"nombre": "DB1_SYS"}])

    evento = _crear(entorno_crear, sesion, dir_plantilla.parent, PLANTILLA)

    assert evento["estado"] == "error"
    assert "debe contener 'base' (int)" in evento["error"]
    # El paso "manifest" es el que quedo en error.
    etapa = _etapa(entorno_crear, "manifest")
    assert etapa["status"] == ERROR
    assert "debe contener 'base' (int)" in etapa["detail"]
    # Sin manifest valido no se copio la plantilla.
    assert not (tmp_path / "procesos_crear" / "Plantilla").exists()


def test_minimos_insuficientes(entorno_crear: Any, tmp_path: Path) -> None:
    """Los N_MAX del proceso por debajo de los minimos: el trabajo aborta
    (como main) y el mensaje lista todas las claves que fallan."""
    dir_plantilla = _plantilla(
        tmp_path,
        manifest={
            "base": 50500,
            "codigo": "CIP1",
            "nombre": "Principal",
            "descripcion": "Plantilla de proceso de alimentacion.",
            "dependencias": [],
            "minimos": {"N_MAX_PREAL": 5, "N_MAX_ALM_HMI": 4},
        },
    )
    sesion = _sesion_con_escaneo([{"nombre": "DB1_SYS"}])

    evento = _crear(entorno_crear, sesion, dir_plantilla.parent, PLANTILLA)

    assert evento["estado"] == "error"
    mensaje = evento["error"]
    assert (
        "Los N_MAX del operario no cubren los minimos de la plantilla:" in mensaje
    )
    assert "N_MAX_PREAL: usuario=2 < plantilla=5" in mensaje
    assert "N_MAX_ALM_HMI: usuario=2 < plantilla=4" in mensaje
    # El paso "minimos" es el que quedo en error.
    etapa = _etapa(entorno_crear, "minimos")
    assert etapa["status"] == ERROR
    # Sin minimos validos no se copio la plantilla.
    assert not (tmp_path / "procesos_crear" / "Plantilla").exists()


def test_colision_por_nombre(entorno_crear: Any, tmp_path: Path) -> None:
    """Un nombre post-rename ya en el PLC: colision, success False."""
    dir_plantilla = _plantilla(tmp_path)
    sesion = _sesion_con_escaneo(
        [{"nombre": "DB1_SYS"}, {"nombre": "DB100_CPR_INTERFAZ"}]
    )

    evento = _crear(entorno_crear, sesion, dir_plantilla.parent, PLANTILLA)

    assert evento["estado"] == "ok", evento.get("error")
    resultado = evento["resultado"]
    assert resultado["precondiciones_ok"] is False
    assert resultado["success"] is False
    assert "DB100_CPR_INTERFAZ" in resultado["colisiones"]
    assert (
        resultado["colisiones_con"]["DB100_CPR_INTERFAZ"]
        == "DB100_CPR_INTERFAZ"
    )
    # El bloque previsto sale marcado DUPLICADO.
    por_nombre = {
        p["nombre_nuevo"]: p["estado"] for p in resultado["archivos_previstos"]
    }
    assert (
        por_nombre["DB100_CPR_INTERFAZ"] == "DUPLICADO - DB100_CPR_INTERFAZ"
    )


def test_dependencia_ausente(entorno_crear: Any, tmp_path: Path) -> None:
    """Una dependencia declarada que no esta en el PLC: no bloquea el
    preview pero precondiciones_ok sale False."""
    dir_plantilla = _plantilla(
        tmp_path,
        manifest={
            "base": 50500,
            "codigo": "CIP1",
            "nombre": "Principal",
            "descripcion": "Plantilla de proceso de alimentacion.",
            "dependencias": ["DB1_SYS", "FC15151_ZC_MARCHA_PARO_SEC"],
            "minimos": {"N_MAX_PREAL": 1},
        },
    )
    sesion = _sesion_con_escaneo([{"nombre": "DB1_SYS"}])

    evento = _crear(entorno_crear, sesion, dir_plantilla.parent, PLANTILLA)

    assert evento["estado"] == "ok", evento.get("error")
    resultado = evento["resultado"]
    assert resultado["dependencias_ok"] == ["DB1_SYS"]
    assert (
        resultado["dependencias_faltantes"] == ["FC15151_ZC_MARCHA_PARO_SEC"]
    )
    assert resultado["precondiciones_ok"] is False


def test_dir_plantilla_nombre_con_traversal(
    entorno_crear: Any, tmp_path: Path
) -> None:
    """Un nombre de carpeta con '/' o '..' es un fallo de operacion."""
    _plantilla(tmp_path)
    sesion = _sesion_con_escaneo([{"nombre": "DB1_SYS"}])

    evento = _crear(
        entorno_crear, sesion, tmp_path / "plantillas", f"../{PLANTILLA}"
    )

    assert evento["estado"] == "error"
    assert "separadores" in evento["error"]


def test_falta_la_plantilla(entorno_crear: Any, tmp_path: Path) -> None:
    """Una subcarpeta que no existe es un fallo de operacion."""
    _plantilla(tmp_path)
    sesion = _sesion_con_escaneo([{"nombre": "DB1_SYS"}])

    evento = _crear(
        entorno_crear, sesion, tmp_path / "plantillas", "99999_NO_EXISTE"
    )

    assert evento["estado"] == "error"
    assert "No se encontro la plantilla" in evento["error"]


def test_sin_plantillas_dir_se_resuelve_contra_la_carpeta_de_datos(
    entorno_crear: Any,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Sin plantillas_dir, la plantilla se busca en
    ``raiz_datos() / config.plantillas_procesos``."""
    _plantilla(tmp_path)
    monkeypatch.setattr(modulo_crear, "raiz_datos", lambda: tmp_path)
    entorno_crear.modelo.plantillas_procesos = "plantillas"
    sesion = _sesion_con_escaneo([{"nombre": "DB1_SYS"}])

    evento = _crear(entorno_crear, sesion, None, PLANTILLA)

    assert evento["estado"] == "ok", evento.get("error")
    resultado = evento["resultado"]
    assert resultado["precondiciones_ok"] is True
    assert (tmp_path / "procesos_crear" / "Plantilla" / "manifest.json").is_file()


def test_symlink_fuera_de_la_carpeta_de_plantillas(
    entorno_crear: Any,
    tmp_path: Path,
) -> None:
    """Un symlink que sale de la carpeta de plantillas se rechaza."""
    if not hasattr(os, "symlink"):
        pytest.skip("el sistema no soporta symlinks")
    dir_plantilla = _plantilla(tmp_path)
    dir_fuera = tmp_path / "fuera"
    dir_fuera.mkdir()
    symlink = dir_plantilla.parent / "ENLACE"
    os.symlink(dir_fuera, symlink)
    sesion = _sesion_con_escaneo([{"nombre": "DB1_SYS"}])

    evento = _crear(entorno_crear, sesion, dir_plantilla.parent, "ENLACE")

    assert evento["estado"] == "error"
    assert "fuera de la carpeta de plantillas" in evento["error"]
    # No se copio nada al workdir.
    assert not (tmp_path / "procesos_crear" / "Plantilla").exists()


def test_no_toca_el_portal(entorno_crear: Any, tmp_path: Path) -> None:
    """El preview no exporta ni importa: el doble no recibe ninguna llamada
    de export/import."""
    dir_plantilla = _plantilla(tmp_path)
    sesion = _sesion_con_escaneo([{"nombre": "DB1_SYS"}])

    evento = _crear(entorno_crear, sesion, dir_plantilla.parent, PLANTILLA)

    assert evento["estado"] == "ok", evento.get("error")
    # El preview no toca la tabla ni los DBs: no hay export en el workdir de
    # procesos (el de la 4.5) y el preview de crear solo deja la plantilla.
    assert not (tmp_path / "procesos" / "preview").exists()
    carpeta_previa = tmp_path / "procesos_crear" / "Plantilla"
    ficheros = sorted(p.name for p in carpeta_previa.rglob("*") if p.is_file())
    # Solo los ficheros de la plantilla: manifest + 2 pares dcl/res.
    assert "manifest.json" in ficheros
    assert any(f.endswith(".s7dcl") for f in ficheros)
    assert any(f.endswith(".s7res") for f in ficheros)
    assert not any(f.endswith((".xml", ".scl")) for f in ficheros)


def test_copiar_limpia_el_workdir_previo(entorno_crear: Any, tmp_path: Path) -> None:
    """Cada preview parte limpio: el workdir previo se borra antes de copiar."""
    dir_plantilla = _plantilla(tmp_path)
    sesion = _sesion_con_escaneo([{"nombre": "DB1_SYS"}])
    carpeta = tmp_path / "procesos_crear" / "Plantilla"
    carpeta.mkdir(parents=True)
    (carpeta / "basura.txt").write_bytes(b"lo viejo")

    evento = _crear(entorno_crear, sesion, dir_plantilla.parent, PLANTILLA)

    assert evento["estado"] == "ok", evento.get("error")
    assert not (carpeta / "basura.txt").exists()
    assert (carpeta / "manifest.json").is_file()
