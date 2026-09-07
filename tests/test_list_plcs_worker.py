"""Tests del handler ``_cmd_list_plcs`` del worker OT.

Mockeamos el portal con ``MagicMock()`` (no ``spec``: el portal es una
instancia arbitraria de Pythonnet con muchos atributos). Cada test
construye un árbol mínimo y verifica:

  - Shape del payload: lista de dicts ``{name, short_designation}``.
  - ``short_designation`` se lee con la property ``ShortDesignation``
    del PLC vía ``plc.get_property("ShortDesignation")`` (mismo
    patrón que ``_cmd_get_project_info`` para "Name", "Path", etc.).
  - ``short_designation`` es ``None`` si:
      * el PLC no expone la property (lanza o devuelve vacío).
      * el PLC no tiene ``get_property`` (modelo no estándar).
  - ``name`` siempre presente (es la identidad del PLC).
  - Registro en ``COMMAND_REGISTRY`` bajo la clave ``"list_plcs"``.

Sept-2026 (armonización): el handler pasa de devolver
``list[str]`` (solo nombres) a ``list[dict]`` con ``name`` y
``short_designation``. La SPA usa ``short_designation`` para pintar
el modelo del PLC en la card de "PLC activo" del
``BloquesCacheView``.

Convenciones heredadas del worker:
  - ``ts`` se ignora (el handler no toca el módulo Siemens directamente).
  - El ``portal`` mockeado expone ``get_project()`` y este a su vez
    expone ``get_plcs()`` (lista de PLCs con ``get_name()`` y
    ``get_property(name)``).
"""
from __future__ import annotations

import importlib
from unittest.mock import MagicMock

import pytest

# Cargar el modulo del worker sin ejecutar ``main()`` (que requiere
# siemens_tia_scripting, no disponible en tests).
worker_tia = importlib.import_module("core.infrastructure.tia.worker_tia")
COMMAND_REGISTRY: dict = worker_tia.COMMAND_REGISTRY
_cmd_list_plcs = worker_tia._cmd_list_plcs


# ────────────────────────────────────────────────────────────────────────
# Helpers
# ────────────────────────────────────────────────────────────────────────


def _make_portal(
    plcs: list[dict[str, object]] | None = None,
) -> MagicMock:
    """Arma el portal mockeado: ``get_project().get_plcs()`` resuelve.

    Args:
        plcs: lista de dicts con la forma::

            [
                {
                    "name": "PLC1",
                    "short_designation": "CPU 1518-4 PN/DP" | None | <Exception>,
                },
                ...
            ]

        Para cada PLC mockeado:
          - ``plc.get_name()`` retorna ``name``.
          - ``plc.get_property("ShortDesignation")`` retorna el valor
            de ``short_designation`` si es un valor normal, lanza
            ``short_designation`` si es una ``Exception``, y lanza
            ``RuntimeError("property not available")`` si es ``None``
            (cubre el caso "el PLC existe pero no expone la property").

        Si ``plcs`` es ``None``, se devuelve un proyecto sin PLCs.
    """
    plcs = plcs or []

    project = MagicMock()
    plc_mocks: list[MagicMock] = []
    for entry in plcs:
        plc = MagicMock()
        plc.get_name.return_value = entry.get("name", "")
        sd_value = entry.get("short_designation", None)

        def _make_get_property(sd):
            def _get_property(name: str = "") -> object:  # noqa: ARG001
                if sd is None:
                    # Property no activa o no legible: simulamos
                    # el mismo comportamiento que ``_cmd_get_project_info``
                    # cuando una property falla.
                    raise RuntimeError("property 'ShortDesignation' not available")
                if isinstance(sd, BaseException):
                    raise sd
                return sd
            return _get_property

        plc.get_property.side_effect = _make_get_property(sd_value)
        plc_mocks.append(plc)

    project.get_plcs.return_value = plc_mocks
    portal = MagicMock()
    portal.get_project.return_value = project
    return portal


# ────────────────────────────────────────────────────────────────────────
# Tests de shape
# ────────────────────────────────────────────────────────────────────────


def test_cmd_list_plcs_returns_list_of_dicts() -> None:
    """``_cmd_list_plcs`` devuelve ``list[dict]`` con ``name`` y ``short_designation``.

    Sept-2026 (armonización): antes este handler devolvía ``list[str]``
    (solo nombres). Ahora devuelve ``list[dict]`` con la property
    "ShortDesignation" de cada PLC para que la SPA pueda pintar el
    modelo en la card del PLC activo sin un round trip extra.
    """
    portal = _make_portal([
        {"name": "PLC1", "short_designation": "CPU 1518-4 PN/DP"},
        {"name": "PLC2", "short_designation": "CPU 1515-2 PN"},
    ])

    result = _cmd_list_plcs(portal, ts=None, args={})

    assert result == [
        {"name": "PLC1", "short_designation": "CPU 1518-4 PN/DP"},
        {"name": "PLC2", "short_designation": "CPU 1515-2 PN"},
    ]


