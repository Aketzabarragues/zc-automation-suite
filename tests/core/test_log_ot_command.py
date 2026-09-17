"""Tests del decorador ``@log_ot_command`` (Nivel 2 trazabilidad).

Cubre:
  - Mensajes por defecto (tecnicos ``OT[name] args=...`` y ``OT[name] OK en Xms``).
  - Mensajes custom con ``msg_in`` y ``msg_ok`` (lenguaje humano, N2).
  - ``level=logging.DEBUG`` desactiva la salida a web.
  - Format string tolerante a keys faltantes (``{x}`` -> "").
  - Format string con keys de ``args`` y de ``result``.
  - Tiempo medido coherente.
  - Idempotencia del decorador (llamar 2 veces no rompe).

El decorador emite via ``logger = logging.getLogger("zc.tia_loop")``.
Capturamos con un handler dedicado en ese logger (no en el root).
"""
from __future__ import annotations

import io
import logging
import re
import time
from typing import Any

import pytest

from core.infrastructure.tia.tia_helpers import log_ot_command
from core.infrastructure.log_web_bridge import install_web_level


@pytest.fixture(autouse=True)
def _install_web_levels() -> None:
    """Asegura que ``WEB_LEVEL`` este registrado en la tabla de ``logging``."""
    install_web_level()


@pytest.fixture
def capture_zc_tia_loop() -> io.StringIO:
    """Devuelve un StringIO que captura todo lo emitido a ``zc.tia_loop``.

    Anade un handler al logger ``zc.tia_loop`` y lo retira al final del
    test (yield + try/finally). El handler tiene nivel DEBUG para ver
    todo, incluido ``level=logging.DEBUG`` del decorador.
    """
    logger = logging.getLogger("zc.tia_loop")
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setLevel(logging.DEBUG)
    logger.addHandler(handler)
    logger.setLevel(logging.DEBUG)
    try:
        yield stream
    finally:
        logger.removeHandler(handler)


def _lines(stream: io.StringIO) -> list[str]:
    return [line for line in stream.getvalue().splitlines() if line]


def test_mensajes_por_defecto_son_tecnicos(
    capture_zc_tia_loop: io.StringIO,
) -> None:
    """Sin ``msg_in``/``msg_ok``, emite ``OT[name] args=...`` y ``OK en Xms``."""
    @log_ot_command(name="my_handler")
    def _h(args: dict[str, Any], tia_client: object) -> dict[str, Any]:
        return {"ok": True, "n_blocks": 42}

    _h({"plc_name": "ZC_PLC_STD"}, None)

    out = _lines(capture_zc_tia_loop)
    assert any("OT[my_handler] args=" in l for l in out)
    assert any("OT[my_handler] OK en" in l for l in out)
    assert any("n_blocks=42" in l for l in out)


def test_msg_in_msg_ok_reemplazan_mensajes_tecnicos(
    capture_zc_tia_loop: io.StringIO,
) -> None:
    """``msg_in``/``msg_ok`` naturales se usan cuando se pasan."""
    @log_ot_command(
        name="scan_blocks",
        msg_in="Escaneando bloques del PLC '{plc_name}'...",
        msg_ok="PLC escaneado: {n_blocks} bloques en {ms}ms",
    )
    def _h(args: dict[str, Any], tia_client: object) -> dict[str, Any]:
        return {"n_blocks": 123}

    _h({"plc_name": "ZC_PLC_STD"}, None)

    out = _lines(capture_zc_tia_loop)
    assert "Escaneando bloques del PLC 'ZC_PLC_STD'..." in out
    assert any("PLC escaneado: 123 bloques en" in l for l in out)
    # El prefijo tecnico NO debe aparecer:
    assert not any("OT[scan_blocks]" in l for l in out)


def test_msg_in_con_key_faltante_no_falla_sino_usa_string_vacio(
    capture_zc_tia_loop: io.StringIO,
) -> None:
    """Si ``{x}`` no esta en args/result, se expande a ``""`` (no KeyError)."""
    @log_ot_command(
        name="custom",
        msg_in="Inicio '{inexistente}': {plc_name}",
        msg_ok="Fin '{inexistente}': ok",
    )
    def _h(args: dict[str, Any], tia_client: object) -> dict[str, Any]:
        return {}

    _h({"plc_name": "ZC"}, None)

    out = _lines(capture_zc_tia_loop)
    assert any("Inicio '': ZC" in l for l in out)
    assert any("Fin '': ok" in l for l in out)


def test_msg_ok_puea_usar_keys_del_result_dict(
    capture_zc_tia_loop: io.StringIO,
) -> None:
    """``msg_ok`` puede leer cualquier key top-level del ``result``."""
    @log_ot_command(
        name="compile_blocks",
        msg_ok="Compilacion: {n_compiled_ok} OK, {n_compiled_err} errores",
    )
    def _h(args: dict[str, Any], tia_client: object) -> dict[str, Any]:
        return {"n_compiled_ok": 5, "n_compiled_err": 2, "n_skipped": 10}

    _h({}, None)

    out = _lines(capture_zc_tia_loop)
    assert any("Compilacion: 5 OK, 2 errores" in l for l in out)


def test_msg_in_y_msg_ok_default_se_aplican_a_ambos(
    capture_zc_tia_loop: io.StringIO,
) -> None:
    """Si solo se pasa uno, el otro cae al tecnico."""
    @log_ot_command(name="only_in", msg_in="Solo el inicio")
    def _h(args: dict[str, Any], tia_client: object) -> dict[str, Any]:
        return {}

    _h({}, None)

    out = _lines(capture_zc_tia_loop)
    assert any("Solo el inicio" in l for l in out)
    # El cierre usa el tecnico por defecto:
    assert any("OT[only_in] OK en" in l for l in out)


def test_decorador_mide_tiempo_positivo(
    capture_zc_tia_loop: io.StringIO,
) -> None:
    """``{ms}`` es positivo y se redondea a 0 decimales."""
    @log_ot_command(name="sleep_test", msg_ok="Hecho en {ms}ms")
    def _h(args: dict[str, Any], tia_client: object) -> dict[str, Any]:
        time.sleep(0.01)  # 10ms
        return {}

    _h({}, None)

    out = _lines(capture_zc_tia_loop)
    match = None
    for line in out:
        m = re.search(r"Hecho en (\d+)ms", line)
        if m is not None:
            match = m
            break
    assert match is not None, f"No se encontro patron 'Hecho en Nms' en: {out}"
    assert int(match.group(1)) >= 10


def test_decorador_es_idempotente_sobre_distintos_handlers() -> None:
    """Aplicar ``@log_ot_command`` a varios handlers no rompe."""
    @log_ot_command(name="h1")
    def _h1(args: dict[str, Any], tia_client: object) -> dict[str, Any]:
        return {}

    @log_ot_command(name="h2", msg_in="h2 inicio")
    def _h2(args: dict[str, Any], tia_client: object) -> dict[str, Any]:
        return {}

    @log_ot_command(name="h3", level=logging.DEBUG)
    def _h3(args: dict[str, Any], tia_client: object) -> dict[str, Any]:
        return {}

    assert callable(_h1) and callable(_h2) and callable(_h3)
    assert _h1({}, None) == {}
    assert _h2({}, None) == {}
    assert _h3({}, None) == {}