"""Generador y parser de MLCs en archivos SimaticSD (.s7res).

TIA Portal V21 espera que cada bloque ``{ S7_MLC := "MLC_xxx"; }`` en
el .s7dcl tenga su entrada correspondiente en el .s7res:

    - id: MLC_xxx
      es-ES: "texto del comentario"

El ID es un string de 4-5 caracteres alfanumericos (TIA acepta cualquier
combinacion; hemos visto ``MLC_q2``, ``MLC_Dz8``, ``MLC_hsVUv`` etc.
mezclando may/min con numeros). El prefijo ``MLC_`` es obligatorio.

Funciones puras expuestas:
  - ``collect_existing_mlc_ids(res_text)``: extrae todos los IDs
    MLC referenciados en el .s7res.
  - ``next_mlc_id(used_ids)``: genera un ID nuevo que no colisiona
    con los existentes.
  - ``parse_mlc_lookup(res_text)``: devuelve el mapping
    ``MLC_id -> texto es-ES`` para resolver IDs a texto en espanol.

El consumidor (commit_array_comments, editor de bloques, etc.) es
responsable de:
  1. Llamar ``collect_existing_mlc_ids`` para obtener el set actual.
  2. Llamar ``next_mlc_id(used)`` cada vez que necesite uno nuevo.
  3. Anadir el ID nuevo al set usado para las siguientes llamadas.
  4. Usar ``parse_mlc_lookup`` para resolver IDs del ``.s7dcl`` al
     texto visible en TIA.
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


def parse_mlc_lookup(res_text: str) -> dict[str, str]:
    """Parsea un ``.s7res`` y devuelve el mapping ``MLC_id -> texto es-ES``.

    El ``.s7res`` de TIA V21 tiene un bloque ``MultiLingualTexts:`` con
    entradas ``- id: MLC_xxx`` y campos por idioma (``es-ES``, ``en-US``,
    ``de-DE``). Esta funcion extrae el ``id`` y el texto ``es-ES`` (con
    fallback a ``en-US``/``de-DE`` si falta) en un dict plano para
    busqueda O(1).

    Pensada para:
      - el helper ``commit_array_comments`` (resuelve el MLC del slot).
      - el editor de bloques TIA (resuelve ``S7_BlockTitle`` y
        ``S7_BlockComment`` del ``.s7dcl`` a texto en espanol del
        ``.s7res``).
      - cualquier feature que necesite mapear ``MLC_id`` a texto.

    Args:
        res_text: contenido completo del archivo ``.s7res`` (UTF-8,
            plano YAML). Si esta vacio o ``None``, retorna dict vacio.

    Returns:
        ``dict[str, str]`` con keys ``MLC_xxx`` y values con el texto
        ``es-ES`` (fallback a ``en-US`` o ``de-DE``). Filtra entradas
        sin ``id`` o que no empiecen por ``MLC_``.

    Notes:
        - Usa ``yaml.safe_load`` (no ``yaml.load``) por seguridad.
        - Si el YAML esta corrupto o no tiene ``MultiLingualTexts``,
          retorna ``{}`` (no raise). El caller decide si falla.
        - IDs repetidos: mantiene el ultimo.
    """
    import yaml  # Lazy: el modulo ya importa 're' y 'uuid'; anadir yaml
                # al top-level penaliza el coste de import de callers que
                # solo necesitan ``next_mlc_id`` o ``collect_existing_mlc_ids``.

    if not res_text:
        return {}

    try:
        res_data = yaml.safe_load(res_text) or {}
    except yaml.YAMLError:
        return {}

    textos = res_data.get("MultiLingualTexts", []) or []
    out: dict[str, str] = {}
    for entry in textos:
        if not isinstance(entry, dict):
            continue
        mlc_id = entry.get("id", "")
        if not mlc_id or not mlc_id.startswith("MLC_"):
            continue
        text = (
            entry.get("es-ES")
            or entry.get("en-US")
            or entry.get("de-DE")
            or ""
        )
        out[mlc_id] = text
    return out


__all__ = [
    "collect_existing_mlc_ids",
    "next_mlc_id",
    "parse_mlc_lookup",
]
