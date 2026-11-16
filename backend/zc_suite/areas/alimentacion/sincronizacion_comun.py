"""zc_suite.areas.alimentacion.sincronizacion_comun — lo comun de los FB de sync.

Lo que los cuatro FB de alimentacion (dispositivos, entidades, procesos y
crear) se copian entre si, en un solo sitio:

- **El estado de las transacciones**: los tres estados (confirmada, revertida
  y no ejecutada), el estado inicial data-driven por nombres y el resumen
  exacto que va al final del mensaje de fallo.
- **La compilacion fuera de transaccion**: :func:`compilar_con_aviso` hace
  todo el flujo: llama al compilador (los FB lo lanzan fuera de la
  transaccion, porque TIA no la admite dentro), registra los avisos en el
  log y devuelve **solo el detalle** (``compile=OK (...)`` o
  ``compile=WARN``). Un fallo **no** tumba el trabajo.
- **Los helpers de texto y rutas** que los FB de sync se repiten:
  :func:`mensaje_corto` (el mensaje de TIA sin la ruta del bloque) y
  :func:`localizar_xml` (el XML de una tabla dentro de un export de TIA).

Es **puro respecto a TIA**: no importa ``zc_suite.nucleo.tia`` ni
``zc_suite.tia_ops``. La transaccion y la compilacion las coordinan los FB
consumidores: aqui solo se preparan datos y estados.

Nota: :func:`localizar_xml` **no** es ``disp_localizar_xml`` de
``dispositivos/sincronizacion.py``: esta devuelve siempre un ``Path`` (sin la
tabla, el del export plano), mientras que la de dispositivos devuelve
``Path | None`` para que el FB omita la tabla.
"""
from __future__ import annotations

import logging
from collections.abc import Callable
from pathlib import Path

logger = logging.getLogger(__name__)

#: La transaccion se confirmo: TIA guardo los cambios.
ESTADO_CONFIRMADA = "confirmada"

#: La transaccion fallo y se revirtio: TIA no guardo nada.
ESTADO_REVIRTIDA = "revertida"

#: La transaccion no llego a ejecutarse.
ESTADO_NO_EJECUTADA = "no ejecutada"


# ── el estado de las transacciones ──────────────────────────────────────────


def estados_iniciales(nombres: dict[str, str]) -> dict[str, dict[str, str]]:
    """El estado inicial de las transacciones de un sync, todas sin ejecutar.

    Args:
        nombres: las transacciones del sync, en el orden en que van, de clave
            a nombre. El nombre es el que se ve en el faceplate y en el
            mensaje de fallo.
    """
    return {
        clave: {
            "nombre": nombre,
            "estado": ESTADO_NO_EJECUTADA,
            "detalle": "",
        }
        for clave, nombre in nombres.items()
    }


def resumen_transacciones(transacciones: dict[str, dict[str, str]]) -> str:
    """El estado de las transacciones, en una frase, en su orden."""
    partes = [
        f"{datos['nombre']}: {datos['estado']}" for datos in transacciones.values()
    ]
    return "Transacciones: " + "; ".join(partes) + "."


def estado_confirmada(transacciones: dict[str, dict[str, str]], clave: str, detalle: str) -> None:
    """La transaccion se confirmo: TIA guardo los cambios."""
    transacciones[clave]["estado"] = ESTADO_CONFIRMADA
    transacciones[clave]["detalle"] = detalle


def estado_revertida(transacciones: dict[str, dict[str, str]], clave: str, detalle: str) -> None:
    """La transaccion fallo y se revirtio: TIA no guardo nada."""
    transacciones[clave]["estado"] = ESTADO_REVIRTIDA
    transacciones[clave]["detalle"] = detalle


def estado_no_ejecutada(transacciones: dict[str, dict[str, str]], clave: str, detalle: str) -> None:
    """La transaccion no llego a ejecutarse (sin cambios, o falta la version)."""
    transacciones[clave]["estado"] = ESTADO_NO_EJECUTADA
    transacciones[clave]["detalle"] = detalle


# ── la compilacion fuera de transaccion ─────────────────────────────────────


