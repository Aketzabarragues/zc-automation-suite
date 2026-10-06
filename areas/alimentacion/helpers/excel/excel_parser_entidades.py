"""Parser de ``Tabla_Entidades`` (hoja ``ENTIDADES``).

Lee SOLO 7 campos del Excel confirmados con el operario:
    Required: ``Numero``, ``PLC``, ``PLC.Tag``
    Optional: ``Descripcion``, ``PLC.Comentario``, ``PLC.Tipo``, ``PLC.Index``

Las 30 columnas ``DispX.Tipo/DispX.Tag`` se ignoran
deliberadamente: el sync de entidades NO crea disp nuevos, solo
PlcUserConstants + comentarios sobre ``DB6_ENT.ENT``. Si manana el
Excel suma ``Disp16/Disp17``, el parser no se toca.

Diferencias con el patron de disp:
    * Recibe el workbook **ya abierto** (``wb: Workbook``). NO abre
      el archivo: esa responsabilidad es del ``ExcelLoader``.
    * Sin pandas: openpyxl directo + ``extract_list_object_rows``.
    * Defensivo: cada fila se envuelve en ``try/except``. Filas
      sin ``Numero``, ``PLC`` o ``PLC.Tag`` se descartan con
      ``logger.warning`` (no rompen la carga).
    * El DTO valida tipos en ``__post_init__``; el parser solo
      extrae valores crudos.

Restriccion arquitectonica: este modulo es OFFLINE; no importa
``siemens_tia_scripting``.
"""
from __future__ import annotations

import logging
from typing import Any

from openpyxl import Workbook

from areas.alimentacion.data.data_entidades import Entidad
from areas.alimentacion.helpers.excel._excel_helpers import (
    _safe_int,
    _safe_str,
    extract_list_object_rows,
)


logger = logging.getLogger(__name__)


class EntidadesParser:
    """Parser de la ``Tabla_Entidades`` (hoja ``ENTIDADES``).

    Atributos de clase:
        * ``SHEET``: nombre literal de la hoja (``"ENTIDADES"``).
        * ``TABLE``: nombre de la ``ListObject``
          (``"Tabla_Entidades"``).

    Uso:
        >>> wb = openpyxl.load_workbook(ruta)
        >>> parser = EntidadesParser(wb)
        >>> entidades = parser.parse()
    """

    SHEET = "ENTIDADES"
    TABLE = "Tabla_Entidades"

    def __init__(self, wb: Workbook) -> None:
        self._wb = wb

    def parse(self) -> list[Entidad]:
        """Lee ``Tabla_Entidades`` y devuelve ``list[Entidad]``.

        Politica defensiva:
            * Hoja o tabla inexistente -> ``[]``.
            * Fila sin ``PLC`` o ``PLC.Tag`` -> descartada con WARNING
              (``ValueError`` desde ``Entidad.__post_init__``).
            * ``Numero`` vacio / negativo -> descartada con WARNING.
            * Celdas vacias en columnas opcionales -> defaults
              tolerantes del DTO (``""`` / ``0``).
        """
        raw_rows = extract_list_object_rows(self._wb, self.SHEET, self.TABLE)
        out: list[Entidad] = []
        for idx, raw in enumerate(raw_rows):
            try:
                out.append(self._build(raw))
            except ValueError as exc:
                logger.warning(
                    "EntidadesParser descarta fila %d (%r): %s",
                    idx + 1,
                    {k: raw.get(k) for k in (
                        "Numero", "PLC", "PLC.Tag",
                        "Descripcion", "PLC.Comentario",
                        "PLC.Tipo", "PLC.Index",
                    )},
                    exc,
                )
        logger.info(
            "EntidadesParser: %d entidades cargadas de %d filas",
            len(out),
            len(raw_rows),
        )
        return out

    @staticmethod
    def _build(raw: dict[str, Any]) -> Entidad:
        """Construye un ``Entidad`` desde una fila cruda del Excel."""
        numero = _safe_int(raw.get("Numero"))
        plc_name = _safe_str(raw.get("PLC"))
        plc_tag = _safe_str(raw.get("PLC.Tag"))
        # Validaciones explicitas para emitir mensajes utiles en WARNING.
        if numero < 0:
            raise ValueError(f"Numero negativo ({numero})")
        if not plc_name:
            raise ValueError("PLC vacio")
        if not plc_tag:
            raise ValueError("PLC.Tag vacio")
        return Entidad(
            numero=numero,
            plc_name=plc_name,
            plc_tag=plc_tag,
            descripcion=_safe_str(raw.get("Descripcion")),
            plc_comentario=_safe_str(raw.get("PLC.Comentario")),
            plc_tipo=_safe_int(raw.get("PLC.Tipo")),
            plc_index=_safe_int(raw.get("PLC.Index")),
        )