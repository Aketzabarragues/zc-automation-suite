"""Cache del Excel corporativo (subdominio alimentaciÃ³n).

Aporta el ``ExcelCacheManager``: Singleton por proceso que cachea
una sola ``ExcelCache`` (raÃ­z con los 10 dominios del Excel).

RestricciÃ³n arquitectÃ³nica: este paquete NO importa
``siemens_tia_scripting``. Solo ``asyncio`` + ``logging`` + DTOs
del subdominio.
"""
from areas.alimentacion.helpers.cache.excel_cache_manager import (
    ExcelCacheManager,
)

__all__ = ["ExcelCacheManager"]
