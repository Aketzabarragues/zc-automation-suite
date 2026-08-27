"""AreaRegistry: contrato y discovery de áreas (Bounded Contexts).

Cada área (`areas/<area>/`) expone una `AreaSpec` en su
`__init__.py`. El registry itera los subpaquetes, importa el
`AREA_SPEC` de cada uno y los cachea como Singleton.

El core invoca los `contributes_*` de cada spec en los composition
roots (web `app.py`, MCP `mcp_server.py`, TIA worker, etc.) para
descubrir dinámicamente routers, tools, comandos y componentes
aportados por las áreas.

Estado: PR 0. Solo discovery vacío (no hay áreas aún). Las
contribuciones se cablean en PR 1+ según el plan.
"""
from __future__ import annotations

import importlib
import pkgutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable


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
            Firma: ``() -> dict``. Devuelve el manifest del área para la SPA.
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
    contributes_frontend_manifest: Callable[[], dict] | None = None
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


__all__ = ["AreaSpec", "AreaRegistry"]
