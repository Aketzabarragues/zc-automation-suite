"""Tests del fix "commit fantasma" en PlcUserConstant (sept-2026).

TIA Portal V21 + Pythonnet puede fallar silenciosamente en
``set_property()``: el método retorna un ``int`` (código 0 = OK,
!= 0 = fallo: valor fuera de rango, proyecto protegido, etc.) pero
NO lanza excepción cuando rechaza la modificación. El código
anterior descartaba el retorno y confiaba en "no excepción = éxito",
lo que causaba "commit fantasma": el log del batch decía
"1 operación aplicada" pero el PLC quedaba sin modificar.

El operario consultó el manual oficial de TIA Scripting Python y
confirmó el patrón (§2.28): doble validación = validar el código
de retorno (debe ser 0) + re-leer con ``get_property()`` para
confirmar que el valor se consolidó. Si cualquiera falla, lanzar
``RuntimeError`` para que el batch wrapper haga rollback atómico.

Estrategia de los tests:
  - Mockeamos la jerarquía de objetos TIA (portal → project →
    plc → table → constant) con ``MagicMock`` para evitar el
    proceso real (requiere TIA + siemens_tia_scripting).
  - Tests 1-3 invocan ``_cmd_update_user_constant_value`` /
    ``_cmd_update_user_constant_name`` directamente, controlando
    el retorno de ``set_property`` y ``get_property`` en el
    constant mockeado.
  - Test 4 parchea ``COMMAND_REGISTRY`` con un op de un solo
    paso que retorna ``False`` y verifica que el batch wrapper
    aborte con ``end_transaction(rollback=True)``.
"""
from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest

from core.infrastructure.tia.worker_tia import (
    COMMAND_REGISTRY,
    _cmd_execute_transactional_batch,
    _cmd_update_user_constant_name,
    _cmd_update_user_constant_value,
)


# ─────────────────────────────────────────────────────────────────────
# Helpers de mock: construyen la jerarquía de objetos TIA que
# ``_cmd_*`` espera recorrer para llegar al ``constant``.
# ─────────────────────────────────────────────────────────────────────


def _make_constant_mock(
    *,
    name: str = "N_MAX_DISP_ED",
    set_property_return: int = 0,
    get_property_after: str = "10",
) -> MagicMock:
    """Crea un mock de PlcUserConstant con ``get_property``/``set_property``.

    Args:
        name: nombre que el constant reporta cuando se le pide
            ``get_property(name="Name")``. El handler de TIA lo
            usa para encontrar el constant a modificar.
        set_property_return: código de retorno que
            ``set_property(...)`` simula. 0 = OK, != 0 = rechazo
            silencioso de TIA.
        get_property_after: valor que ``get_property("Value")``
            retorna cuando se le pide la post-condición.
            - Si es igual al valor deseado, el handler acepta el
              cambio (caso normal de éxito).
            - Si difiere y ``set_property_return == 0``, simula
              un fallo silencioso de Pythonnet (TIA aceptó pero
              el valor no se consolidó).
    """
    # Capturamos en variables locales para evitar el shadowing
    # del parámetro ``name`` dentro del closure de ``fake_get_property``.
    const_name = name
    after_val = get_property_after

    def fake_get_property(**kwargs: Any) -> str:
        # El handler de TIA solo consulta ``get_property("Value")``
        # UNA vez (post-condición, tras ``set_property``). En la
        # búsqueda del constant por nombre usa ``get_property("Name")``.
        # Así que esta función solo necesita devolver el valor
        # "después" cuando le piden "Value" y el nombre del constant
        # cuando le piden "Name".
        prop = kwargs.get("name", "")
        if prop == "Value":
            return after_val
        if prop == "Name":
            return const_name
        return ""

    const = MagicMock()
    const.get_property.side_effect = fake_get_property
    const.set_property.return_value = set_property_return
    return const


def _make_tia_hierarchy(
    *,
    constant: MagicMock | None = None,
    table_name: str = "000_Config_Dispositivos",
    plc_name: str = "PLC1",
) -> tuple[MagicMock, MagicMock, MagicMock, MagicMock]:
    """Construye (portal, project, plc, table) con la jerarquía que ``_cmd_*`` espera.

    Si ``constant`` es None, crea uno por defecto con
    set_property_return=0, initial_value="10", name="N_MAX_DISP_ED".
    """
    if constant is None:
        constant = _make_constant_mock()

    table = MagicMock()
    table.get_name.return_value = table_name
    table.get_user_constants.return_value = [constant]

    plc = MagicMock()
    plc.get_name.return_value = plc_name
    plc.get_plc_tag_tables.return_value = [table]

    project = MagicMock()
    project.get_plcs.return_value = [plc]

    portal = MagicMock()
    portal.get_project.return_value = project

    return portal, project, plc, table


