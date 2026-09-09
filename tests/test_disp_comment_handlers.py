"""Tests del handler de comentarios del worker.

Mockeamos ``export_block`` e ``import_block`` en el ``COMMAND_REGISTRY``
para no tocar TIA. El test verifica que el handler:
  - invoca export/import con los args correctos.
  - devuelve el ``DispCommentResult`` populado.
  - falla con args incompletos.
  - propaga excepciones (el batch hará rollback).
  - lee la carpeta del config (no hardcoded).
"""
from __future__ import annotations

import importlib
import sys
from pathlib import Path
import tempfile
from unittest.mock import MagicMock

import pytest

# Cargar worker_tia sin ejecutar su ``main()`` (que requiere siemens_tia_scripting).
worker_tia = importlib.import_module("core.infrastructure.tia.worker_tia")
COMMAND_REGISTRY: dict = worker_tia.COMMAND_REGISTRY


@pytest.fixture(autouse=True)
def mock_export_import_blocks() -> None:
    """Sustituye ``export_block`` e ``import_block`` con MagicMocks.

    Restaurar el original al final de cada test.
    """
    orig_export = COMMAND_REGISTRY["export_block"]
    orig_import = COMMAND_REGISTRY["import_block"]
    COMMAND_REGISTRY["export_block"] = MagicMock(return_value="C:/work")
    COMMAND_REGISTRY["import_block"] = MagicMock(return_value=True)
    yield
    COMMAND_REGISTRY["export_block"] = orig_export
    COMMAND_REGISTRY["import_block"] = orig_import


def _write_minimal_s7dcl_s7res(work_dir: Path, db_name: str = "DB2000_ED") -> None:
    """Crea un par .s7dcl / .s7res mínimos en ``work_dir``."""
    s7dcl = f"""DATA_BLOCK {db_name}
    VAR
        "X" : Array[0..10] of _.UDT_ZC_DISP_X;
    END_VAR

        "X"[0].Estado_AutoMan := FALSE;
        "X"[0] := ();

END_DATA_BLOCK
"""
    s7res = "MultiLingualTexts:\n"
    (work_dir / f"{db_name}.s7dcl").write_text(s7dcl, encoding="utf-8")
    (work_dir / f"{db_name}.s7res").write_text(s7res, encoding="utf-8-sig")


def test_handler_actualiza_un_db(tmp_path: Path) -> None:
    """Handler invoca export+import con la ruta correcta y devuelve DispCommentResult."""
    work_dir = tmp_path / "work"
    work_dir.mkdir()
    _write_minimal_s7dcl_s7res(work_dir)

    handler = COMMAND_REGISTRY["update_disp_comments_db_ed"]
    result = handler(
        portal=MagicMock(),
        ts=MagicMock(),
        args={
            "plc_name":      "PLC_X",
            "db_name":       "DB2000_ED",
            "db_array_name": "ED",
            "slot_map":      {"0": "NO USAR", "1": "Bomba 1"},
            "work_dir":      str(work_dir),
            "target_folder": "2000_Dispositivos",
        },
    )

    # export_block se llamó con block_name = db_name.
    COMMAND_REGISTRY["export_block"].assert_called_once()
    call = COMMAND_REGISTRY["export_block"].call_args
    assert call.args[2]["plc_name"] == "PLC_X"
    assert call.args[2]["block_name"] == "DB2000_ED"
    assert call.args[2]["target_dir"] == str(work_dir)

    # import_block se llamó con target_folder.
    COMMAND_REGISTRY["import_block"].assert_called_once()
    call = COMMAND_REGISTRY["import_block"].call_args
    assert call.args[2]["target_folder"] == "2000_Dispositivos"

    # Resultado poblado.
    assert result["hw_type"] == "ed"
    assert result["db_name"] == "DB2000_ED"
    assert result["modified"] is True
    assert "MLC_" in result["disp_comment_result"]["no_usar_mlc"]


def test_handler_falla_si_args_incompletos(tmp_path: Path) -> None:
    """Args incompletos → ValueError."""
    handler = COMMAND_REGISTRY["update_disp_comments_db_ea"]
    with pytest.raises(ValueError, match="args incompletos"):
        handler(
            portal=MagicMock(),
            ts=MagicMock(),
            args={"plc_name": "PLC_X", "db_name": "DB2001_EA"},
        )


