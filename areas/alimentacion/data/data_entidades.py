"""Data Block de entidades (DB6_ENT.ENT).

DTO minimo (7 campos) leido del Excel ``Tabla_Entidades`` (hoja
``ENTIDADES``). Las 30 columnas ``DispX.Tipo/DispX.Tag`` del Excel NO
se procesan: el sync no crea disp nuevos, solo PlcUserConstants y
comentarios sobre el array ``ENT`` de ``DB6_ENT``.

Convencion: ``frozen=True``, sin I/O, sin imports de
``siemens_tia_scripting`` u openpyxl. Replica el patron de
``data_dispositivos.py``.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Entidad:
    """Una entidad del Excel ``Tabla_Entidades``.

    Cada fila del Excel se traduce a:

      * 1 PlcUserConstant ``plc_tag`` con ``value = numero``
        (gestionadas por ``update_user_constant_*`` del TIA worker).
      * 1 comentario en ``DB6_ENT.ENT[numero]`` (escrito por
        ``commit_array_comments`` con ``array_type="UDT"``).

    Campos:
        numero:            slot del array ``ENT`` + ``value`` de la PlcUserConstant.
        plc_name:          filtro multi-PLC (una Entidad por PLC).
        plc_tag:           nombre de la PlcUserConstant homonima.
        descripcion:       nombre legible en UI.
        plc_comentario:    comentario a aplicar a ``DB6_ENT.ENT[numero]``.
        plc_tipo:          ``tipo`` de la PlcUserConstant (metadata, opcional).
        plc_index:         ``index`` de la PlcUserConstant (metadata, opcional).

    Los 3 primeros son required; el resto tiene defaults tolerantes
    (``""`` para ``str``, ``0`` para ``int``) para tolerar filas del
    Excel con celdas vacias en columnas opcionales.
    """

    numero: int
    plc_name: str
    plc_tag: str
    descripcion: str = ""
    plc_comentario: str = ""
    plc_tipo: int = 0
    plc_index: int = 0

    def __post_init__(self) -> None:
        if self.numero < 0:
            raise ValueError(
                f"Entidad.numero debe ser >= 0, got {self.numero!r}"
            )
        if not self.plc_name:
            raise ValueError("Entidad.plc_name no puede ser vacio")
        if not self.plc_tag:
            raise ValueError("Entidad.plc_tag no puede ser vacio")