def compilar_con_aviso(
    *,
    compilador: Callable[[], dict[str, object]],
    cola: str,
    logger: logging.Logger,
) -> str:
    """La compilacion fuera de la transaccion, con aviso, en un solo sitio.

    Llama a ``compilador`` (el FB decide cuando y desde donde; el callable
    debe invocar **su** ``compilar_bloques`` local para que los tests puedan
    parchearlo) y convierte cualquier fallo en el aviso ``compile=WARN``:
    la compilacion la lanza el FB fuera de la transaccion (TIA no la admite
    dentro) y un fallo **no** tumba el trabajo: los cambios ya estan
    aplicados y el operario tiene que ver el aviso, no perder el sync.

    Args:
        compilador: lo que compila: devuelve el resultado de
            ``tia_ops.compilar_bloques`` o lanza.
        cola: la cola final del aviso de errores de cada FB.
        logger: donde se registran los avisos (el logger del FB).

    Returns:
        Solo el detalle del paso: ``compile=OK (N compilados, M sin cambios)``
        o ``compile=WARN``.
    """
    try:
        resultado = compilador()
    except Exception as exc:
        logger.warning("La compilacion fallo (los cambios ya estan aplicados): %s", exc)
        return "compile=WARN"
    if resultado["n_compilados_error"] or resultado["n_errores"]:
        logger.warning(
            "Compilacion con errores (los cambios ya estan aplicados): %s",
            texto_errores_compilacion(resultado) + cola,
        )
        return "compile=WARN"
    return (
        f"compile=OK ({resultado['n_compilados_ok']} compilados, "
        f"{resultado['n_sin_cambios']} sin cambios)"
    )


def texto_errores_compilacion(resultado: dict[str, object]) -> str:
    """El cuerpo del aviso de una compilacion con errores.

    ``resultado`` es lo que devuelve ``tia_ops.compilar_bloques``: las
    listas ``compilados``, ``errores`` y ``no_encontrados`` y sus contadores.
    No se incluye la cola final: la pone el llamador (cada FB tiene la suya).
    """
    partes: list[str] = []
    con_errores = resultado["con_errores"]
    if con_errores:
        detalles: list[str] = []
        for compilado in resultado["compilados"]:
            if not compilado["tiene_errores"]:
                continue
            mensajes = compilado.get("mensajes") or []
            if mensajes:
                detalles.append(f"{compilado['nombre']} ({mensaje_corto(mensajes[0])})")
            else:
                detalles.append(compilado["nombre"])
        partes.append(f"{len(con_errores)} bloque(s) con errores: " + ", ".join(detalles))
    errores = resultado["errores"]
    if errores:
        partes.append(
            f"{len(errores)} no se pudieron compilar: "
            + ", ".join(e["nombre"] for e in errores)
        )
    no_encontrados = resultado["no_encontrados"]
    if no_encontrados:
        partes.append(
            f"{len(no_encontrados)} no encontrado(s): " + ", ".join(no_encontrados)
        )
    return "TIA reporta errores de compilacion: " + "; ".join(partes)


# ── los helpers de texto y rutas ────────────────────────────────────────────


def mensaje_corto(mensaje: str) -> str:
    """El mensaje de TIA sin la ruta del bloque.

    ``"ZC_PLC_STD > Program blocks > DB5 (DB5) > Interface > Data type Boo
    is unknown."`` queda en ``"Interface > Data type Boo is unknown."``.
    """
    partes = [parte.strip() for parte in mensaje.split(" > ")]
    for indice, parte in enumerate(partes):
        if parte.endswith(")") and "(" in parte:
            resto = partes[indice + 1 :]
            return " > ".join(resto) if resto else mensaje
    return mensaje


def localizar_xml(base: Path, tabla: str) -> Path:
    """Localiza el XML de una tabla dentro de un export de TIA.

    Tolera los dos layouts: plano o con la jerarquia de carpetas del PLC.
    Sin la tabla, devuelve el XML plano del export (que no existe): el
    llamador decide que hacer con un XML ausente.
    """
    directo = base / f"{tabla}.xml"
    if directo.is_file():
        return directo
    for encontrado in sorted(base.rglob(f"{tabla}.xml")):
        return encontrado
    return base / f"{tabla}.xml"
