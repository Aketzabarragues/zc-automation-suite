"""AreaRegistry: contrato y discovery de áreas (Bounded Contexts).

Cada área (`areas/<area>/`) expone una `AreaSpec` en su
`__init__.py`. El registry itera los subpaquetes, importa el
`AREA_SPEC` de cada uno y los cachea como Singleton.

El core invoca los `contributes_*` de cada spec en los composition
roots (web `app.py`, MCP `mcp_server.py`, TIA worker, etc.) para
descubrir dinámicamente routers, tools, comandos y componentes
aportados por las áreas.

Tras PR 2 este módulo también expone el caso de uso
``ListAreasUseCase`` (y su DTO ``AreaInfo``) que se usaba en
``application/areas/catalog.py``. Se mantiene en este mismo archivo
para evitar tener dos módulos conceptualmente juntos: el registry
de áreas (``AreaSpec`` / ``AreaRegistry``) y la presentación del
catálogo de áreas al frontend (``ListAreasUseCase``).
"""
from __future__ import annotations

import importlib
import logging
import pkgutil
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable, TypedDict

if TYPE_CHECKING:
    from core.infrastructure.config_manager import ConfigManager

_logger = logging.getLogger(f"{__name__}.AreaRegistry")


# ── Shape del manifest de frontend (contrato cross-language) ────────────
# Las áreas exponen su UI a la SPA via un dict JSON. El shell SPA
# (``core/interfaces/web_server/static/js/area-loader.js``) consume
# este dict por nombre de campo. TypedDict documenta el contrato
# para los autores Python de áreas nuevas; en runtime sigue siendo
# un ``dict`` estándar, así que la interop con JS no cambia.


class AreaFrontendComponents(TypedDict, total=False):
    """Composición de componentes Vue 3 del área.

    Attributes:
        sidebar: Nombre del componente del sidebar (entry-point del área).
        landing: Nombre del componente de bienvenida.
        views:   Dict ``{route_key: component_name}`` para sub-vistas
                 del área. La SPA enrutará cada key a su componente.
    """

    sidebar: str
    landing: str
    views: dict[str, str]


class AreaFrontendManifest(TypedDict, total=False):
    """Manifest que un ``contributes_frontend_manifest`` debe devolver.

    Serializado a JSON por el endpoint del backend y consumido por la
    SPA. Todas las claves son opcionales (``total=False``) para no
    romper áreas que aún no aportan sidebar o views, pero la SPA
    asumirá que ``id``, ``label``, ``icon`` y ``loaders`` existen
    para renderizar el área.
    """

    id: str
    label: str
    icon: str
    components: AreaFrontendComponents
    loaders: dict[str, str]


# ── AreaSpec: contrato de área ─────────────────────────────────────────


@dataclass(frozen=True)
class AreaSpec:
    """Contrato que cada área declara en su ``__init__.py``.

    Todos los campos son opcionales. Un área solo implementa los
    extension points que aporta. Si un campo no se implementa, el
    área no aporta ese punto (p. ej. un área sin UI solo aporta
    ``contributes_tia_commands``).

    Attributes:
        id:           Identificador estable ("alimentacion"). Clave del config.
        label:        Texto humano-legible ("Alimentación").
        icon:         Glifo/emoji para la UI.
        config_block: Clave bajo `departments` en `infrastructure/config.json`.

        contributes_routers:
            Firma: ``(app: FastAPI) -> None``. ``include_router()`` por router.
        contributes_tia_commands:
            Firma: ``(registry: dict[str, Callable]) -> None``. Muta el
            COMMAND_REGISTRY del worker in-place con los handlers extra.
        contributes_mcp_tools:
            Firma: ``(mcp: FastMCP) -> None``. Registra ``@mcp.tool()``
            para tools específicas del área.
        contributes_frontend_manifest:
            Firma: ``() -> AreaFrontendManifest``. Devuelve el manifest
            del área para la SPA (ver shape en ``AreaFrontendManifest``).
        contributes_state_extensions:
            Firma: ``(app_state: AppState) -> None``. Patchea properties
            de back-compat sobre la clase `AppState`.
        contributes_config_defaults:
            Firma: ``(dept_cfg: dict) -> None``. Rellena claves ausentes
            en el bloque del departamento en config.json.
        contributes_catalog:
            Firma: ``(cm: ConfigManager) -> dict``. Aporta su parte del
            payload de ``GET /api/v1/catalog``.
    """

    id: str
    label: str
    icon: str = "📁"
    config_block: str = ""

    contributes_routers: Callable[[Any], None] | None = None
    contributes_tia_commands: Callable[[dict], None] | None = None
    contributes_mcp_tools: Callable[[Any], None] | None = None
    contributes_frontend_manifest: Callable[[], "AreaFrontendManifest"] | None = None
    contributes_state_extensions: Callable[[Any], None] | None = None
    contributes_config_defaults: Callable[[dict], None] | None = None
    contributes_catalog: Callable[[Any], dict] | None = None


