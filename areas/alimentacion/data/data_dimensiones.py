"""Cantidades N_MAX de dispositivos y entidades, con nombres
canonicos de TIA.

Modulo multi-PLC: cada PLC del Excel tiene su propio
``DataDimensionesPLC`` con sus N_MAX. ``DimensionesDispositivos`` es
el contenedor simetrico con ``DataProcesoPLC`` y ``Disp*``.

Convencion: las 9 N_MAX de dispositivos viven en ``extras`` (dict
flexible para absorber futuras hw_types). La 1 N_MAX de entidades
vive en un campo tipado (``n_max_entidades``) porque NO es de
dispositivos y no debe compartir dict con ellas.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping


@dataclass(frozen=True)
class DataDimensionesPLC:
    """N_MAX de UN PLC del Excel.

    Un PLC tiene varios N_MAX (uno por tipo de dispositivo: ED, EA, SA, V,
    M, M_VF, M_SINA, TOT, PID, mas futuros SD/TQ/M_TQ_AE) y 1 N_MAX de
    entidades (``N_MAX_ENTIDAD``).

    Atributos:
        plc_name: nombre del PLC (strict match con TIA Portal).
        extras: ``{nombre_canonico: valor}`` con los N_MAX de
            dispositivos del PLC en el Excel.
        n_max_entidades: dimension del array ``ENT`` de ``DB6_ENT``
            (PlcUserConstant ``N_MAX_ENTIDAD`` en tabla
            ``0_Config_Generales``). Default ``0`` para back-compat
            con Excels sin la columna ``N_Max_ENT``.

    Convenciones:
        - ``get(nmax_name)`` lee un N_MAX de dispositivo por nombre
          canonico TIA (``N_MAX_DISP_ED``, etc.). ``None`` si falta.
          Para entidades usar el campo ``n_max_entidades`` directo.
        - ``to_api_dict()`` retorna copia serializable.
        - Sin I/O, sin imports de ``siemens_tia_scripting`` u openpyxl.
    """

    plc_name: str
    extras: Mapping[str, int] = field(default_factory=dict)
    n_max_entidades: int = 0

    def get(self, nmax_name: str) -> int | None:
        """Lee un N_MAX de dispositivo por nombre canonico de TIA.

        ``None`` si no existe. Para N_MAX de entidades usar el campo
        ``n_max_entidades`` directo (no esta en ``extras``).
        """
        v = self.extras.get(nmax_name)
        return int(v) if v is not None else None

    def to_api_dict(self) -> dict[str, int]:
        """Serializa a ``{nmax_name: int}`` para JSON.

        Incluye el campo ``N_MAX_ENTIDAD`` junto a los ``N_MAX_DISP_*``
        para que la SPA lo muestre en el mismo bloque de cards N_MAX.
        Siempre se serializa (incluso con valor ``0``) para que el
        consumidor no tenga que distinguir "ausente" vs "valor 0".
        """
        out = dict(self.extras)
        out["N_MAX_ENTIDAD"] = self.n_max_entidades
        return out


@dataclass(frozen=True)
class DimensionesDispositivos:
    """Contenedor: una entrada por PLC del Excel.

    Reemplaza el shape pre-multi-PLC (``Mapping[nmax_name, int]`` global).
    Para acceder a los N_MAX de un PLC concreto:
        ``dims.get_for_plc("PLC1").get("N_MAX_DISP_ED")``.

    Atributos:
        por_plc: tupla inmutable de ``DataDimensionesPLC``, una por PLC
            presente en el Excel.

    Convenciones:
        - ``get_for_plc(plc_name)`` devuelve el ``DataDimensionesPLC``
          exacto o ``None``.
        - ``to_api_dict()`` serializa a ``{plc_name: {nmax: int}}``.
    """

    por_plc: tuple[DataDimensionesPLC, ...] = ()

    def get_for_plc(self, plc_name: str) -> DataDimensionesPLC | None:
        """Devuelve el ``DataDimensionesPLC`` del PLC ``plc_name`` o ``None``."""
        for d in self.por_plc:
            if d.plc_name == plc_name:
                return d
        return None

    def to_api_dict(self) -> dict[str, dict[str, int]]:
        """Serializa a ``{plc_name: {nmax_name: int}}`` para JSON."""
        return {d.plc_name: d.to_api_dict() for d in self.por_plc}


__all__ = ["DataDimensionesPLC", "DimensionesDispositivos"]