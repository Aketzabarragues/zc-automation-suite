"""zc_suite.areas.alimentacion.procesos.plantillas — el manifest de una plantilla.

El ``manifest.json`` de una plantilla TIA (la carpeta exportada de un
proceso existente) y las validaciones que se hacen con el antes de clonarla:

- ``proc_leer_manifest`` lee y valida el ``manifest.json`` (``base``,
  ``codigo``, ``descripcion`` y ``dependencias`` obligatorios).
- ``proc_validar_minimos`` exige que los N_MAX del operario cubran los
  minimos declarados en el manifest.
- ``proc_detectar_colisiones`` cruza los nombres post-rename
  (``dicc_bloques`` de ``procesos.clonacion``) contra el escaneo de bloques
  del PLC, por nombre exacto o por la tupla ``(prefijo_upper, numero)``.
- ``proc_validar_dependencias`` exige que cada bloque externo declarado en
  el manifest exista ya en el PLC (nombre exacto).

Es logica pura: no habla con el portal de TIA y no abre transacciones. El FB
que la usara sera ``../funciones/procesos/crear.py``.

El port de ``main`` (``function_proc_crear_generar_preview.py``, funciones
``proc_process_leer_manifest``, ``proc_process_validar_minimos``,
``proc_process_detectar_colisiones`` y ``proc_process_validar_dependencias``)
con los mismos textos de error. Diferencia intencionada: en ``main`` las
excepciones cuelgan de ``ValueError`` y las funciones de deteccion pueblan el
ctx; aqui cuelgan de ``ZCError`` y devuelven sus resultados.
"""
from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any

from zc_suite.areas.alimentacion.procesos.clonacion import N_MAX_KEYS
from zc_suite.errores import ZCError

logger = logging.getLogger(__name__)

__all__ = [
    "ManifestInvalido",
    "PlantillaMinimosNoCumplidos",
    "proc_detectar_colisiones",
    "proc_leer_manifest",
    "proc_validar_dependencias",
    "proc_validar_minimos",
]

#: El patron de un nombre de bloque con prefijo alfabetico y numero
#: (``FC100``, ``OB3``...). Para el match por numero el prefijo manda:
#: ``FC100`` y ``OB100`` son bloques distintos en TIA Portal.
PREFIJO_NUMERO = re.compile(r"^([A-Za-z]+)(\d+)")


class ManifestInvalido(ZCError):  # noqa: N818 (nombre heredado de main)
    """El ``manifest.json`` de la plantilla no existe o le faltan campos."""


class PlantillaMinimosNoCumplidos(ZCError):  # noqa: N818 (nombre heredado de main)
    """Los N_MAX del operario no cubren los minimos de la plantilla."""


def proc_leer_manifest(dir_plantilla: Path) -> dict[str, Any]:
    """Lee y valida el ``manifest.json`` de una plantilla.

    Args:
        dir_plantilla: la carpeta de la plantilla (donde esta el
            ``manifest.json``).

    Returns:
        El dict del manifest.

    Raises:
        ManifestInvalido: si el fichero no existe, no es JSON valido o le
            falta alguno de los campos obligatorios.
    """
    manifest_path = dir_plantilla / "manifest.json"
    if not manifest_path.exists():
        raise ManifestInvalido(f"No se encontro manifest.json en: {dir_plantilla}")

    try:
        manifest_text = manifest_path.read_text(encoding="utf-8")
        manifest = json.loads(manifest_text)
    except (OSError, json.JSONDecodeError) as exc:
        raise ManifestInvalido(f"manifest.json invalido: {exc}") from exc

    if "base" not in manifest or not isinstance(manifest["base"], int):
        raise ManifestInvalido("manifest.json debe contener 'base' (int).")
    if "codigo" not in manifest or not str(manifest["codigo"]).strip():
        raise ManifestInvalido("manifest.json debe contener 'codigo' (str).")
    if "descripcion" not in manifest or not str(manifest["descripcion"]).strip():
        raise ManifestInvalido(
            "manifest.json debe contener 'descripcion' (str no vacio). "
            "Es obligatorio para mostrar la plantilla en la SPA."
        )
    if "dependencias" not in manifest or not isinstance(manifest["dependencias"], list):
        raise ManifestInvalido(
            "manifest.json debe contener 'dependencias' (list[str]). "
            "Es obligatorio para validar bloques externos en el PLC."
        )
    if not all(isinstance(d, str) and d.strip() for d in manifest["dependencias"]):
        raise ManifestInvalido(
            "manifest.json 'dependencias' debe ser una lista de strings no vacios."
        )

    return manifest


