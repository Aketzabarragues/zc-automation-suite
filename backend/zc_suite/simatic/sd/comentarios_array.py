"""Helper para actualizar comentarios de arrays en DBs SimaticSD.

Version simple (sin estado mutable, sin dataclasses, sin parser
custom). Cuatro casos explicitos al iterar sobre los indices:
insertar, eliminar, actualizar o anadir MLC.

Caso de uso tipico (FB el sync de procesos, Tx B):
  >>> from zc_suite.simatic.sd import confirmar_comentarios_array
  >>> # Para PReal (UDT) + PReal_Vis (Bool) + Aux.PReal_ValorAnterior (Real)
  >>> for nombre_array, tipo_array, mapa_indices in [
  ...     ("PReal",                   "UDT",  preal_map),
  ...     ("PReal_Vis",               "Bool", preal_map),
  ...     ("Aux.PReal_ValorAnterior", "Real", preal_map),
  ...     ("PInt",                    "UDT",  pint_map),
  ...     ("PInt_Vis",                "Bool", pint_map),
  ...     ("Aux.PInt_ValorAnterior",  "Int",  pint_map),
  ... ]:
  ...     confirmar_comentarios_array(dcl, res, nombre_array, mapa_indices, tipo_array=tipo_array)

Formato .s7dcl esperado (TIA V21 export):
  DATA_BLOCK DB...
      VAR RETAIN
          { S7_MLC := "MLC_q2"; }
          PReal : Array[0..N] of _.UDT_ZC_PREAL;  <-- indice 0 = "NO USAR" (placeholder)
      END_VAR
      ...
      PReal[1].Valor := 50.0;        <-- Seccion A (inline / inicializacion)
      PReal_Vis[1] := FALSE;
      PInt_Vis[1] := false;
      { S7_MLC := "MLC_GXnT"; }       <-- MLC antes de la siguiente asignacion
      PInt_Vis[2] := false;
  END_VAR                               <-- fin Seccion A

      { S7_MLC := "MLC_Dz8"; }         <-- MLC antes de la asignacion
      PReal[1] := ();                   <-- Seccion B (standalone / MLCs)
      ...
  END_DATA_BLOCK

El helper maneja los 4 casos (mismo algoritmo que el script del
operario, parametrizado y testeable):

  - **A. Inyectar**: el indice no existe en el .s7dcl. Inserta
    ``{ MLC } Nombre[X] := ();`` antes de ``END_DATA_BLOCK``.
  - **B. Eliminar**: el indice existe con MLC y el comentario nuevo es
    vacio. Quita el MLC del bloque; si el bloque queda vacio y la
    asignacion es ``:= ()`` (ancla vacia), borra toda la linea.
  - **C. Actualizar**: el indice existe con MLC y comentario nuevo.
    Cambia el texto en .s7res (YAML).
  - **D. Anadir MLC**: el indice existe SIN MLC adyacente. Esto pasa
    en TIA cuando ``PReal_Vis[1] := FALSE;`` se escribio sin un
    bloque ``{ S7_MLC := ... }`` delante. Inyecta el bloque.

Tipo del array:
  - ``UDT`` (PReal, PInt): el indice es una struct con sub-campos. El
    helper busca la asignacion RAIZ ``Nombre[X] := ();`` (no los
    sub-campos ``.Valor``, ``.Maximo``, etc.).
  - ``Simple`` (Bool, Int, Real, etc.): el indice es un valor escalar.
    El helper busca cualquier asignacion ``Nombre[X] := <valor>;``.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from zc_suite.simatic.sd.mlc import (
    ids_mlc_existentes,
    mapa_mlc,
    siguiente_id_mlc,
)

_logger = logging.getLogger(__name__)


# ── Encoding (TIA V21) ───────────────────────────────────────────────

# TIA V21 exporta los archivos en UTF-8 con BOM. Leemos con
# ``utf-8-sig`` para que el BOM no contamine los strings.
SD_ENCODING = "utf-8-sig"

# TIA exporta con saltos CRLF. Se escriben siempre con CRLF, en cualquier
# sistema operativo, para que el resultado no dependa de la maquina.
SD_NEWLINE = "\r\n"


def _patron_de_indice(
    nombre_array: str, indice: int, tipo_array: str
) -> re.Pattern[str]:
    """Compila el regex para un indice concreto.

    - UDT: busca SOLO la asignacion raiz vacia ``Nombre[X] := ();``
      (los sub-campos ``.Valor``, ``.Maximo`` no entran).
    - Simple: busca cualquier asignacion ``Nombre[X] := <valor>;``
      (cubre ``:= true;``, ``:= 50.0;``, ``:= ();``, etc.).
    """
    name = re.escape(f"{nombre_array}[{indice}]")
    # UDT: la raiz vacia (sin sub-campos). Simple: cualquier valor.
    rhs = r"\(\s*\)" if tipo_array.upper() == "UDT" else r"[^;]+"
    pattern = (
        r"(?:\{\s*(?P<meta>[^}]+?)\s*\}\s*)?"
        r"(?P<decl>" + name + r"\s*:=\s*" + rhs + r";)"
    )
    return re.compile(pattern, re.MULTILINE)


_RE_ATRIBUTO_MLC = re.compile(r"""S7_MLC\s*:=\s*"(?P<id>[^"]+)"\s*;?""")


