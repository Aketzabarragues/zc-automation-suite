"""Modelos de dominio (entidades, value objects, dataclasses) del proyecto ZC.

⚠️ SCAFFOLDING — Los modelos reales residen en el repositorio antiguo
(``_legacy_reference/``) y deben portarse manualmente.

Restricción arquitectónica heredada de las ``.clinerules``:
**prohibido** importar ``siemens_tia_scripting`` en este paquete.
Únicamente se permite la stdlib y tipos primitivos.
"""
from __future__ import annotations

from core.models.bloque_cache import BloqueCache
from core.models.bloque_plc import BloquePLC

__all__ = ["BloqueCache", "BloquePLC"]