def test_handler_no_import_si_no_modificado(tmp_path: Path) -> None:
    """Si el updater no modifica nada, no se invoca ``import_block`` (evita ruido en Undo)."""
    work_dir = tmp_path / "work"
    work_dir.mkdir()

    # .s7dcl / .s7res ya correctos: slot 0 con MLC + texto NO USAR en s7res.
    s7dcl = """DATA_BLOCK DB2000_ED
    VAR
        "ED" : Array[0..10] of _.UDT_ZC_DISP_ED;
    END_VAR

        "ED"[0].Estado_AutoMan := FALSE;
        { S7_MLC := "MLC_old0" }
        "ED"[0] := ();

END_DATA_BLOCK
"""
    s7res = (
        "MultiLingualTexts:\n"
        "  - id: MLC_old0\n"
        "    es-ES: NO USAR\n"
    )
    (work_dir / "DB2000_ED.s7dcl").write_text(s7dcl, encoding="utf-8")
    (work_dir / "DB2000_ED.s7res").write_text(s7res, encoding="utf-8-sig")

    handler = COMMAND_REGISTRY["update_disp_comments_db_ed"]
    result = handler(
        portal=MagicMock(),
        ts=MagicMock(),
        args={
            "plc_name":      "PLC_X",
            "db_name":       "DB2000_ED",
            "db_array_name": "ED",
            "slot_map":      {"0": "NO USAR"},  # ya coincide, no hay cambios.
            "work_dir":      str(work_dir),
            "target_folder": "2000_Dispositivos",
        },
    )

    assert result["modified"] is False
    COMMAND_REGISTRY["import_block"].assert_not_called()


def test_handler_propagates_exception(tmp_path: Path) -> None:
    """Si export_block lanza, la excepción se propaga (rollback del batch)."""
    COMMAND_REGISTRY["export_block"] = MagicMock(
        side_effect=RuntimeError("TIA no disponible")
    )

    handler = COMMAND_REGISTRY["update_disp_comments_db_sa"]
    with pytest.raises(RuntimeError, match="TIA no disponible"):
        handler(
            portal=MagicMock(),
            ts=MagicMock(),
            args={
                "plc_name":      "PLC_X",
                "db_name":       "DB2006_SA",
                "db_array_name": "SA",
                "slot_map":      {"0": "NO USAR"},
                "work_dir":      str(tmp_path),
                "target_folder": "2000_Dispositivos",
            },
        )


def test_ruta_destino_viene_del_config(tmp_path: Path) -> None:
    """El handler NO debe hardcodear la carpeta TIA; usa el ``target_folder`` de args.

    Si alguien hardcodea ``"2000_Dispositivos"`` en el código del handler,
    este test fallaría porque el ``target_folder`` que pasamos es otro
    (``OTRA_CARPETA``) y el handler debe respetarlo.
    """
    work_dir = tmp_path / "work"
    work_dir.mkdir()
    _write_minimal_s7dcl_s7res(work_dir, db_name="DB2010_V")

    handler = COMMAND_REGISTRY["update_disp_comments_db_v"]
    handler(
        portal=MagicMock(),
        ts=MagicMock(),
        args={
            "plc_name":      "PLC_X",
            "db_name":       "DB2010_V",
            "db_array_name": "V",
            "slot_map":      {"0": "NO USAR", "1": "Valvula 1"},
            "work_dir":      str(work_dir),
            "target_folder": "OTRA_CARPETA",
        },
    )

    call = COMMAND_REGISTRY["import_block"].call_args
    assert call.args[2]["target_folder"] == "OTRA_CARPETA", (
        "El handler debe respetar el target_folder del caller, no hardcodearlo."
    )


def test_handler_todos_los_hw_types_registrados() -> None:
    """Los 6 handlers del dominio dispositivos están en el COMMAND_REGISTRY."""
    expected = [
        "update_disp_comments_db_ed",
        "update_disp_comments_db_ea",
        "update_disp_comments_db_sa",
        "update_disp_comments_db_v",
        "update_disp_comments_db_m",
        "update_disp_comments_db_m_vf",
    ]
    for name in expected:
        assert name in COMMAND_REGISTRY, f"Falta handler {name!r} en COMMAND_REGISTRY"
        assert callable(COMMAND_REGISTRY[name]), f"{name!r} no es callable"


