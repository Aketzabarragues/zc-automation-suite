"""Discovery y catálogo de áreas (Bounded Contexts).

Las áreas exponen su ``AreaSpec`` desde su ``__init__.py``. El registry
importa cada spec via ``pkgutil.iter_modules`` y lo cachea como
Singleton. El core invoca los ``contributes_*`` en los composition
roots (Flask, TIA worker) para descubrir routers, commands, manifest
de frontend, etc.
"""
from __future__ import annotations

import importlib
import logging
import pkgutil
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Callable, TypedDict

if TYPE_CHECKING:
    from core.infrastructure.config.config_manager import ConfigManager

logger = logging.getLogger(__name__)


# Shape del manifest de frontend (contrato cross-language Python <-> JS).
# TypedDict documenta el contrato para autores Python de areas nuevas;
# en runtime sigue siendo un dict estandar.


class AreaFrontendComponents(TypedDict, total=False):
    """Composicion Vue 3 del area."""

    sidebar: str
    landing: str
    views: dict[str, str]


class AreaFrontendManifest(TypedDict, total=False):
    """Manifest que devuelve un ``contributes_frontend_manifest``."""

    id: str
    label: str
    icon: str
    components: AreaFrontendComponents
    loaders: dict[str, str]


@dataclass(frozen=True)
class AreaSpec:
    """Contrato que cada area declara en su ``__init__.py``.

    Todos los campos son opcionales. Un area solo implementa los
    extension points que aporta.
    """

    id: str
    label: str
    icon: str = ""
    config_block: str = ""

    contributes_routers: Callable[[Any], None] | None = None
    contributes_tia_commands: Callable[[dict], None] | None = None
    contributes_mcp_tools: Callable[[Any], None] | None = None
    contributes_frontend_manifest: Callable[[], "AreaFrontendManifest"] | None = None
    contributes_state_extensions: Callable[[Any], None] | None = None
    contributes_config_defaults: Callable[[dict], None] | None = None
    contributes_catalog: Callable[[Any], dict] | None = None


class AreaRegistry:
    """Descubre areas en ``areas/*/`` y cachea sus ``AreaSpec``.

    Singleton. El primer ``discover()`` puebla el cache; los siguientes
    retornan la misma instancia.
    """

    _instance: "AreaRegistry | None" = None

    def __init__(self) -> None:
        self._specs: dict[str, AreaSpec] = {}

    @classmethod
    def discover(cls) -> "AreaRegistry":
        """Descubre y cachea areas. Thread-unsafe (se llama una sola vez)."""
        if cls._instance is None:
            instance = cls()
            instance._scan()
            cls._instance = instance
        return cls._instance

    def _scan(self) -> None:
        """Itera ``areas/*/`` e importa cada ``__init__.py``."""
        try:
            import areas as _areas_pkg
        except ImportError as exc:
            logger.warning("AreaRegistry: areas no se pudo importar: %s", exc)
            return

        if not hasattr(_areas_pkg, "__path__"):
            logger.warning(
                "AreaRegistry: areas no tiene __path__; no se puede iterar "
                "subpaquetes. _areas_pkg=%r",
                _areas_pkg,
            )
            return

        for module_info in pkgutil.iter_modules(_areas_pkg.__path__):
            module_name = module_info.name
            if module_name.startswith("_"):
                continue
            full_name = f"areas.{module_name}"
            try:
                module = importlib.import_module(full_name)
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "AreaRegistry: no se pudo importar %s: %s", full_name, exc
                )
                continue
            spec: AreaSpec | None = getattr(module, "AREA_SPEC", None)
            if spec is None:
                logger.warning(
                    "AreaRegistry: %s no expone AREA_SPEC; area ignorada.",
                    full_name,
                )
                continue
            if spec.id in self._specs:
                logger.warning(
                    "AreaRegistry: id duplicado %r (area %s ignorada)",
                    spec.id, full_name,
                )
                continue
            self._specs[spec.id] = spec
        logger.info(
            "AreaRegistry: descubrimiento completo. areas=%d (%s)",
            len(self._specs),
            list(self._specs.keys()),
        )

    def get(self, area_id: str) -> AreaSpec | None:
        """Devuelve la ``AreaSpec`` con ``id == area_id``, o ``None``."""
        return self._specs.get(area_id)

    def all(self) -> list[AreaSpec]:
        """Devuelve la lista de specs en orden de discovery."""
        return list(self._specs.values())

    def for_each(self, hook: str, **kwargs: Any) -> None:
        """Invoca ``spec.<hook>(**kwargs)`` en cada spec que aporte ese hook.

        Specs sin ese hook se ignoran silenciosamente.
        """
        for spec in self._specs.values():
            fn = getattr(spec, hook, None)
            if fn is None:
                continue
            fn(**kwargs)


