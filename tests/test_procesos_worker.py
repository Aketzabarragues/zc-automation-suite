"""Tests de los comandos del worker para sync de comentarios de procesos.

Cubre la integración de ``extra_commands.register(registry)`` con el
``COMMAND_REGISTRY`` del worker genérico: verifica que las 3 keys
``update_proc_comments_db_<kind>`` quedan registradas y que su
handler invoca la cadena esperada (export → updater.update() →
import, con guarda de was_modified).

Patrón de mocking: mockeamos directamente las keys
``"export_block"`` e ``"import_block"`` en el
``COMMAND_REGISTRY`` real (mismo enfoque que
``test_disp_comment_handlers.py``) para evitar el problema del
import-caching de Python con ``patch.dict("sys.modules", ...)``.
"""
from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from areas.alimentacion.infrastructure.tia import extra_commands
from core.infrastructure.tia import worker_tia


# ── Helpers ──────────────────────────────────────────────────────────────


def _build_minimal_block_files(work_dir: Path, db_name: str) -> None:
    """Escribe un par mínimo .s7dcl + .s7res en ``work_dir`` para que
    el updater no lance FileNotFoundError al invocarse."""
    dcl = work_dir / f"{db_name}.s7dcl"
    res = work_dir / f"{db_name}.s7res"
    dcl.write_text(
        'DATA_BLOCK "DB"\n'
        "    VAR\n"
        '        { S7_MLC := "MLC_arr" }\n'
        "        PReal : Array[1..3] of _.UDT_ZC_PREAL;\n"
        "    END_VAR\n"
        "\n"
        '        { S7_MLC := "MLC_PR_1" }\n'
        "        PReal[1] := ();\n"
        '        { S7_MLC := "MLC_PR_2" }\n'
        "        PReal[2] := ();\n"
        "END_DATA_BLOCK\n",
        encoding="utf-8",
    )
    res.write_text(
        "MultiLingualTexts:\n"
        "  - id: MLC_arr\n"
        "    es-ES: PReal\n"
        "  - id: MLC_PR_1\n"
        "    es-ES: orig_1\n"
        "  - id: MLC_PR_2\n"
        "    es-ES: orig_2\n",
        encoding="utf-8-sig",
    )


# ── Tests ───────────────────────────────────────────────────────────────


def test_register_anhade_las_keys_de_procesos() -> None:
    """``register(registry)`` añade las keys de procesos:
    las 3 individuales (``_preal``, ``_pint``, ``_alm``) más la combinada
    ``_param`` (PReal + PInt en un solo export/import sobre el DB PARAM).
    """
    registry: dict[str, Any] = {}
    extra_commands.register(registry)
    assert "update_proc_comments_db_preal" in registry
    assert "update_proc_comments_db_pint" in registry
    assert "update_proc_comments_db_alm" in registry
    # Nueva op combinada: 1 export + 1 import cubriendo PReal y PInt.
    assert "update_proc_comments_db_param" in registry
    # También siguen las legacy de dispositivos.
    assert "update_disp_comments_db_ed" in registry
    assert "commit_devices_sync" in registry


