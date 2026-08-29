"""Tests del handler ``_cmd_scan_blocks`` del worker OT.

Mockeamos el portal con ``MagicMock()`` (no ``spec``: el portal es una
instancia arbitraria de Pythonnet con muchos atributos). Cada test
construye un árbol mínimo de bloques + tag tables y verifica:
  - Shape del payload devuelto (4 keys primitivas, ISO 8601).
  - Resilencia ante ``get_path()`` que lanza excepción.
  - Resilencia ante ``get_name()`` que lanza ``UnicodeDecodeError``.
  - Registro en ``COMMAND_REGISTRY``.

Convenciones heredadas del worker:
  - ``ts`` se ignora (el handler no toca el modulo Siemens directamente).
  - El ``portal`` mockeado expone ``get_project()`` y este a su vez
    ``get_plcs()`` (lo usa ``_find_plc``).
"""
from __future__ import annotations

import importlib
import re
from datetime import datetime
from unittest.mock import MagicMock

import pytest

# Cargar el modulo del worker sin ejecutar ``main()`` (que requiere
# siemens_tia_scripting, no disponible en tests).
worker_tia = importlib.import_module("core.infrastructure.tia.worker_tia")
COMMAND_REGISTRY: dict = worker_tia.COMMAND_REGISTRY
_cmd_scan_blocks = worker_tia._cmd_scan_blocks


# ────────────────────────────────────────────────────────────────────────
# Helpers
# ────────────────────────────────────────────────────────────────────────


def _make_block(name: str, path: str | None = "0_Sistema\\" + "DB") -> MagicMock:
    """Crea un mock de bloque con ``get_name`` y ``get_path`` por defecto."""
    b = MagicMock()
    b.get_name.return_value = name
    b.get_path.return_value = path if path is not None else ""
    return b


def _make_table(name: str, path: str = "0_Sistema\\") -> MagicMock:
    """Crea un mock de PlcTagTable."""
    t = MagicMock()
    t.get_name.return_value = name
    t.get_path.return_value = path
    return t


def _make_portal(blocks, tag_tables, user_data_types=None) -> MagicMock:
    """Arma el portal mockeado: ``get_project().get_plcs()[0]`` resuelve.

    Args:
        blocks: lista de mocks de bloques (DB/FB/FC/OB) o grupo raiz.
        tag_tables: lista de mocks de PlcTagTable.
        user_data_types: lista de mocks de UDTs (o grupo raiz). Si es
            ``None``, ``plc.get_user_data_types()`` queda como
            ``MagicMock`` auto-creado (compatible con tests que no
            esperan UDTs en su payload: el walker recursivo produce
            ``[]`` porque MagicMock no tiene ``get_blocks`` que
            devuelva datos).
    """
    plc = MagicMock()
    plc.get_name.return_value = "PLC_1"
    plc.get_program_blocks.return_value = blocks
    plc.get_plc_tag_tables.return_value = tag_tables
    if user_data_types is not None:
        plc.get_user_data_types.return_value = user_data_types

    project = MagicMock()
    project.get_plcs.return_value = [plc]

    portal = MagicMock()
    portal.get_project.return_value = project
    return portal


# ────────────────────────────────────────────────────────────────────────
# Tests de shape
# ────────────────────────────────────────────────────────────────────────