def test_handler_usa_exports_subdir_y_copytree_si_se_pasa() -> None:
    """Commit 7: cuando se pasa ``exports_subdir``, el handler de disp
    exporta al snapshot limpio (``exports_subdir``) y hace
    ``shutil.copytree`` a ``work_dir`` antes del modify. El snapshot
    pre-commit queda intacto en ``exports_subdir`` y la versión
    modificada vive en ``work_dir`` (= ``modified_bloques/``).

    Consecuencia: ``git diff exports/bloques/ modified/bloques/``
    muestra los cambios del updater (audit pre vs post).
    """
    import shutil
    from unittest.mock import MagicMock
    from core.infrastructure.tia import worker_tia
    from core.models.bloque_plc import BloquePLC

    portal = MagicMock()
    ts = MagicMock()

    tmp_exports = Path(tempfile.mkdtemp(prefix="exports_"))
    tmp_work = Path(tempfile.mkdtemp(prefix="work_"))
    db_name = "DB2000_ED"

    # Simulamos el export de TIA: escribe ``.s7dcl`` y ``.s7res`` en
    # ``exports_subdir`` (= snapshot pre-commit).
    pre_dcl = tmp_exports / f"{db_name}.s7dcl"
    pre_res = tmp_exports / f"{db_name}.s7res"
    pre_dcl.write_text("PRE_DCL_CONTENT", encoding="utf-8")
    pre_res.write_text("MultiLingualTexts: []\n", encoding="utf-8-sig")

    def fake_export_block(portal_, ts_, args):
        target_dir = Path(args["target_dir"])
        # Simulamos: TIA escribe en target_dir (que en el flujo Commit 7
        # es ``exports_subdir``, NO ``work_dir``).
        (target_dir / f"{args['block_name']}.s7dcl").write_text(
            "PRE_DCL_CONTENT", encoding="utf-8"
        )
        (target_dir / f"{args['block_name']}.s7res").write_text(
            "MultiLingualTexts: []\n", encoding="utf-8-sig"
        )
        return target_dir

    def fake_import_block(portal_, ts_, args):
        # Capturamos el import_dir para verificar de dónde se importa.
        captured["import_dir"] = args.get("import_dir")
        return True

    captured: dict = {}
    core_registry = worker_tia.COMMAND_REGISTRY
    original_export = core_registry["export_block"]
    original_import = core_registry["import_block"]
    core_registry["export_block"] = fake_export_block
    core_registry["import_block"] = fake_import_block
    try:
        handler = COMMAND_REGISTRY["update_disp_comments_db_ed"]
        result = handler(portal, ts, {
            "plc_name": "PLC1",
            "db_name": db_name,
            "db_array_name": "ED",
            "slot_map": {"0": "NO USAR"},
            "work_dir": str(tmp_work),
            "target_folder": "2000_Dispositivos",
            "exports_subdir": str(tmp_exports),
        })
    finally:
        core_registry["export_block"] = original_export
        core_registry["import_block"] = original_import

    # 1. El snapshot pre-commit en ``exports_subdir`` está INTACTO
    #    (el updater NO lo modificó).
    assert pre_dcl.read_text(encoding="utf-8") == "PRE_DCL_CONTENT", (
        "El snapshot pre-commit en ``exports_subdir`` debe quedar intacto."
    )
    # 2. La copia en ``work_dir`` (modified_bloques) tiene el archivo
    #    escrito por el export inicial (vía copytree).
    assert (tmp_work / f"{db_name}.s7dcl").exists(), (
        "El handler debe hacer shutil.copytree de ``exports_subdir`` a ``work_dir``."
    )
    # 3. El import_block se llamó desde ``work_dir`` (modified_bloques).
    assert str(captured.get("import_dir")) == str(tmp_work), (
        f"El import debe hacerse desde ``work_dir`` (modified_bloques), "
        f"got: {captured.get('import_dir')!r}"
    )
    # 4. El export_block se llamó a ``exports_subdir`` (NO a ``work_dir``).
    assert pre_dcl.exists(), "El export debe escribirse en ``exports_subdir``."


