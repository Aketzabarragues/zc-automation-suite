"""Tests del handler ``_cmd_get_project_info`` del worker OT.

Mockeamos el portal con ``MagicMock()`` (no ``spec``: el portal es una
instancia arbitraria de Pythonnet con muchos atributos). Cada test
construye un árbol mínimo y verifica:
  - Shape del payload devuelto (al menos ``name``).
  - Resilencia ante ``get_property()`` que lanza excepción.
  - Normalización de datetimes .NET a ISO 8601 string.
  - Registro en ``COMMAND_REGISTRY``.

Convenciones heredadas del worker:
  - ``ts`` se ignora (el handler no toca el módulo Siemens directamente).
  - El ``portal`` mockeado expone ``get_project()`` y este a su vez
    expone ``get_property(name=...)``.
"""
from __future__ import annotations

import importlib
from datetime import datetime
from unittest.mock import MagicMock

import pytest

# Cargar el modulo del worker sin ejecutar ``main()`` (que requiere
# siemens_tia_scripting, no disponible en tests).
worker_tia = importlib.import_module("core.infrastructure.tia.worker_tia")
COMMAND_REGISTRY: dict = worker_tia.COMMAND_REGISTRY
_cmd_get_project_info = worker_tia._cmd_get_project_info


# ────────────────────────────────────────────────────────────────────────
# Helpers
# ────────────────────────────────────────────────────────────────────────


def _make_portal(properties: dict[str, object] | None = None) -> MagicMock:
    """Arma el portal mockeado: ``get_project().get_property(name)`` resuelve.

    Args:
        properties: dict ``{property_name: value}`` que ``get_property``
            devuelve cuando se invoca con ``name=property_name``. Si
            ``None``, todas las propiedades lanzan ``RuntimeError`` (modo
            "proyecto sin ninguna propiedad legible").
    """
    properties = properties or {}

    project = MagicMock()

    def _get_property(name: str = "") -> object:
        if name in properties:
            value = properties[name]
            if isinstance(value, BaseException):
                raise value
            return value
        # Default: la propiedad no está activa o no es legible.
        raise RuntimeError(f"property '{name}' not available")

    project.get_property.side_effect = _get_property
    portal = MagicMock()
    portal.get_project.return_value = project
    return portal


def _make_portal_with_no_project() -> MagicMock:
    """Portal sin proyecto activo (``get_project()`` devuelve ``None``)."""
    portal = MagicMock()
    portal.get_project.return_value = None
    return portal


# ────────────────────────────────────────────────────────────────────────
# Tests de shape
# ────────────────────────────────────────────────────────────────────────


def test_cmd_get_project_info_returns_name_only() -> None:
    """Solo ``Name`` legible → payload con solo ``{"name": "..."}``."""
    portal = _make_portal({"Name": "PROYECTO_MINIMO"})

    result = _cmd_get_project_info(portal, ts=None, args={})

    assert result == {"name": "PROYECTO_MINIMO"}


def test_cmd_get_project_info_includes_optional_props() -> None:
    """Todas las propiedades legibles → 7 keys con tipos primitivos."""
    portal = _make_portal({
        "Name": "25077_UF_RENY_PICOT_260603",
        "Path": r"D:\_PROYECTOS\25077\proyecto.ap18",
        "Author": "ABH",
        "Version": "1.0",
    })

    result = _cmd_get_project_info(portal, ts=None, args={})

    # Solo las propiedades que mockeamos deben estar presentes.
    assert result["name"] == "25077_UF_RENY_PICOT_260603"
    assert result["path"] == r"D:\_PROYECTOS\25077\proyecto.ap18"
    assert result["author"] == "ABH"
    assert result["version"] == "1.0"
    # El resto (creation_time, last_modified, last_modified_by) no
    # estaban en el mock → no aparecen.
    assert "creation_time" not in result
    assert "last_modified" not in result
    assert "last_modified_by" not in result
    # Todos los valores son primitivos (no objetos .NET).
    for k, v in result.items():
        assert isinstance(v, (str, int, bool, float)), (
            f"key '{k}' no es primitivo: {type(v).__name__}"
        )


def test_cmd_get_project_info_normalizes_datetime_to_iso() -> None:
    """Valores con ``.isoformat()`` (datetime .NET) → string ISO 8601.

    Pythonnet expone ``System.DateTime`` que luce como ``datetime``
    para nuestros mocks; el handler debe serializarlo a string antes
    de emitir JSON, porque ``json.dumps`` no sabe manejar ``datetime``
    y reventaría en el gateway.
    """
    fake_now = datetime(2025, 8, 12, 10, 25, 16)
    portal = _make_portal({
        "Name": "PROY",
        "CreationTime": fake_now,
        "LastModified": fake_now,
    })

    result = _cmd_get_project_info(portal, ts=None, args={})

    assert isinstance(result["creation_time"], str)
    assert isinstance(result["last_modified"], str)
    # El formato debe ser parseable como ISO 8601.
    parsed = datetime.fromisoformat(result["creation_time"])
    assert parsed == fake_now
    parsed2 = datetime.fromisoformat(result["last_modified"])
    assert parsed2 == fake_now


# ────────────────────────────────────────────────────────────────────────
# Resilencia
# ────────────────────────────────────────────────────────────────────────


def test_cmd_get_project_info_requires_active_project() -> None:
    """Sin proyecto activo → ``RuntimeError`` (sale de ``_get_active_project``)."""
    portal = _make_portal_with_no_project()

    with pytest.raises(RuntimeError, match="proyecto"):
        _cmd_get_project_info(portal, ts=None, args={})


def test_cmd_get_project_info_omits_failed_properties() -> None:
    """Si ``get_property`` lanza para ``Author`` y ``Version``, esas keys
    no aparecen; el resto sí.

    El handler NUNCA debe propagar excepciones de propiedades individuales:
    debe omitir la key y continuar con las demás, devolviendo un payload
    parcial. Si todas fallan, devuelve ``{"name": None}`` (que la SPA
    ignora con el ``v-if``).
    """
    portal = _make_portal({
        "Name": "PROY",
        "Path": "x",
        "Author": RuntimeError("permission denied"),
        "Version": RuntimeError("not available"),
    })

    result = _cmd_get_project_info(portal, ts=None, args={})

    # Las que mockeamos con valor siguen presentes.
    assert result["name"] == "PROY"
    assert result["path"] == "x"
    # Las que mockeamos para lanzar NO aparecen en el payload.
    assert "author" not in result
    assert "version" not in result


def test_cmd_get_project_info_all_failed_returns_name_none() -> None:
    """Si TODO falla (incluso ``Name``), el payload es ``{"name": None}``.

    La SPA no muestra la línea porque el ``v-if`` requiere ``name`` truthy.
    Comportamiento defensivo: el operario ve la app sin caption, no
    un error 500.
    """
    portal = _make_portal({
        "Name": RuntimeError("encoding error"),
    })

    result = _cmd_get_project_info(portal, ts=None, args={})

    assert result == {"name": None}


# ────────────────────────────────────────────────────────────────────────
# Registro
# ────────────────────────────────────────────────────────────────────────


def test_get_project_info_registered_in_command_registry() -> None:
    """``"get_project_info"`` está en ``COMMAND_REGISTRY`` y mapea al handler."""
    assert "get_project_info" in COMMAND_REGISTRY
    assert COMMAND_REGISTRY["get_project_info"] is _cmd_get_project_info
