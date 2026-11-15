"""zc_suite.areas.alimentacion.procesos.clonacion — clonar una plantilla TIA.

Renombrado de una plantilla de proceso para crear un proceso nuevo: los
nombres de los bloques (``FC|FB|DB<num>``), los prefijos numericos de
carpetas y stems (``<num>_``), los metadatos ``S7_BlockNumber``, el codigo
y el nombre del proceso, en el **contenido** de los ficheros
``.s7dcl``/``.s7res``/``.scl``/``.awl``/``.xml`` y en los **nombres** de
ficheros y carpetas.

Es logica pura: no habla con el portal de TIA y no abre transacciones. El
FB que la usara sera ``../funciones/procesos/crear.py``.

El port de ``main`` (``helpers/proc/proc_process_construir_diccionarios.py``
y ``proc_process_aplicar_clonacion.py``) con los mismos criterios:

- ``proc_construir_diccionarios`` recorre la copia de la plantilla y
  construye dos diccionarios (ordenados por longitud de clave,
  descendente):

  - ``dicc_bloques``: el regex ``(FC|FB|DB)(\\d+)`` sobre el walk
    (``prefijo(num - base_vieja + base_nueva)``), los prefijos numericos
    de carpetas (``^(\\d+)_`` -> ``{p}_`` -> ``{p - base_vieja +
    base_nueva}_``) y de stems de archivos, los metadatos
    ``S7_BlockNumber := "X"`` de los bloques, las tres bases estandar
    (``base`` y ``base+3000``/``base+5000``), y los fallbacks de codigo y
    nombre del proceso.
  - ``dicc_xml``: solo los prefijos (carpetas, stems y bases estandar) y
    los fallbacks de codigo y nombre.

- ``proc_aplicar_clonacion`` copia la plantilla a ``dir_nuevo`` (sin el
  ``manifest.json``), renombra los nombres de ficheros y carpetas
  (profundidad descendente, para no romper los paths de los hijos) y
  reescribe el contenido segun la extension:

  - ``.s7res``: ``dicc_bloques``, encoding ``utf-8-sig`` (BOM).
  - ``.xml``: ``dicc_xml``, encoding ``utf-8``.
  - ``.s7dcl``/``.scl``/``.awl``: ``dicc_bloques``, encoding ``utf-8``.
  - El resto (binarios) no se toca.

  Los saltos de linea se preservan (``newline=""`` al leer y al escribir):
  los ``.s7dcl``/``.s7res`` de TIA son CRLF y no se normalizan.
"""
from __future__ import annotations

import re
from pathlib import Path

__all__ = ["proc_aplicar_clonacion", "proc_construir_diccionarios"]

#: La carpeta de los bloques dentro de la exportacion de TIA.
CARPETA_BLOQUES = "Bloques de programa"

#: El regex de un bloque canonico TIA: prefijo (FC/FB/DB) y numero.
PREFIJO_BLOQUE = re.compile(r"(FC|FB|DB)(\d+)")

#: El prefijo numerico de una carpeta (``50500_``).
PREFIJO_CARPETA = re.compile(r"^(\d+)_")

#: El prefijo numerico de un stem de archivo (``FC50501_``).
PREFIJO_STEM = re.compile(r"^(FC|FB|DB)(\d+)_")

#: Extension -> (diccionario que se aplica, encoding del fichero).
EXTENSIONES: dict[str, tuple[str, str]] = {
    ".s7res": ("bloques", "utf-8-sig"),
    ".s7dcl": ("bloques", "utf-8"),
    ".scl": ("bloques", "utf-8"),
    ".awl": ("bloques", "utf-8"),
    ".xml": ("xml", "utf-8"),
}


