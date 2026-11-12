"""zc_suite.tia_ops.constantes — constantes de usuario del PLC.

Portado de ``core/infrastructure/tia/tia_cmd_user_consts.py`` de la version
anterior, pero sin el vocabulario del area: aqui son *constantes de usuario*
de una *tabla de tags*. Lo especifico del area (que tablas las tienen, como
se llaman, de donde sale el valor) vive en ``areas/``.

Peculiaridades conservadas:

- ``set_property`` puede devolver 0 (OK) sin aplicar el cambio en TIA V21
  (fallo silencioso de Pythonnet). Por eso toda escritura se **vuelve a
  leer** para confirmar que en TIA el valor o el nombre ha cambiado de
  verdad.
- La constante se localiza recorriendo las constantes de usuario de la
  tabla y comparando su propiedad ``Name``.
- Una constante que no existe es un fallo, no un silencio.

Las escrituras (``cambiar_valor`` y ``renombrar``) se llaman **dentro de
una transaccion**: ``with transaccion(job, "Cambiar valor")``. TIA no aplica
el cambio si no.
"""
from __future__ import annotations

from typing import Any

from zc_suite.errores import OperacionError
from zc_suite.tia_ops._resolver import buscar_plc, buscar_tabla_tags


def leer_constantes(portal: Any, plc: str, tabla: str) -> list[dict[str, Any]]:
    """Las constantes de usuario de una tabla de tags.

    Args:
        portal: el portal de TIA.
        plc: nombre del PLC.
        tabla: nombre de la tabla de tags.

    Returns:
        Lista de ``{"nombre": str, "valor": str}``. El valor va tal cual lo
        devuelve TIA: el que llama decide que valores le interesan.

    Raises:
        OperacionError: si el PLC o la tabla no existen.
    """
    constantes = _constantes_de(portal, plc, tabla)
    return [
        {
            "nombre": str(constante.get_property(name="Name")),
            "valor": _texto(constante.get_property(name="Value")),
        }
        for constante in constantes
    ]


def cambiar_valor(
    portal: Any,
    plc: str,
    tabla: str,
    nombre: str,
    valor: str | int,
) -> dict[str, Any]:
    """Cambia el valor de una constante de usuario.

    **Debe llamarse dentro de una transaccion.** Sin transaccion, TIA no
    aplica el cambio.

    Args:
        portal: el portal de TIA.
        plc: nombre del PLC.
        tabla: nombre de la tabla de tags.
        nombre: nombre de la constante.
        valor: valor nuevo.

    Returns:
        ``{"nombre": ..., "valor": ...}``.

    Raises:
        OperacionError: si la constante no existe o si TIA no aplica el
            cambio (y no solo dice que si).
    """
    constante = _buscar_constante(portal, plc, tabla, nombre)
    codigo = constante.set_property(name="Value", value=str(valor))
    if codigo != 0:
        raise OperacionError(
            f"Constante '{nombre}' en la tabla '{tabla}': TIA rechazo la "
            f"modificacion (codigo de retorno {codigo}). "
            f"Valor intentado: '{valor}'."
        )
    actual = constante.get_property(name="Value")
    if str(actual).strip() != str(valor).strip():
        raise OperacionError(
            f"Constante '{nombre}' en la tabla '{tabla}': set_property devolvio 0 "
            f"(OK) pero el valor real en TIA es '{actual}', no '{valor}'. "
            f"Posible fallo silencioso de Pythonnet/TIA V21."
        )
    return {"nombre": nombre, "valor": valor}


def renombrar(
    portal: Any,
    plc: str,
    tabla: str,
    nombre: str,
    nuevo_nombre: str,
) -> dict[str, Any]:
    """Renombra una constante de usuario.

    **Debe llamarse dentro de una transaccion.** Sin transaccion, TIA no
    aplica el cambio.

    Args:
        portal: el portal de TIA.
        plc: nombre del PLC.
        tabla: nombre de la tabla de tags.
        nombre: nombre actual de la constante.
        nuevo_nombre: nombre nuevo.

    Returns:
        ``{"nombre": ..., "nuevo_nombre": ...}``.

    Raises:
        OperacionError: si la constante no existe o si TIA no aplica el
            renombrado (y no solo dice que si).
    """
    constante = _buscar_constante(portal, plc, tabla, nombre)
    codigo = constante.set_property(name="Name", value=nuevo_nombre)
    if codigo != 0:
        raise OperacionError(
            f"Renombrar '{nombre}' -> '{nuevo_nombre}' en la tabla '{tabla}': "
            f"TIA rechazo la modificacion (codigo de retorno {codigo})."
        )
    actual = constante.get_property(name="Name")
    if actual != nuevo_nombre:
        raise OperacionError(
            f"Renombrar '{nombre}' -> '{nuevo_nombre}' en la tabla '{tabla}': "
            f"set_property devolvio 0 (OK) pero el nombre real en TIA es "
            f"'{actual}', no '{nuevo_nombre}'. Posible fallo silencioso de "
            f"Pythonnet/TIA V21."
        )
    return {"nombre": nombre, "nuevo_nombre": nuevo_nombre}


# ── helpers ────────────────────────────────────────────────────────────────


def _constantes_de(portal: Any, plc: str, tabla: str) -> list[Any]:
    """Las constantes de usuario de la tabla de tags del PLC."""
    objetivo = buscar_plc(portal, plc)
    return list(buscar_tabla_tags(objetivo, tabla).get_user_constants())


def _buscar_constante(portal: Any, plc: str, tabla: str, nombre: str) -> Any:
    """La constante de usuario con ese nombre en esa tabla.

    Raises:
        OperacionError: si no existe ninguna constante con ese nombre.
    """
    for constante in _constantes_de(portal, plc, tabla):
        if constante.get_property(name="Name") == nombre:
            return constante
    raise OperacionError(f"Constante '{nombre}' no encontrada en la tabla '{tabla}'.")


def _texto(bruto: Any) -> str:
    """El valor de TIA como texto. ``None`` es cadena vacia."""
    return "" if bruto is None else str(bruto)