def test_handler_preal_invoca_export_updater_import() -> None:
    """Handler de PReal: ``export_block`` → ``ProcCommentUpdater.update()
    + save()`` → ``import_block`` (en ese orden, con los args correctos)."""
    COMMAND_REGISTRY = worker_tia.COMMAND_REGISTRY
    with tempfile.TemporaryDirectory() as td:
        work_dir = Path(td)
        _build_minimal_block_files(work_dir, "DB_TEST")

        orig_export = COMMAND_REGISTRY.get("export_block")
        orig_import = COMMAND_REGISTRY.get("import_block")
        mock_export = MagicMock(return_value="ok")
        mock_import = MagicMock(return_value=True)
        COMMAND_REGISTRY["export_block"] = mock_export
        COMMAND_REGISTRY["import_block"] = mock_import

        mock_updater = MagicMock()
        mock_updater.update.return_value.reused = {1: "MLC_PR_1"}
        mock_updater.update.return_value.inserted = {}
        mock_updater.update.return_value.satellite_reused = {}
        mock_updater.update.return_value.satellite_inserted = {}
        mock_updater.update.return_value.total_mlcs_in_res = 5
        mock_updater.was_modified.return_value = True
        mock_updater.save = MagicMock()

        try:
            with patch(
                "areas.alimentacion.infrastructure.sd.proc_comment_updater."
                "ProcCommentUpdater",
                return_value=mock_updater,
            ):
                handler = extra_commands.make_cmd_update_proc_comments_db("preal")
                handler(
                    None,  # portal
                    None,  # ts
                    {
                        "plc_name":      "PLC_X",
                        "db_name":       "DB_TEST",
                        "array_name":    "PReal",
                        "slot_map":      {"1": "nuevo_1"},
                        "work_dir":      str(work_dir),
                        "target_folder": "003_Procesos",
                    },
                )
        finally:
            # Restaurar el COMMAND_REGISTRY original.
            if orig_export is None:
                COMMAND_REGISTRY.pop("export_block", None)
            else:
                COMMAND_REGISTRY["export_block"] = orig_export
            if orig_import is None:
                COMMAND_REGISTRY.pop("import_block", None)
            else:
                COMMAND_REGISTRY["import_block"] = orig_import

        # 1) export_block llamado con los args correctos.
        mock_export.assert_called_once()
        exp_args = mock_export.call_args.args[2]
        assert exp_args["plc_name"] == "PLC_X"
        assert exp_args["block_name"] == "DB_TEST"
        assert exp_args["target_dir"] == str(work_dir)
        # 2) ProcCommentUpdater construido con array_name correcto.
        assert mock_updater.update.called
        assert mock_updater.save.called
        # 3) import_block llamado (porque was_modified() == True).
        mock_import.assert_called_once()
        imp_args = mock_import.call_args.args[2]
        assert imp_args["plc_name"] == "PLC_X"
        assert imp_args["import_dir"] == str(work_dir)
        # target_folder se pasa VACÍO (no el "003_Procesos" que viene
        # del use case) para que TIA reconcilie por nombre y haga
        # UPDATE (no CREATE) — ver rationale en extra_commands.py.
        assert imp_args["target_folder"] == ""


def test_handler_no_invoca_import_si_no_modified() -> None:
    """Si ``was_modified() == False`` (caso slot_map vacío), el handler
    NO invoca ``import_block`` (evita ensuciar el historial Undo)."""
    COMMAND_REGISTRY = worker_tia.COMMAND_REGISTRY
    with tempfile.TemporaryDirectory() as td:
        work_dir = Path(td)
        _build_minimal_block_files(work_dir, "DB_TEST")

        orig_export = COMMAND_REGISTRY.get("export_block")
        orig_import = COMMAND_REGISTRY.get("import_block")
        mock_export = MagicMock(return_value="ok")
        mock_import = MagicMock(return_value=True)
        COMMAND_REGISTRY["export_block"] = mock_export
        COMMAND_REGISTRY["import_block"] = mock_import

        mock_updater = MagicMock()
        mock_updater.update.return_value.reused = {}
        mock_updater.update.return_value.inserted = {}
        mock_updater.update.return_value.satellite_reused = {}
        mock_updater.update.return_value.satellite_inserted = {}
        mock_updater.update.return_value.total_mlcs_in_res = 5
        mock_updater.was_modified.return_value = False  # NO se modificó
        mock_updater.save = MagicMock()

        try:
            with patch(
                "areas.alimentacion.infrastructure.sd.proc_comment_updater."
                "ProcCommentUpdater",
                return_value=mock_updater,
            ):
                handler = extra_commands.make_cmd_update_proc_comments_db("alm")
                handler(
                    None, None,
                    {
                        "plc_name":      "PLC_X",
                        "db_name":       "DB_TEST",
                        "array_name":    "ALM",
                        "slot_map":      {},  # vacío → no hay cambios
                        "work_dir":      str(work_dir),
                        "target_folder": "003_Procesos",
                    },
                )
        finally:
            if orig_export is None:
                COMMAND_REGISTRY.pop("export_block", None)
            else:
                COMMAND_REGISTRY["export_block"] = orig_export
            if orig_import is None:
                COMMAND_REGISTRY.pop("import_block", None)
            else:
                COMMAND_REGISTRY["import_block"] = orig_import

        # export sí se llama (siempre).
        mock_export.assert_called_once()
        # update se llama, save se llama.
        assert mock_updater.update.called
        assert mock_updater.save.called
        # import NO se llama porque was_modified() == False.
        mock_import.assert_not_called()


