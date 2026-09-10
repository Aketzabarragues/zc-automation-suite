"""Tests del handler ``_cmd_compile_blocks`` del worker OT (sept-2026).

Cubre el comando que compila SOLO los bloques indicados en
``block_names`` (no todo el software del PLC), saltando los que ya
estan consistentes (``is_consistent()=True``). Es el caso de uso del
sync de dispositivos: tras modificar N_MAX + comentarios solo se
tocan 6 DBs, asi que compilar todo el software del PLC es
desproporcionado.

Estrategia:
  - Mockeamos el portal con ``MagicMock()`` (Pythonnet, sin spec).
  - El portal expone ``get_project()`` -> ``project`` con
    ``get_plcs()``. El PLC mockeado expone ``get_program_blocks()`` y
    ``get_name()``.
  - Cada bloque expone ``get_name()``, ``is_consistent()`` y
    ``compile()``. La semantica Siemens de ``compile()`` retorna
    ``True`` si hay errores, ``False`` si OK.
  - Verificamos shape del payload, semantica de skip/error/not_found,
    y la contratacion con ``COMMAND_REGISTRY`` y
    ``_TRANSACTION_FORBIDDEN_COMMANDS``.

Convenciones heredadas del worker:
  - ``ts`` se ignora (el handler no toca el modulo Siemens).
  - ``portal.get_project()`` retorna el proyecto activo.
  - ``_get_active_project`` y ``_find_plc`` son los helpers internos
    que el handler usa (los mockeamos via sus efectos: portal chain).
"""
from __future__ import annotations

import importlib
from unittest.mock import MagicMock

import pytest

# Cargar el modulo del worker sin ejecutar ``main()`` (que requiere
# siemens_tia_scripting, no disponible en tests).
worker_tia = importlib.import_module("core.infrastructure.tia.worker_tia")
COMMAND_REGISTRY: dict = worker_tia.COMMAND_REGISTRY
_cmd_compile_blocks = worker_tia._cmd_compile_blocks
_TRANSACTION_FORBIDDEN_COMMANDS = worker_tia._TRANSACTION_FORBIDDEN_COMMANDS


# ────────────────────────────────────────────────────────────────────────
# Helpers
# ────────────────────────────────────────────────────────────────────────


def _make_block(
    name: str,
    is_consistent: bool = False,
    compile_result: bool = False,
    compile_raises: BaseException | None = None,
    is_consistent_raises: BaseException | None = None,
) -> MagicMock:
    """Crea un bloque mockeado con la semantica de TIA Openness.

    Args:
        name: nombre del bloque (lo retorna ``get_name()``).
        is_consistent: valor de retorno de ``is_consistent()`` cuando no
            lanza. Si ``is_consistent_raises`` se da, este parametro
            se ignora.
        compile_result: valor de retorno de ``.compile()`` (True=hay
            errores, False=OK). Si ``compile_raises`` se da, este
            parametro se ignora.
        compile_raises: si se da, ``.compile()`` lanza esta excepcion
            (caso defensivo: error grave durante compilacion).
        is_consistent_raises: si se da, ``is_consistent()`` lanza
            esta excepcion (caso defensivo: el handler trata esto como
            "no consistente" y compila).
    """
    block = MagicMock()
    block.get_name.return_value = name
    if is_consistent_raises is not None:
        block.is_consistent.side_effect = is_consistent_raises
    else:
        block.is_consistent.return_value = is_consistent
    if compile_raises is not None:
        block.compile.side_effect = compile_raises
    else:
        block.compile.return_value = compile_result
    return block


def _make_portal_with_plc(
    plc_name: str,
    blocks: list[MagicMock],
) -> MagicMock:
    """Arma el portal mockeado con un PLC y su lista de bloques.

    Chain: ``portal.get_project()`` -> ``project`` -> ``get_plcs()``
    -> ``[plc]`` -> ``get_name()`` == ``plc_name`` ->
    ``get_program_blocks()`` == ``blocks``.
    """
    plc = MagicMock()
    plc.get_name.return_value = plc_name
    plc.get_program_blocks.return_value = blocks

    project = MagicMock()
    project.get_plcs.return_value = [plc]

    portal = MagicMock()
    portal.get_project.return_value = project
    return portal