def test_cmd_scan_blocks_returns_correct_shape() -> None:
    """El payload tiene exactamente 5 keys y los tipos correctos."""
    blocks = [
        _make_block("DB1_SYS", "0_Sistema\\DB1_SYS"),
        _make_block("FB_Main", "0_Sistema\\FB_Main"),
    ]
    sub_group = MagicMock()
    sub_group.get_blocks.return_value = [_make_block("FC10", "0_Sistema\\FC10")]
    sub_group.get_groups.return_value = []

    # Grupo anidado con un sub-grupo dentro.
    nested = MagicMock()
    nested.get_blocks.return_value = [_make_block("OB1", "0_Sistema\\OB1")]
    nested.get_groups.return_value = []

    root_group = MagicMock()
    root_group.get_blocks.return_value = blocks
    root_group.get_groups.return_value = [sub_group, nested]

    tables = [
        _make_table("Default_tag_table", "0_Sistema\\Default_tag_table"),
        _make_table("IO_tags", "0_Sistema\\IO_tags"),
    ]
    # UDTs en este test: ninguno (los UDTs viven en su propia coleccion
    # ``get_user_data_types()``; aqui el default es MagicMock sin valor
    # explicito y basta con que NO lance para que ``udts=[]``).
    portal = _make_portal(root_group, tables)

    result = _cmd_scan_blocks(portal, ts=None, args={"plc_name": "PLC_1"})

    assert isinstance(result, dict)
    assert set(result.keys()) == {
        "plc_name",
        "blocks",
        "tag_tables",
        "udts",
        "scanned_at",
    }
    assert result["plc_name"] == "PLC_1"
    # 4 bloques: DB1_SYS, FB_Main, FC10, OB1.
    assert isinstance(result["blocks"], list)
    assert len(result["blocks"]) == 4
    for b in result["blocks"]:
        assert set(b.keys()) == {"nombre", "numero", "tipo", "ruta"}
    # 2 tablas.
    assert len(result["tag_tables"]) == 2
    # UDTs: 0 (no mockeamos get_user_data_types en este test).
    assert result["udts"] == []
    # ISO 8601 parseable.
    assert isinstance(result["scanned_at"], str)
    # Acepta formatos con offset (+00:00) o con Z.
    iso = result["scanned_at"].replace("Z", "+00:00")
    parsed = datetime.fromisoformat(iso)
    assert parsed.tzinfo is not None


def test_cmd_scan_blocks_classifies_db_fb_fc_ob() -> None:
    """El handler detecta el tipo y numero a partir del prefijo del nombre."""
    blocks = [
        _make_block("DB1_SYS", "p1"),
        _make_block("FB42", "p2"),
        _make_block("FC10", "p3"),
        _make_block("OB100", "p4"),
        _make_block("MyBlock", "p5"),  # OTHER, numero 0
    ]
    portal = _make_portal(blocks, [])

    result = _cmd_scan_blocks(portal, ts=None, args={"plc_name": "PLC_1"})

    by_name = {b["nombre"]: b for b in result["blocks"]}
    assert by_name["DB1_SYS"]["tipo"] == "DB" and by_name["DB1_SYS"]["numero"] == 1
    assert by_name["FB42"]["tipo"] == "FB" and by_name["FB42"]["numero"] == 42
    assert by_name["FC10"]["tipo"] == "FC" and by_name["FC10"]["numero"] == 10
    assert by_name["OB100"]["tipo"] == "OB" and by_name["OB100"]["numero"] == 100
    assert by_name["MyBlock"]["tipo"] == "OTHER" and by_name["MyBlock"]["numero"] == 0


def test_cmd_scan_blocks_classifies_udt() -> None:
    """``UDT<n>`` → tipo UDT con su numero."""
    blocks = [_make_block("UDT5", "x"), _make_block("UDT_NoNum", "y")]
    portal = _make_portal(blocks, [])

    result = _cmd_scan_blocks(portal, ts=None, args={"plc_name": "PLC_1"})
    by_name = {b["nombre"]: b for b in result["blocks"]}
    assert by_name["UDT5"]["tipo"] == "UDT" and by_name["UDT5"]["numero"] == 5
    # El regex exige digitos inmediatamente tras el prefijo: UDT_NoNum
    # no encaja, queda como OTHER con numero 0. Esto es coherente con
    # el legacy ``scanner.py`` y con el spec del DTO.
    assert by_name["UDT_NoNum"]["tipo"] == "OTHER" and by_name["UDT_NoNum"]["numero"] == 0


def test_cmd_scan_blocks_tag_tables_get_other_tipo() -> None:
    """Las PlcTagTable se mapean a tipo=OTHER y numero=0."""
    tables = [_make_table("Default_tag_table", "0_Sistema")]
    portal = _make_portal([], tables)

    result = _cmd_scan_blocks(portal, ts=None, args={"plc_name": "PLC_1"})

    assert len(result["tag_tables"]) == 1
    t = result["tag_tables"][0]
    assert t["nombre"] == "Default_tag_table"
    assert t["tipo"] == "OTHER"
    assert t["numero"] == 0
    assert t["ruta"] == "0_Sistema"


# ────────────────────────────────────────────────────────────────────────
# Resilencia
# ────────────────────────────────────────────────────────────────────────


