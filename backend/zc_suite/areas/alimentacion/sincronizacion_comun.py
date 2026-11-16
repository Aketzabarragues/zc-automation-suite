"""zc_suite.areas.alimentacion.sincronizacion_comun — lo comun de los FB de sync.

Lo que los cuatro FB de alimentacion (dispositivos, entidades, procesos y
crear) se copian entre si, en un solo sitio:

- **El estado de las transacciones**: los tres estados (confirmada, revertida
  y no ejecutada), el estado inicial data-driven por nombres y el resumen
  exacto que va al final del mensaje de fallo.
- **La compilacion fuera de transaccion**: los FB la lanzan fuera de la
  transaccion (TIA no la admite dentro) y un fallo **no** tumba el trabajo:
  se convierte en el aviso ``compile=WARN``. La excepcion tipada
  :class:`CompilacionConErroresError` lleva el mensaje del aviso: el llamador
  la captura y lo convierte en el ``compile=WARN`` exactamente igual que antes.
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
from pathlib import Path

from zc_suite.errores import OperacionError

logger = logging.getLogger(__name__)

#: La transaccion se confirmo: TIA guardo los cambios.
ESTADO_CONFIRMADA = "confirmada"

#: La transaccion fallo y se revirtio: TIA no guardo nada.
ESTADO_REVIRTIDA = "revertida"

#: La transaccion no llego a ejecutarse.
ESTADO_NO_EJECUTADA = "no ejecutada"


class CompilacionConErroresError(OperacionError):
    """La compilacion termino con errores de TIA.

    El llamador la captura y la convierte en el aviso ``compile=WARN``
    exactamente igual que antes de la extraccion: el mensaje es el texto
    completo del aviso.
    """


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


def texto_errores_compilacion(resultado: dict[str, object]) -> str:
    """El cuerpo del aviso de una compilacion con errores.

    ``resultado`` es lo que devuelve ``tia_ops.compilar_bloques``: las
    listas ``compilados``, ``errores`` y ``no_encontrados`` y sus contadores.
    No se incluye la cola final: la pone el llamador (cada FB tiene la suya).

    Args:
        resultado: el resultado de ``compilar_bloques``.
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