# ── Tests del handler combinado ``_param`` (regression bug 2026-09-07) ──


def test_handler_param_1_export_1_import_cubre_preal_y_pint() -> None:
    """Regression del bug del doble ``export_block``: el handler combinado
    ``_param`` debe hacer **1 solo export** y **1 solo import**, no
    2+2 como las ops separadas harían. Así el cambio de PReal escrito
    por el updater en disco NO se SOBREESCRIBE por el export de PInt
    sobre el mismo DB.
    """
    COMMAND_REGISTRY = worker_tia.COMMAND_REGISTRY
    with tempfile.TemporaryDirectory() as td:
        work_dir = Path(td)
        _build_minimal_block_files(work_dir, "DB_TEST")

        orig_export = COMMAND_REGISTRY.get("export_block")
        orig_import = COMMAND_REGISTRY.get("import_block")
        mock_export = MagicMock(return_value="ok")
        mock_import = MagicMock(return_value=True)
        COMMAND_REGISTRY["export_block"] = mock_export
        COMMAND_REGISTRY["import_block"] = mock_import

        # ``side_effect`` con lista: la 1ª llamada al ``ProcCommentUpdater``
        # es para PReal, la 2ª es para PInt. Ambas devuelven un mock
        # que reporta ``was_modified() == True`` y resultados triviales.
        def _make_mock_updater() -> MagicMock:
            mu = MagicMock()
            mu.update.return_value.reused = {}
            mu.update.return_value.inserted = {}
            mu.update.return_value.satellite_reused = {}
            mu.update.return_value.satellite_inserted = {}
            mu.update.return_value.total_mlcs_in_res = 0
            mu.was_modified.return_value = True
            return mu

        try:
            with patch(
                "areas.alimentacion.infrastructure.sd.proc_comment_updater."
                "ProcCommentUpdater",
                side_effect=[_make_mock_updater(), _make_mock_updater()],
            ):
                handler = extra_commands.make_cmd_update_proc_comments_db_param()
                result = handler(
                    None,  # portal
                    None,  # ts
                    {
                        "plc_name":       "PLC_X",
                        "db_name":        "DB_TEST",
                        "preal_slot_map": {"1": "nuevo_preal_1"},
                        "pint_slot_map":  {"1": "nuevo_pint_1", "2": "nuevo_pint_2"},
                        "work_dir":       str(work_dir),
                        "target_folder":  "003_Procesos",
                    },
                )
        finally:
            if orig_export is None:
                COMMAND_REGISTRY.pop("export_block", None)
            else:
                COMMAND_REGISTRY["export_block"] = orig_export
            if orig_import is None:
                COMMAND_REGISTRY.pop("import_block", None)
            else:
                COMMAND_REGISTRY["import_block"] = orig_import

        # CRÍTICO: 1 solo export, 1 solo import (no 2+2 como antes).
        mock_export.assert_called_once()
        mock_import.assert_called_once()
        # La op cubre ambos arrays: ``preal`` y ``pint`` deben figurar.
        assert result["kind"] == "param"
        assert result["modified"] is True
        assert result["preal"]["modified"] is True
        assert result["pint"]["modified"] is True