def test_cmd_scan_blocks_handles_path_failure_gracefully() -> None:
    """``get_path()`` que lanza → bloque con ``ruta=""`` (defensivo)."""
    bad = MagicMock()
    bad.get_name.return_value = "DB_ROTO"
    bad.get_path.side_effect = RuntimeError("COM transient error")
    good = _make_block("DB_OK", "x")

    portal = _make_portal([bad, good], [])

    result = _cmd_scan_blocks(portal, ts=None, args={"plc_name": "PLC_1"})

    by_name = {b["nombre"]: b for b in result["blocks"]}
    assert "DB_ROTO" in by_name
    assert by_name["DB_ROTO"]["ruta"] == ""  # fallback defensivo
    # El bloque bueno sigue presente con su ruta.
    assert by_name["DB_OK"]["ruta"] == "x"


def test_cmd_scan_blocks_handles_unicode_name_error() -> None:
    """``get_name()`` que lanza ``UnicodeDecodeError`` → bloque omitido."""
    bad = MagicMock()
    bad.get_name.side_effect = UnicodeDecodeError("utf-8", b"\xe1", 0, 1, "no")
    # Aseguramos que ``Name`` tampoco esta (al ser MagicMock, .Name existe
    # como atributo auto-creado; lo sobreescribimos para forzar el
    # fallback a None).
    bad.Name = None
    good = _make_block("DB_OK", "x")

    portal = _make_portal([bad, good], [])

    result = _cmd_scan_blocks(portal, ts=None, args={"plc_name": "PLC_1"})

    nombres = [b["nombre"] for b in result["blocks"]]
    assert "DB_OK" in nombres
    # El bloque con UnicodeDecodeError fue descartado silenciosamente.
    assert not any("ROTO" in n for n in nombres)


# ────────────────────────────────────────────────────────────────────────
# Validación
# ────────────────────────────────────────────────────────────────────────


def test_cmd_scan_blocks_requires_plc_name() -> None:
    """``plc_name`` ausente → ``ValueError``."""
    portal = _make_portal([], [])
    with pytest.raises(ValueError, match="plc_name"):
        _cmd_scan_blocks(portal, ts=None, args={})


def test_cmd_scan_blocks_requires_active_project() -> None:
    """Sin proyecto activo → ``RuntimeError``."""
    portal = MagicMock()
    portal.get_project.return_value = None
    with pytest.raises(RuntimeError, match="proyecto"):
        _cmd_scan_blocks(portal, ts=None, args={"plc_name": "PLC_1"})


def test_cmd_scan_blocks_unknown_plc_raises() -> None:
    """PLC inexistente → ``RuntimeError``."""
    plc = MagicMock()
    plc.get_name.return_value = "OTRO"
    project = MagicMock()
    project.get_plcs.return_value = [plc]
    portal = MagicMock()
    portal.get_project.return_value = project

    with pytest.raises(RuntimeError, match="PLC_FANTASMA"):
        _cmd_scan_blocks(portal, ts=None, args={"plc_name": "PLC_FANTASMA"})


def test_cmd_scan_blocks_empty_program_blocks_yields_empty_list() -> None:
    """PLC sin bloques ni tablas ni UDTs → las 3 listas son ``[]`` (no falla)."""
    portal = _make_portal([], [])
    result = _cmd_scan_blocks(portal, ts=None, args={"plc_name": "PLC_1"})
    assert result["blocks"] == []
    assert result["tag_tables"] == []
    assert result["udts"] == []


# ────────────────────────────────────────────────────────────────────────
# UDTs (tercera categoria, escaneados via ``get_user_data_types()``)
# ────────────────────────────────────────────────────────────────────────


