"""Core infrastructure layer: gateway, TIA worker, parsers base, cache, config.

Esta capa es TRANSVERSAL. NO sabe de áreas concretas: solo expone
adaptadores comunes (gateway hacia TIA Portal, parsers base genéricos,
cache IT en memoria) que las áreas usan para registrar sus
contribuciones.

Importante: los MODIFICADORES SimaticML/SD son específicos de cada
área y viven en ``areas/<area>/infrastructure/xml/`` y
``areas/<area>/infrastructure/sd/``, NO aquí. Esta capa solo aporta
el gateway y los parsers base que no saben de áreas.
"""
