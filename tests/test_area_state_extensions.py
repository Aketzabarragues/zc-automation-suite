"""Tests del extension point ``contributes_state_extensions`` (PR 2).

Cubre la instalación de las 6 properties legacy
``dispositivos_ed/ea/sa/v/m/m_vf`` sobre la CLASE ``AppState`` que
el área de alimentación aporta vía su ``AreaSpec``.

Estos tests verifican que:
  - ``install()`` pega las 6 properties a la CLASE (no a la instancia).
  - Las properties delegan en ``get_devices`` / ``set_devices``.
  - El área está registrada en el ``AreaRegistry`` con los hooks
    esperados tras PR 2 (``state_extensions``, ``config_defaults``,
    ``catalog``).
  - El Singleton del ``AppState`` activa las properties automáticamente
    (vía ``get_app_state()``).
"""
from __future__ import annotations

import pytest

from core.application.area_registry import AreaRegistry, AreaSpec
from core.application.state import AppState, get_app_state


# ── Registry: el área de alimentación se autoregistra ─────────────────


def test_alimentacion_area_is_registered() -> None:
    """El área de alimentación está en el ``AreaRegistry`` tras PR 2."""
    specs = AreaRegistry.discover().all()
    ids = {s.id for s in specs}
    assert "alimentacion" in ids


def test_alimentacion_spec_has_expected_hooks() -> None:
    """La ``AreaSpec`` de alimentación tiene los hooks esperados tras PR 2..6.

    PR 2 implementó ``contributes_state_extensions``,
    ``contributes_config_defaults`` y ``contributes_catalog``.
    PR 3 implementó ``contributes_tia_commands`` (los 6 handlers
    ``update_disp_comments_db_*`` aportados al ``COMMAND_REGISTRY``
    del worker OT desde ``infrastructure/tia/extra_commands.py``).
    PR 4 implementó ``contributes_routers`` (3 routers web movidos
    desde el shell a ``areas/alimentacion/interfaces/web/`` y
    descubiertos vía ``AreaRegistry.for_each("contributes_routers", app=app)``).
    PR 5 implementó ``contributes_frontend_manifest`` (manifest del
    área para la SPA).
    PR 6 implementó ``contributes_mcp_tools`` (4 tools MCP que dan
    paridad con los endpoints web del área: sync preview/commit,
    aplicar comentarios, upload excel).

    Este test se actualiza por PR: cada vez que un PR añade un hook
    nuevo, lo promovemos de ``is None`` a ``is not None``. Cuando
    los 7 hooks estén implementados, el bloque final desaparece.
    """
    spec = AreaRegistry.discover().get("alimentacion")
    assert spec is not None
    assert spec.id == "alimentacion"
    assert spec.label == "Área de alimentación"
    assert spec.config_block == "alimentacion"
    # Implementados en PR 2
    assert spec.contributes_state_extensions is not None
    assert spec.contributes_config_defaults is not None
    assert spec.contributes_catalog is not None
    # Implementado en PR 3
    assert spec.contributes_tia_commands is not None
    # Implementado en PR 4
    assert spec.contributes_routers is not None
    # Implementado en PR 5
    assert spec.contributes_frontend_manifest is not None
    # Implementado en PR 6
    assert spec.contributes_mcp_tools is not None


# ── state_extensions.install: pega las 6 properties a la CLASE ────────


@pytest.fixture
def fresh_state() -> AppState:
    """Una instancia fresca de ``AppState`` (no el Singleton global)."""
    return AppState()


def test_install_attaches_six_properties_to_class(fresh_state: AppState) -> None:
    """``install`` pega (o re-pega) 6 properties a la CLASE ``AppState``.

    Nota: ``install()`` es idempotente — reasignar ``property`` sobre
    la clase no la duplica, solo la sustituye. Esto significa que
    podemos llamarlo múltiples veces (p. ej. desde distintos tests
    o desde ``get_app_state()``) sin efectos colaterales.

    En este test verificamos que las 6 properties están presentes
    en la CLASE tras invocar ``install`` (sea la primera vez o una
    posterior). Verificamos también que la ``property`` retornada es
    un ``property`` descriptor (no un valor estático).
    """
    from areas.alimentacion.application.state_extensions import install

    install(fresh_state)
    for attr in (
        "dispositivos_ed", "dispositivos_ea", "dispositivos_sa",
        "dispositivos_v", "dispositivos_m", "dispositivos_m_vf",
    ):
        assert hasattr(AppState, attr), f"AppState.{attr} falta tras install"
        # La entry de la clase debe ser un descriptor ``property``.
        assert isinstance(
            getattr(AppState, attr, None), property
        ), f"AppState.{attr} no es ``property``"


