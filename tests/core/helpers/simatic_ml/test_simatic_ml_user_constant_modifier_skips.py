"""Tests de los tags omitidos al escribir las tablas de dispositivos.

El diff razona por ``uid`` (el ``<Value>`` del PlcUserConstant) y el
modificador razona por ``nombre`` (el ``<Name>``). Un add cuyo nombre ya
existe en la tabla (con otro uid) no se puede escribir: el modificador
lo descarta y el preview, que lo contaba, promete mas tags de los que
acaban en TIA.

El descarte no puede ser silencioso: el operador tiene que ver cuantos
tags se han escrito de verdad y cuales se han quedado fuera.
"""
from __future__ import annotations

import logging
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

TABLA = "2000_Disp_ED"

XML_TABLA = (
    '<?xml version="1.0" encoding="utf-8"?>\n'
    '<Document>\n'
    '  <SW.Tags.PlcTagTable ID="0">\n'
    '    <ObjectList>\n'
    '      <SW.Tags.PlcUserConstant ID="1">\n'
    '        <AttributeList><Name>ED_000</Name><Value>0</Value></AttributeList>\n'
    '      </SW.Tags.PlcUserConstant>\n'
    '    </ObjectList>\n'
    '  </SW.Tags.PlcTagTable>\n'
    '</Document>\n'
)


def _escribir_xml(path: Path, contenido: str) -> Path:
    path.write_text(contenido, encoding="utf-8")
    return path


def _modifier(path: Path):
    from core.helpers.simatic_ml import PlcUserConstantModifier

    return PlcUserConstantModifier(path)


# ── Modificador ─────────────────────────────────────────────────────


def test_add_omite_el_nombre_que_ya_existe_y_lo_avisa(caplog):
    """Un add con nombre ya presente se omite y se dice cual es."""
    with tempfile.TemporaryDirectory() as tmp:
        path = _escribir_xml(
            Path(tmp) / f"{TABLA}.xml", XML_TABLA
        )
        modifier = _modifier(path)
        with caplog.at_level(
            logging.WARNING,
            logger="core.helpers.simatic_ml.simatic_ml_user_constant_modifier",
        ):
            added = modifier.add_user_constants_by_table(
                TABLA,
                [
                    {"uid": "1", "plc_tag": "ED_001"},
                    {"uid": "0", "plc_tag": "ED_000"},
                ],
            )

    assert added == 1, "Solo se escribe el nombre que no existe."
    assert "ED_000" in caplog.text, caplog.text
    assert "el nombre ya existe" in caplog.text


def test_add_omite_el_plc_tag_vacio_y_lo_avisa(caplog):
    """Un add sin ``plc_tag`` se omite y se avisa."""
    with tempfile.TemporaryDirectory() as tmp:
        path = _escribir_xml(
            Path(tmp) / f"{TABLA}.xml", XML_TABLA
        )
        modifier = _modifier(path)
        with caplog.at_level(
            logging.WARNING,
            logger="core.helpers.simatic_ml.simatic_ml_user_constant_modifier",
        ):
            added = modifier.add_user_constants_by_table(
                TABLA,
                [{"uid": "1", "plc_tag": "  "}],
            )

    assert added == 0
    assert "plc_tag vacio" in caplog.text


def test_add_no_avisa_si_no_hay_omitidos(caplog):
    """Sin omitidos no hay warning (el log normal no es ruido)."""
    with tempfile.TemporaryDirectory() as tmp:
        path = _escribir_xml(
            Path(tmp) / f"{TABLA}.xml", XML_TABLA
        )
        modifier = _modifier(path)
        with caplog.at_level(
            logging.WARNING,
            logger="core.helpers.simatic_ml.simatic_ml_user_constant_modifier",
        ):
            added = modifier.add_user_constants_by_table(
                TABLA, [{"uid": "1", "plc_tag": "ED_001"}]
            )

    assert added == 1
    assert "omitidos" not in caplog.text


# ── Sync de dispositivos ────────────────────────────────────────────


def _patch_build_cache(tmp_path: Path) -> MagicMock:
    return patch(
        "areas.alimentacion.helpers.layout.build_cache.build_cache"
    )


def _disp_ctx_mock(tmp_path: Path) -> MagicMock:
    disp_ctx = MagicMock()
    disp_ctx.sync_variables_export = tmp_path / "export"
    disp_ctx.sync_variables_modified = tmp_path / "modified"
    disp_ctx.clean_sincronizar = MagicMock()
    return disp_ctx


def test_sync_informa_de_los_tags_escritos(caplog):
    """El sync dice cuantos tags ha escrito de los pedidos."""
    from areas.alimentacion.functions.function_disp_sincronizar import (
        _copy_and_edit_offline,
    )

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        export = root / "export"
        export.mkdir(parents=True)
        _escribir_xml(export / f"{TABLA}.xml", XML_TABLA)

        with _patch_build_cache(root) as bc:
            bc.return_value.dispositivos = _disp_ctx_mock(root)
            with caplog.at_level(
                logging.INFO,
                logger=(
                    "areas.alimentacion.functions.function_disp_sincronizar"
                ),
            ):
                _copy_and_edit_offline(
                    root,
                    [
                        {
                            "table_name": TABLA,
                            "adds": [
                                {"uid": "1", "plc_tag": "ED_001"},
                                {"uid": "0", "plc_tag": "ED_000"},
                            ],
                            "removes": [],
                        }
                    ],
                )

    assert "1 de 2" in caplog.text, caplog.text
    assert f"{TABLA}: 1/2" in caplog.text


def test_sync_no_avisa_si_se_escriben_todos(caplog):
    """Si todos los tags se escriben, no hay warning."""
    from areas.alimentacion.functions.function_disp_sincronizar import (
        _copy_and_edit_offline,
    )

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        export = root / "export"
        export.mkdir(parents=True)
        _escribir_xml(export / f"{TABLA}.xml", XML_TABLA)

        with _patch_build_cache(root) as bc:
            bc.return_value.dispositivos = _disp_ctx_mock(root)
            with caplog.at_level(
                logging.WARNING,
                logger=(
                    "areas.alimentacion.functions.function_disp_sincronizar"
                ),
            ):
                _copy_and_edit_offline(
                    root,
                    [
                        {
                            "table_name": TABLA,
                            "adds": [{"uid": "1", "plc_tag": "ED_001"}],
                            "removes": [],
                        }
                    ],
                )

    assert "tags escritos" not in caplog.text