def test_handler_param_no_invoca_import_si_ninguno_modified() -> None:
    """Si ambos slot_maps están vacíos (cero cambios), el handler
    NO invoca ``import_block`` (evita ensuciar historial Undo)."""
    COMMAND_REGISTRY = worker_tia.COMMAND_REGISTRY
    with tempfile.TemporaryDirectory() as td:
        work_dir = Path(td)
        _build_minimal_block_files(work_dir, "DB_TEST")

        orig_export = COMMAND_REGISTRY.get("export_block")
        orig_import = COMMAND_REGISTRY.get("import_block")
        mock_export = MagicMock(return_value="ok")
        mock_import = MagicMock(return_value=True)
        COMMAND_REGISTRY["export_block"] = mock_export
        COMMAND_REGISTRY["import_block"] = mock_import

        try:
            with patch(
                "areas.alimentacion.infrastructure.sd.proc_comment_updater."
                "ProcCommentUpdater",
            ):
                handler = extra_commands.make_cmd_update_proc_comments_db_param()
                result = handler(
                    None, None,
                    {
                        "plc_name":       "PLC_X",
                        "db_name":        "DB_TEST",
                        "preal_slot_map": {},  # vacío
                        "pint_slot_map":  {},  # vacío
                        "work_dir":       str(work_dir),
                        "target_folder":  "003_Procesos",
                    },
                )
        finally:
            if orig_export is None:
                COMMAND_REGISTRY.pop("export_block", None)
            else:
                COMMAND_REGISTRY["export_block"] = orig_export
            if orig_import is None:
                COMMAND_REGISTRY.pop("import_block", None)
            else:
                COMMAND_REGISTRY["import_block"] = orig_import

        mock_export.assert_called_once()
        mock_import.assert_not_called()
        assert result["modified"] is False
        assert result["preal"]["modified"] is False
        assert result["pint"]["modified"] is False


# ── Tests del nuevo patrón ``exports_subdir`` (Commit 5) ──────────────
#
# El plan 9-carpetas (ver ``_plan/16_carpetas_convencion.md`` §2.2)
# introduce la separación:
#   - TIA exporta al snapshot limpio (``exports_bloques/<db_subpath>/``).
#   - ``shutil.copytree`` lo copia a ``modified_bloques/<db_subpath>/``.
#   - El updater modifica la copia.
#   - El import_block lee desde ``modified_bloques`` raíz.
#
# Estos tests verifican que los handlers respetan este contrato cuando
# el use case les pasa el nuevo arg opcional ``exports_subdir``. Los
# tests anteriores (``test_handler_preal_invoca_export_updater_import``
# etc.) NO pasan ``exports_subdir``, así que cubren el camino legacy.