def test_install_makes_getter_delegate_to_get_devices(
    fresh_state: AppState,
) -> None:
    """``state.dispositivos_<hw>`` lee de ``get_devices(hw)``."""
    from areas.alimentacion.application.state_extensions import install

    install(fresh_state)
    fresh_state.set_devices("ed", [{"uid": "ED_001"}, {"uid": "ED_002"}])
    assert fresh_state.dispositivos_ed == [
        {"uid": "ED_001"}, {"uid": "ED_002"}
    ]


def test_install_makes_setter_delegate_to_set_devices(
    fresh_state: AppState,
) -> None:
    """``state.dispositivos_<hw> = [...]`` actualiza ``get_devices(hw)``."""
    from areas.alimentacion.application.state_extensions import install

    install(fresh_state)
    fresh_state.dispositivos_ea = [{"uid": "EA_001"}]
    # El setter debe haber escrito en ``_dispositivos["ea"]`` vía
    # ``set_devices`` (defensa: ver tests de ``get_devices`` abajo).
    assert fresh_state.get_devices("ea") == [{"uid": "EA_001"}]
    # Y la property de lectura refleja el cambio.
    assert fresh_state.dispositivos_ea == [{"uid": "EA_001"}]


def test_install_returns_empty_list_for_unset_hw(
    fresh_state: AppState,
) -> None:
    """Las 6 properties retornan ``[]`` si el hw aún no se asignó."""
    from areas.alimentacion.application.state_extensions import install

    install(fresh_state)
    assert fresh_state.dispositivos_ed == []
    assert fresh_state.dispositivos_ea == []
    assert fresh_state.dispositivos_sa == []
    assert fresh_state.dispositivos_v == []
    assert fresh_state.dispositivos_m == []
    assert fresh_state.dispositivos_m_vf == []


def test_install_propagates_to_existing_and_future_instances() -> None:
    """Las properties se pegan a la CLASE: afectan a todas las instancias.

    Nota: el ``install()`` es idempotente — reasignar ``property``
    sobre la clase no la duplica, solo la sustituye. Tras la
    primera invocación (p. ej. por ``get_app_state()`` en otro test
    o en el setup de pytest), las properties ya están en la clase.
    Este test verifica el comportamiento estable: tras invocar
    ``install()``, una nueva instancia ve las properties y comparte
    estado con otra instancia vía el ``_dispositivos`` interno.
    """
    from areas.alimentacion.application.state_extensions import install

    # Forzar install (idempotente: solo re-asigna ``property``).
    install(AppState())

    # Tras install: la CLASE tiene las properties. Dos instancias
    # distintas ven la misma property (herencia de clase) y comparten
    # el ``_dispositivos`` subyacente porque ``AppState.__init__``
    # crea un dict NUEVO por instancia — son dos backends distintos.
    inst_a = AppState()
    inst_b = AppState()
    inst_a.set_devices("ed", [{"uid": "shared"}])
    # Las properties se leen del dict interno de la instancia.
    assert inst_a.dispositivos_ed == [{"uid": "shared"}]
    # inst_b tiene su propio dict: independiente.
    assert inst_b.dispositivos_ed == []


# ── get_app_state() activa las properties automáticamente ─────────────


def test_get_app_state_activates_legacy_properties() -> None:
    """``get_app_state()`` instala las properties vía el ``AreaRegistry``.

    El Singleton del ``AppState`` no necesita setup manual: al primer
    acceso, ``get_app_state()`` itera las áreas registradas y aplica
    los ``contributes_state_extensions`` que aporten.
    """
    state = get_app_state()
    # El área "alimentación" ya está registrada tras el import del
    # módulo raíz ``areas.alimentacion``, así que las 6 properties
    # están en la CLASE.
    for attr in (
        "dispositivos_ed", "dispositivos_ea", "dispositivos_sa",
        "dispositivos_v", "dispositivos_m", "dispositivos_m_vf",
    ):
        assert hasattr(state, attr), (
            f"AppState Singleton sin property {attr}: el hook del "
            f"área no se invocó en get_app_state()"
        )
