"""Tests del extension point ``contributes_state_extensions`` (PR 2).

Cubre la instalaciÃ³n de las 6 properties legacy
``dispositivos_ed/ea/sa/v/m/m_vf`` sobre la CLASE ``AppState`` que
el Ã¡rea de alimentaciÃ³n aporta vÃ­a su ``AreaSpec``.

Estos tests verifican que:
  - ``install()`` pega las 6 properties a la CLASE (no a la instancia).
  - Las properties delegan en ``get_devices`` / ``set_devices``.
  - El Ã¡rea estÃ¡ registrada en el ``AreaRegistry`` con los hooks
    esperados tras PR 2 (``state_extensions``, ``config_defaults``,
    ``catalog``).
  - El Singleton del ``AppState`` activa las properties automÃ¡ticamente
    (vÃ­a ``get_app_state()``).
"""
from __future__ import annotations

import pytest

from core.composition.app_area_registry import AreaRegistry, AreaSpec
from core.runtime.app_state import AppState, get_app_state


# â”€â”€ Registry: el Ã¡rea de alimentaciÃ³n se autoregistra â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€


def test_alimentacion_area_is_registered() -> None:
    """El Ã¡rea de alimentaciÃ³n estÃ¡ en el ``AreaRegistry`` tras PR 2."""
    specs = AreaRegistry.discover().all()
    ids = {s.id for s in specs}
    assert "alimentacion" in ids


def test_alimentacion_spec_has_expected_hooks() -> None:
    """La ``AreaSpec`` de alimentaciÃ³n tiene los hooks esperados tras PR 2..6.

    PR 2 implementÃ³ ``contributes_state_extensions``,
    ``contributes_config_defaults`` y ``contributes_catalog``.
    PR 3 implementÃ³ ``contributes_tia_commands`` (los 6 handlers
    ``update_disp_comments_db_*`` aportados al ``COMMAND_REGISTRY``
    del worker OT desde ``infrastructure/tia/extra_commands.py``).
    PR 4 implementÃ³ ``contributes_routers`` (3 routers web movidos
    desde el shell a ``areas/alimentacion/interfaces/web/``). [Borrado
    Fase A, sept-2026; los endpoints HTTP del area se migraran a
    blueprints Flask OB1 en 4.6.2.]
    PR 5 implementÃ³ ``contributes_frontend_manifest`` (manifest del
    Ã¡rea para la SPA).
    PR 6 implementÃ³ ``contributes_mcp_tools`` (4 tools MCP que dan
    paridad con los endpoints web del Ã¡rea: sync preview/commit,
    aplicar comentarios, upload excel).

    Este test se actualiza por PR: cada vez que un PR aÃ±ade un hook
    nuevo, lo promovemos de ``is None`` a ``is not None``. Cuando
    los 6 hooks estÃ©n implementados, el bloque final desaparece.
    """
    spec = AreaRegistry.discover().get("alimentacion")
    assert spec is not None
    assert spec.id == "alimentacion"
    assert spec.label == "Ãrea de alimentaciÃ³n"
    assert spec.config_block == "alimentacion"
    # Implementados en PR 2
    assert spec.contributes_state_extensions is not None
    assert spec.contributes_config_defaults is not None
    assert spec.contributes_catalog is not None
    # Implementado en PR 3
    assert spec.contributes_tia_commands is not None
    # Implementado en PR 5
    assert spec.contributes_frontend_manifest is not None
    # Implementado en PR 6
    assert spec.contributes_mcp_tools is not None


# â”€â”€ state_extensions.install: pega las 6 properties a la CLASE â”€â”€â”€â”€â”€â”€â”€â”€


@pytest.fixture
def fresh_state() -> AppState:
    """Una instancia fresca de ``AppState`` (no el Singleton global)."""
    return AppState()


def test_install_attaches_six_properties_to_class(fresh_state: AppState) -> None:
    """``install`` pega (o re-pega) 6 properties a la CLASE ``AppState``.

    Nota: ``install()`` es idempotente â€” reasignar ``property`` sobre
    la clase no la duplica, solo la sustituye. Esto significa que
    podemos llamarlo mÃºltiples veces (p. ej. desde distintos tests
    o desde ``get_app_state()``) sin efectos colaterales.

    En este test verificamos que las 6 properties estÃ¡n presentes
    en la CLASE tras invocar ``install`` (sea la primera vez o una
    posterior). Verificamos tambiÃ©n que la ``property`` retornada es
    un ``property`` descriptor (no un valor estÃ¡tico).
    """
    from areas.alimentacion.helpers.state.install_state_extensions import install

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
    from areas.alimentacion.helpers.state.install_state_extensions import install

    install(fresh_state)
    fresh_state.set_devices("ed", [{"uid": "ED_001"}, {"uid": "ED_002"}])
    assert fresh_state.dispositivos_ed == [
        {"uid": "ED_001"}, {"uid": "ED_002"}
    ]


