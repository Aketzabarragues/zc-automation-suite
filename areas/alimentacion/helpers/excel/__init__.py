"""Excel: loader, cache manager y parsers del subdominio alimentación.

Aporta:
  - ``ExcelLoader``: abre el workbook UNA sola vez y construye el
    ``DataExcelCache`` con los 10 dominios del Excel.
  - ``ExcelCacheManager``: Singleton por proceso que cachea una sola
    ``DataExcelCache``.

Restricción arquitectónica: este paquete NO importa
``siemens_tia_scripting``.
"""
from areas.alimentacion.helpers.excel.excel_loader import ExcelLoader
from areas.alimentacion.helpers.excel.excel_cache_manager import (
    ExcelCacheManager,
)

__all__ = ["ExcelLoader", "ExcelCacheManager"]
