"""Loaders del subdominio alimentaciÃƒÂ³n.

Aporta el ``ExcelLoader``: componente sÃƒÂ­ncrono que abre el workbook
UNA sola vez y construye el ``DataExcelCache`` con los 10 dominios del
Excel.

RestricciÃƒÂ³n arquitectÃƒÂ³nica: este paquete NO importa
``siemens_tia_scripting``.
"""
from areas.alimentacion.helpers.loaders.excel_loader import (
    ExcelLoader,
)

__all__ = ["ExcelLoader"]
