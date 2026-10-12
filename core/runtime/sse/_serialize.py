"""core.runtime.sse._serialize - normalizacion de payloads para SSE.

Los publishers pasan valores (a menudo dataclasses u objetos vivos
de TIA/.NET) que ``json.dumps`` no sabe serializar. Este helper
convierte cualquier valor a algo serializable por ``json.dumps``
aplicando reglas en orden hasta agotar el tipo:

Reglas (en orden):
  1. ``None`` / ``str`` / ``int`` / ``float`` / ``bool`` -> tal cual.
  2. ``datetime`` -> ``isoformat()``.
  3. ``tuple`` / ``list`` -> recursivo sobre cada elemento.
  4. ``dict`` -> recursivo sobre cada valor (claves se mantienen).
  5. objeto con metodo ``to_dict()`` -> llamada y luego recursivo
     (tiene prioridad sobre ``asdict`` para que un dataclass que
     expone ``to_dict()`` use la shape plana del dominio en lugar
     de la estructura interna de la dataclass).
  6. ``dataclass`` (vía ``dataclasses.is_dataclass``) -> ``asdict()``
     y luego recursivo.
  7. resto -> ``repr()`` como fallback (mejor que un TypeError en
     el generador SSE).

Uso:
    from core.runtime.sse._serialize import to_jsonable
    bus.publish({"type": "cache_changed", "data": to_jsonable(value)})

Restricciones:
    - No es un serializador universal: objetos con estado no
      dictable (locks, conexiones, .NET RCW) caen al ``repr()``.
      Los publishers deben seguir mapeando sus DTOs nativos a
      dicts planos en el worker (regla ``.clinerules`` sec. 3) y
      usar este helper solo como red de seguridad.
"""
from __future__ import annotations

from dataclasses import asdict, is_dataclass
from datetime import datetime
from typing import Any


def to_jsonable(value: Any) -> Any:
    """Convierte ``value`` a una estructura JSON-serializable.

    Aplica las reglas descritas en el docstring del modulo en
    orden hasta agotar el tipo. El fallback final ``repr()``
    garantiza que NUNCA lanza ``TypeError`` por tipos opacos;
    eso es preferible a tirar la conexion SSE del operario.
    """
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, (list, tuple)):
        return [to_jsonable(v) for v in value]
    if isinstance(value, dict):
        return {k: to_jsonable(v) for k, v in value.items()}
    # Regla 5: ``to_dict()`` tiene prioridad sobre ``asdict`` para que
    # un dataclass que expone ``to_dict()`` (``DataExcelCache``,
    # ``PlcInfo``, ``PlcProject``) use la shape plana del dominio y
    # no la estructura interna de la dataclass.
    to_dict = getattr(value, "to_dict", None)
    if callable(to_dict):
        try:
            return to_jsonable(to_dict())
        except Exception:  # noqa: BLE001
            return repr(value)
    # Regla 6: dataclass sin ``to_dict()`` -> ``asdict``.
    if is_dataclass(value):
        return to_jsonable(asdict(value))
    return repr(value)


__all__ = ["to_jsonable"]