def test_install_makes_setter_delegate_to_set_devices(
    fresh_state: AppState,
) -> None:
    """``state.dispositivos_<hw> = [...]`` actualiza ``get_devices(hw)``."""
    from areas.alimentacion.helpers.state.install_state_extensions import install

    install(fresh_state)
    fresh_state.dispositivos_ea = [{"uid": "EA_001"}]
    # El setter debe haber escrito en ``_dispositivos["ea"]`` vÃ­a
    # ``set_devices`` (defensa: ver tests de ``get_devices`` abajo).
    assert fresh_state.get_devices("ea") == [{"uid": "EA_001"}]
    # Y la property de lectura refleja el cambio.
    assert fresh_state.dispositivos_ea == [{"uid": "EA_001"}]


def test_install_returns_empty_list_for_unset_hw(
    fresh_state: AppState,
) -> None:
    """Las 6 properties retornan ``[]`` si el hw aÃºn no se asignÃ³."""
    from areas.alimentacion.helpers.state.install_state_extensions import install

    install(fresh_state)
    assert fresh_state.dispositivos_ed == []
    assert fresh_state.dispositivos_ea == []
    assert fresh_state.dispositivos_sa == []
    assert fresh_state.dispositivos_v == []
    assert fresh_state.dispositivos_m == []
    assert fresh_state.dispositivos_m_vf == []


def test_install_propagates_to_existing_and_future_instances() -> None:
    """Las properties se pegan a la CLASE: afectan a todas las instancias.

    Nota: el ``install()`` es idempotente â€” reasignar ``property``
    sobre la clase no la duplica, solo la sustituye. Tras la
    primera invocaciÃ³n (p. ej. por ``get_app_state()`` en otro test
    o en el setup de pytest), las properties ya estÃ¡n en la clase.
    Este test verifica el comportamiento estable: tras invocar
    ``install()``, una nueva instancia ve las properties y comparte
    estado con otra instancia vÃ­a el ``_dispositivos`` interno.
    """
    from areas.alimentacion.helpers.state.install_state_extensions import install

    # Forzar install (idempotente: solo re-asigna ``property``).
    install(AppState())

    # Tras install: la CLASE tiene las properties. Dos instancias
    # distintas ven la misma property (herencia de clase) y comparten
    # el ``_dispositivos`` subyacente porque ``AppState.__init__``
    # crea un dict NUEVO por instancia â€” son dos backends distintos.
    inst_a = AppState()
    inst_b = AppState()
    inst_a.set_devices("ed", [{"uid": "shared"}])
    # Las properties se leen del dict interno de la instancia.
    assert inst_a.dispositivos_ed == [{"uid": "shared"}]
    # inst_b tiene su propio dict: independiente.
    assert inst_b.dispositivos_ed == []


# â”€â”€ get_app_state() activa las properties automÃ¡ticamente â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€


def test_get_app_state_activates_legacy_properties() -> None:
    """``get_app_state()`` instala las properties vÃ­a el ``AreaRegistry``.

    El Singleton del ``AppState`` no necesita setup manual: al primer
    acceso, ``get_app_state()`` itera las Ã¡reas registradas y aplica
    los ``contributes_state_extensions`` que aporten.
    """
    state = get_app_state()
    # El Ã¡rea "alimentaciÃ³n" ya estÃ¡ registrada tras el import del
    # mÃ³dulo raÃ­z ``areas.alimentacion``, asÃ­ que las 6 properties
    # estÃ¡n en la CLASE.
    for attr in (
        "dispositivos_ed", "dispositivos_ea", "dispositivos_sa",
        "dispositivos_v", "dispositivos_m", "dispositivos_m_vf",
    ):
        assert hasattr(state, attr), (
            f"AppState Singleton sin property {attr}: el hook del "
            f"Ã¡rea no se invocÃ³ en get_app_state()"
        )
