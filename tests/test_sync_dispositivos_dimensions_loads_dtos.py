"""Tests de regresión: ``SyncDispositivosDimensionsUseCase`` carga DTOs + dimensiones.

Bug original (FIX preflight): la versión anterior solo llamaba
``extraer_dimensiones`` y dejaba ``AppState.dispositivos_*`` vacío.
Por tanto, el flujo MCP (``tia_sync_dispositivos_dimensions_from_excel``)
reportaba "Excel cargado" pero las 6 listas de dispositivos quedaban
vacías, lo que producía preflights con 0 cambios aun teniendo
dispositivos en el Excel.

Estrategia: mockear el ``AlimentacionExcelParser`` para que devuelva
dimensiones + DTOs sintéticos, ejecutar ``.execute()`` y verificar
que ``AppState`` queda poblado correctamente.
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from application.state import AppState, get_app_state, reset_app_state
from application.use_cases.sync_dispositivos_dimensions import (
    SyncDispositivosDimensionsUseCase,
)
from core.alimentacion.models.dispositivos import (
    DimensionesDispositivos,
    DispED,
    DispV,
)


@pytest.fixture
def fresh_app_state(monkeypatch: pytest.MonkeyPatch) -> AppState:
    """Garantiza un ``AppState`` vacío antes de cada test."""
    reset_app_state()
    yield get_app_state()
    reset_app_state()


@pytest.fixture
def mock_parser_with_data() -> MagicMock:
    """Parser mock que devuelve DTOs + dimensiones sintéticos."""
    parser = MagicMock()

    dispositivos_v = [
        DispV(
            numero=1, plc_tag="V_VA_101", plc_comentario="", descripcion="",
            uid="V_001", tag=0, fat=0, s_byte=0, s_bit=0,
            rr_byte=0, rr_bit=0, rt_byte=0, rt_bit=0,
            gr_alarma="", cuadro="", observaciones="", plc_tipo="int",
            plc_index=1, hmi_index=1, hmi_texto="VA-101",
            cfg_habilitar="", cfg_byteretornoreposo="",
            cfg_bitretornoreposo="", cfg_byteretornotrabajo="",
            cfg_bitretornotrabajo="", cfg_byteactivacion="",
            cfg_bitactivacion="", cfg_habitreposo="",
            cfg_habitrtrabajo="", cfg_grupoalarma="",
            comentario_db="",
        ),
        DispV(
            numero=2, plc_tag="V_VA_102", plc_comentario="", descripcion="",
            uid="V_002", tag=0, fat=0, s_byte=0, s_bit=0,
            rr_byte=0, rr_bit=0, rt_byte=0, rt_bit=0,
            gr_alarma="", cuadro="", observaciones="", plc_tipo="int",
            plc_index=2, hmi_index=2, hmi_texto="VA-102",
            cfg_habilitar="", cfg_byteretornoreposo="",
            cfg_bitretornoreposo="", cfg_byteretornotrabajo="",
            cfg_bitretornotrabajo="", cfg_byteactivacion="",
            cfg_bitactivacion="", cfg_habitreposo="",
            cfg_habitrtrabajo="", cfg_grupoalarma="",
            comentario_db="",
        ),
    ]
    dispositivos_ed = [
        DispED(
            numero=1, plc_tag="ED_001", plc_comentario="", descripcion="",
            uid="ED_001", tag=0, fat=0, e_byte=0, e_bit=0,
            gr_alarma="", cuadro="", observaciones="", plc_tipo="int",
            plc_index=1, hmi_index=1, hmi_texto="E1",
            cfg_habilitar="", cfg_byte_entrada="", cfg_bit_entrada="",
            cfg_grupo_alarma="", comentario_db="",
        ),
    ]
    parser.extraer_dtos = MagicMock(return_value={
        "DispED": dispositivos_ed,
        "DispV": dispositivos_v,
    })
    parser.extraer_dimensiones = MagicMock(
        return_value=DimensionesDispositivos(
            num_disp_ed=5, num_disp_ea=0, num_disp_sa=0,
            num_disp_v=2, num_disp_m=0, num_disp_m_vf=0,
        )
    )
    return parser


def test_execute_loads_dtos_and_dimensiones(
    fresh_app_state: AppState, mock_parser_with_data: MagicMock, tmp_path,
) -> None:
    """``execute()`` carga DTOs **y** dimensiones en ``AppState``.

    Regresión del bug principal: antes solo cargaba dimensiones, las
    listas ``dispositivos_*`` quedaban vacías y la preflight daba 0
    cambios aunque el Excel tuviese dispositivos.
    """
    fake_excel = tmp_path / "fake.xlsx"
    fake_excel.write_bytes(b"")  # No se lee (mockeamos el parser).

    use_case = SyncDispositivosDimensionsUseCase(
        excel_parser=mock_parser_with_data,
        state=fresh_app_state,
    )
    result = use_case.execute.__class__.__call__ if False else None
    # Llamada síncrona al execute (el método no es async).
    import asyncio
    result = asyncio.run(use_case.execute(str(fake_excel)))

    # 1) AppState.dispositivos_v tiene 2 elementos.
    assert len(fresh_app_state.dispositivos_v) == 2
    assert fresh_app_state.dispositivos_v[0].plc_tag == "V_VA_101"
    assert fresh_app_state.dispositivos_v[0].numero == 1
    assert fresh_app_state.dispositivos_v[1].plc_tag == "V_VA_102"
    assert fresh_app_state.dispositivos_v[1].numero == 2

    # 2) AppState.dispositivos_ed tiene 1 elemento.
    assert len(fresh_app_state.dispositivos_ed) == 1
    assert fresh_app_state.dispositivos_ed[0].plc_tag == "ED_001"

    # 3) Listas no presentes en el Excel quedan VACÍAS (no nulas).
    assert fresh_app_state.dispositivos_ea == []
    assert fresh_app_state.dispositivos_sa == []
    assert fresh_app_state.dispositivos_m == []
    assert fresh_app_state.dispositivos_m_vf == []

    # 4) AppState.dimensiones está poblado.
    assert fresh_app_state.dimensiones.num_disp_v == 2
    assert fresh_app_state.dimensiones.num_disp_ed == 5

    # 5) El resultado expone el resumen.
    assert result["success"] is True
    assert result["dispositivos"]["DispV"] == 2
    assert result["dispositivos"]["DispED"] == 1
    assert result["dimensiones"]["num_disp_v"] == 2


def test_execute_order_dtos_before_dimensiones(
    fresh_app_state: AppState, mock_parser_with_data: MagicMock, tmp_path,
) -> None:
    """El orden de carga es **DTOs primero, dimensiones después**.

    Esto unifica el criterio con el router web
    ``/api/v1/excel/upload`` y evita abrir dos workbooks
    simultáneos sobre el mismo ``.xlsx``.
    """
    fake_excel = tmp_path / "fake.xlsx"
    fake_excel.write_bytes(b"")

    call_order: list[str] = []
    dtos_return = mock_parser_with_data.extraer_dtos.return_value
    dims_return = mock_parser_with_data.extraer_dimensiones.return_value

    def spy_dtos(*a, **kw):
        call_order.append("dtos")
        return dtos_return

    def spy_dims(*a, **kw):
        call_order.append("dimensiones")
        return dims_return

    mock_parser_with_data.extraer_dtos.side_effect = spy_dtos
    mock_parser_with_data.extraer_dimensiones.side_effect = spy_dims

    use_case = SyncDispositivosDimensionsUseCase(
        excel_parser=mock_parser_with_data,
        state=fresh_app_state,
    )
    import asyncio
    asyncio.run(use_case.execute(str(fake_excel)))

    assert call_order == ["dtos", "dimensiones"]


def test_execute_raises_if_excel_missing(
    fresh_app_state: AppState, mock_parser_with_data: MagicMock, tmp_path,
) -> None:
    """Si la ruta no existe, ``FileNotFoundError`` con mensaje claro."""
    use_case = SyncDispositivosDimensionsUseCase(
        excel_parser=mock_parser_with_data,
        state=fresh_app_state,
    )
    import asyncio
    with pytest.raises(FileNotFoundError, match="no existe"):
        asyncio.run(use_case.execute(str(tmp_path / "nope.xlsx")))