# ── AreaRegistry: discovery + dispatch ────────────────────────────────


class AreaRegistry:
    """Descubre áreas en ``areas/*/`` y cachea sus ``AreaSpec``.

    Discovery: itera los subpaquetes de `areas` con `pkgutil.iter_modules`
    (no introspección mágica de archivos), importa cada `__init__.py`
    y captura el símbolo `AREA_SPEC` que cada uno debe exportar.

    Cache: Singleton. El primer `discover()` puebla el cache; los
    siguientes retornan la misma instancia. La lista de áreas no
    cambia en runtime.

    Uso:
        reg = AreaRegistry.discover()
        for spec in reg.all():
            ...
        reg.for_each("contributes_routers", app=fastapi_app)
        reg.get("alimentacion").contributes_tia_commands(cmd_registry)
    """

    _instance: "AreaRegistry | None" = None

    def __init__(self) -> None:
        self._specs: dict[str, AreaSpec] = {}

    @classmethod
    def discover(cls) -> "AreaRegistry":
        """Descubre y cachea todas las áreas. Singleton thread-unsafe (se llama
        una sola vez por proceso al inicio)."""
        if cls._instance is None:
            instance = cls()
            instance._scan()
            cls._instance = instance
        return cls._instance

    def _scan(self) -> None:
        """Itera `areas/*/` e importa cada `__init__.py`."""
        # `areas` debe ser importable como paquete (necesita `__init__.py`,
        # que ya creamos en este PR 0).
        try:
            import areas as _areas_pkg
        except ImportError:
            return

        for module_info in pkgutil.iter_modules(_areas_pkg.__path__):
            module_name = module_info.name
            # Ignora paquetes privados (que empiezan por `_`).
            if module_name.startswith("_"):
                continue
            full_name = f"areas.{module_name}"
            try:
                module = importlib.import_module(full_name)
            except Exception as exc:  # noqa: BLE001
                # Si un área falla al importar, loggea y sigue con las demás.
                import logging
                logging.getLogger(__name__).warning(
                    "AreaRegistry: no se pudo importar %s: %s", full_name, exc
                )
                continue
            spec: AreaSpec | None = getattr(module, "AREA_SPEC", None)
            if spec is None:
                continue
            if spec.id in self._specs:
                import logging
                logging.getLogger(__name__).warning(
                    "AreaRegistry: id duplicado %r (área %s ignorada)",
                    spec.id, full_name,
                )
                continue
            self._specs[spec.id] = spec

    def get(self, area_id: str) -> AreaSpec | None:
        """Devuelve la `AreaSpec` con `id == area_id`, o `None`."""
        return self._specs.get(area_id)

    def all(self) -> list[AreaSpec]:
        """Devuelve la lista de specs en orden de discovery."""
        return list(self._specs.values())

    def for_each(self, hook: str, **kwargs: Any) -> None:
        """Invoca ``spec.<hook>(**kwargs)`` en cada spec que aporte ese hook.

        Args:
            hook: Nombre del atributo de la spec (p. ej.
                ``"contributes_routers"``).
            **kwargs: Argumentos extra que se pasan al callable. Cada spec
                que tenga el hook a `None` se ignora silenciosamente.
        """
        for spec in self._specs.values():
            fn = getattr(spec, hook, None)
            if fn is None:
                continue
            fn(**kwargs)


# ── ListAreasUseCase + AreaInfo (antes en application/areas/catalog.py) ──
# Tras PR 2 el caso de uso del catálogo de áreas vive aquí, junto al
# ``AreaRegistry`` que lo origina. La antigua ruta
# ``application.areas.catalog`` queda como shim de back-compat que
# re-exporta estos símbolos.
#
# Diseño:
#   - ``ListAreasUseCase`` es **puro** (sin I/O): opera sobre el JSON
#     cacheado en memoria por ``ConfigManager``.
#   - Si el ``ConfigManager`` está cacheando, este use case no relee
#     disco en cada llamada.
#   - ``available`` se calcula a partir del bloque ``Dispositivos`` del
#     departamento: si tiene al menos una entrada, el departamento es
#     "accesible"; si no, queda como "Próximamente" en la welcome.
#
# Las constantes de icono/label/description por clave viven aquí (no en
# ``config.json``) para no requerir migración de configs antiguos. Si
# en el futuro se quiere flexibilidad total, se puede añadir un bloque
# opcional ``display: {label, icon, description}`` al JSON y leerlo con
# ``get``.