def proc_validar_minimos(
    manifest: dict[str, Any],
    minimos_usuario: dict[str, int],
) -> None:
    """Exige que los N_MAX del operario cubran los minimos de la plantilla.

    Args:
        manifest: el dict del manifest (``proc_leer_manifest``).
        minimos_usuario: los N_MAX del operario (``{clave: valor}``).

    Raises:
        PlantillaMinimosNoCumplidos: si alguna clave N_MAX del operario es
            menor que la minima de la plantilla.
    """
    minimos_plantilla = manifest.get("minimos", {}) or {}
    problemas: list[str] = []
    for clave in N_MAX_KEYS:
        valor_plantilla = int(minimos_plantilla.get(clave, 0))
        valor_usuario = int(minimos_usuario.get(clave, 0))
        if valor_usuario < valor_plantilla:
            problemas.append(
                f"{clave}: usuario={valor_usuario} < plantilla={valor_plantilla}"
            )
    if problemas:
        raise PlantillaMinimosNoCumplidos(
            "Los N_MAX del operario no cubren los minimos de la plantilla:\n"
            "  - " + "\n  - ".join(problemas)
        )


def _entrada_bloque_plc(item: Any) -> dict[str, Any] | None:
    """Normaliza una entrada de la cache de bloques del PLC.

    Dict -> como esta; ``str`` (formato legacy) -> ``{"nombre": s,
    "numero": None}``; lo demas -> ``None`` (se descarta).
    """
    if isinstance(item, dict):
        return item
    if isinstance(item, str):
        return {"nombre": item, "numero": None}
    return None