# ─────────────────────────────────────────────────────────────────────
# Tests de post-condición en update_user_constant_value
# ─────────────────────────────────────────────────────────────────────


class TestUpdateUserConstantValuePostcondition:
    """Doble validación en ``_cmd_update_user_constant_value`` (manual §2.28)."""

    def test_value_update_raises_when_set_property_returns_nonzero(self) -> None:
        """Si ``set_property`` retorna código != 0, lanzar ``RuntimeError``.

        Caso real: el operario intenta asignar un valor fuera del
        rango válido de TIA (p.ej. ``N_MAX = 999999`` cuando el
        PlcUserConstant está limitado a 0..255). Antes del fix,
        el batch cerraba con éxito y el PLC quedaba con el valor
        anterior. Ahora aborta con rollback.
        """
        constant = _make_constant_mock(
            set_property_return=5,  # 5 = "valor fuera de rango" (ejemplo)
        )
        portal, _, _, _ = _make_tia_hierarchy(constant=constant)

        with pytest.raises(RuntimeError, match="código de retorno"):
            _cmd_update_user_constant_value(
                portal,
                ts=MagicMock(),
                args={
                    "plc_name": "PLC1",
                    "table_name": "000_Config_Dispositivos",
                    "constant_name": "N_MAX_DISP_ED",
                    "new_value": 999999,
                },
            )

        # set_property SÍ se llamó (la validación ocurre DESPUÉS).
        constant.set_property.assert_called_once_with(
            name="Value", value="999999"
        )

    def test_value_update_raises_when_get_property_returns_stale(self) -> None:
        """Si ``set_property`` retorna 0 pero ``get_property`` retorna el valor viejo, abortar.

        Caso real: TIA V21 + Pythonnet reporta éxito (rc=0) pero
        el valor real en el proyecto es el anterior. Esto ocurre
        en ciertos proyectos protegidos o cuando el constant
        tiene un tipo declarado que el wrapper no detecta. Sin
        esta validación, el batch cierra con éxito mientras el PLC
        no se modifica.
        """
        constant = _make_constant_mock(
            set_property_return=0,
            get_property_after="10",  # stale: el valor viejo sigue ahí
        )
        portal, _, _, _ = _make_tia_hierarchy(constant=constant)

        with pytest.raises(RuntimeError, match="set_property retornó 0"):
            _cmd_update_user_constant_value(
                portal,
                ts=MagicMock(),
                args={
                    "plc_name": "PLC1",
                    "table_name": "000_Config_Dispositivos",
                    "constant_name": "N_MAX_DISP_ED",
                    "new_value": 42,
                },
            )

    def test_value_update_succeeds_when_value_consolidates(self) -> None:
        """Caso feliz: set_property=0, get_property retorna el valor nuevo -> OK.

        Sanity check: el fix NO rompe el happy path.
        """
        constant = _make_constant_mock(
            set_property_return=0,
            get_property_after="42",
        )
        portal, _, _, _ = _make_tia_hierarchy(constant=constant)

        result = _cmd_update_user_constant_value(
            portal,
            ts=MagicMock(),
            args={
                "plc_name": "PLC1",
                "table_name": "000_Config_Dispositivos",
                "constant_name": "N_MAX_DISP_ED",
                "new_value": 42,
            },
        )

        assert result is True


# ─────────────────────────────────────────────────────────────────────
# Tests de post-condición en update_user_constant_name
# ─────────────────────────────────────────────────────────────────────


class TestUpdateUserConstantNamePostcondition:
    """Doble validación en ``_cmd_update_user_constant_name`` (manual §2.28)."""

    def test_rename_raises_when_set_property_returns_nonzero(self) -> None:
        """Si ``set_property(Name)`` retorna código != 0, lanzar ``RuntimeError``.

        Caso real: el operario renombra ``N_MAX_DISP_ED`` a un
        nombre que choca con un PlcUserConstant ya existente
        (TIA retorna 0x80070057 = "nombre duplicado"). Antes del
        fix, el batch cerraba con éxito y el nombre anterior
        quedaba intacto. Ahora aborta con rollback.

        Para este test basta con que ``set_property`` retorne != 0:
        el handler lanza ``RuntimeError`` ANTES de la post-condición,
        así que el valor que ``get_property("Name")`` devuelva
        después es irrelevante (de hecho nunca se llama).
        """
        const = MagicMock()
        const.get_property.return_value = "N_MAX_DISP_ED"  # lo que sea
        const.set_property.return_value = 0x80070057  # código de error

        portal, _, _, _ = _make_tia_hierarchy(constant=const)

        with pytest.raises(RuntimeError, match="código de retorno"):
            _cmd_update_user_constant_name(
                portal,
                ts=MagicMock(),
                args={
                    "plc_name": "PLC1",
                    "table_name": "000_Config_Dispositivos",
                    "current_name": "N_MAX_DISP_ED",
                    "new_name": "N_MAX_DISP_ED_NEW",
                },
            )

    def test_rename_succeeds_when_name_consolidates(self) -> None:
        """Caso feliz: set_property(Name)=0, get_property(Name) retorna el nuevo -> OK.

        Sanity check: el fix NO rompe el happy path del rename.
        """
        # Para el rename, el handler hace 2 lecturas de "Name":
        #   1. Búsqueda en el bucle (debe == current_name).
        #   2. Post-condición (debe == new_name).
        # Usamos ``side_effect`` con una lista de respuestas.
        const = MagicMock()
        const.get_property.side_effect = ["OLD", "NEW"]
        const.set_property.return_value = 0

        portal, _, _, _ = _make_tia_hierarchy(constant=const)

        result = _cmd_update_user_constant_name(
            portal,
            ts=MagicMock(),
            args={
                "plc_name": "PLC1",
                "table_name": "000_Config_Dispositivos",
                "current_name": "OLD",
                "new_name": "NEW",
            },
        )

        assert result is True