def test_cmd_list_plcs_empty_project() -> None:
    """Proyecto sin PLCs → lista vacía (no ``None`` ni error)."""
    portal = _make_portal([])

    result = _cmd_list_plcs(portal, ts=None, args={})

    assert result == []


def test_cmd_list_plcs_short_designation_none_when_property_fails() -> None:
    """Si ``get_property("ShortDesignation")`` lanza, ``short_designation`` es ``None``.

    Cubre el caso real: TIA Openness lanza ``RuntimeError`` o
    ``OpennessAccessException`` cuando la property no está activa
    en un modelo concreto de PLC. La SPA pinta "Modelo: —" en ese
    caso, no rompe la card.
    """
    portal = _make_portal([
        {"name": "PLC1", "short_designation": None},
    ])

    result = _cmd_list_plcs(portal, ts=None, args={})

    assert result == [{"name": "PLC1", "short_designation": None}]


def test_cmd_list_plcs_short_designation_none_when_property_raises_specific() -> None:
    """Si ``get_property`` lanza una excepción concreta (no solo ``RuntimeError``),
    ``short_designation`` también es ``None``.

    Cubre el caso de ``COMException`` / ``OpennessAccessException``
    que TIA puede lanzar para PLCs protegidos o sin permisos.
    """
    portal = _make_portal([
        {"name": "PLC1", "short_designation": RuntimeError("permission denied")},
    ])

    result = _cmd_list_plcs(portal, ts=None, args={})

    assert result == [{"name": "PLC1", "short_designation": None}]


def test_cmd_list_plcs_handles_plc_without_get_property_method() -> None:
    """Si el PLC no expone ``get_property`` (modelo no estándar),
    ``short_designation`` es ``None`` (defensivo: NO tumba el handler).

    El handler hace ``getattr(plc, "get_property", None)`` y si
    devuelve ``None`` (no existe el método), rellena con ``None``
    en vez de lanzar ``AttributeError``. Verifica que esto NO
    rompe el listado de PLCs: el operario ve el nombre del PLC
    aunque no vea el modelo.
    """
    # 1 PLC estandar con ShortDesignation OK + 1 PLC "fantasma"
    # construido con ``spec=["get_name"]`` (no expone ``get_property``).
    portal = _make_portal([
        {"name": "PLC_NORMAL", "short_designation": "CPU 1518-4 PN/DP"},
    ])
    plc_fantasma = MagicMock(spec=["get_name"])
    plc_fantasma.get_name.return_value = "PLC_FANTASMA"
    portal.get_project().get_plcs.return_value.append(plc_fantasma)

    result = _cmd_list_plcs(portal, ts=None, args={})

    assert result == [
        {"name": "PLC_NORMAL", "short_designation": "CPU 1518-4 PN/DP"},
        {"name": "PLC_FANTASMA", "short_designation": None},
    ]


def test_cmd_list_plcs_name_always_present() -> None:
    """``name`` siempre está presente aunque ``short_designation`` sea ``None``.

    El ``name`` es la identidad del PLC (``get_name()``) y la SPA
    lo necesita para el dropdown y el ``@change`` handler. Si
    ``get_name()`` devolviera vacío, el PLC aparece como cadena
    vacía (defensivo, no rompe nada).
    """
    portal = _make_portal([
        {"name": "PLC_ESTANDAR", "short_designation": None},
        {"name": "", "short_designation": "CPU 1510-1 PN"},
    ])

    result = _cmd_list_plcs(portal, ts=None, args={})

    assert result[0]["name"] == "PLC_ESTANDAR"
    assert result[0]["short_designation"] is None
    assert result[1]["name"] == ""
    assert result[1]["short_designation"] == "CPU 1510-1 PN"


# ────────────────────────────────────────────────────────────────────────
# Tests de registro en COMMAND_REGISTRY
# ────────────────────────────────────────────────────────────────────────


def test_cmd_list_plcs_is_registered_in_command_registry() -> None:
    """``_cmd_list_plcs`` está registrado bajo la clave ``"list_plcs"``.

    El gateway (``_dispatch_worker``) usa ``COMMAND_REGISTRY[command]``
    para resolver el handler. Si alguien renombra la función o el
    registry, este test lo caza.
    """
    assert "list_plcs" in COMMAND_REGISTRY
    assert COMMAND_REGISTRY["list_plcs"] is _cmd_list_plcs
