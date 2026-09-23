"""Helpers transversales para envolver infra TIA con ergonomia async.

Diferencia con ``core/infrastructure/tia/``:
  - ``infrastructure/tia/``: bajo nivel (gateway, handlers, worker).
  - ``helpers/tia/``: wrappers de ergonomia sobre el gateway para
    callers async (cualquier area o FB que quiera hablar con TIA).

Regla arquitectonica: este paquete NO importa
``siemens_tia_scripting``. Solo ``asyncio`` + ``functools``.
"""
from __future__ import annotations

from core.helpers.tia.tia_dispatch_async import dispatch_async
from core.helpers.tia.tia_validate_batch import validate_execute_batch_result


__all__ = ["dispatch_async", "validate_execute_batch_result"]