# ── Defaults por clave ───────────────────────────────────────────────
# Cuando un departamento no declara ``display`` en el JSON, se usan
# estos valores por defecto. Mantenerlos en Python (no en JSON) evita
# tocar configs de instalaciones existentes.
_AREA_DEFAULTS: dict[str, dict[str, str]] = {
    "alimentacion": {
        "label":       "Área de alimentación",
        "icon":        "",
        "description": "Dispositivos, sincronización e inspección de PLCs del área de alimentación.",
    },
}


def _humanize(key: str) -> str:
    """Capitaliza una clave (``"alimentacion"`` → ``"Alimentacion"``).

    Si existe un default específico, se usa el label de
    ``_AREA_DEFAULTS`` que ya incluye tildes/ortografía.
    """
    if not key:
        return ""
    return key[0].upper() + key[1:].replace("_", " ")


@dataclass(frozen=True)
class AreaInfo:
    """Vista pública de un departamento para la SPA.

    Attributes:
        key:         Identificador (``"alimentacion"``). Estable: NO
                     se renombra nunca (es la clave del config).
        label:       Texto humano-legible mostrado en la tarjeta.
        description: Resumen de una línea. Vacío si no hay.
        icon:        Glifo/emoji representativo.
        available:   ``True`` si el departamento tiene un bloque
                     ``Dispositivos`` con al menos una entrada.
    """

    key: str
    label: str
    description: str
    icon: str
    available: bool


class ListAreasUseCase:
    """Caso de Uso: lista las áreas configuradas en ``config.json``.

    Args:
        config_manager: Instancia de ``ConfigManager``. Se mantiene
                        una referencia; **no se re-instancia**.
    """

    def __init__(self, config_manager: "ConfigManager") -> None:
        self._config_manager = config_manager

    def execute(self) -> list[AreaInfo]:
        """Devuelve la lista de ``AreaInfo`` configuradas.

        Returns:
            Lista de áreas en el orden de aparición del JSON. Lista
            vacía si el JSON no tiene bloque ``departments`` o si el
            bloque está vacío.

        Notas:
            - NO muta el config.
            - NO lanza excepciones: ante cualquier inconsistencia del
              JSON, se loggea warning y se omite la entrada.
        """
        departments = self._config_manager.get_departments_config()
        if not departments:
            _logger.info(
                "No hay bloque 'departments' en config.json. "
                "Se devuelve lista vacía de áreas."
            )
            return []

        # Se consulta una sola vez por ejecución; el cache es caliente
        # porque ``create_app()`` ya llamó a ``AreaRegistry.discover()``
        # al construir el shell.
        registry = AreaRegistry.discover()
        areas: list[AreaInfo] = []
        for key, dept_cfg in departments.items():
            if not isinstance(key, str) or not isinstance(dept_cfg, dict):
                _logger.warning(
                    f"Departamento mal formado en config.json "
                    f"(key={key!r}, type={type(dept_cfg).__name__}). "
                    f"Se omite."
                )
                continue

            # Cadena de fallback para label/icon/description:
            #   1. Override en el bloque ``display`` del config.json.
            #   2. ``AreaSpec`` registrado para esta clave (label, icon).
            #   3. ``_AREA_DEFAULTS[key]`` (description + legacy).
            #   4. Fallback genérico (humanizado, 📁, "").
            spec = registry.get(key)
            defaults = _AREA_DEFAULTS.get(key, {})
            display = dept_cfg.get("display") if isinstance(
                dept_cfg.get("display"), dict
            ) else {}

            label = (
                display.get("label")
                or (spec.label if spec is not None else None)
                or defaults.get("label")
                or f"Área {_humanize(key)}"
            )
            icon = (
                display.get("icon")
                or (spec.icon if spec is not None else None)
                or defaults.get("icon")
                or "📁"
            )
            description = (
                display.get("description")
                or defaults.get("description")
                or ""
            )

            # available: el bloque Dispositivos existe y tiene >=1 entrada.
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

        _logger.info(f"ListAreasUseCase: {len(areas)} área(s) encontrada(s).")
        return areas


__all__ = ["AreaSpec", "AreaRegistry", "AreaInfo", "ListAreasUseCase"]