def test_cmd_scan_blocks_returns_udts_third_list() -> None:
    """``get_user_data_types()`` con 1-2 UDTs → aparecen en ``result['udts']``.

    La coleccion vive en su propio slot, separada de ``blocks`` y
    ``tag_tables``; cada entrada respeta el shape ``BloquePLC.to_dict()``.
    """
    # Un UDT suelto + un grupo que contiene un UDT anidado.
    udt_root = MagicMock()
    udt_root.get_blocks.return_value = [
        _make_block("UDT1_Dispositivo", "Tipos\\UDT1_Dispositivo"),
    ]
    nested_udt_group = MagicMock()
    nested_udt_group.get_blocks.return_value = [
        _make_block("UDT2_Config", "Tipos\\Sub\\UDT2_Config"),
    ]
    nested_udt_group.get_groups.return_value = []
    udt_root.get_groups.return_value = [nested_udt_group]

    portal = _make_portal(blocks=[], tag_tables=[], user_data_types=udt_root)

    result = _cmd_scan_blocks(portal, ts=None, args={"plc_name": "PLC_1"})

    assert "udts" in result
    assert isinstance(result["udts"], list)
    assert len(result["udts"]) == 2
    for u in result["udts"]:
        assert set(u.keys()) == {"nombre", "numero", "tipo", "ruta"}

    by_name = {u["nombre"]: u for u in result["udts"]}
    # El primero proviene del root group, el segundo del sub-grupo.
    assert by_name["UDT1_Dispositivo"]["tipo"] == "UDT"
    assert by_name["UDT1_Dispositivo"]["numero"] == 1
    assert by_name["UDT1_Dispositivo"]["ruta"] == "Tipos\\UDT1_Dispositivo"
    assert by_name["UDT2_Config"]["tipo"] == "UDT"
    assert by_name["UDT2_Config"]["numero"] == 2
    assert by_name["UDT2_Config"]["ruta"] == "Tipos\\Sub\\UDT2_Config"
    # La categoria blocks/tag_tables queda vacia en este test.
    assert result["blocks"] == []
    assert result["tag_tables"] == []


def test_cmd_scan_blocks_handles_user_data_types_failure() -> None:
    """``get_user_data_types()`` que lanza → scan OK, ``udts=[]``."""
    plc = MagicMock()
    plc.get_name.return_value = "PLC_1"
    plc.get_program_blocks.return_value = [_make_block("DB1_SYS", "p1")]
    plc.get_plc_tag_tables.return_value = [
        _make_table("Default_tag_table", "p2"),
    ]
    plc.get_user_data_types.side_effect = RuntimeError(
        "Coleccion no expuesta en este build"
    )

    project = MagicMock()
    project.get_plcs.return_value = [plc]
    portal = MagicMock()
    portal.get_project.return_value = project

    result = _cmd_scan_blocks(portal, ts=None, args={"plc_name": "PLC_1"})

    # Scan sigue devolviendo los 2 slots historicos intactos.
    assert len(result["blocks"]) == 1
    assert result["blocks"][0]["nombre"] == "DB1_SYS"
    assert len(result["tag_tables"]) == 1
    assert result["tag_tables"][0]["nombre"] == "Default_tag_table"
    # Y la nueva coleccion degrada a vacia sin reventar el handler.
    assert result["udts"] == []


def test_cmd_scan_blocks_separates_udts_from_blocks() -> None:
    """Invariante: un DB nunca aparece en ``udts`` y un UDT nunca en ``blocks``.

    Aunque TIA internamente los UDTs podrian colgar del mismo arbol de
    bloques, en nuestro cache viven en colecciones separadas. Esto es
    critico para que la SPA pueda pintarlos en tabs distintos.
    """
    # 1 DB en get_program_blocks (root + grupo anidado).
    db_group = MagicMock()
    db_group.get_blocks.return_value = [_make_block("DB1_SYS", "DBs\\DB1_SYS")]
    db_group.get_groups.return_value = []

    # 1 UDT en get_user_data_types (root + grupo anidado).
    udt_group = MagicMock()
    udt_group.get_blocks.return_value = [
        _make_block("UDT5_Tipo", "Tipos\\UDT5_Tipo"),
    ]
    udt_group.get_groups.return_value = []

    portal = _make_portal(
        blocks=db_group, tag_tables=[], user_data_types=udt_group
    )

    result = _cmd_scan_blocks(portal, ts=None, args={"plc_name": "PLC_1"})

    block_names = {b["nombre"] for b in result["blocks"]}
    udt_names = {u["nombre"] for u in result["udts"]}

    # Invariante: cada nombre vive EXACTAMENTE en una coleccion.
    assert block_names == {"DB1_SYS"}
    assert udt_names == {"UDT5_Tipo"}
    assert block_names.isdisjoint(udt_names)
    # Y la clasificacion de tipo es coherente con el slot.
    assert result["blocks"][0]["tipo"] == "DB"
    assert result["udts"][0]["tipo"] == "UDT"


# ────────────────────────────────────────────────────────────────────────
# Registro
# ────────────────────────────────────────────────────────────────────────


def test_scan_blocks_registered_in_command_registry() -> None:
    """``"scan_blocks"`` esta en ``COMMAND_REGISTRY`` y mapea al handler."""
    assert "scan_blocks" in COMMAND_REGISTRY
    assert COMMAND_REGISTRY["scan_blocks"] is _cmd_scan_blocks