# ────────────────────────────────────────────────────────────────────────
# Tests de shape y registro
# ────────────────────────────────────────────────────────────────────────


def test_compile_blocks_registrado_en_command_registry() -> None:
    """El handler esta registrado bajo la clave ``"compile_blocks"``.

    Invariante: si el operario llama a ``gateway.compile_blocks(...)``
    el dispatcher del worker resuelve el handler via esta clave.
    """
    assert "compile_blocks" in COMMAND_REGISTRY
    assert COMMAND_REGISTRY["compile_blocks"] is _cmd_compile_blocks


def test_compile_blocks_en_transaction_forbidden_commands() -> None:
    """``compile_blocks`` esta prohibido dentro de transacciones.

    Consistencia con ``compile_plc``: la compilacion es una operacion
    de mutacion LARGA (segundos en S7-1500) y debe ir DESPUES de cerrar
    la transaccion, no dentro. Si alguien intenta meterlo en un batch
    transaccional, el dispatcher lo rechaza con error claro.
    """
    assert "compile_blocks" in _TRANSACTION_FORBIDDEN_COMMANDS


# ────────────────────────────────────────────────────────────────────────
# Tests de validacion de argumentos
# ────────────────────────────────────────────────────────────────────────


def test_cmd_compile_blocks_sin_plc_name_lanza_value_error() -> None:
    """Sin ``plc_name`` el handler rechaza con ``ValueError``.

    Decisión del operario: error explicito > ``KeyError`` o
    ``AttributeError`` confuso. El caller sabe qué le falta.
    """
    portal = _make_portal_with_plc("PLC1", [])

    with pytest.raises(ValueError, match="plc_name"):
        _cmd_compile_blocks(portal, ts=None, args={
            "block_names": ["DB2000_ED"],
        })


def test_cmd_compile_blocks_sin_block_names_lanza_value_error() -> None:
    """Sin ``block_names`` el handler rechaza con ``ValueError``.

    El argumento es obligatorio; ``None`` se rechaza igual que la
    lista vacia (mismo control determinista).
    """
    portal = _make_portal_with_plc("PLC1", [])

    with pytest.raises(ValueError, match="block_names"):
        _cmd_compile_blocks(portal, ts=None, args={"plc_name": "PLC1"})


def test_cmd_compile_blocks_block_names_vacio_lanza_value_error() -> None:
    """``block_names=[]`` se rechaza con ``ValueError``.

    Decisión sept-2026 del operario: si quieres compilar todo el PLC,
    usa ``compile_plc`` (con todas sus consecuencias). El handler
    ``compile_blocks`` exige lista no vacia para tener control
    determinista sobre que se compila.
    """
    portal = _make_portal_with_plc("PLC1", [])

    with pytest.raises(ValueError, match="block_names"):
        _cmd_compile_blocks(portal, ts=None, args={
            "plc_name": "PLC1",
            "block_names": [],
        })


def test_cmd_compile_blocks_plc_no_encontrado_lanza_runtime_error() -> None:
    """Si el PLC no existe en el proyecto, ``RuntimeError`` claro.

    Mensaje incluye el nombre del PLC para que el operario sepa
    qué PLC no se encontro (util en proyectos multi-PLC).
    """
    portal = _make_portal_with_plc("PLC_REAL", [])

    with pytest.raises(RuntimeError, match="PLC_FANTASMA"):
        _cmd_compile_blocks(portal, ts=None, args={
            "plc_name": "PLC_FANTASMA",
            "block_names": ["DB2000_ED"],
        })


# ────────────────────────────────────────────────────────────────────────
# Tests de la semantica de compilacion
# ────────────────────────────────────────────────────────────────────────