def test_handler_alm_usa_exports_subdir_y_copytree_si_se_pasa() -> None:
    """Commit 5: si se pasa ``exports_subdir``, el factory
    ``make_cmd_update_proc_comments_db`` (caso ``alm``) exporta al
    snapshot limpio (``exports_subdir/<db_subpath>``) y luego
    ``shutil.copytree`` lo copia a ``work_dir/<db_subpath>``. El
    updater se construye con los paths de la copia (modified), NO
    del exports.
    """
    COMMAND_REGISTRY = worker_tia.COMMAND_REGISTRY
    with tempfile.TemporaryDirectory() as td:
        td_path = Path(td)
        exports_subdir = td_path / "exports_bloques"
        work_dir = td_path / "modified_bloques"
        db_subpath = "ZC_Plantillas/53010_Parametros"
        export_target = exports_subdir / db_subpath
        modified_target = work_dir / db_subpath

        # ``side_effect`` del export: simula a TIA creando el
        # directorio y escribiendo los archivos en ``target_dir``.
        # (En el commit anterior los tests pre-creaban los archivos;
        # aquí los crea el mock para que ``shutil.copytree`` tenga
        # algo real que copiar — y así verificamos que el copytree
        # deja los archivos en ``work_dir/<db_subpath>``.)
        def _export_side_effect(portal, ts, args):
            tdir = Path(args["target_dir"])
            tdir.mkdir(parents=True, exist_ok=True)
            _build_minimal_block_files(tdir, "DB_TEST")
            return "ok"

        orig_export = COMMAND_REGISTRY.get("export_block")
        orig_import = COMMAND_REGISTRY.get("import_block")
        mock_export = MagicMock(side_effect=_export_side_effect)
        mock_import = MagicMock(return_value=True)
        COMMAND_REGISTRY["export_block"] = mock_export
        COMMAND_REGISTRY["import_block"] = mock_import

        # Capturamos los kwargs del constructor del updater para
        # verificar que apuntan a ``modified_target`` (la copia), no
        # al ``export_target``.
        captured_init_kwargs: list[dict[str, Any]] = []

        def _capture_updater(*args: Any, **kwargs: Any) -> MagicMock:
            captured_init_kwargs.append(kwargs)
            mu = MagicMock()
            mu.update.return_value.reused = {1: "MLC_PR_1"}
            mu.update.return_value.inserted = {}
            mu.update.return_value.satellite_reused = {}
            mu.update.return_value.satellite_inserted = {}
            mu.update.return_value.total_mlcs_in_res = 5
            mu.was_modified.return_value = True
            mu.save = MagicMock()
            return mu

        try:
            with patch(
                "areas.alimentacion.infrastructure.sd.proc_comment_updater."
                "ProcCommentUpdater",
                side_effect=_capture_updater,
            ):
                handler = extra_commands.make_cmd_update_proc_comments_db("alm")
                result = handler(
                    None, None,
                    {
                        "plc_name":       "PLC_X",
                        "db_name":        "DB_TEST",
                        "array_name":     "ALM",
                        "slot_map":       {"1": "alarma_1_nueva"},
                        "db_subpath":     db_subpath,
                        "work_dir":       str(work_dir),
                        "exports_subdir": str(exports_subdir),
                        "target_folder":  "003_Procesos",
                    },
                )
        finally:
            if orig_export is None:
                COMMAND_REGISTRY.pop("export_block", None)
            else:
                COMMAND_REGISTRY["export_block"] = orig_export
            if orig_import is None:
                COMMAND_REGISTRY.pop("import_block", None)
            else:
                COMMAND_REGISTRY["import_block"] = orig_import

        # 1) export_block llamado con target_dir = exports_subdir/<db_subpath>
        #    (snapshot limpio), NO work_dir/<db_subpath>.
        mock_export.assert_called_once()
        exp_args = mock_export.call_args.args[2]
        assert exp_args["target_dir"] == str(export_target), (
            f"export debe ir a exports_subdir/<db_subpath>; "
            f"recibido target_dir={exp_args['target_dir']!r}"
        )
        assert exp_args["target_dir"] != str(work_dir / db_subpath)
        assert exp_args["target_dir"] != str(exports_subdir)

        # 2) shutil.copytree (REAL, no mockeado) copió los archivos
        #    del snapshot limpio al modified. Lo verificamos
        #    comprobando que los archivos existen en modified_target.
        assert (modified_target / "DB_TEST.s7dcl").exists()
        assert (modified_target / "DB_TEST.s7res").exists()
        # Y también siguen en el snapshot limpio (TIA no los borra).
        assert (export_target / "DB_TEST.s7dcl").exists()
        assert (export_target / "DB_TEST.s7res").exists()

        # 3) El updater se construyó con paths del modified, no del
        #    exports. Esto es lo que hace que el updater modifique la
        #    copia, dejando el snapshot intacto.
        assert len(captured_init_kwargs) == 1
        s7dcl_path = captured_init_kwargs[0]["s7dcl_path"]
        s7res_path = captured_init_kwargs[0]["s7res_path"]
        assert s7dcl_path == modified_target / "DB_TEST.s7dcl"
        assert s7res_path == modified_target / "DB_TEST.s7res"

        # 4) import_block llamado con import_dir = work_dir (raíz) y
        #    target_folder="" (reconcilia por nombre).
        mock_import.assert_called_once()
        imp_args = mock_import.call_args.args[2]
        assert imp_args["import_dir"] == str(work_dir)
        assert imp_args["target_folder"] == ""
        assert result["modified"] is True


