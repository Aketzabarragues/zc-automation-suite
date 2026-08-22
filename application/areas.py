"""Application Layer - Catálogo de Áreas (Departamentos).

DTO ``AreaInfo`` y caso de uso ``ListAreasUseCase``. Una *área* es un
departamento configurado en ``infrastructure/config.json`` bajo la clave
``departments`` (ej. ``alimentacion``). El catálogo de áreas alimenta
la pantalla de bienvenida de la SPA.

Diseño:
  - ``ListAreasUseCase`` es **puro** (sin I/O): opera sobre el JSON
    cacheado en memoria por ``ConfigManager``.
  - Si el ``ConfigManager`` está cacheando, este use case no relee
    disco en cada llamada.
  - ``available`` se calcula a partir del bloque ``Dispositivos`` del
    departamento: si tiene al menos una entrada, el departamento es
    "accesible"; si no, queda como "Próximamente" en la welcome.

Las constantes de icono/label/description por clave viven aquí (no en
``config.json``) para no requerir migración de configs antiguos. Si
en el futuro se quiere flexibilidad total, se puede añadir un bloque
opcional ``display: {label, icon, description}`` al JSON y leerlo con
``get``.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from infrastructure.config_manager import ConfigManager


_logger = logging.getLogger(f"{__name__}.ListAreasUseCase")


# ── Defaults por clave ───────────────────────────────────────────────
# Cuando un departamento no declara ``display`` en el JSON, se usan
# estos valores por defecto. Mantenerlos en Python (no en JSON) evita
# tocar configs de instalaciones existentes.
_AREA_DEFAULTS: dict[str, dict[str, str]] = {
    "alimentacion": {
        "label":       "Área Alimentación",
        "icon":        "🍞",
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
        full_config = self._config_manager._full_config  # noqa: SLF001 (uso interno documentado)
        departments = full_config.get("departments")
        if not isinstance(departments, dict) or not departments:
            _logger.info(
                "No hay bloque 'departments' en config.json. "
                "Se devuelve lista vacía de áreas."
            )
            return []

        areas: list[AreaInfo] = []
        for key, dept_cfg in departments.items():
            if not isinstance(key, str) or not isinstance(dept_cfg, dict):
                _logger.warning(
                    f"Departamento mal formado en config.json "
                    f"(key={key!r}, type={type(dept_cfg).__name__}). "
                    f"Se omite."
                )
                continue

            # Defaults por clave + override opcional vía display en el JSON.
            defaults = _AREA_DEFAULTS.get(key, {})
            display = dept_cfg.get("display") if isinstance(
                dept_cfg.get("display"), dict
            ) else {}

            label = (
                display.get("label")
                or defaults.get("label")
                or f"Área {_humanize(key)}"
            )
            icon = (
                display.get("icon")
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


__all__ = ["AreaInfo", "ListAreasUseCase"]