def proc_construir_diccionarios(
    dir_plantilla_copia: Path,
    base_vieja: int,
    base_nueva: int,
    codigo_viejo: str,
    codigo_nuevo: str,
    nombre_viejo: str,
    nombre_nuevo: str,
) -> tuple[dict[str, str], dict[str, str]]:
    """Los diccionarios de renombrado de una copia de plantilla.

    Recorre ``dir_plantilla_copia`` y construye el par de diccionarios que
    ``proc_aplicar_clonacion`` aplicara, cada uno ordenado por longitud de
    clave **descendente** (las claves mas especificas, por ejemplo
    ``DB50500_CIP1_INTERFAZ``, ganan a los prefijos numericos,
    ``50500_``).

    Args:
        dir_plantilla_copia: la copia de la plantilla (ya con su prefijo
            numerico reescrito).
        base_vieja: la base numerica de la plantilla (``50500``).
        base_nueva: la base numerica del proceso nuevo.
        codigo_viejo: el codigo del proceso de la plantilla (fallback).
        codigo_nuevo: el codigo del proceso nuevo.
        nombre_viejo: el nombre del proceso de la plantilla (fallback).
        nombre_nuevo: el nombre del proceso nuevo.

    Returns:
        El par ``(dicc_bloques, dicc_xml)``.
    """
    dicc_bloques: dict[str, str] = {}
    dicc_xml: dict[str, str] = {}
    numeros_usados: set[int] = set()
    prefijos_walk: set[int] = set()

    raiz_bloques = dir_plantilla_copia / CARPETA_BLOQUES
    for item in dir_plantilla_copia.rglob("*"):
        if not item.exists():
            continue
        nombre_base = item.stem if item.is_file() else item.name

        # Prefijos numericos de carpetas de la zona de bloques.
        if item.is_dir() and raiz_bloques in item.parents and item != raiz_bloques:
            m_prefijo = PREFIJO_CARPETA.match(item.name)
            if m_prefijo:
                prefijos_walk.add(int(m_prefijo.group(1)))

        # Prefijos numericos de stems de archivos (FC/FB/DB): cubre bloques
        # cuyo numero no aparece como prefijo de carpeta.
        if item.is_file():
            m_stem = PREFIJO_STEM.match(item.stem)
            if m_stem:
                prefijos_walk.add(int(m_stem.group(2)))

        nuevo_nombre_base = PREFIJO_BLOQUE.sub(
            lambda m: f"{m.group(1)}{int(m.group(2)) - base_vieja + base_nueva}",
            nombre_base,
        )
        if codigo_viejo:
            nuevo_nombre_base = nuevo_nombre_base.replace(codigo_viejo, codigo_nuevo)
        if nombre_viejo and nombre_nuevo:
            nuevo_nombre_base = nuevo_nombre_base.replace(nombre_viejo, nombre_nuevo)

        if nombre_base != nuevo_nombre_base:
            dicc_bloques[nombre_base] = nuevo_nombre_base

        for match in PREFIJO_BLOQUE.finditer(nombre_base):
            numeros_usados.add(int(match.group(2)))

    for prefijo_viejo in sorted(prefijos_walk):
        prefijo_nuevo = prefijo_viejo - base_vieja + base_nueva
        if prefijo_viejo == prefijo_nuevo:
            continue
        regla_vieja = f"{prefijo_viejo}_"
        regla_nueva = f"{prefijo_nuevo}_"
        dicc_xml[regla_vieja] = regla_nueva
        dicc_bloques[regla_vieja] = regla_nueva

    for base_v, base_n in zip(
        (base_vieja, base_vieja + 3000, base_vieja + 5000),
        (base_nueva, base_nueva + 3000, base_nueva + 5000),
        strict=True,
    ):
        dicc_xml.setdefault(f"{base_v}_", f"{base_n}_")
        dicc_bloques.setdefault(f"{base_v}_", f"{base_n}_")

    for numero in numeros_usados:
        dicc_bloques[f'S7_BlockNumber := "{numero}"'] = (
            f'S7_BlockNumber := "{numero - base_vieja + base_nueva}"'
        )

    if codigo_viejo:
        dicc_xml[codigo_viejo] = codigo_nuevo
        dicc_bloques[codigo_viejo] = codigo_nuevo
    if nombre_viejo and nombre_nuevo:
        dicc_xml[nombre_viejo] = nombre_nuevo
        dicc_bloques[nombre_viejo] = nombre_nuevo

    def _ordenar(dicc: dict[str, str]) -> dict[str, str]:
        return dict(sorted(dicc.items(), key=lambda x: len(x[0]), reverse=True))

    return _ordenar(dicc_bloques), _ordenar(dicc_xml)


def _aplicar_diccionario(texto: str, dicc: dict[str, str]) -> str:
    """Aplica los reemplazos en cascada (el orden del dicc manda)."""
    for viejo, nuevo in dicc.items():
        texto = texto.replace(viejo, nuevo)
    return texto


def _leer_texto(path: Path, encoding: str) -> str:
    """Lee texto con fallback ``latin-1`` si el utf-8 falla (caso TIA V21)."""
    try:
        with open(path, encoding=encoding, newline="") as f:
            return f.read()
    except UnicodeDecodeError:
        with open(path, encoding="latin-1", newline="") as f:
            return f.read()


def _escribir_texto(path: Path, contenido: str, encoding: str) -> None:
    """Escribe texto preservando los saltos de linea (``newline=""``)."""
    with open(path, "w", encoding=encoding, newline="") as f:
        f.write(contenido)


def proc_aplicar_clonacion(
    dir_nuevo: Path,
    dicc_bloques: dict[str, str],
    dicc_xml: dict[str, str],
) -> list[str]:
    """Renombra la clonacion ya copiada en ``dir_nuevo``.

    Aplica el dicc_bloques a los **nombres** de ficheros y carpetas (en
    profundidad descendente, para no romper los paths de los hijos) y el
    **contenido** de ``.s7res`` (utf-8-sig), ``.s7dcl``/``.scl``/``.awl``
    (utf-8) y ``.xml`` (``dicc_xml``, utf-8). El resto (binarios) no se
    toca.

    Args:
        dir_nuevo: la clonacion ya copiada (``shutil.copytree`` desde la
            plantilla, sin el ``manifest.json``).
        dicc_bloques: el diccionario de bloques
            (``proc_construir_diccionarios``).
        dicc_xml: el diccionario de XML.

    Returns:
        Las rutas relativas (con ``"/"``) de todos los ficheros generados.
    """
    renombres: list[tuple[Path, Path]] = []
    for path in list(dir_nuevo.rglob("*")):
        if path == dir_nuevo:
            continue
        if path.is_file():
            nuevo_nombre = f"{_aplicar_diccionario(path.stem, dicc_bloques)}{path.suffix}"
        else:
            nuevo_nombre = _aplicar_diccionario(path.name, dicc_bloques)
        if path.name != nuevo_nombre:
            renombres.append((path, path.with_name(nuevo_nombre)))

    renombres.sort(key=lambda par: -len(par[0].parts))
    for viejo, nuevo in renombres:
        nuevo.parent.mkdir(parents=True, exist_ok=True)
        viejo.rename(nuevo)

    generados: list[str] = []
    for path in sorted(dir_nuevo.rglob("*")):
        if not path.is_file():
            continue
        generados.append(str(path.relative_to(dir_nuevo)).replace("\\", "/"))
        clave, encoding = EXTENSIONES.get(path.suffix.lower(), (None, None))
        if clave is None:
            continue
        dicc = dicc_bloques if clave == "bloques" else dicc_xml
        contenido = _leer_texto(path, encoding)
        _escribir_texto(path, _aplicar_diccionario(contenido, dicc), encoding)
    return generados
