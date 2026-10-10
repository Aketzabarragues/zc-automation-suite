"""Tests del FB ``FunctionEntidadesGenerarPreview``.

Cubre la logica del FB (validaciones, state machine, composicion del
response). Mockeamos el worker TIA (dispatch_async) y los parsers de
disco para que el test sea rapido y determinista.

Los tests de las funciones puras (compute_diff_entities, etc.) viven en
``tests/areas/alimentacion/helpers/test_entidades_generate_preview``.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from core.runtime.app_state import AppState
from areas.alimentacion.functions.function_entidades_generar_preview import (
    FunctionEntidadesGenerarPreview,
)


# ---------------------------------------------------------------------------
# Helpers de fixtures
# ---------------------------------------------------------------------------


class FakeEntidad:
    def __init__(self, numero: int, plc_tag: str, plc_comentario: str = "") -> None:
        self.numero = numero
        self.plc_tag = plc_tag
        self.plc_comentario = plc_comentario
        self.plc_name = "PLC_S1500"


def _make_config_manager() -> MagicMock:
    cm = MagicMock()
    cm.get_entidades_config.return_value = {
        "db_name":       "DB6_ENT",
        "db_array_name": "ENT",
        "tag_table":     "6_Entidades",
        "config_table":  "0_Config_Generales",
    }
    cm.get_global_config_table_name.return_value = "0_Config_Generales"
    cm.list_hw_types_active.return_value = []
    return cm


def _make_app_state(entidades: list | None = None, n_max_entidades: dict | None = None) -> AppState:
    """Crea un AppState con entidades + N_MAX_ENTIDAD.

    El cache activo vive en ``app_cache.excel_active_by_area[
    "alimentacion"]``. Lo inyectamos via ``excel_set_active``.
    """
    from core.runtime.excel_cache import excel_set_active
    from types import MappingProxyType
    from datetime import datetime, timezone

    from core.data.data_excel_cache import DataExcelCache
    from areas.alimentacion.state.area_cache import AlimentacionAreaCache

    state = AppState()
    state.app_cache.register_area("alimentacion", AlimentacionAreaCache())
    cache = DataExcelCache(
        excel_path="/x.xlsx",
        excel_mtime_ns=1,
        parsed_at=datetime(2026, 9, 1, tzinfo=timezone.utc),
        dispositivos={},
        n_max=type("NMax", (), {
            "por_plc": (
                type("Dim", (), {"extras": n_max_entidades or {},
                                 "n_max_entidades": 0})(),
            ),
            "to_api_dict": lambda self: {},
        })(),
        plcs=(),
        procesos=(),
        parametros_real=(),
        parametros_int=(),
        alarmas=(),
        entidades=tuple(entidades) if entidades else (),
        procesos_by_codigo=MappingProxyType({}),
        parametros_real_by_codigo=MappingProxyType({}),
        parametros_int_by_codigo=MappingProxyType({}),
    )
    excel_set_active(state.app_cache, "alimentacion", cache)
    return state


# ---------------------------------------------------------------------------
# Tests de on_start (validaciones)
# ---------------------------------------------------------------------------


def test_on_start_falla_si_config_manager_es_none() -> None:
    """Sin config_manager, ``on_start`` raise ``RuntimeError`` accionable."""
    fb = FunctionEntidadesGenerarPreview(nombre="test")
    with pytest.raises(RuntimeError, match="config_manager"):
        fb.on_start(plc_name="PLC_S1500")


def test_on_start_falla_si_tia_client_es_none() -> None:
    """Sin tia_client, ``on_start`` raise ``RuntimeError`` accionable."""
    fb = FunctionEntidadesGenerarPreview(
        nombre="test",
        config_manager=_make_config_manager(),
    )
    with pytest.raises(RuntimeError, match="tia_client"):
        fb.on_start(plc_name="PLC_S1500")


def test_on_start_falla_si_plc_name_vacio() -> None:
    """Sin plc_name, ``on_start`` raise ``ValueError`` accionable."""
    fb = FunctionEntidadesGenerarPreview(
        nombre="test",
        config_manager=_make_config_manager(),
        tia_client=MagicMock(),
        app_state=_make_app_state(),
    )
    with pytest.raises(ValueError, match="plc_name"):
        fb.on_start(plc_name="")


def test_on_start_crea_ctx_con_deps_inyectadas() -> None:
    """Happy path: deps inyectadas + plc_name -> EntidadesPreviewContext creado."""
    cm = _make_config_manager()
    tia = MagicMock()
    state = _make_app_state(entidades=[FakeEntidad(0, "AAA")])

    with patch(
        "areas.alimentacion.functions.function_entidades_generar_preview."
        "validate_plc_in_tia",
    ), patch(
        "areas.alimentacion.functions.function_entidades_generar_preview."
        "validate_plc_in_excel",
    ), patch(
        "areas.alimentacion.functions.function_entidades_generar_preview."
        "with_plc",
    ):
        fb = FunctionEntidadesGenerarPreview(
            nombre="test",
            config_manager=cm,
            tia_client=tia,
            app_state=state,
        )
        fb.on_start(plc_name="PLC_S1500")

    assert fb._plc_name == "PLC_S1500"
    assert fb._ctx is not None
    assert fb._ctx.plc_name == "PLC_S1500"
    assert fb._ctx.config_manager is cm
    assert fb._ctx.tia_client is tia
    assert fb._ctx.app_state is state


# ---------------------------------------------------------------------------
# Tests de on_finish (shape del result)
# ---------------------------------------------------------------------------


def test_on_finish_sin_ctx_devuelve_empty_result() -> None:
    """Sin ctx (error temprano), ``on_finish`` vuelca shape vacia valida."""
    fb = FunctionEntidadesGenerarPreview(
        nombre="test",
        config_manager=_make_config_manager(),
        tia_client=MagicMock(),
    )
    fb.on_finish()
    assert fb.result["precondiciones_ok"] is False
    assert fb.result["db_name"] == "DB6_ENT"
    assert fb.result["db_array_name"] == "ENT"
    assert fb.result["summary"]["total"] == 0


def test_on_finish_vuelca_ctx_result() -> None:
    """Con ctx, ``on_finish`` vuelca ``self.result = ctx.result``."""
    fb = FunctionEntidadesGenerarPreview(
        nombre="test",
        config_manager=_make_config_manager(),
        tia_client=MagicMock(),
        app_state=_make_app_state(),
    )
    fb._ctx = MagicMock()
    fb._ctx.plc_name = "PLC_S1500"
    fb._ctx.result = {
        "precondiciones_ok": True,
        "missing_blocks":    [],
        "db_name":           "DB6_ENT",
        "db_array_name":     "ENT",
        "tag_table":         "6_Entidades",
        "config_table":      "0_Config_Generales",
        "db_present":        True,
        "table_present":     True,
        "arrays":            {"ENT": []},
        "constants":         {"agregados": [], "eliminados": [],
                              "renombrados": [], "todos": []},
        "nmax":              {},
        "summary":           {"constants_agregados": 1,
                              "constants_eliminados": 0,
                              "constants_renombrados": 0,
                              "constants_sin_cambios": 0,
                              "comments_added": 0,
                              "comments_updated": 0,
                              "comments_unchanged": 0,
                              "total": 1},
        "warnings":          [],
    }
    fb.on_finish()
    assert fb.result["precondiciones_ok"] is True
    assert fb.result["summary"]["constants_agregados"] == 1


# ---------------------------------------------------------------------------
# Tests de run_step (dispatch + state machine)
# ---------------------------------------------------------------------------


def test_run_step_falla_si_ctx_no_inicializado() -> None:
    """``run_step`` sin ctx raise ``RuntimeError``."""
    fb = FunctionEntidadesGenerarPreview(
        nombre="test",
        config_manager=_make_config_manager(),
        tia_client=MagicMock(),
    )
    with pytest.raises(RuntimeError, match="EntidadesPreviewContext"):
        import asyncio
        asyncio.run(fb.run_step(0))


def test_run_step_falla_si_step_desconocido() -> None:
    """Step con nombre que no esta en STAGES raise ``ValueError``."""
    fb = FunctionEntidadesGenerarPreview(
        nombre="test",
        config_manager=_make_config_manager(),
        tia_client=MagicMock(),
        app_state=_make_app_state(),
    )
    fb._ctx = MagicMock()
    fb.steps = [{"nombre": "step inventado"}]
    with pytest.raises(ValueError, match="no esta en STAGES"):
        import asyncio
        asyncio.run(fb.run_step(0))


def test_run_step_stage_5_no_revienta_await_none() -> None:
    """Reproduce el bug del smoke del operario (oct-2026).

    Caso real: el FB llega al stage 5 (Componer respuesta). ``run_step``
    hace ``getattr(self, s_attr)`` y luego ``await handler()``. Si el
    handler esta declarado como ``def`` (sync), ``handler()`` retorna
    ``None`` y ``await None`` revienta con ``TypeError: object NoneType
    can't be used in 'await' expression``.

    Tras C.8 (``_stage_5_build_response`` es ``async def``), el handler
    retorna una corutina valida y ``run_step`` puede ejecutarlo.

    Verificacion en 2 partes:
      1. ``inspect.iscoroutinefunction`` del metodo declarado: si falla,
         el fix esta ausente.
      2. ``run_step(4)`` corre end-to-end con los 4 stages previos
         mockeados; el stage 5 se ejecuta real y compone
         ``self._ctx.result`` correctamente.
    """
    import asyncio
    import inspect

    assert inspect.iscoroutinefunction(
        FunctionEntidadesGenerarPreview._stage_5_build_response
    ), (
        "_stage_5_build_response debe ser ``async def``; "
        "si es ``def`` sync, run_step() explota con "
        "TypeError: object NoneType can't be used in 'await' expression"
    )

    from unittest.mock import patch as _patch
    fb = _make_fb_with_ctx()
    fb._ctx.db_name = "DB6_ENT"
    fb._ctx.db_array_name = "ENT"
    fb._ctx.tag_table = "6_Entidades"
    fb._ctx.config_table = "0_Config_Generales"
    fb._ctx.nmax_block = {
        "current": {}, "desired": {}, "todos": [],
        "summary": {"actualizar": 0, "sin_cambios": 0, "total": 0},
        "nmax_error": None,
    }
    fb._ctx.entities_block = {
        "base": {}, "desired": {}, "added": [], "removed": [],
        "renamed": {}, "missing_xml": False,
    }
    fb._ctx.comments_block = {
        "slots_tia": [], "current": {}, "desired": {},
        "added": [], "removed": [], "updated": [],
        "unchanged": [], "missing_xml": False,
    }
    fb._ctx.warnings = []

    with _patch.object(fb, "_stage_1_exportar", new=AsyncMock()), \
         _patch.object(fb, "_stage_2_compute_nmax", new=AsyncMock()), \
         _patch.object(fb, "_stage_3_compute_entidades", new=AsyncMock()), \
         _patch.object(fb, "_stage_4_compute_comentarios", new=AsyncMock()):
        # El stage 5 NO se mockea: queremos ejercitar el metodo real.
        result = asyncio.run(fb.run_step(4))

    assert "Componer respuesta" in result
    assert fb._ctx.result.get("db_name") == "DB6_ENT"


# ---------------------------------------------------------------------------
# Tests de stages individuales (con mocks)
# ---------------------------------------------------------------------------


def _make_fb_with_ctx() -> FunctionEntidadesGenerarPreview:
    """Crea un FB con deps inyectadas + ctx inicializado."""
    from pathlib import Path
    from areas.alimentacion.functions.function_entidades_generar_preview import (
        EntidadesPreviewContext,
    )
    fb = FunctionEntidadesGenerarPreview(
        nombre="test",
        config_manager=_make_config_manager(),
        tia_client=MagicMock(),
        app_state=_make_app_state(),
        build_cache=Path("/tmp/build_cache"),
    )
    fb._plc_name = "PLC_S1500"
    # Ctx real (dataclass) para que las mutaciones (warnings, blocks)
    # persistan correctamente. MagicMock auto-generado rompe esto.
    fb._ctx = EntidadesPreviewContext(
        plc_name="PLC_S1500",
        tia_client=fb._tia_client,
        config_manager=fb._config,
        app_state=fb._state,
        build_cache_root=Path("/tmp/build_cache"),
    )
    return fb


def test_stage_1_exportar_llama_dispatch_async() -> None:
    """Stage 1 llama a ``dispatch_async`` para ``export_plc_tags_xml`` + ``export_block``."""
    from pathlib import Path
    fb = _make_fb_with_ctx()

    with patch(
        "areas.alimentacion.functions.function_entidades_generar_preview."
        "dispatch_async",
        new=AsyncMock(return_value={"ok": True}),
    ) as mock_dispatch, patch(
        "areas.alimentacion.helpers.layout.build_cache.build_cache"
    ) as mock_layout:
        mock_layout.return_value.entidades.preview_config = Path("/tmp/cfg")
        mock_layout.return_value.entidades.preview_disp = Path("/tmp/disp")
        mock_layout.return_value.entidades.preview_bloques = Path("/tmp/blq")

        import asyncio
        asyncio.run(fb._stage_1_exportar())

    # 2 dispatchs: export_plc_tags_xml + export_block.
    assert mock_dispatch.call_count == 2
    first_call_args = mock_dispatch.call_args_list[0].args
    second_call_args = mock_dispatch.call_args_list[1].args
    assert first_call_args[1] == "export_plc_tags_xml"
    assert second_call_args[1] == "export_block"
    # Sin warnings en happy path.
    assert fb._ctx.warnings == []


def test_stage_1_exportar_si_worker_falla_sigue_con_warnings() -> None:
    """Si el worker TIA falla (None), el FB sigue + acumula warnings.

    Caso real: operario aun no creo DB6_ENT en TIA. El preview debe
    degradarse gracioso y NO abortar con TypeError.
    """
    from pathlib import Path
    fb = _make_fb_with_ctx()

    # Mockeamos dispatch_async para que retorne None (simula
    # dispatch_failed del worker TIA: TIA no encuentra el bloque).
    with patch(
        "areas.alimentacion.functions.function_entidades_generar_preview."
        "dispatch_async",
        new=AsyncMock(return_value=None),
    ), patch(
        "areas.alimentacion.helpers.layout.build_cache.build_cache"
    ) as mock_layout:
        mock_layout.return_value.entidades.preview_config = Path("/tmp/cfg")
        mock_layout.return_value.entidades.preview_disp = Path("/tmp/disp")
        mock_layout.return_value.entidades.preview_bloques = Path("/tmp/blq")

        import asyncio
        # NO debe lanzar TypeError.
        asyncio.run(fb._stage_1_exportar())

    # 2 warnings acumulados (tags + block).
    assert len(fb._ctx.warnings) == 2
    assert "export_plc_tags_xml fallo" in fb._ctx.warnings[0]
    assert "DB6_ENT" in fb._ctx.warnings[1]
    assert "no encontrado" in fb._ctx.warnings[1]


def test_stage_2_compute_nmax_usa_n_max_del_cache() -> None:
    """Stage 2 extrae ``N_MAX_ENTIDAD`` del cache y lo pasa al helper."""
    from pathlib import Path
    fb = _make_fb_with_ctx()
    fb._state = _make_app_state(n_max_entidades={"N_MAX_ENTIDAD": 5})
    fb._ctx.app_state = fb._state
    fb._ctx.preview_disp_dir = Path("/tmp/disp")

    fake_diff = MagicMock()
    fake_diff.current = {"N_MAX_ENTIDAD": 5}
    fake_diff.desired = {"N_MAX_ENTIDAD": 5}
    fake_diff.todos = [{"name": "N_MAX_ENTIDAD", "status": "sin_cambios",
                        "actual": 5, "nuevo": 5}]
    fake_diff.summary = {"actualizar": 0, "sin_cambios": 1, "total": 1}
    fake_diff.missing_xml = False

    with patch(
        "areas.alimentacion.helpers.entidades.entidades_generate_preview."
        "compute_nmax_diff_entidades",
        return_value=fake_diff,
    ):
        import asyncio
        asyncio.run(fb._stage_2_compute_nmax())

    assert fb._ctx.nmax_block["current"] == {"N_MAX_ENTIDAD": 5}
    assert fb._ctx.nmax_block["summary"]["sin_cambios"] == 1


def test_stage_5_build_response_compose_shape() -> None:
    """Stage 5 compone la shape legacy con arrays + constants + nmax + summary."""
    from pathlib import Path
    from areas.alimentacion.helpers.entidades.entidades_generate_preview import (
        DiffEntities,
        DiffComments,
    )

    fb = _make_fb_with_ctx()
    fb._ctx.db_name = "DB6_ENT"
    fb._ctx.db_array_name = "ENT"
    fb._ctx.tag_table = "6_Entidades"
    fb._ctx.config_table = "0_Config_Generales"
    fb._ctx.nmax_block = {
        "current":   {"N_MAX_ENTIDAD": 5},
        "desired":   {"N_MAX_ENTIDAD": 5},
        "todos":     [{"name": "N_MAX_ENTIDAD", "status": "sin_cambios",
                        "actual": 5, "nuevo": 5}],
        "summary":   {"actualizar": 0, "sin_cambios": 1, "total": 1},
        "nmax_error": None,
    }
    fb._ctx.entities_block = {
        "base":        {"AAA": 1},
        "desired":     {"AAA": 1, "BBB": 2},
        "added":       ["BBB"],
        "removed":     [],
        "renamed":     {},
        "missing_xml": False,
    }
    fb._ctx.entities_ops = [
        {"kind": "add", "plc_tag": "BBB", "value_excel": 2,
         "comment_excel": None},
    ]
    fb._ctx.comments_block = {
        "slots_tia":   [0],
        "current":     {0: "old"},
        "desired":     {0: "new"},
        "added":       [],
        "removed":     [],
        "updated":     [0],
        "unchanged":   [],
        "missing_xml": False,
    }
    fb._ctx.warnings = []

    import asyncio
    asyncio.run(fb._stage_5_build_response())

    r = fb._ctx.result
    assert r["precondiciones_ok"] is True
    assert r["db_name"] == "DB6_ENT"
    assert r["table_present"] is True
    assert r["db_present"] is True
    assert len(r["constants"]["agregados"]) == 1
    assert r["constants"]["agregados"][0]["plc_tag"] == "BBB"
    assert r["arrays"]["ENT"][0]["slot"] == 0
    assert r["arrays"]["ENT"][0]["status"] == "renombrar"
    assert r["summary"]["constants_agregados"] == 1
    assert r["summary"]["comments_updated"] == 1
    assert r["nmax"]["summary"]["sin_cambios"] == 1
    # Lista unica de ops a aplicar (5 pasadas de Aketza).
    ops = r["ops"]
    assert len(ops) >= 1
    for op in ops:
        assert "kind" in op
        assert op["kind"] in {"delete", "add", "rename", "update_comment"}


def test_stage_5_build_response_stages_previos_fallaron() -> None:
    """Si entities_block o comments_block son None, devuelve shape vacio."""
    fb = _make_fb_with_ctx()
    fb._ctx.entities_block = None
    fb._ctx.comments_block = None

    import asyncio
    asyncio.run(fb._stage_5_build_response())

    assert fb._ctx.result["precondiciones_ok"] is False
    assert "Stages previos no completaron" in fb._ctx.result["missing_blocks"][0]


def test_stage_5_build_response_missing_xml_table() -> None:
    """``missing_xml`` en tabla de entidades -> ``table_present: False``."""
    from pathlib import Path
    fb = _make_fb_with_ctx()
    fb._ctx.db_name = "DB6_ENT"
    fb._ctx.db_array_name = "ENT"
    fb._ctx.tag_table = "6_Entidades"
    fb._ctx.config_table = "0_Config_Generales"
    fb._ctx.nmax_block = {"current": {}, "desired": {}, "todos": [],
                           "summary": {"actualizar": 0, "sin_cambios": 0, "total": 0},
                           "nmax_error": "XML ausente"}
    fb._ctx.entities_block = {
        "base":        {},
        "desired":     {"AAA": 1},
        "added":       ["AAA"],
        "removed":     [],
        "renamed":     {},
        "missing_xml": True,
    }
    fb._ctx.comments_block = {
        "slots_tia":   [],
        "current":     {},
        "desired":     {},
        "added":       [],
        "removed":     [],
        "updated":     [],
        "unchanged":   [],
        "missing_xml": False,
    }
    fb._ctx.warnings = []

    import asyncio
    asyncio.run(fb._stage_5_build_response())

    assert fb._ctx.result["table_present"] is False
    assert fb._ctx.result["db_present"] is True


# ---------------------------------------------------------------------------
# Tests de STAGES (tabla declarativa)
# ---------------------------------------------------------------------------


def test_stages_match_steps_names() -> None:
    """Cada ``STAGES[i].nombre_step`` debe existir en ``self.steps[i]['nombre']``."""
    fb = FunctionEntidadesGenerarPreview(
        nombre="test",
        config_manager=_make_config_manager(),
        tia_client=MagicMock(),
    )
    assert len(fb.STAGES) == len(fb.steps)
    for idx, (st_idx, st_nombre, st_attr) in enumerate(fb.STAGES):
        assert fb.steps[idx]["nombre"] == st_nombre, (
            f"stage {st_idx} ({st_nombre!r}) != "
            f"steps[{idx}].nombre ({fb.steps[idx]['nombre']!r})"
        )
        assert hasattr(fb, st_attr), (
            f"STAGES declara {st_attr!r} pero el FB no lo expone"
        )


def test_step_timeout_es_60_segundos() -> None:
    """``STEP_TIMEOUT_S = 60.0`` (export bulk + parse)."""
    assert FunctionEntidadesGenerarPreview.STEP_TIMEOUT_S == 60.0