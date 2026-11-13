"""zc_suite.areas.alimentacion.dispositivos.sincronizacion — el calculo del sync.

Que cambios hay que meter en TIA y como se editan los ficheros en disco.

Es logica pura: no habla con el portal de TIA y no abre transacciones. El FB
que la usa es ``../funciones/dispositivos/sincronizar.py``.

El port de los helpers de ``main`` (``disp_Sincronizar``) con los mismos
criterios:

- El diff razona por **valor**: la clave de un dispositivo es su numero, que
  es el ``<Value>`` de la ``PlcUserConstant``. El ``<Name>`` es el ``plc_tag``.
- La tabla de N_MAX **no** se importa en la transaccion de dispositivos: sus
  valores se aplican en linea, en la transaccion anterior. Si se copiara a
  ``modified/``, la importacion le devolveria los valores previos y anularia
  los ya aplicados.
- Los XML del export pueden estar planos o con la jerarquia de carpetas del
  PLC: el lector no depende de acertar el nombre de la carpeta.
"""
from __future__ import annotations

import logging
import shutil
from collections.abc import Callable
from pathlib import Path
from typing import Any

from zc_suite.areas.alimentacion.dispositivos.diferencias import DiffNMax, DiffTabla
from zc_suite.simatic.ml import ModificadorConstantesUsuario

logger = logging.getLogger(__name__)

#: El comentario del slot 0 de los arrays de dispositivos: no se usa.
COMENTARIO_SLOT_CERO = "NO USAR"

#: La extension de los XML de tablas de tags.
EXTENSION_XML = ".xml"


# ── localizar los XML del export ────────────────────────────────────────────


def disp_localizar_xml(base: Path, tabla: str) -> Path | None:
    """Localiza el XML de una tabla dentro de un export de TIA.

    Tolera los dos layouts de export:

    - plano: ``<base>/<tabla>.xml``.
    - con la jerarquia de carpetas del PLC: ``<base>/<carpeta>/<tabla>.xml``.

    Args:
        base: la carpeta raiz del export.
        tabla: el nombre de la tabla, sin extension.

    Returns:
        La ruta del XML, o ``None`` si la tabla no esta en el export.
    """
    directo = base / f"{tabla}{EXTENSION_XML}"
    if directo.is_file():
        return directo
    for encontrado in sorted(base.rglob(f"{tabla}{EXTENSION_XML}")):
        return encontrado
    return None


# ── las operaciones que hay que aplicar ─────────────────────────────────────


def disp_calcular_operaciones_n_max(tabla: str, diff: DiffNMax) -> list[dict[str, Any]]:
    """Las operaciones de N_MAX que hay que aplicar en linea.

    Solo se proponen las constantes que **ya existen** en TIA y cuyo valor
    no coincide. Una constante que no esta en TIA no se puede cambiar: el
    cambio de valor fallaria. Es lo que hace ``main``.

    Sin XML de TIA no se propone nada: no se puede saber cual es el valor
    actual, y cambiarlo a ciegas dejaria el PLC mal dimensionado.

    Args:
        tabla: la tabla de TIA donde viven los N_MAX.
        diff: el diff de los N_MAX.

    Returns:
        La lista de ``{"tabla", "constante", "valor"}``.
    """
    return [
        {
            "tabla": tabla,
            "constante": str(fila["name"]),
            "valor": int(fila["nuevo"]),
        }
        for fila in diff.todos
        if fila["status"] == "actualizar" and str(fila["name"]) in diff.actual
    ]


def disp_calcular_renombres(diffs: dict[str, DiffTabla]) -> list[dict[str, str]]:
    """Los renombres de constantes que hay que aplicar en linea.

    Un dispositivo cuyo ``plc_tag`` cambio es un ``PlcUserConstant`` con otro
    ``<Name>``: el valor (el numero) no se mueve.

    Args:
        diffs: el diff de cada tabla de dispositivos.

    Returns:
        La lista de ``{"tabla", "actual", "nuevo"}``.
    """
    renombres: list[dict[str, str]] = []
    for tabla, diff in diffs.items():
        for _numero, (actual, nuevo) in diff.renombrados.items():
            renombres.append({"tabla": tabla, "actual": actual, "nuevo": nuevo})
    return renombres


