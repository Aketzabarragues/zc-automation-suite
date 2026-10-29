"""Guard del export estructurado del sync de dispositivos.

El sync de dispositivos reimporta las tablas de tags en TIA dentro de
una transaccion (Tx B). Para que TIA haga UPDATE y no CREATE, el export
tiene que conservar la jerarquia de carpetas del PLC
(``keep_folder_structure=True``): con el export FLAT la tabla se crea de
nuevo, el objeto ya existe y la transaccion muere con
``CommitOnDispose``.

Los lectores del export (diff de dispositivos y N_MAX) tienen que
encontrar el XML tanto en layout FLAT como con jerarquia de carpetas:
el nombre de la carpeta TIA no se puede hardcodear.

Este modulo lo cierra de dos formas:

  1. Guard estructural: todo ``export_tables`` declara
     ``keep_folder_structure`` de forma explicita (nunca por defecto).
  2. Guard de comportamiento: los 2 exports del sync de dispositivos
     exportan con la jerarquia de carpetas, y los 2 lectores encuentran
     el XML con la jerarquia.
"""
from __future__ import annotations

import ast
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from areas.alimentacion.functions.function_disp_sincronizar import (
    FunctionDispSincronizar,
    _compute_nmax_ops_for_apply,
)

REPO_ROOT = Path(__file__).resolve().parents[4]

TABLA_DISP = "2000_Disp_ED"
TABLA_NMAX = "0_Config_Dispositivos"
CARPETA_DISP = "2000_Dispositivos"
CARPETA_NMAX = "0_Sistema"


XML_DISP = (
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

XML_NMAX = (
    '<?xml version="1.0" encoding="utf-8"?>\n'
    '<Document>\n'
    '  <SW.Tags.PlcTagTable ID="0">\n'
    '    <ObjectList>\n'
    '      <SW.Tags.PlcUserConstant ID="1">\n'
    '        <AttributeList><Name>N_MAX_DISP_ED</Name><Value>5</Value></AttributeList>\n'
    '      </SW.Tags.PlcUserConstant>\n'
    '    </ObjectList>\n'
    '  </SW.Tags.PlcTagTable>\n'
    '</Document>\n'
)


# ── 1. Guard estructural ────────────────────────────────────────────


def _fb_files() -> list[Path]:
    """Ficheros de FB del area de alimentacion."""
    return sorted(REPO_ROOT.glob("areas/alimentacion/functions/function_*.py"))


def _const_keys(d: ast.Dict) -> set[str]:
    """Claves literales de un dict del AST."""
    return {
        k.value
        for k in d.keys
        if isinstance(k, ast.Constant) and isinstance(k.value, str)
    }


def _dict_value(d: ast.Dict, key: str) -> ast.Dict | None:
    """Valor de ``key`` si es un dict literal."""
    for k, v in zip(d.keys, d.values):
        if isinstance(k, ast.Constant) and k.value == key:
            return v if isinstance(v, ast.Dict) else None
    return None


def _export_tables_ops(path: Path) -> list[ast.Dict]:
    """Dicts que describen una op de ``export_tables``."""
    tree = ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))
    ops: list[ast.Dict] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Dict):
            continue
        for k, v in zip(node.keys, node.values):
            if (
                isinstance(k, ast.Constant)
                and k.value == "command"
                and isinstance(v, ast.Constant)
                and v.value == "export_tables"
            ):
                ops.append(node)
                break
    return ops


def test_todo_export_tables_declara_keep_folder_structure() -> None:
    """Ningun ``export_tables`` puede heredar el default del handler.

    El default del handler es ``False`` (export FLAT). Un call site que
    no declare el flag elige el layout por omision: si lo que se importa
    despues necesita la jerarquia de carpetas del PLC, el import hace
    CREATE en vez de UPDATE y la transaccion muere con
    ``CommitOnDispose``.
    """
    ofensores: list[str] = []
    for path in _fb_files():
        for op in _export_tables_ops(path):
            args = _dict_value(op, "args")
            if args is None or "keep_folder_structure" not in _const_keys(args):
                ofensores.append(f"{path.relative_to(REPO_ROOT)}")
    assert not ofensores, (
        "export_tables sin keep_folder_structure explicito (el default "
        "del handler es FLAT): " + ", ".join(sorted(set(ofensores)))
    )


# ── 2. Guard de comportamiento ──────────────────────────────────────


def _make_config_manager() -> MagicMock:
    cm = MagicMock()
    cm.get_global_config_table_name.return_value = TABLA_NMAX
    cm.get_tia_folder_nmax.return_value = CARPETA_NMAX
    cm.get_tia_folder_dispositivos.return_value = CARPETA_DISP
    cm.list_hw_types_active.return_value = ["ed"]
    cm.get_dispositivo_config.return_value = SimpleNamespace(
        tag_table=TABLA_DISP,
        db_name="DB2000_ED",
    )
    cm.get_tag_table_name.return_value = TABLA_DISP
    cm.list_nmax_active.return_value = ["N_MAX_DISP_ED"]
    return cm


def _make_fb() -> FunctionDispSincronizar:
    cm = _make_config_manager()
    client = MagicMock()
    client.submit_and_wait.return_value = {
        "ok": True,
        "result": {
            "success": True,
            "operations_executed": 1,
            "operations_failed": 0,
            "details": [],
        },
    }
    fb = FunctionDispSincronizar(
        nombre="disp_sincronizar_test",
        config_manager=cm,
        tia_client=client,
        build_cache=Path("."),
        app_cache=MagicMock(),
    )
    ctx = MagicMock()
    ctx.config_manager = cm
    ctx.tia_client = client
    ctx.plc_name = "ZC_PLC_STD"
    ctx.build_cache_root = Path(".")
    fb._ctx = ctx
    return fb


