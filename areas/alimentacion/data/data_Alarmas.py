"""areas.alimentacion.data.data_Alarmas — Data Block de AlarmaPLC.

Fase 3, paso 3.2.7.  Migrado de ``areas/alimentacion/domain/models/excel_cache.py``.

Una **alarma** es un bit de un DB de alarmas (``DB{num_db}``) que el
HMI monitoriza para senalizar un evento.  Las alarmas se agrupan en
un DB por proceso: ``DB{num_db}_{proceso_codigo}_ALM`` (uno por proceso,
contiene varios ``AlarmaPLC`` consecutivos en una ``ARRAY[0..N] OF BOOL``
o similar).

Mas simple que ``DataParamRealPLC`` / ``DataParamIntPLC`` (7 campos, sin
``Visibilidad``/``Producto``/``Tipo``/``num_lista``/``txt_lista``).  La
razon es historica: el legacy TUI define ``Alarma`` con solo 6 columnas
en la ``ListObject`` (``UID``, ``Numero``, ``Proceso``, ``Num.DB``,
``Descripcion``, ``ComentarioDB``); ``Visibilidad`` no existe en esta
tabla.

R-F4.1 (defensa contra schema drift): si el Excel del corporativo
incluye en el futuro una columna ``Visibilidad`` en ``Tabla_Alarmas``,
el parser la **ignora silenciosamente**.  El DTO ``DataAlarmaPLC`` NO
tiene atributo ``visibilidad`` por diseno.

El legacy sigue coexistiendo (DA-006) hasta Fase 4 (4.0.2).
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class DataAlarmaPLC:
    """DTO de una alarma del PLC (hoja ``ALARMAS`` -> ``Tabla_Alarmas``).

    Campos (7):
      - ``uid``: identificador unico **str** (``'AL_1_001'``).
      - ``numero``: nº logico de la alarma (``"001"``, ``"002"``).
      - ``proceso``: nombre del proceso al que pertenece la alarma.
      - ``num_db``: nº del DB de alarmas donde se mapea este bit.
      - ``descripcion``: descripcion legible (visible en HMI al activarse).
      - ``comentario_db``: comentario del DB (no del bit).
    """

    uid: str
    numero: str
    proceso: str
    num_db: int
    descripcion: str
    comentario_db: str


__all__ = ["DataAlarmaPLC"]