def test_cmd_compile_blocks_todos_inconsistentes_compila_todos() -> None:
    """Si todos los bloques son inconsistentes, se compilan todos.

    Caso feliz del sync de dispositivos: tras modificar N_MAX, los
    6 DBs reportan ``is_consistent()=False``. El handler los compila
    uno a uno y devuelve la lista de compilados con ``had_errors``.
    """
    blocks = [
        _make_block("DB2000_ED", is_consistent=False, compile_result=False),
        _make_block("DB2001_EA", is_consistent=False, compile_result=False),
        _make_block("DB2002_SA", is_consistent=False, compile_result=False),
    ]
    portal = _make_portal_with_plc("PLC1", blocks)

    result = _cmd_compile_blocks(portal, ts=None, args={
        "plc_name": "PLC1",
        "block_names": ["DB2000_ED", "DB2001_EA", "DB2002_SA"],
    })

    assert result == {
        "compiled": [
            {"name": "DB2000_ED", "had_errors": False, "was_inconsistent": True},
            {"name": "DB2001_EA", "had_errors": False, "was_inconsistent": True},
            {"name": "DB2002_SA", "had_errors": False, "was_inconsistent": True},
        ],
        "skipped_unchanged": [],
        "not_found": [],
        "errors": [],
    }
    # Cada bloque fue compilado exactamente una vez.
    for b in blocks:
        b.compile.assert_called_once()


def test_cmd_compile_blocks_todos_consistentes_salta_todos() -> None:
    """Si todos los bloques son consistentes, se saltan (no se compilan).

    Caso real (sept-2026): tras sync, la mayoria de las veces los DBs
    ya estaban consistentes. ``is_consistent()=True`` -> skip
    inmediato, sin tocar ``.compile()``. Decisión del operario:
    ahorra tiempo de compilacion.
    """
    blocks = [
        _make_block("DB2000_ED", is_consistent=True),
        _make_block("DB2001_EA", is_consistent=True),
    ]
    portal = _make_portal_with_plc("PLC1", blocks)

    result = _cmd_compile_blocks(portal, ts=None, args={
        "plc_name": "PLC1",
        "block_names": ["DB2000_ED", "DB2001_EA"],
    })

    assert result == {
        "compiled": [],
        "skipped_unchanged": ["DB2000_ED", "DB2001_EA"],
        "not_found": [],
        "errors": [],
    }
    # Ningun bloque fue compilado.
    for b in blocks:
        b.compile.assert_not_called()


def test_cmd_compile_blocks_mezcla_consistentes_e_inconsistentes() -> None:
    """Mezcla: solo se compilan los inconsistentes; los consistentes se saltan.

    Caso real: tras sync, puede que el operario modifique 2 DBs y los
    otros 4 ya estuvieran consistentes. El handler reporta cada uno
    en su bucket correspondiente para trazabilidad.
    """
    blocks = [
        _make_block("DB2000_ED", is_consistent=False, compile_result=False),
        _make_block("DB2001_EA", is_consistent=True),
        _make_block("DB2002_SA", is_consistent=False, compile_result=False),
    ]
    portal = _make_portal_with_plc("PLC1", blocks)

    result = _cmd_compile_blocks(portal, ts=None, args={
        "plc_name": "PLC1",
        "block_names": ["DB2000_ED", "DB2001_EA", "DB2002_SA"],
    })

    assert result["compiled"] == [
        {"name": "DB2000_ED", "had_errors": False, "was_inconsistent": True},
        {"name": "DB2002_SA", "had_errors": False, "was_inconsistent": True},
    ]
    assert result["skipped_unchanged"] == ["DB2001_EA"]
    assert result["not_found"] == []
    assert result["errors"] == []


