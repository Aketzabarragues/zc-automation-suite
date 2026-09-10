"""Registro en memoria de IDs MLC únicos por ``.s7res``.

Restricción arquitectónica: este módulo es OFFLINE; no importa
``siemens_tia_scripting``. Solo usa ``random`` + ``string`` de la
stdlib.

Convención de IDs MLC
---------------------
Los IDs MLC son las claves que cruzan un archivo ``.s7dcl`` con su
``.s7res`` asociado (formato Simatic Source Documents de Siemens).
TIA los genera como strings aleatorios tipo ``MLC_aB7xQ`` (3-5
caracteres alfanuméricos precedidos de ``MLC_``).

Responsabilidad
---------------
Esta clase garantiza que los MLCs nuevos que inventamos no colisionen
con:
  1. Los MLCs ya existentes en el ``.s7res`` que estamos procesando.
  2. Los MLCs que hemos generado previamente en esta misma sesión de
     actualización.

No persiste estado en disco: la "fuente de verdad" entre runs es el
propio ``.s7res`` (lo que está escrito en él); este registro es solo
un seguro en memoria para evitar colisiones dentro de UN update.
"""
from __future__ import annotations

import logging
import random
import string
from typing import Iterable


_logger: logging.Logger = logging.getLogger(f"{__name__}.MLCRegistry")

# Alfabeto usado para generar MLCs: alfanumérico + "_" (mismo set
# que Siemens usa). Excluimos caracteres visualmente confusos (0/O,
# 1/l/I) para minimizar errores de transcripción en logs.
_MLC_ALPHABET: str = "abcdefghijkmnpqrstuvwxyzABCDEFGHJKLMNPQRSTUVWXYZ23456789"

# Rango de longitud del sufijo aleatorio (3-5 chars). Coherente con
# los ejemplos de Siemens (MLC_32c, MLC_3Vz, MLC_3vw, MLC_wT).
_MLC_LEN_MIN: int = 3
_MLC_LEN_MAX: int = 5

# Prefijo obligatorio de todo MLC.
_MLC_PREFIX: str = "MLC_"

# Número máximo de intentos para encontrar un MLC no colisionante
# antes de abortar. Con 3-5 chars alfanuméricos (~55^5 = 503M
# combinaciones) el espacio es prácticamente infinito; 50 intentos
# es un tope defensivo para el caso de un registry saturado.
_MAX_ATTEMPTS: int = 50


class MLCRegistry:
    """Set en memoria de MLCs únicos durante la sesión del worker.

    El uso típico es::

        registry = MLCRegistry()
        registry.reserve(existing_mlcs_from_s7res)   # IDs previos
        new_id = registry.next_mlc_id()              # genera uno nuevo
        # ... usar new_id ...
        registry.release(new_id)                     # si se descarta
    """

    def __init__(self, used_ids: Iterable[str] | None = None) -> None:
        self._used: set[str] = set(used_ids) if used_ids else set()

    def reserve(self, used_ids: Iterable[str]) -> None:
        """Añade IDs al set (los del ``.s7res`` actual al abrir)."""
        new_ids = set(used_ids)
        added = len(new_ids - self._used)
        self._used |= new_ids
        if added:
            _logger.debug(
                f"MLCRegistry.reserve: {added} IDs nuevos añadidos "
                f"(total: {len(self._used)})."
            )

    def is_used(self, mlc_id: str) -> bool:
        """Devuelve ``True`` si ``mlc_id`` está registrado."""
        return mlc_id in self._used

    __contains__ = is_used  # azúcar: ``mlc_id in registry``

    def release(self, mlc_id: str) -> None:
        """Saca ``mlc_id`` del set (cuando se elimina del ``.s7res``).

        Es seguro llamar a ``release`` con un ID que no estaba
        registrado (no-op).
        """
        self._used.discard(mlc_id)

    def next_mlc_id(self) -> str:
        """Genera un MLC nuevo no colisionante.

        Formato: ``MLC_<sufijo_aleatorio>`` con sufijo de 3-5 chars
        del alfabeto ``_MLC_ALPHABET``.

        Raises:
            RuntimeError: si tras ``_MAX_ATTEMPTS`` intentos no se
                          encuentra un ID libre (improbable salvo
                          registry saturado o bug).
        """
        for _ in range(_MAX_ATTEMPTS):
            length = random.randint(_MLC_LEN_MIN, _MLC_LEN_MAX)
            suffix = "".join(random.choices(_MLC_ALPHABET, k=length))
            candidate = f"{_MLC_PREFIX}{suffix}"
            if candidate not in self._used:
                self._used.add(candidate)
                return candidate
        raise RuntimeError(
            f"MLCRegistry: no se pudo generar un MLC único tras "
            f"{_MAX_ATTEMPTS} intentos (registry saturado: "
            f"{len(self._used)} IDs en uso)."
        )

    def __len__(self) -> int:
        return len(self._used)


__all__ = ["MLCRegistry"]
