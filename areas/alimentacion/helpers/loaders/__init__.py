"""Loaders del subdominio alimentaciÃ³n.

Aporta el ``ExcelLoader``: componente sÃ­ncrono que abre el workbook
UNA sola vez y construye el ``ExcelCache`` con los 10 dominios del
Excel.

RestricciÃ³n arquitectÃ³nica: este paquete NO importa
``siemens_tia_scripting``.
"""
from areas.alimentacion.helpers.loaders.excel_loader import (
    ExcelLoader,
)

__all__ = ["ExcelLoader"]