def test_cmd_compile_blocks_bloque_no_existe_en_plc() -> None:
    """Nombres pedidos que no existen en el PLC van a ``not_found``.

    Decisión: el handler no falla el batch entero si un nombre no
    existe. Lo reporta en ``not_found`` para que el caller decida
    (probablemente warn, no abortar, porque el use case solo
    necesita compilar lo que SI encontro).
    """
    blocks = [
        _make_block("DB2000_ED", is_consistent=False, compile_result=False),
    ]
    portal = _make_portal_with_plc("PLC1", blocks)

    result = _cmd_compile_blocks(portal, ts=None, args={
        "plc_name": "PLC1",
        "block_names": ["DB2000_ED", "DB_FANTASMA", "DB_OTRO_FANTASMA"],
    })

    assert result["compiled"] == [
        {"name": "DB2000_ED", "had_errors": False, "was_inconsistent": True},
    ]
    assert result["skipped_unchanged"] == []
    assert sorted(result["not_found"]) == ["DB_FANTASMA", "DB_OTRO_FANTASMA"]
    assert result["errors"] == []


def test_cmd_compile_blocks_bloque_compila_con_errores() -> None:
    """Bloque que compila con errores: ``had_errors=True``.

    Semantica Siemens: ``.compile()`` retorna ``True`` si encontro
    errores de compilacion. El handler lo refleja en
    ``compiled[].had_errors`` para que el caller pueda abortar el
    commit o reportar al operario.
    """
    blocks = [
        _make_block("DB2000_ED", is_consistent=False, compile_result=True),  # errores
        _make_block("DB2001_EA", is_consistent=False, compile_result=False),  # OK
    ]
    portal = _make_portal_with_plc("PLC1", blocks)

    result = _cmd_compile_blocks(portal, ts=None, args={
        "plc_name": "PLC1",
        "block_names": ["DB2000_ED", "DB2001_EA"],
    })

    assert result["compiled"] == [
        {"name": "DB2000_ED", "had_errors": True, "was_inconsistent": True},
        {"name": "DB2001_EA", "had_errors": False, "was_inconsistent": True},
    ]
    assert result["skipped_unchanged"] == []
    assert result["not_found"] == []
    assert result["errors"] == []


def test_cmd_compile_blocks_excepcion_en_compile_no_aborta_batch() -> None:
    """Si ``.compile()`` lanza, el siguiente bloque se sigue procesando.

    Decisión del operario: un bloque problematico (e.g. DB corrupto,
    error de sintaxis grave que rompe el wrapper) NO debe impedir
    que el resto se compile. Se registra en ``errors`` con tipo y
    mensaje, y el batch sigue.
    """
    blocks = [
        _make_block(
            "DB2000_ED",
            is_consistent=False,
            compile_raises=RuntimeError("sintaxis invalida"),
        ),
        _make_block("DB2001_EA", is_consistent=False, compile_result=False),
    ]
    portal = _make_portal_with_plc("PLC1", blocks)

    result = _cmd_compile_blocks(portal, ts=None, args={
        "plc_name": "PLC1",
        "block_names": ["DB2000_ED", "DB2001_EA"],
    })

    # El primero fue a errors, el segundo se compilo OK.
    assert result["compiled"] == [
        {"name": "DB2001_EA", "had_errors": False, "was_inconsistent": True},
    ]
    assert result["skipped_unchanged"] == []
    assert result["not_found"] == []
    assert len(result["errors"]) == 1
    assert result["errors"][0]["name"] == "DB2000_ED"
    assert "RuntimeError" in result["errors"][0]["error"]
    assert "sintaxis invalida" in result["errors"][0]["error"]


def test_cmd_compile_blocks_is_consistent_que_lanza_se_trata_como_inconsistente() -> None:
    """Si ``is_consistent()`` lanza, asumimos NO consistente y compilamos.

    Caso defensivo: algunas versiones de TIA o algunos modelos de
    bloque pueden lanzar al consultar ``is_consistent()``. El
    handler opta por el camino conservador: si no sabemos si es
    consistente, lo compilamos. Es preferible una compilacion de mas
    que un skip erroneo.
    """
    blocks = [
        _make_block(
            "DB2000_ED",
            is_consistent_raises=RuntimeError("is_consistent no soportado"),
            compile_result=False,
        ),
    ]
    portal = _make_portal_with_plc("PLC1", blocks)

    result = _cmd_compile_blocks(portal, ts=None, args={
        "plc_name": "PLC1",
        "block_names": ["DB2000_ED"],
    })

    # Se compilo (no se skipeo), aunque is_consistent() habia lanzado.
    assert result["compiled"] == [
        {"name": "DB2000_ED", "had_errors": False, "was_inconsistent": True},
    ]
    assert result["skipped_unchanged"] == []
    blocks[0].compile.assert_called_once()


