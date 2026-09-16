"""Loaders del subdominio alimentación.

Aporta el ``ExcelLoader``: componente síncrono que abre el workbook
UNA sola vez y construye el ``DataExcelCache`` con los 10 dominios del
Excel.

Restricción arquitectónica: este paquete NO importa
``siemens_tia_scripting``.
"""
from areas.alimentacion.helpers.loaders.excel_loader import (
    ExcelLoader,
)

__all__ = ["ExcelLoader"]
