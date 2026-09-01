"""Modelos de dominio del subdominio alimentación.

Expone las dataclasses inmutables (frozen) que modelan los dispositivos
de hardware del departamento de alimentación, los DTOs derivados del
Excel corporativo (``ProcesoPLC`` y los que se añadan en Fases 2-5 del
plan ``_plan/04_excel_cache_phased_plan.md``) y el ``Protocol`` base
``Dispositivo`` que comparten.

Restricción arquitectónica: estos modelos son ESTRICTAMENTE PUROS.
- Sin imports de ``siemens_tia_scripting``.
- Sin imports de openpyxl u otras librerías de infraestructura.
- Sin uso de ``Any`` en los atributos declarados.

Nota de fase (Fases 1-3 del plan): ``ProcesoPLC``, ``ParamRealPLC``
y ``ParamIntPLC`` se re-exportan desde ``excel_cache``.
``dispositivos.py`` se BORRARÁ en Fase 5.5 — sus DTOs se
consolidarán entonces en ``excel_cache.py`` (Fase 5.1 del plan).
Hasta entonces, los re-exports de ``dispositivos.py`` se conservan
intactos.
"""

from areas.alimentacion.domain.models.dispositivos import (
    DimensionesDispositivos,
    DispEA,
    DispED,
    DispM,
    DispM_VF,
    DispSA,
    DispV,
    Dispositivo,
)
from areas.alimentacion.domain.models.excel_cache import (
    ParamIntPLC,
    ParamRealPLC,
    ProcesoPLC,
)

__all__ = [
    # Protocol y dimensiones
    "Dispositivo",
    "DimensionesDispositivos",
    # Dataclasses de dispositivos (purgado de "hardware")
    "DispED",
    "DispEA",
    "DispSA",
    "DispV",
    "DispM",
    "DispM_VF",
    # DTOs del Excel (Fases 1-3 del plan; Fases 4-5 amplían)
    "ProcesoPLC",
    "ParamRealPLC",
    "ParamIntPLC",
]
