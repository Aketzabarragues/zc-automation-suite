"""Core application layer: state, progress, logs, area registry.

Esta capa es TRANSVERSAL. NO sabe de áreas concretas: solo expone
servicios comunes (singletons, registry) que las áreas usan para
registrar sus contribuciones.
"""