# Defaults por clave. Cuando un departamento no declara ``display`` en
# el JSON, se usan estos. Mantenerlos en Python evita tocar configs
# de instalaciones existentes.
_AREA_DEFAULTS: dict[str, dict[str, str]] = {
    "alimentacion": {
        "label":       "Area de alimentacion",
        "icon":        "📁",
        "description": "Dispositivos, sincronizacion e inspeccion de PLCs del area de alimentacion.",
    },
}


def _humanize(key: str) -> str:
    """Capitaliza una clave (``"alimentacion"`` -> ``"Alimentacion"``).

    Si hay default en ``_AREA_DEFAULTS`` se usa su label (ya tildes/ortografia).
    """
    if not key:
        return ""
    return key[0].upper() + key[1:].replace("_", " ")


@dataclass(frozen=True)
class AreaInfo:
    """Vista publica de un departamento para la SPA."""

    key: str
    label: str
    description: str
    icon: str
    available: bool


class ListAreasUseCase:
    """Lista las areas configuradas en ``config.json`` (puro, sin I/O)."""

    def __init__(self, config_manager: "ConfigManager") -> None:
        self._config_manager = config_manager

    def execute(self) -> list[AreaInfo]:
        """Devuelve la lista de ``AreaInfo`` configuradas.

        NO muta el config. NO lanza excepciones: ante cualquier
        inconsistencia del JSON, se loggea warning y se omite.
        """
        departments = self._config_manager.get_departments_config()
        if not departments:
            logger.info(
                "No hay bloque 'departments' en config.json. "
                "Se devuelve lista vacia de areas."
            )
            return []

        registry = AreaRegistry.discover()
        areas: list[AreaInfo] = []
        for key, dept_cfg in departments.items():
            if not isinstance(key, str) or not isinstance(dept_cfg, dict):
                logger.warning(
                    "Departamento mal formado en config.json "
                    "(key=%r, type=%s). Se omite.",
                    key, type(dept_cfg).__name__,
                )
                continue

            # Cadena de fallback para label/icon/description:
            #   1. Override en ``display`` del config.json.
            #   2. ``AreaSpec`` registrado (label, icon).
            #   3. ``_AREA_DEFAULTS[key]`` (description + legacy).
            #   4. Fallback generico (humanizado, emoji por defecto, "").
            spec = registry.get(key)
            defaults = _AREA_DEFAULTS.get(key, {})
            display = dept_cfg.get("display") if isinstance(
                dept_cfg.get("display"), dict
            ) else {}

            label = (
                display.get("label")
                or (spec.label if spec is not None else None)
                or defaults.get("label")
                or f"Area {_humanize(key)}"
            )
            icon = (
                display.get("icon")
                or (spec.icon if spec is not None else None)
                or defaults.get("icon")
                or ""
            )
            description = (
                display.get("description")
                or defaults.get("description")
                or ""
            )

            dispositivos = dept_cfg.get("Dispositivos")
            available = bool(
                isinstance(dispositivos, dict) and len(dispositivos) > 0
            )

            areas.append(
                AreaInfo(
                    key=key,
                    label=label,
                    description=description,
                    icon=icon,
                    available=available,
                )
            )

        logger.info("ListAreasUseCase: %d area(s) encontrada(s).", len(areas))
        return areas


__all__ = ["AreaSpec", "AreaRegistry", "AreaInfo", "ListAreasUseCase"]
