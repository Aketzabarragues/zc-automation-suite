"""Capa de Aplicación (Casos de Uso).

Orquesta la interacción entre el Dominio (``core/``), la Infraestructura
(``infrastructure/``) y la Presentación (``interfaces/``). Aquí residen
los flujos de negocio asíncronos que cruzan el estado *deseado* (Excel)
con el estado *actual* (TIA Portal) bajo transacciones atómicas.
"""