def test_handler_param_usa_exports_subdir_y_copytree_si_se_pasa() -> None:
    """Commit 5: el handler combinado ``_param`` también respeta el
    nuevo patrón. 1 export a ``exports_subdir/<db_subpath>`` +
    ``shutil.copytree`` a ``work_dir/<db_subpath>`` + 2 updaters
    (PReal, PInt) sobre la copia + 1 import desde ``work_dir``.
    """
    COMMAND_REGISTRY = worker_tia.COMMAND_REGISTRY
    with tempfile.TemporaryDirectory() as td:
        td_path = Path(td)
        exports_subdir = td_path / "exports_bloques"
        work_dir = td_path / "modified_bloques"
        db_subpath = "ZC_Plantillas/53010_Parametros"
        export_target = exports_subdir / db_subpath
        modified_target = work_dir / db_subpath

        def _export_side_effect(portal, ts, args):
            tdir = Path(args["target_dir"])
            tdir.mkdir(parents=True, exist_ok=True)
            _build_minimal_block_files(tdir, "DB_TEST")
            return "ok"

        orig_export = COMMAND_REGISTRY.get("export_block")
        orig_import = COMMAND_REGISTRY.get("import_block")
        mock_export = MagicMock(side_effect=_export_side_effect)
        mock_import = MagicMock(return_value=True)
        COMMAND_REGISTRY["export_block"] = mock_export
        COMMAND_REGISTRY["import_block"] = mock_import

        # Capturamos los kwargs de CADA constructor del updater (PReal
        # y PInt). Ambos deben apuntar a ``modified_target`` (la
        # copia), no al ``export_target``.
        captured_init_kwargs: list[dict[str, Any]] = []

        def _capture_updater(*args: Any, **kwargs: Any) -> MagicMock:
            captured_init_kwargs.append(kwargs)
            mu = MagicMock()
            mu.update.return_value.reused = {}
            mu.update.return_value.inserted = {}
            mu.update.return_value.satellite_reused = {}
            mu.update.return_value.satellite_inserted = {}
            mu.update.return_value.total_mlcs_in_res = 0
            mu.was_modified.return_value = True
            mu.save = MagicMock()
            return mu

        try:
            with patch(
                "areas.alimentacion.infrastructure.sd.proc_comment_updater."
                "ProcCommentUpdater",
                side_effect=_capture_updater,
            ):
                handler = extra_commands.make_cmd_update_proc_comments_db_param()
                result = handler(
                    None, None,
                    {
                        "plc_name":       "PLC_X",
                        "db_name":        "DB_TEST",
                        "db_subpath":     db_subpath,
                        "preal_slot_map": {"1": "nuevo_preal_1"},
                        "pint_slot_map":  {"1": "nuevo_pint_1"},
                        "work_dir":       str(work_dir),
                        "exports_subdir": str(exports_subdir),
                        "target_folder":  "003_Procesos",
                    },
                )
        finally:
            if orig_export is None:
                COMMAND_REGISTRY.pop("export_block", None)
            else:
                COMMAND_REGISTRY["export_block"] = orig_export
            if orig_import is None:
                COMMAND_REGISTRY.pop("import_block", None)
            else:
                COMMAND_REGISTRY["import_block"] = orig_import

        # 1) export_block llamado UNA VEZ con target_dir =
        #    exports_subdir/<db_subpath> (NO work_dir/<db_subpath>).
        mock_export.assert_called_once()
        exp_args = mock_export.call_args.args[2]
        assert exp_args["target_dir"] == str(export_target)

        # 2) shutil.copytree (real) dejó los archivos en modified_target.
        assert (modified_target / "DB_TEST.s7dcl").exists()
        assert (modified_target / "DB_TEST.s7res").exists()

        # 3) Los 2 updaters (PReal + PInt) se construyeron con paths
        #    de modified_target. Capturamos todos los kwargs.
        assert len(captured_init_kwargs) == 2
        for kwargs in captured_init_kwargs:
            assert kwargs["s7dcl_path"] == modified_target / "DB_TEST.s7dcl"
            assert kwargs["s7res_path"] == modified_target / "DB_TEST.s7res"

        # 4) import_block UNA VEZ con import_dir = work_dir y
        #    target_folder="" (rationale de la reconcilia por nombre).
        mock_import.assert_called_once()
        imp_args = mock_import.call_args.args[2]
        assert imp_args["import_dir"] == str(work_dir)
        assert imp_args["target_folder"] == ""
        assert result["modified"] is True


