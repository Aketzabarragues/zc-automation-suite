"""Capa de infraestructura: caches IT en memoria.

Singletons por proceso que mantienen el estado IT cacheado entre llamadas
al worker OT. Aqui vive ``BloqueCacheManager`` (caches de bloques de PLC
escaneados). Los caches de bloques existentes en
``TIAProcessGateway._cache`` siguen siendo el origen canonico para
lecturas ligeras (lista de PLCs, listas de bloques simples); este paquete
aporta caches especializados (bloques + tag tables con metadata completa).
"""
