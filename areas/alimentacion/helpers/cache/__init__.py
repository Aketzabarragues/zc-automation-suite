"""Cache del Excel corporativo (subdominio alimentaciÃƒÂ³n).

Aporta el ``ExcelCacheManager``: Singleton por proceso que cachea
una sola ``DataExcelCache`` (raÃƒÂ­z con los 10 dominios del Excel).

RestricciÃƒÂ³n arquitectÃƒÂ³nica: este paquete NO importa
``siemens_tia_scripting``. Solo ``asyncio`` + ``logging`` + DTOs
del subdominio.
"""
from areas.alimentacion.helpers.cache.excel_cache_manager import (
    ExcelCacheManager,
)

__all__ = ["ExcelCacheManager"]