def _patch_build_cache(tmp_path: Path) -> MagicMock:
    """Mock de ``build_cache`` con un workdir de dispositivos."""
    return patch(
        "areas.alimentacion.helpers.layout.build_cache.build_cache"
    )


def _disp_ctx_mock(tmp_path: Path) -> MagicMock:
    disp_ctx = MagicMock()
    disp_ctx.sync_variables_export = tmp_path / "export"
    disp_ctx.sync_variables_modified = tmp_path / "modified"
    disp_ctx.clean_sincronizar = MagicMock()
    return disp_ctx


def test_stage_1_exporta_conservando_la_jerarquia_de_carpetas(
    tmp_path: Path,
) -> None:
    """El Stage 1 exporta las tablas con ``keep_folder_structure=True``."""
    fb = _make_fb()
    with _patch_build_cache(tmp_path) as bc:
        bc.return_value.dispositivos = _disp_ctx_mock(tmp_path)
        fb._stage_1_exportar_tags()

    call = fb._ctx.tia_client.submit_and_wait.call_args_list[0]
    op = call.args[1]["operations"][0]
    assert op["command"] == "export_tables"
    assert op["args"]["keep_folder_structure"] is True, (
        "El export FLAT hace que TIA cree la tabla de nuevo al "
        "reimportarla: la transaccion muere con CommitOnDispose."
    )


def test_stage_6_reexporta_conservando_la_jerarquia_de_carpetas(
    tmp_path: Path,
) -> None:
    """El Stage 6 (re-export post Tx A) tambien conserva la jerarquia."""
    fb = _make_fb()
    fb._ctx.tags_base = tmp_path / "export"
    fb._ctx.device_changes = [
        {"table_name": TABLA_DISP, "adds": [], "removes": []},
    ]
    with _patch_build_cache(tmp_path) as bc:
        bc.return_value.dispositivos = _disp_ctx_mock(tmp_path)
        fb._stage_6_exportar_post_tx_a()

    call = fb._ctx.tia_client.submit_and_wait.call_args_list[0]
    op = call.args[1]["operations"][0]
    assert op["command"] == "export_tables"
    assert op["args"]["keep_folder_structure"] is True


def test_stage_2_lee_el_xml_que_vive_en_una_subcarpeta(
    tmp_path: Path,
) -> None:
    """El diff encuentra el XML aunque viva en una subcarpeta."""
    tags_base = tmp_path / "export"
    (tags_base / CARPETA_DISP).mkdir(parents=True)
    (tags_base / CARPETA_DISP / f"{TABLA_DISP}.xml").write_text(
        XML_DISP, encoding="utf-8"
    )
    fb = _make_fb()
    fb._ctx.tags_base = tags_base
    devices = [
        SimpleNamespace(numero=0, plc_tag="ED_000"),
        SimpleNamespace(numero=1, plc_tag="ED_001"),
    ]
    with patch(
        "areas.alimentacion.functions.function_disp_sincronizar.get_devices",
        return_value=devices,
    ):
        fb._stage_2_compute_diff()

    assert fb._ctx.added_per_table == {TABLA_DISP: ["1"]}, (
        "El XML en subcarpeta no se ha leido: el diff se ha calculado "
        "contra una base vacia."
    )


def test_stage_2_omite_la_tabla_cuando_no_encuentra_el_xml(
    tmp_path: Path,
) -> None:
    """Sin XML no se proponen cambios: la base seria inventada."""
    tags_base = tmp_path / "export"
    tags_base.mkdir(parents=True)
    fb = _make_fb()
    fb._ctx.tags_base = tags_base
    devices = [SimpleNamespace(numero=1, plc_tag="ED_001")]
    with patch(
        "areas.alimentacion.functions.function_disp_sincronizar.get_devices",
        return_value=devices,
    ):
        fb._stage_2_compute_diff()

    assert fb._ctx.added_per_table == {}
    assert fb._ctx.base_state_per_table == {}


def test_lector_nmax_encuentra_el_xml_que_vive_en_una_subcarpeta(
    tmp_path: Path,
) -> None:
    """El lector de N_MAX encuentra el XML con la jerarquia de carpetas."""
    tags_base = tmp_path / "export"
    (tags_base / CARPETA_NMAX).mkdir(parents=True)
    (tags_base / CARPETA_NMAX / f"{TABLA_NMAX}.xml").write_text(
        XML_NMAX, encoding="utf-8"
    )
    cm = _make_config_manager()
    with patch(
        "areas.alimentacion.functions.function_disp_sincronizar.get_nmax",
        return_value={"N_MAX_DISP_ED": 7},
    ):
        ops = _compute_nmax_ops_for_apply(tags_base, cm, MagicMock())

    assert ops == [
        {
            "table_name": TABLA_NMAX,
            "constant_name": "N_MAX_DISP_ED",
            "new_value": 7,
        }
    ], "El XML de N_MAX con jerarquia de carpetas no se ha leido: 0 ops."


def test_lector_nmax_no_propone_cambios_sin_xml(tmp_path: Path) -> None:
    """Sin el XML de N_MAX no se proponen cambios (fallo silencioso)."""
    tags_base = tmp_path / "export"
    tags_base.mkdir(parents=True)
    cm = _make_config_manager()
    with patch(
        "areas.alimentacion.functions.function_disp_sincronizar.get_nmax",
        return_value={"N_MAX_DISP_ED": 7},
    ):
        ops = _compute_nmax_ops_for_apply(tags_base, cm, MagicMock())

    assert ops == []