def proc_detectar_colisiones(
    dicc_bloques: dict[str, str],
    bloques_plc: list[Any] | None,
) -> tuple[list[str], dict[str, str]]:
    """Cruza los nombres post-rename contra los bloques del PLC.

    Cualquier valor de ``dicc_bloques`` que ya exista en el PLC es una
    colision: o por nombre exacto, o por la tupla ``(prefijo_upper,
    numero)`` (match por numero — el numero del bloque nuevo coincide con el
    de un bloque del PLC; el prefijo alfabetico debe coincidir,
    ``FC100`` != ``OB100``, porque FC/FB/DB/OB/UDT coexisten con el mismo
    numero en TIA Portal). TIA Portal fallaria el import en ambos casos.

    Args:
        dicc_bloques: los reemplazamientos de bloques de la clonacion
            (``procesos.clonacion``).
        bloques_plc: el escaneo de bloques del PLC (``{"nombre", "numero"}``
            o, en formato legacy, ``str``); ``None`` si la cache no esta
            inicializada.

    Returns:
        La tupla ``(colisiones, colisiones_con)``: los nombres que
        colisionan y el identificador del bloque del PLC que produjo cada
        colision.
    """
    if bloques_plc is None:
        logger.warning(
            "[proc_detectar_colisiones] bloques_plc=None; el FB deberia abortar."
        )
        return (
            [
                "Cache de bloques PLC no inicializado "
                "(escanea primero con 'Escanear bloques PLC')"
            ],
            {},
        )

    entradas = [
        entrada
        for item in bloques_plc
        if (entrada := _entrada_bloque_plc(item)) is not None
    ]

    nombres_plc: set[str] = set()
    tipo_numero_plc: set[tuple[str, int]] = set()
    id_por_nombre: dict[str, str] = {}
    id_por_tipo_numero: dict[tuple[str, int], str] = {}
    for bloque in entradas:
        nombre_raw = bloque.get("nombre")
        nombre = str(nombre_raw) if nombre_raw else ""
        numero_raw = bloque.get("numero")
        if isinstance(numero_raw, bool):
            continue
        if isinstance(numero_raw, int):
            numero: int | None = numero_raw
        elif isinstance(numero_raw, str) and numero_raw.isdigit():
            numero = int(numero_raw)
        else:
            numero = None
        ident = nombre if nombre else (str(numero) if numero is not None else "")
        if not ident:
            continue
        if nombre and nombre not in nombres_plc:
            nombres_plc.add(nombre)
            id_por_nombre[nombre] = ident
        prefijo_para_tipo: str | None = None
        num_para_tipo: int | None = numero
        if nombre:
            m_plc = PREFIJO_NUMERO.match(nombre)
            if m_plc:
                prefijo_para_tipo = m_plc.group(1).upper()
                if num_para_tipo is None:
                    num_para_tipo = int(m_plc.group(2))
        if prefijo_para_tipo and num_para_tipo is not None:
            clave_tipo_num = (prefijo_para_tipo, num_para_tipo)
            if clave_tipo_num not in tipo_numero_plc:
                tipo_numero_plc.add(clave_tipo_num)
                id_por_tipo_numero[clave_tipo_num] = ident

    colisiones: list[str] = []
    colisiones_con: dict[str, str] = {}
    colisiones_vistas: set[str] = set()
    for clave, valor in dicc_bloques.items():
        if clave.startswith("S7_BlockNumber") or clave.isdigit() or clave.endswith("_"):
            continue
        if valor in colisiones_vistas:
            continue
        if valor in nombres_plc:
            colisiones.append(valor)
            colisiones_con[valor] = id_por_nombre[valor]
            colisiones_vistas.add(valor)
            continue
        m = PREFIJO_NUMERO.match(valor)
        if m:
            prefijo = m.group(1).upper()
            numero_valor = int(m.group(2))
            clave_tipo_num = (prefijo, numero_valor)
            if clave_tipo_num in tipo_numero_plc:
                colisiones.append(valor)
                colisiones_con[valor] = id_por_tipo_numero[clave_tipo_num]
                colisiones_vistas.add(valor)

    return colisiones, colisiones_con


def proc_validar_dependencias(
    dependencias: list[str],
    bloques_plc: list[Any] | None,
) -> list[str]:
    """Las dependencias del manifest que no estan en el PLC.

    Cada dependencia declarada debe coincidir con el nombre de un bloque ya
    existente en el PLC (match por nombre exacto, case-sensitive, y **no**
    por prefijo+numero: el operario declara bloques externos con su nombre
    completo canonico TIA, y TIA Portal resuelve los imports por nombre
    completo, no por tipo+numero).

    Args:
        dependencias: las dependencias declaradas en el manifest.
        bloques_plc: el escaneo de bloques del PLC (``{"nombre", ...}`` o
            ``str`` legacy); ``None`` si la cache no esta inicializada.

    Returns:
        Las dependencias ausentes (``[]`` si todas estan presentes; si
        ``bloques_plc`` es ``None``, todas las dependencias, porque el
        estado del PLC es desconocido).
    """
    if not dependencias:
        return []

    if bloques_plc is None:
        logger.warning(
            "[proc_validar_dependencias] bloques_plc=None; "
            "todas las dependencias iran a 'faltantes'."
        )
        return list(dependencias)

    nombres_plc: set[str] = set()
    for item in bloques_plc:
        if isinstance(item, dict):
            nombre_raw = item.get("nombre")
            if isinstance(nombre_raw, str) and nombre_raw:
                nombres_plc.add(nombre_raw)
        elif isinstance(item, str) and item:
            nombres_plc.add(item)

    faltantes: list[str] = []
    for dependencia in dependencias:
        if dependencia not in nombres_plc:
            faltantes.append(dependencia)
    return faltantes