def test_handler_sin_exports_subdir_usa_patron_legacy() -> None:
    """Sin ``exports_subdir`` (legacy), el handler exporta directo a ``work_dir``.

    Mantiene backward compat con tests legacy que no pasan
    ``exports_subdir``. En este caso, el snapshot pre y post-commit
    viven en el mismo path (asimétrico; pre-Commit 7).
    """
    from unittest.mock import MagicMock
    from core.infrastructure.tia import worker_tia

    portal = MagicMock()
    ts = MagicMock()
    tmp_work = Path(tempfile.mkdtemp(prefix="legacy_"))
    db_name = "DB2000_ED"

    captured: dict = {}

    def fake_export_block(portal_, ts_, args):
        captured["target_dir"] = args.get("target_dir")
        target_dir = Path(args["target_dir"])
        (target_dir / f"{args['block_name']}.s7dcl").write_text(
            "DCL", encoding="utf-8"
        )
        (target_dir / f"{args['block_name']}.s7res").write_text(
            "MultiLingualTexts: []\n", encoding="utf-8-sig"
        )
        return target_dir

    def fake_import_block(portal_, ts_, args):
        captured["import_dir"] = args.get("import_dir")
        return True

    core_registry = worker_tia.COMMAND_REGISTRY
    original_export = core_registry["export_block"]
    original_import = core_registry["import_block"]
    core_registry["export_block"] = fake_export_block
    core_registry["import_block"] = fake_import_block
    try:
        handler = COMMAND_REGISTRY["update_disp_comments_db_ed"]
        # NOTAR: NO pasamos ``exports_subdir`` (legacy).
        handler(portal, ts, {
            "plc_name": "PLC1",
            "db_name": db_name,
            "db_array_name": "ED",
            "slot_map": {"0": "NO USAR"},
            "work_dir": str(tmp_work),
            "target_folder": "2000_Dispositivos",
        })
    finally:
        core_registry["export_block"] = original_export
        core_registry["import_block"] = original_import

    # Legacy: export e import ambos sobre ``work_dir``.
    assert str(captured.get("target_dir")) == str(tmp_work)
    assert str(captured.get("import_dir")) == str(tmp_work)


# ──────────────────────────────────────────────────────────────────────
# Tests del NUEVO handler ``update_disp_comments_db_apply_<hw>``
# (sept-2026, fix del SOBREESCRIBIR entre handlers del batch).
#
# Diferencias vs el handler original (``update_disp_comments_db_<hw>``):
#   * NO hace export ni copytree propio.
#   * Asume que los ``.s7dcl``/``.s7res`` ya están en ``work_dir``
#     (preparados por el IT con export + copytree pre-batch).
#   * Abre/cierra su propia ``start_transaction`` /
#     ``end_transaction`` (mismo patrón que N_MAX/devices).
# ──────────────────────────────────────────────────────────────────────


def test_apply_handler_registrado() -> None:
    """Los 6 handlers ``update_disp_comments_db_apply_<hw>`` están en el registry."""
    expected = [
        "update_disp_comments_db_apply_ed",
        "update_disp_comments_db_apply_ea",
        "update_disp_comments_db_apply_sa",
        "update_disp_comments_db_apply_v",
        "update_disp_comments_db_apply_m",
        "update_disp_comments_db_apply_m_vf",
    ]
    for name in expected:
        assert name in COMMAND_REGISTRY, f"Falta handler {name!r} en COMMAND_REGISTRY"
        assert callable(COMMAND_REGISTRY[name]), f"{name!r} no es callable"


def test_apply_handler_no_hace_export(tmp_path: Path) -> None:
    """El handler NUEVO NO invoca ``export_block`` (asume que el IT ya
    preparó los archivos).
    """
    work_dir = tmp_path / "work"
    work_dir.mkdir()
    _write_minimal_s7dcl_s7res(work_dir)

    # El mock del fixture (autouse) sustituye ``export_block`` por un
    # MagicMock. Si el handler lo invocara, ``await_count > 0``.
    handler = COMMAND_REGISTRY["update_disp_comments_db_apply_ed"]

    # Mock del project para capturar start_transaction / end_transaction.
    import importlib
    worker_tia = importlib.import_module("core.infrastructure.tia.worker_tia")
    portal = MagicMock()
    project = MagicMock()
    portal.get_project.return_value = project
    project.start_transaction = MagicMock()
    project.end_transaction = MagicMock()

    handler(portal, MagicMock(), {
        "plc_name": "PLC_X",
        "db_name": "DB2000_ED",
        "db_array_name": "ED",
        "slot_map": {"0": "NO USAR"},
        "work_dir": str(work_dir),
        "target_folder": "2000_Dispositivos",
    })

    # El handler NO llama export_block (lo hace el IT pre-batch).
    COMMAND_REGISTRY["export_block"].assert_not_called()
    # Pero SÍ llama import_block (porque el updater modificó algo).
    COMMAND_REGISTRY["import_block"].assert_called_once()
    # Y abre/cierra su propia tx.
    project.start_transaction.assert_called_once()
    project.end_transaction.assert_called_once_with(rollback=False)


