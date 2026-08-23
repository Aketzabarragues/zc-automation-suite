"""Marcador de paquete.

Los casos de uso del proyecto se organizan por área de negocio bajo
``application/areas/<area>/use_cases/``. Por ejemplo:

  - application/areas/alimentacion/use_cases/sync_disp_alimentacion.py
  - application/areas/alimentacion/use_cases/diff_constants.py

Este paquete raíz se conserva únicamente para evitar imports rotos en
herramientas externas (linters, IDEs) que esperan ``application.use_cases``
como punto de entrada. NO añadir nuevos use cases aquí.
"""