def test_cmd_compile_blocks_sin_bloques_en_plc_todo_not_found() -> None:
    """PLC sin bloques (recien creado) -> todos los nombres van a ``not_found``.

    El handler no falla: simplemente reporta que ningun bloque
    pedido existe. El caller puede decidir si eso es un error o un
    no-op (en el caso del sync, significaria que el PLC no tiene
    los DBs esperados, lo que SI es un error de configuracion).
    """
    portal = _make_portal_with_plc("PLC1", [])

    result = _cmd_compile_blocks(portal, ts=None, args={
        "plc_name": "PLC1",
        "block_names": ["DB2000_ED", "DB2001_EA"],
    })

    assert result["compiled"] == []
    assert result["skipped_unchanged"] == []
    assert result["not_found"] == ["DB2000_ED", "DB2001_EA"]
    assert result["errors"] == []


def test_cmd_compile_blocks_mezcla_completa_todos_los_casos() -> None:
    """Smoke test: un solo batch con los 4 casos (compilado OK,
    compilado con errores, skipped, not_found, error de excepcion).

    Garantiza que los 4 buckets son independientes y que el handler
    procesa una lista heterogenea correctamente, reportando cada
    bloque en su categoria adecuada.
    """
    blocks = [
        _make_block("DB2000_ED", is_consistent=False, compile_result=False),
        _make_block("DB2001_EA", is_consistent=True),
        _make_block("DB2002_SA", is_consistent=False, compile_result=True),  # con errores
        _make_block(
            "DB2003_V",
            is_consistent=False,
            compile_raises=ValueError("boom"),
        ),
    ]
    portal = _make_portal_with_plc("PLC1", blocks)

    result = _cmd_compile_blocks(portal, ts=None, args={
        "plc_name": "PLC1",
        "block_names": [
            "DB2000_ED",   # compilado OK
            "DB2001_EA",   # skipped (consistente)
            "DB2002_SA",   # compilado con errores
            "DB2003_V",    # excepcion
            "DB_FAKE",     # not found
        ],
    })

    assert result["compiled"] == [
        {"name": "DB2000_ED", "had_errors": False, "was_inconsistent": True},
        {"name": "DB2002_SA", "had_errors": True, "was_inconsistent": True},
    ]
    assert result["skipped_unchanged"] == ["DB2001_EA"]
    assert result["not_found"] == ["DB_FAKE"]
    assert len(result["errors"]) == 1
    assert result["errors"][0]["name"] == "DB2003_V"
    assert "ValueError" in result["errors"][0]["error"]


def test_cmd_compile_blocks_no_llama_get_program_blocks_dos_veces() -> None:
    """``get_program_blocks()`` se llama exactamente una vez por invocacion.

    El handler indexa los bloques por nombre una sola vez (mapa
    ``by_name``) y luego itera ``block_names``. Si lo llamara en cada
    iteracion seria O(N*M) y romperia con PLCs grandes (200+
    bloques). Esta invariante protege el rendimiento.
    """
    blocks = [
        _make_block("DB2000_ED", is_consistent=False, compile_result=False),
        _make_block("DB2001_EA", is_consistent=False, compile_result=False),
    ]
    portal = _make_portal_with_plc("PLC1", blocks)

    _cmd_compile_blocks(portal, ts=None, args={
        "plc_name": "PLC1",
        "block_names": ["DB2000_ED", "DB2001_EA", "DB_FAKE"],
    })

    # Solo se pidio una vez la lista completa de bloques.
    portal.get_project.return_value.get_plcs.return_value[
        0
    ].get_program_blocks.assert_called_once()
