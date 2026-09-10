"""Cache del Excel corporativo (subdominio alimentación).

Aporta el ``ExcelCacheManager``: Singleton por proceso que cachea
una sola ``ExcelCache`` (raíz con los 10 dominios del Excel).

Restricción arquitectónica: este paquete NO importa
``siemens_tia_scripting``. Solo ``asyncio`` + ``logging`` + DTOs
del subdominio.
"""
from areas.alimentacion.infrastructure.cache.excel_cache_manager import (
    ExcelCacheManager,
)

__all__ = ["ExcelCacheManager"]
