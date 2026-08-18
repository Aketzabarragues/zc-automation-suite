"""DEPRECATED — Reemplazado por ``interfaces/web_server/app.py``.

Este archivo se conserva vacío para no romper imports antiguos
mientras se completa la migración. La factoría oficial es
``create_app(gateway)`` en ``interfaces.web_server.app``, que
ensambla los routers vía ``app.include_router(...)`` y deja las
dependencias en ``app.state`` para los ``Depends``.
"""
from __future__ import annotations

# Intencionalmente sin código: la implementación vive en ``app.py``.
