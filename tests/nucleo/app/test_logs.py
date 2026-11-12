"""Tests del log en fichero: la configuracion, la rotacion y las excepciones."""

from __future__ import annotations

import contextlib
import logging
import threading
import time
from collections.abc import Iterator
from pathlib import Path

import pytest

from zc_suite.nucleo.app import logs


@pytest.fixture
def carpeta_log(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    """Prepara el logging en una carpeta temporal y restaura el root."""
    monkeypatch.setenv("ZC_LOG_DIR", str(tmp_path / "logs"))
    monkeypatch.setattr(logs, "_setup_hecho", False)
    manejadores = list(logging.root.handlers)
    nivel = logging.root.level
    # El logger de la app puede tener un nivel puesto por otro test: sin
    # esto sus registros INFO no llegarian al fichero.
    nivel_app = logging.getLogger("zc_suite").level
    propaga = logging.getLogger("zc_suite").propagate
    logging.getLogger("zc_suite").setLevel(logging.DEBUG)
    logging.getLogger("zc_suite").propagate = True
    try:
        yield tmp_path / "logs"
    finally:
        for manejador in list(logging.root.handlers):
            logging.root.removeHandler(manejador)
            # El RotatingFileHandler tiene el fichero abierto: si no se
            # cierra, al borrarlo la carpeta temporal avisa.
            with contextlib.suppress(Exception):
                manejador.close()
        for manejador in manejadores:
            logging.root.addHandler(manejador)
        logging.root.setLevel(nivel)
        logging.getLogger("zc_suite").setLevel(nivel_app)
        logging.getLogger("zc_suite").propagate = propaga
        monkeypatch.setattr(logs, "_setup_hecho", False)


def test_el_log_se_escribe_en_el_fichero(carpeta_log: Path) -> None:
    """Lo que se registra queda en ``zc.log``."""
    fichero = logs.configurar_logging()
    logging.getLogger("zc_suite.prueba").info("hola %s", "mundo")

    assert fichero == carpeta_log / "zc.log"
    assert "hola mundo" in fichero.read_text(encoding="utf-8")


def test_el_fichero_lleva_el_formato_de_main(carpeta_log: Path) -> None:
    """El formato es el de la app anterior: fecha, nivel y logger."""
    fichero = logs.configurar_logging()
    logging.getLogger("zc_suite.prueba").info("linea de prueba")

    linea = fichero.read_text(encoding="utf-8").strip().splitlines()[-1]

    assert "[INFO] [zc_suite.prueba] linea de prueba" in linea


def test_el_fichero_rota_con_tres_backups(carpeta_log: Path) -> None:
    """El fichero rota a los 10 MB y guarda 3 copias."""
    logs.configurar_logging()

    manejadores = [
        manejador
        for manejador in logging.root.handlers
        if isinstance(manejador, logging.handlers.RotatingFileHandler)
    ]

    assert len(manejadores) == 1
    assert manejadores[0].maxBytes == 10_000_000
    assert manejadores[0].backupCount == 3
    assert manejadores[0].encoding == "utf-8"


def test_sin_consola_no_hay_handler_de_consola(
    carpeta_log: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """El .exe va sin consola: ahi no se puede escribir en stdout."""
    monkeypatch.setattr(logging.sys, "stdout", None)

    logs.configurar_logging()

    assert not [
        manejador
        for manejador in logging.root.handlers
        if isinstance(manejador, logging.StreamHandler)
        and not isinstance(manejador, logging.handlers.RotatingFileHandler)
    ]


def test_con_consola_hay_handler_de_consola(carpeta_log: Path) -> None:
    """En desarrollo, la consola tambien recibe el log."""
    logs.configurar_logging()

    hay_consola = [
        manejador
        for manejador in logging.root.handlers
        if isinstance(manejador, logging.StreamHandler)
        and not isinstance(manejador, logging.handlers.RotatingFileHandler)
    ]

    assert hay_consola


def test_el_log_acepta_acentos(carpeta_log: Path) -> None:
    """El fichero es UTF-8: los acentos se guardan bien."""
    fichero = logs.configurar_logging()
    logging.getLogger("zc_suite.prueba").info("a\u00f1o \u00f3 \u00bf")

    assert "a\u00f1o \u00f3 \u00bf" in fichero.read_text(encoding="utf-8")


def test_una_excepcion_en_un_hilo_va_al_log(carpeta_log: Path) -> None:
    """Una excepcion no controlada en un hilo no se pierde."""
    fichero = logs.configurar_logging()
    logs.instalar_hooks_de_excepcion()

    def _reventar() -> None:
        raise RuntimeError("se ha roto el hilo")

    hilo = threading.Thread(target=_reventar, name="hilo-de-prueba")
    hilo.start()
    hilo.join(timeout=5)

    limite = time.time() + 5
    while time.time() < limite:
        if "se ha roto el hilo" in fichero.read_text(encoding="utf-8"):
            break
        time.sleep(0.05)

    assert "se ha roto el hilo" in fichero.read_text(encoding="utf-8")


def test_el_log_de_la_app_va_a_logs(carpeta_log: Path) -> None:
    """La carpeta del log es la que dice ``ZC_LOG_DIR``."""
    logs.configurar_logging()

    assert logs.carpeta_de_logs() == carpeta_log
    assert logs.ruta_log() == carpeta_log / "zc.log"
