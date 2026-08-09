"""Modelos de lógica pura (software) del subdominio alimentación.

Define dataclasses ``frozen=True`` para entidades lógicas: ``Proceso``,
``Alarma``, ``PInt`` y ``PReal``. Estos modelos no se inyectan como
PlcTag directos; representan configuración/estructura del proyecto.

Restricciones arquitectónicas:
- Prohibido importar ``siemens_tia_scripting``.
- Prohibido el uso de ``Any`` en los atributos declarados.
- Prohibido depender de openpyxl u otras librerías de infraestructura.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Proceso:
    """Proceso de producción del departamento de alimentación.

    Modela una unidad lógica de proceso (p. ej. ``"PROCESO_PASTAS"``).
    """

    nombre: str
    descripcion: str = ""

    @property
    def db_alm_nombre(self) -> str:
        """Nombre canónico del DB de alarmas asociado al proceso.

        Convención: ``"<nombre>_ALM"`` (snake case en mayúsculas).
        """
        return f"{self.nombre}_ALM"


@dataclass(frozen=True)
class Alarma:
    """Alarma del proceso.

    Modela una alarma individual con prioridad y mensaje por defecto.
    """

    nombre: str
    prioridad: int = 0
    mensaje: str = ""

    @property
    def es_critica(self) -> bool:
        """``True`` si la prioridad es ``>= 16`` (umbral convencional)."""
        return self.prioridad >= 16


@dataclass(frozen=True)
class PInt:
    """Parámetro entero de configuración del proceso."""

    nombre: str
    valor: int = 0


@dataclass(frozen=True)
class PReal:
    """Parámetro real (coma flotante) de configuración del proceso."""

    nombre: str
    valor: float = 0.0


__all__ = ["Proceso", "Alarma", "PInt", "PReal"]