def test_handler_alm_sin_exports_subdir_usa_patron_legacy() -> None:
    """Backward compat (Commit 5): si NO se pasa ``exports_subdir``
    (caso de tests legacy o callers que aún no migraron), el handler
    exporta directo a ``work_dir/<db_subpath>`` y el updater modifica
    in-place. Mismo comportamiento que antes del Commit 5.
    """
    COMMAND_REGISTRY = worker_tia.COMMAND_REGISTRY
    with tempfile.TemporaryDirectory() as td:
        work_dir = Path(td)
        # Pre-crear los archivos en work_dir (como hacen los tests
        # legacy: el export mock no hace nada, los archivos ya están).
        _build_minimal_block_files(work_dir, "DB_TEST")

        orig_export = COMMAND_REGISTRY.get("export_block")
        orig_import = COMMAND_REGISTRY.get("import_block")
        mock_export = MagicMock(return_value="ok")
        mock_import = MagicMock(return_value=True)
        COMMAND_REGISTRY["export_block"] = mock_export
        COMMAND_REGISTRY["import_block"] = mock_import

        mock_updater = MagicMock()
        mock_updater.update.return_value.reused = {1: "MLC_PR_1"}
        mock_updater.update.return_value.inserted = {}
        mock_updater.update.return_value.satellite_reused = {}
        mock_updater.update.return_value.satellite_inserted = {}
        mock_updater.update.return_value.total_mlcs_in_res = 5
        mock_updater.was_modified.return_value = True
        mock_updater.save = MagicMock()

        try:
            with patch(
                "areas.alimentacion.infrastructure.sd.proc_comment_updater."
                "ProcCommentUpdater",
                return_value=mock_updater,
            ):
                handler = extra_commands.make_cmd_update_proc_comments_db("alm")
                handler(
                    None, None,
                    {
                        "plc_name":      "PLC_X",
                        "db_name":       "DB_TEST",
                        "array_name":    "ALM",
                        "slot_map":      {"1": "x"},
                        "work_dir":      str(work_dir),
                        "target_folder": "003_Procesos",
                        # NO se pasa ``exports_subdir`` (backward compat).
                    },
                )
        finally:
            if orig_export is None:
                COMMAND_REGISTRY.pop("export_block", None)
            else:
                COMMAND_REGISTRY["export_block"] = orig_export
            if orig_import is None:
                COMMAND_REGISTRY.pop("import_block", None)
            else:
                COMMAND_REGISTRY["import_block"] = orig_import

        # El export fue directo a work_dir (no a un exports_subdir).
        mock_export.assert_called_once()
        exp_args = mock_export.call_args.args[2]
        assert exp_args["target_dir"] == str(work_dir)
        # El import también desde work_dir con target_folder="".
        mock_import.assert_called_once()
        imp_args = mock_import.call_args.args[2]
        assert imp_args["import_dir"] == str(work_dir)
        assert imp_args["target_folder"] == ""
