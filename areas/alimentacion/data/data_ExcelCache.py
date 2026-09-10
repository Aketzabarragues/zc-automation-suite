"""areas.alimentacion.data.data_ExcelCache — Data Block raiz del cache del Excel.

Fase 3, paso 3.2.3.  Migrado de ``areas/alimentacion/domain/models/excel_cache.py``
(que contiene el root ``ExcelCache`` + los DTOs hoja).  Esta migracion
se hace al final del bloque 3.2 (despues de 3.2.4-3.2.7) porque la
raiz importa los DTOs hoja: ``DataProcesoPLC``, ``DataParamRealPLC``,
``DataParamIntPLC``, ``DataAlarmaPLC``, ``DataDimensionesDispositivos``.

Esta dataclass ``frozen=True`` agrupa TODOS los datos derivados del
Excel (10 dominios: 6 dispositivos + N_MAX + 4 software) en una sola
estructura inmutable.  Es la **unica fuente de verdad** que
``ExcelCacheManager`` cachea por proceso.

Diseno:
  - ``dispositivos``: ``dict[hw_type, tuple[Dispositivo, ...]]`` (los 6
    tipos legacy como ``tuple`` para preservar ``frozen=True``).
  - ``n_max``: ``DataDimensionesDispositivos`` con los 6 contadores
    canonicos + ``extras`` para N_MAX adicionales.
  - ``procesos`` / ``parametros_real`` / ``parametros_int`` / ``alarmas``:
    las 4 listas de software (tambien ``tuple``).
  - ``*_by_codigo``: lookups ``Mapping[str, DTO]`` precomputados para
    evitar O(n) por cada acceso.
  - ``software_parsers_implemented``: flag para que la SPA detecte si
    el backend expone los 4 dominios nuevos.

El legacy sigue coexistiendo (DA-006) hasta Fase 4 (4.0.2).
"""
from __future__ import annotations

import dataclasses
from dataclasses import dataclass, field
from datetime import datetime
from typing import Mapping

from areas.alimentacion.data.data_Alarmas import DataAlarmaPLC
from areas.alimentacion.data.data_Dispositivos import Dispositivo
from areas.alimentacion.data.data_Dimensiones import DimensionesDispositivos
from areas.alimentacion.data.data_ParametrosInt import DataParamIntPLC
from areas.alimentacion.data.data_ParametrosReal import DataParamRealPLC
from areas.alimentacion.data.data_Procesos import DataProcesoPLC


@dataclass(frozen=True)
class DataExcelCache:
    """Raiz del cache IT del Excel corporativo.

    Atributos:
      - ``excel_path``: ruta absoluta del Excel actualmente cacheado.
      - ``excel_mtime_ns``: ``st_mtime_ns`` del Excel (resolucion
        Windows-safe para invalidacion por mtime).
      - ``parsed_at``: ``datetime`` UTC del parseo.
      - ``dispositivos``: ``{hw_type: tuple[Dispositivo, ...]}``.
      - ``n_max``: cantidades de dispositivos por tipo.
      - ``procesos`` / ``parametros_real`` / ``parametros_int`` /
        ``alarmas``: listas de los 4 dominios de software.
      - ``procesos_by_codigo`` / ``parametros_real_by_codigo`` /
        ``parametros_int_by_codigo``: lookups precomputados por
        ``codigo`` (Mapping para preservar ``frozen=True``).
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
        """Serializa las 4 listas a JSON (lookups omitidos, son derivables).

        Returns:
            ``dict`` con ``excel_path``, ``excel_mtime_ns``,
            ``parsed_at`` (ISO), ``n_max`` (via ``to_api_dict``),
            las 4 listas de software via ``dataclasses.asdict``, y el
            flag ``software_parsers_implemented``.  Los lookups
            precomputados NO se serializan: son derivables iterando
            las listas.
        """
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
