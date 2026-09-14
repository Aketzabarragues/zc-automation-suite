"""Data Blocks (DBs) transversales.

Value Objects inmutables compartidos por todas las areas y la capa
SSE/routers. Sin I/O, sin dependencias de TIA: logica pura.

Convencion: prefijo ``data_`` en el nombre de archivo y ``Data`` en el
de la clase (ej: ``data_block_cache.py`` -> ``DataBloqueCache``).
"""
