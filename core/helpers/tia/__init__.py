"""Helpers transversales para hablar con la infraestructura TIA.

Diferencia con ``core/infrastructure/tia/``:
  - ``infrastructure/tia/``: bajo nivel (comandos TIA, worker OT, cache).
  - ``helpers/tia/``: utilidades sobre los comandos TIA para cualquier
    area o FB que quiera hablar con TIA.

Regla arquitectonica: este paquete NO importa
``siemens_tia_scripting``. Solo ``functools``.

Los FBs hablan con TIA a traves de ``SyncTIAClient.submit_and_wait``
sobre el cliente que inyecta el supervisor. No hay wrapper async: los
FBs se ejecutan en el hilo del dispatcher del OB1, sin event loop.
"""
from __future__ import annotations

from core.helpers.tia.tia_validate_batch import validate_execute_batch_result


__all__ = ["validate_execute_batch_result"]
