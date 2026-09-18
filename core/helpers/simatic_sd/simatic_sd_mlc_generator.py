"""Generador de IDs MLC unicos para archivos SimaticSD (.s7res).

Sept-2026 refactor DRY: reemplaza al ``MLCRegistry`` (viejo, con state
machine + reserve/next_mlc_id) por funciones puras mas simples.

TIA Portal V21 espera que cada bloque ``{ S7_MLC := "MLC_xxx"; }`` en
el .s7dcl tenga su entrada correspondiente en el .s7res:

    - id: MLC_xxx
      es-ES: "texto del comentario"

El ID es un string de 4-5 caracteres alfanumericos (TIA acepta cualquier
combinacion; hemos visto ``MLC_q2``, ``MLC_Dz8``, ``MLC_hsVUv`` etc.
mezclando may/min con numeros). El prefijo ``MLC_`` es obligatorio.

Este modulo ofrece dos funciones puras:
  - ``collect_existing_mlc_ids(res_text)``: extrae todos los IDs
    MLC referenciados en el .s7res.
  - ``next_mlc_id(used_ids)``: genera un ID nuevo que no colisiona
    con los existentes.

El consumidor (commit_array_comments, etc.) es responsable de:
  1. Llamar ``collect_existing_mlc_ids`` para obtener el set actual.
  2. Llamar ``next_mlc_id(used)`` cada vez que necesite uno nuevo.
  3. Anadir el ID nuevo al set usado para las siguientes llamadas.
"""
from __future__ import annotations

import re
import uuid


# Regex para extraer IDs MLC del .s7res (formato YAML plano).
# El formato real es:
#
#   MultiLingualTexts:
#     - id: MLC_xxx
#       es-ES: "texto"
#     - id: MLC_yyy
#       es-ES: "otro texto"
#
# Aceptamos tambien lineas con indentacion variable.
_MLC_ID_RE = re.compile(
    r"""^\s*-\s*id\s*:\s*(?P<id>MLC_[A-Za-z0-9_]+)\s*$""",
    re.MULTILINE,
)


def collect_existing_mlc_ids(res_text: str) -> set[str]:
    """Extrae todos los IDs MLC presentes en el texto del .s7res.

    Acepta el formato YAML plano que exporta TIA V21 (entradas
    ``- id: MLC_xxx`` en lineas separadas). Si el .s7res tiene
    otro formato, devuelve set vacio (el caller debe manejarlo).

    Args:
        res_text: contenido completo del archivo .s7res.

    Returns:
        Set con los IDs ``MLC_*`` encontrados (sin duplicados).
    """
    return set(_MLC_ID_RE.findall(res_text))


def next_mlc_id(used_ids: set[str]) -> str:
    """Genera un ID MLC nuevo que NO colisiona con ``used_ids``.

    Usa ``uuid.uuid4().hex[:5]`` (5 chars hex, 0-9a-f) que es
    compatible con TIA V21 (hemos visto IDs hex puros como ``MLC_q2``
    en exports reales).

    Args:
        used_ids: Set de IDs ya usados (se debe actualizar con el
            nuevo ID tras llamar a esta funcion).

    Returns:
        ID nuevo, formato ``MLC_xxxxx`` (5 chars hex).

    Raises:
        RuntimeError: Si tras 16 intentos no se encuentra un ID unico
            (probabilidad astronomicamente baja: 16/16^5 = ~1e-6).
    """
    for _ in range(16):
        candidate = f"MLC_{uuid.uuid4().hex[:5]}"
        if candidate not in used_ids:
            return candidate
    # Si llegamos aqui, uuid fallo 16 veces seguidas (practicamente
    # imposible: espacio de 16^5 = 1M IDs).
    raise RuntimeError(
        "next_mlc_id: no se pudo generar un ID unico tras 16 intentos. "
        "El .s7res probablemente tiene 1M+ IDs MLC (saturacion imposible "
        "en la practica; revisar el archivo)."
    )


__all__ = [
    "collect_existing_mlc_ids",
    "next_mlc_id",
]
