"""Cantidades N_MAX de dispositivos, con nombres canonicos de TIA."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping


@dataclass(frozen=True)
class DimensionesDispositivos:
    """Cantidades N_MAX del Excel, con nombres canonicos de TIA.

    Los nombres canonicados siguen el patron ``N_MAX_DISP_<hw>`` (los
    mismos que el PLC expone como ``PlcUserConstant``). No hay forma
    alternativa: el caller compara contra el XML exportado de TIA y
    las claves deben coincidir exactamente.

    Atributos:
        extras: ``{nombre_canonico: valor}`` con todos los N_MAX del
            Excel (los principales del área + cualquier extra del
            ``n_max_catalog`` del ConfigManager).

    Convenciones:
        - ``to_api_dict()`` retorna una copia serializable para JSON.
        - ``get(nmax_name)`` lee por nombre canonico (``None`` si
            falta). Sin fallback legacy.
        - Sin I/O, sin imports de ``siemens_tia_scripting`` u openpyxl.
    """

    extras: Mapping[str, int] = field(default_factory=dict)

    def to_api_dict(self) -> dict[str, int]:
        """Copia de ``extras`` lista para serializar a JSON."""
        return dict(self.extras)

    def get(self, nmax_name: str) -> int | None:
        """Lee por nombre canonico de TIA. ``None`` si no existe."""
        v = self.extras.get(nmax_name)
        return int(v) if v is not None else None


__all__ = ["DimensionesDispositivos"]
