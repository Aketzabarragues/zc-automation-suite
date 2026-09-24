"""Cache IT del Excel: dispositivos + N_MAX + 4 listas de software.

Fuente de verdad unica que ``ExcelCacheManager`` cachea por proceso.
``frozen=True`` para que el cache sea inmutable entre lecturas.
"""
from __future__ import annotations

import dataclasses
from dataclasses import dataclass, field
from datetime import datetime
from typing import Mapping

from areas.alimentacion.data.data_alarmas import DataAlarmaPLC
from areas.alimentacion.data.data_dispositivos import Dispositivo
from areas.alimentacion.data.data_dimensiones import DimensionesDispositivos
from areas.alimentacion.data.data_parametros_int import DataParamIntPLC
from areas.alimentacion.data.data_ParametrosReal import DataParamRealPLC
from areas.alimentacion.data.data_Procesos import DataProcesoPLC


@dataclass(frozen=True)
class DataExcelCache:
    """Cache IT del Excel corporativo. Inmutable.

    Atributos:
      - ``excel_path``: ruta absoluta del Excel cacheado.
      - ``excel_mtime_ns``: ``st_mtime_ns`` del Excel (Windows-safe).
      - ``parsed_at``: ``datetime`` UTC del parseo.
      - ``dispositivos``: ``{hw_type: tuple[Dispositivo, ...]}``.
      - ``n_max``: ``DimensionesDispositivos`` con nombres canonicos
        de TIA (``N_MAX_DISP_*``).
      - ``procesos`` / ``parametros_real`` / ``parametros_int`` /
        ``alarmas``: listas de los 4 dominios de software.
      - ``*_by_codigo``: lookups ``Mapping[str, DTO]`` precomputados.
      - ``software_parsers_implemented``: flag para la SPA.
    """

    excel_path: str
    excel_mtime_ns: int
    parsed_at: datetime
    dispositivos: dict[str, tuple[Dispositivo, ...]]
    n_max: DimensionesDispositivos
    procesos: tuple[DataProcesoPLC, ...]
    parametros_real: tuple[DataParamRealPLC, ...]
    parametros_int: tuple[DataParamIntPLC, ...]
    alarmas: tuple[DataAlarmaPLC, ...]
    procesos_by_codigo: Mapping[str, DataProcesoPLC]
    parametros_real_by_codigo: Mapping[str, DataParamRealPLC]
    parametros_int_by_codigo: Mapping[str, DataParamIntPLC]
    software_parsers_implemented: bool = True

    def to_dict(self) -> dict:
        """Serializa a JSON. Lookups precomputados omitidos (son derivables)."""
        return {
            "excel_path": self.excel_path,
            "excel_mtime_ns": self.excel_mtime_ns,
            "parsed_at": self.parsed_at.isoformat(),
            "n_max": self.n_max.to_api_dict(),
            "procesos": [dataclasses.asdict(p) for p in self.procesos],
            "parametros_real": [dataclasses.asdict(p) for p in self.parametros_real],
            "parametros_int": [dataclasses.asdict(p) for p in self.parametros_int],
            "alarmas": [dataclasses.asdict(a) for a in self.alarmas],
            "software_parsers_implemented": self.software_parsers_implemented,
        }


__all__ = ["DataExcelCache"]