# ─────────────────────────────────────────────────────────────────────
# Test de batch: abortar si una op retorna False
# ─────────────────────────────────────────────────────────────────────


class TestBatchAbortsWhenOpReturnsFalse:
    """El batch wrapper aborta con rollback si una op retorna ``False`` (defensa en profundidad)."""

    def test_batch_aborts_when_op_returns_false(self) -> None:
        """Mockeamos un op en el ``COMMAND_REGISTRY`` que retorna ``False`` y verificamos:

        1. El batch lanza ``RuntimeError`` con "retornó False".
        2. ``start_transaction`` se llamó UNA vez (al inicio del batch).
        3. ``end_transaction(rollback=True)`` se llamó UNA vez
           (rollback por la op que retornó False).
        4. ``end_transaction(rollback=False)`` NO se llamó
           (sería cerrar con éxito, lo que es lo que estamos
           defendiendo contra).
        """
        project = MagicMock()
        portal = MagicMock()
        portal.get_project.return_value = project

        # Op mockeado que retorna False (simulando un fallo no-excepción
        # de un sub-handler). El nombre NO debe estar en
        # _TRANSACTION_FORBIDDEN_COMMANDS.
        op_name = "fake_op_returns_false"

        def fake_op(portal: Any, ts: Any, args: dict[str, Any]) -> bool:
            return False

        # Patcheamos COMMAND_REGISTRY en el módulo y restauramos al final.
        orig_registry = COMMAND_REGISTRY.copy()
        COMMAND_REGISTRY[op_name] = fake_op
        try:
            with pytest.raises(RuntimeError, match="retornó False"):
                _cmd_execute_transactional_batch(
                    portal,
                    ts=MagicMock(),
                    args={
                        "undo_text": "Test op returns False",
                        "operations": [
                            {"command": op_name, "args": {}},
                        ],
                    },
                )
        finally:
            # Restauramos el registry original.
            COMMAND_REGISTRY.clear()
            COMMAND_REGISTRY.update(orig_registry)

        # start_transaction se llamó UNA vez.
        project.start_transaction.assert_called_once()
        # end_transaction(rollback=True) se llamó UNA vez.
        assert project.end_transaction.call_count == 1
        project.end_transaction.assert_called_once_with(rollback=True)
        # end_transaction(rollback=False) NUNCA se llamó: verificamos
        # que TODAS las llamadas a end_transaction usaron rollback=True
        # (es decir, ninguna cerró con éxito).
        for call_obj in project.end_transaction.call_args_list:
            assert call_obj.kwargs.get("rollback") is True, (
                f"Se llamó end_transaction con "
                f"rollback={call_obj.kwargs.get('rollback')!r}; se esperaba "
                f"rollback=True (el batch debe abortar y hacer rollback)."
            )


# ─────────────────────────────────────────────────────────────────────
# Sanity check final: el módulo importa limpio y los símbolos existen.
# ─────────────────────────────────────────────────────────────────────


def test_module_imports_and_symbols_exist() -> None:
    """Sanity: el módulo importa y los símbolos modificados existen en el registry.

    Detecta si alguien refactoriza y rompe accidentalmente las
    firmas o el registro. Complementa los tests funcionales
    anteriores.
    """
    assert "update_user_constant_value" in COMMAND_REGISTRY
    assert "update_user_constant_name" in COMMAND_REGISTRY
    assert "execute_transactional_batch" in COMMAND_REGISTRY
    assert COMMAND_REGISTRY["update_user_constant_value"] is _cmd_update_user_constant_value
    assert COMMAND_REGISTRY["update_user_constant_name"] is _cmd_update_user_constant_name
    assert COMMAND_REGISTRY["execute_transactional_batch"] is _cmd_execute_transactional_batch
