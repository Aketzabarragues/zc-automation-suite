"""Core infrastructure layer: gateway, TIA worker, XML/SD modifiers, parsers, config.

Esta capa es TRANSVERSAL. NO sabe de áreas concretas: solo expone
adaptadores comunes (gateway hacia TIA Portal, modificadores
SimaticML/SD, parsers base) que las áreas usan para registrar sus
contribuciones.
"""