# ── Resultado ────────────────────────────────────────────────────────

@dataclass(frozen=True)
class ResultadoArray:
    """Resumen de la operacion sobre un array.

    Atributos:
        nombre_array: nombre del array procesado (p.ej. ``"PReal"``).
        injected: indices NUEVOS inyectados (no existian en el .s7dcl).
        reused: indices con MLC pre-existente que se reutilizo.
        updated: indices con MLC pre-existente cuyo texto se actualizo.
        removed: indices con MLC pre-existente cuyo comentario se elimino.
        noop: indices sin cambios (comentario identico al actual).
    """
    nombre_array: str
    injected: dict[int, str] = field(default_factory=dict)
    reused: dict[int, str] = field(default_factory=dict)
    updated: dict[int, str] = field(default_factory=dict)
    removed: list[int] = field(default_factory=list)
    noop: list[int] = field(default_factory=list)


# ── API publica ─────────────────────────────────────────────────────

def indices_de_array(
    texto_dcl: str,
    nombre_array: str,
    tipo_array: str = "UDT",
) -> set[int]:
    """Devuelve los indices que tienen una asignacion en el .s7dcl.

    Para UDT busca ``Nombre[X] := ();`` (raiz vacia). Para Simple
    busca cualquier asignacion ``Nombre[X] := <valor>;``.

    Usado por el preview (``el preview de procesos``) para saber
    que indices existen en TIA Portal y detectar los "eliminar"
    (indices que el el libro maestro no incluye pero TIA si).
    """
    indices: set[int] = set()
    name = re.escape(nombre_array)
    # Acepta tanto ``:= ();`` (UDT) como ``:= <valor>;`` (Simple).
    rhs = r"\(\s*\)" if tipo_array.upper() == "UDT" else r"[^;]+"
    pattern = re.compile(
        r"(?:\{\s*[^}]+?\s*\}\s*)?"
        + name + r"\s*\[\s*(?P<idx>\d+)\s*\]\s*:=\s*" + rhs + r";",
        re.MULTILINE,
    )
    for m in pattern.finditer(texto_dcl):
        try:
            indices.add(int(m.group("idx")))
        except (ValueError, TypeError):
            continue
    return indices


def comentarios_actuales(
    texto_res: str,
    nombre_array: str,
    indices: list[int],
    texto_dcl: str | None = None,
    tipo_array: str = "UDT",
) -> dict[int, str | None]:
    """Lee los comentarios actuales de un array desde .s7res + .s7dcl.

    Para cada indice de ``indices``:
      1. Busca el MLC adyacente en el .s7dcl (si ``texto_dcl`` dado).
      2. Busca el texto ``es-ES`` en el .s7res por MLC id.
      3. Devuelve ``{indice: texto}``. Si no hay MLC, devuelve ``None``.

    Usado por el preview para mostrar el texto actual de TIA
    (con el que se compara el el libro maestro en el diff).
    """
    id_a_texto = mapa_mlc(texto_res)

    result: dict[int, str | None] = {}
    for indice in indices:
        mlc_id = None
        if texto_dcl is not None:
            pattern = _patron_de_indice(nombre_array, indice, tipo_array)
            match = pattern.search(texto_dcl)
            if match:
                meta = match.group("meta") or ""
                mlc_match = _RE_ATRIBUTO_MLC.search(meta)
                if mlc_match:
                    mlc_id = mlc_match.group("id")
        if mlc_id and mlc_id in id_a_texto:
            result[indice] = id_a_texto[mlc_id]
        else:
            result[indice] = None
    return result