def disp_calcular_cambios_dispositivos(
    diffs: dict[str, DiffTabla],
) -> list[dict[str, Any]]:
    """Los cambios de cada tabla de dispositivos: que se anade y que se quita.

    Args:
        diffs: el diff de cada tabla de dispositivos.

    Returns:
        La lista de ``{"tabla", "agregados", "eliminados"}``. ``agregados``
        son ``{"valor", "plc_tag"}`` y ``eliminados`` son los numeros (el
        ``<Value>``) que sobran en TIA.
    """
    cambios: list[dict[str, Any]] = []
    for tabla, diff in diffs.items():
        agregados = [
            {"valor": numero, "plc_tag": diff.deseado.get(numero, "")}
            for numero in diff.agregados
            if diff.deseado.get(numero)
        ]
        eliminados = list(diff.eliminados)
        if agregados or eliminados:
            cambios.append(
                {"tabla": tabla, "agregados": agregados, "eliminados": eliminados}
            )
    return cambios


def disp_mapa_comentarios(filas: list[dict[str, Any]]) -> dict[int, str]:
    """El mapa de slots de un tipo de dispositivo.

    El slot 0 no se usa y lleva el comentario ``"NO USAR"``. Cada dispositivo
    ocupa el slot de su numero, con su comentario de DB.

    Args:
        filas: las filas del Excel de ese tipo, ya filtradas por PLC.

    Returns:
        ``{slot: comentario}``.
    """
    mapa: dict[int, str] = {0: COMENTARIO_SLOT_CERO}
    vistos: set[int] = set()
    for fila in filas:
        numero = int(fila.get("numero", 0) or 0)
        if numero <= 0 or numero in vistos:
            continue
        vistos.add(numero)
        mapa[numero] = str(fila.get("comentario_db", "") or "")
    return mapa


# ── la edicion offline ──────────────────────────────────────────────────────


def disp_copiar_y_editar(
    origen: Path,
    destino: Path,
    cambios: list[dict[str, Any]],
) -> dict[str, Any]:
    """Copia el export a ``modified/`` y edita los XML de los cambios.

    La copia **excluye** los XML que no son de una tabla con cambios. Asi la
    tabla de N_MAX no llega al import: sus valores se aplican en linea, en la
    transaccion anterior, y reimportarla dejaria el PLC con los valores
    previos.

    Args:
        origen: la carpeta ``export/``.
        destino: la carpeta ``modified/``.
        cambios: los cambios por tabla (``disp_calcular_cambios_dispositivos``).

    Returns:
        ``{"pedidos", "escritos", "eliminados", "parciales"}``. ``parciales``
        son las tablas en las que no se pudo escribir todo lo pedido.
    """
    tablas = {str(cambio["tabla"]) for cambio in cambios}
    if not origen.is_dir():
        logger.warning("[disp sync] El origen no existe: '%s'. No hay nada que copiar.", origen)
        return {"pedidos": 0, "escritos": 0, "eliminados": 0, "parciales": []}

    shutil.copytree(
        origen,
        destino,
        ignore=_ignorar_xmls_fuera_de(tablas),
        dirs_exist_ok=True,
    )

    pedidos = 0
    escritos = 0
    eliminados = 0
    parciales: list[str] = []
    for cambio in cambios:
        tabla = str(cambio["tabla"])
        agregados = list(cambio.get("agregados") or [])
        a_eliminar = {str(valor) for valor in (cambio.get("eliminados") or [])}
        ruta = disp_localizar_xml(destino, tabla)
        if ruta is None:
            parciales.append(f"{tabla}: 0/{len(agregados)} (XML no encontrado)")
            continue
        modificador = ModificadorConstantesUsuario(ruta)
        anadidos = modificador.anadir_constantes_de_tabla(tabla, agregados)
        quitados = modificador.eliminar_constantes_por_valor(a_eliminar)
        if modificador.modificado():
            modificador.guardar(ruta)
        pedidos += len(agregados)
        escritos += anadidos
        eliminados += quitados
        if anadidos != len(agregados):
            parciales.append(f"{tabla}: {anadidos}/{len(agregados)}")

    if parciales:
        logger.warning(
            "[disp sync] Tags escritos: %d de %d pedidos (%s).",
            escritos,
            pedidos,
            "; ".join(parciales),
        )
    return {
        "pedidos": pedidos,
        "escritos": escritos,
        "eliminados": eliminados,
        "parciales": parciales,
    }


def _ignorar_xmls_fuera_de(tablas: set[str]) -> Callable[[str, list[str]], set[str]]:
    """El ``ignore`` de ``shutil.copytree`` que deja fuera los XML ajenos.

    Se ignoran los ``.xml`` cuyo nombre no sea el de una tabla con cambios.
    Los demas ficheros (los de los bloques, por ejemplo) se copian siempre.
    """

    def _ignore(_directorio: str, nombres: list[str]) -> set[str]:
        return {
            nombre
            for nombre in nombres
            if nombre.endswith(EXTENSION_XML) and nombre[: -len(EXTENSION_XML)] not in tablas
        }

    return _ignore