def test_apply_handler_falla_si_no_hay_s7dcl(tmp_path: Path) -> None:
    """Si el IT no preparó el ``.s7dcl`` (pre-export ausente), el handler
    lanza ``FileNotFoundError`` explicando el motivo.
    """
    work_dir = tmp_path / "work"
    work_dir.mkdir()
    # NO escribimos los archivos -> el handler debe fallar con un error
    # claro indicando que el IT debe hacer export + copytree primero.
    handler = COMMAND_REGISTRY["update_disp_comments_db_apply_ea"]
    with pytest.raises(FileNotFoundError, match="no se encontró '.s7dcl'"):
        handler(
            portal=MagicMock(),
            ts=MagicMock(),
            args={
                "plc_name":      "PLC_X",
                "db_name":       "DB2001_EA",
                "db_array_name": "EA",
                "slot_map":      {"0": "NO USAR"},
                "work_dir":      str(work_dir),
                "target_folder": "2000_Dispositivos",
            },
        )


def test_apply_handler_abre_y_cierra_tx_propia(tmp_path: Path) -> None:
    """El handler abre/cierra SU PROPIA ``start_transaction`` /
    ``end_transaction(rollback=False)``.

    Patrón equivalente a ``commit_disp_nmax_renames_online`` y
    ``commit_disp_devices_offline``: cada handler con su tx evita el
    rollback silencioso de TIA V21 al mezclar múltiples imports en la
    misma tx.
    """
    work_dir = tmp_path / "work"
    work_dir.mkdir()
    _write_minimal_s7dcl_s7res(work_dir, db_name="DB2010_V")

    portal = MagicMock()
    project = MagicMock()
    portal.get_project.return_value = project
    project.start_transaction = MagicMock()
    project.end_transaction = MagicMock()

    handler = COMMAND_REGISTRY["update_disp_comments_db_apply_v"]
    handler(portal, MagicMock(), {
        "plc_name": "PLC_X",
        "db_name": "DB2010_V",
        "db_array_name": "V",
        "slot_map": {"0": "NO USAR", "1": "Valvula 1"},
        "work_dir": str(work_dir),
        "target_folder": "2000_Dispositivos",
    })

    # Tx abierta y cerrada exactamente 1 vez.
    project.start_transaction.assert_called_once()
    project.end_transaction.assert_called_once_with(rollback=False)


def test_apply_handler_rollback_si_falla(tmp_path: Path) -> None:
    """Si ``import_block`` falla, el handler hace
    ``end_transaction(rollback=True)`` y re-lanza la excepción.
    """
    work_dir = tmp_path / "work"
    work_dir.mkdir()
    _write_minimal_s7dcl_s7res(work_dir, db_name="DB2015_M")

    # El fixture autouse mockea ``import_block`` como MagicMock(return_value=True).
    # Lo sobrescribimos para que lance una excepción.
    COMMAND_REGISTRY["import_block"] = MagicMock(
        side_effect=RuntimeError("TIA no disponible")
    )

    portal = MagicMock()
    project = MagicMock()
    portal.get_project.return_value = project
    project.start_transaction = MagicMock()
    project.end_transaction = MagicMock()

    handler = COMMAND_REGISTRY["update_disp_comments_db_apply_m"]
    with pytest.raises(RuntimeError, match="Rollback"):
        handler(portal, MagicMock(), {
            "plc_name": "PLC_X",
            "db_name": "DB2015_M",
            "db_array_name": "M",
            "slot_map": {"0": "NO USAR", "1": "Motor 1"},
            "work_dir": str(work_dir),
            "target_folder": "2000_Dispositivos",
        })

    # La tx se abrió y se cerró con rollback=True.
    project.start_transaction.assert_called_once()
    project.end_transaction.assert_called_once_with(rollback=True)