def confirmar_comentarios_array(
    ruta_dcl: str | Path,
    ruta_res: str | Path,
    nombre_array: str,
    mapa_indices: dict[int, str],
    *,
    tipo_array: str = "UDT",
    escribir_en_original: bool = False,
) -> ResultadoArray:
    """Actualiza los comentarios de un array en un DB SimaticSD.

    Lee el .s7dcl y el .s7res del disco, aplica las modificaciones
    del ``mapa_indices`` (indice -> texto comentario), y escribe los
    archivos modificados con prefijo ``modificado_`` (no toca los
    originales, igual que el script original del operario).

    Args:
        ruta_dcl: ruta al .s7dcl del DB.
        ruta_res: ruta al .s7res del DB.
        nombre_array: nombre del array (p.ej. ``"PReal"``,
            ``"PReal_Vis"``, ``"Aux.PReal_ValorAnterior"``).
        mapa_indices: dict ``{indice: texto_comentario}``. Indice es 0-based
            con indice 0 = "NO USAR" como placeholder (proc y disp,
            mismo patron que ``el mapa de indices del area``). El PLC
            debe estar dimensionado ``Array[0..N]`` y el codigo del
            PLC omite el indice 0. Texto vacio ``""`` = eliminar el
            comentario existente.
        tipo_array: ``"UDT"`` para arrays de UDT (PReal, PInt),
            ``"Simple"`` (o cualquier otro) para escalares (Bool,
            Int, Real, etc.).
        escribir_en_original: si True, escribe sobre los archivos
            originales (no a ``modificado_<file>``). Util cuando
            se hacen varias llamadas seguidas sobre el mismo DB
            (FB el sync de procesos itera 6 arrays sobre PARAM);
            cada llamada acumula cambios en el mismo archivo.

    Returns:
        ``ResultadoArray`` con el resumen de la operacion.
    """
    ruta_dcl = Path(ruta_dcl)
    ruta_res = Path(ruta_res)

    texto_dcl = ruta_dcl.read_text(encoding=SD_ENCODING)
    texto_res = ruta_res.read_text(encoding=SD_ENCODING)

    # ``datos_res`` se reusa al final para preservar el resto de claves
    # top-level del .s7res original al re-dumplear. ``textos_mlc`` se
    # construye desde la utility compartida para garantizar que solo
    # contiene entradas ``MLC_*`` con ``id`` + ``es-ES``.
    datos_res = yaml.safe_load(texto_res) or {}
    textos_mlc: list[dict[str, str]] = [
        {"id": k, "es-ES": v}
        for k, v in mapa_mlc(texto_res).items()
    ]
    ids_a_eliminar: set[str] = set()
    ids_usados = ids_mlc_existentes(texto_res)

    result = ResultadoArray(nombre_array=nombre_array)

    for indice, nuevo_comentario in mapa_indices.items():
        nuevo_comentario = str(nuevo_comentario or "")
        pattern = _patron_de_indice(nombre_array, indice, tipo_array)
        match = pattern.search(texto_dcl)

        # CASO A: indice no existe. Inyectar antes de END_DATA_BLOCK.
        if match is None:
            if not nuevo_comentario:
                result.noop.append(indice)
                continue
            nuevo_id = siguiente_id_mlc(ids_usados)
            ids_usados.add(nuevo_id)
            inyeccion = (
                f'\n        {{\n            S7_MLC := "{nuevo_id}"\n        }}\n'
                f"        {nombre_array}[{indice}] := ();"
            )
            if "\nEND_DATA_BLOCK" not in texto_dcl:
                raise ValueError(
                    f"confirmar_comentarios_array: '{ruta_dcl}' no contiene "
                    f"'END_DATA_BLOCK'; no se donde inyectar '{nombre_array}[{indice}]'."
                )
            texto_dcl = texto_dcl.replace(
                "\nEND_DATA_BLOCK", f"{inyeccion}\nEND_DATA_BLOCK", 1,
            )
            textos_mlc.append({"id": nuevo_id, "es-ES": nuevo_comentario})
            result.injected[indice] = nuevo_id
            continue

        # Indice existe. Procesar metadata + declaracion.
        meta_str = match.group("meta") or ""
        declaracion = match.group("decl")
        bloque_completo = match.group(0)

        mlc_match = _RE_ATRIBUTO_MLC.search(meta_str) if meta_str else None
        id_existente = mlc_match.group("id") if mlc_match else None

        # CASO B: eliminar comentario (texto vacio y MLC pre-existente).
        if not nuevo_comentario and id_existente:
            ids_a_eliminar.add(id_existente)
            nuevos_meta = _RE_ATRIBUTO_MLC.sub("", meta_str).strip()
            es_ancla_vacia = bool(re.search(r":=\s*\(\s*\)\s*;", declaracion))
            if not nuevos_meta and es_ancla_vacia:
                # Borrar la linea entera (bloque + asignacion ancla).
                texto_dcl = texto_dcl.replace(bloque_completo, "", 1)
            elif not nuevos_meta:
                texto_dcl = texto_dcl.replace(
                    bloque_completo, f"        {declaracion}", 1,
                )
            else:
                texto_dcl = texto_dcl.replace(
                    bloque_completo,
                    f"{{\n            {nuevos_meta}\n        }}\n        {declaracion}",
                    1,
                )
            result.removed.append(indice)
            continue

        # CASO C: actualizar texto de MLC pre-existente.
        if nuevo_comentario and id_existente:
            for item in textos_mlc:
                if item.get("id") == id_existente:
                    texto_actual = item.get("es-ES", "")
                    if texto_actual == nuevo_comentario:
                        result.noop.append(indice)
                    else:
                        item["es-ES"] = nuevo_comentario
                        result.updated[indice] = id_existente
                    break
            else:
                # MLC existe en .s7dcl pero no en .s7res (estado
                # inconsistente, caso raro). Anadir entrada nueva.
                textos_mlc.append(
                    {"id": id_existente, "es-ES": nuevo_comentario}
                )
                result.updated[indice] = id_existente
            continue

        # CASO D: anadir MLC a un indice que existia sin MLC.
        if nuevo_comentario and not id_existente:
            nuevo_id = siguiente_id_mlc(ids_usados)
            ids_usados.add(nuevo_id)
            textos_mlc.append({"id": nuevo_id, "es-ES": nuevo_comentario})

            if meta_str:
                # Hay bloque { ... } con otros metadatos: anadir S7_MLC al inicio.
                nuevo_meta = (
                    f'{{ S7_MLC := "{nuevo_id}"; {meta_str.strip()} }}'
                )
                texto_dcl = texto_dcl.replace(
                    bloque_completo, f"        {nuevo_meta}\n        {declaracion}", 1,
                )
            else:
                # No hay bloque: crear uno nuevo.
                nuevo_bloque = (
                    f'        {{\n            S7_MLC := "{nuevo_id}"\n        }}\n'
                    f"        {declaracion}"
                )
                texto_dcl = texto_dcl.replace(bloque_completo, nuevo_bloque, 1)
            result.injected[indice] = nuevo_id
            continue

        # Sin MLC y texto vacio: no-op.
        result.noop.append(indice)

    # Limpiar entradas eliminadas del .s7res.
    datos_res["MultiLingualTexts"] = [
        t for t in textos_mlc if t.get("id") not in ids_a_eliminar
    ]

    # Escribir archivos modificados (mismo prefijo que el script del
    # operario: no tocamos los originales por defecto). Si el caller
    # quiere acumular cambios sobre el mismo archivo (modo in-place,
    # usado por ``el commit de procesos`` que itera 6 arrays),
    # escribe sobre los originales.
    if escribir_en_original:
        salida_dcl = ruta_dcl
        salida_res = ruta_res
    else:
        salida_dcl = ruta_dcl.parent / f"modificado_{ruta_dcl.name}"
        salida_res = ruta_res.parent / f"modificado_{ruta_res.name}"
    salida_dcl.write_text(texto_dcl, encoding=SD_ENCODING, newline=SD_NEWLINE)
    salida_res.write_text(
        yaml.dump(datos_res, allow_unicode=True, sort_keys=False),
        encoding=SD_ENCODING,
        newline=SD_NEWLINE,
    )

    _logger.debug(
        f"confirmar_comentarios_array: array={nombre_array!r} type={tipo_array!r} "
        f"indices={len(mapa_indices)} injected={len(result.injected)} "
        f"reused={len(result.reused)} updated={len(result.updated)} "
        f"removed={len(result.removed)} noop={len(result.noop)}"
    )
    return result


__all__ = [
    "SD_ENCODING",
    "ResultadoArray",
    "confirmar_comentarios_array",
]
