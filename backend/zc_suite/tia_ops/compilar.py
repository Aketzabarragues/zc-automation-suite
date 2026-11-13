"""zc_suite.tia_ops.compilar — compilar el software del PLC.

Portado de ``core/infrastructure/tia/tia_cmd_compile.py`` de la version
anterior, con una correccion de fondo.

Lo que devuelve compilar (comprobado contra TIA, no en el manual):

- ``block.compile()`` y ``plc.compile_software()`` devuelven un
  ``ExecutionResult`` del SDK, no un booleano. El manual de Openness no lo
  documenta (§2.29.4 no dice nada; §2.2.11 dice "True si hay errores").
  main hacia ``bool(resultado)``, y un objeto es siempre verdadero: contaba
  como "con errores" **todo** lo que compilaba.
- El ``ExecutionResult`` trae ``get_result_state()`` (0 sin errores, 20 con
  errores), ``get_errors()``, ``get_warnings()``, ``get_information()`` y
  ``get_all_messages()``. Los mensajes son textos de TIA, por ejemplo
  ``"ZC_PLC_STD > Program blocks > DB_NO_OK (DB5) > Interface > Data type
  Boo is unknown."``. La ultima linea es el resumen
  ``"Compiling finished (errors: 1; warnings: 0)"``.

Como se decide si hay errores:

- Si el resultado trae ``get_errors()``, hay errores si devuelve alguno.
- En un bloque, ademas, si sigue sin ser consistente tras compilar
  (``is_consistent()``, documentado). Es el respaldo si el SDK cambia.
- Si TIA devolviera un booleano (versiones antiguas del SDK), en el PLC se
  toma como "True = errores" (§2.2.11); en un bloque se ignora y manda
  ``is_consistent()``.

Peculiaridades conservadas de main:

- Al compilar bloques, uno que ya esta consistente se **salta**.
- Un bloque que no existe no hace fallar el lote: se anota.
- Si ``is_consistent()`` falla antes de compilar, se compila igualmente.
- Si ``compile()`` lanza en un bloque, se anota y se sigue con los demas.

La compilacion se hace **fuera** de la transaccion: TIA no la admite
dentro.

No se porta ``compile_hardware``: no tiene ningun llamador.
"""
from __future__ import annotations

import logging
from typing import Any

from zc_suite.errores import OperacionError
from zc_suite.tia_ops._resolver import buscar_plc, nombre_bloque

logger = logging.getLogger(__name__)

#: Prefijo de la linea de resumen que TIA anade al final de los mensajes.
_RESUMEN = "Compiling finished"


def leer_resultado(resultado: Any) -> dict[str, Any]:
    """Lee el ``ExecutionResult`` de una compilacion.

    Args:
        resultado: lo que devuelve ``compile()`` o ``compile_software()``.

    Returns:
        ``{"estado", "errores", "avisos", "resumen"}``. ``estado`` es el
        ``get_result_state()`` (``None`` si no lo hay). ``errores`` y
        ``avisos`` son los mensajes de TIA sin la linea de resumen;
        ``resumen`` es esa linea (o ``""``). Si ``resultado`` no es un
        ``ExecutionResult``, ``estado`` es ``None`` y las listas van vacias.
    """

    def _lista(nombre: str) -> list[str]:
        metodo = getattr(resultado, nombre, None)
        if not callable(metodo):
            return []
        try:
            return [str(m) for m in (metodo() or [])]
        except Exception:
            logger.debug("No se pudo leer %s() del resultado de compilar", nombre)
            return []

    estado: int | None = None
    metodo_estado = getattr(resultado, "get_result_state", None)
    if callable(metodo_estado):
        try:
            estado = int(metodo_estado())
        except Exception:
            estado = None

    todos = _lista("get_all_messages")
    resumen = next((m for m in reversed(todos) if m.startswith(_RESUMEN)), "")
    return {
        "estado": estado,
        "errores": [m for m in _lista("get_errors") if not m.startswith(_RESUMEN)],
        "avisos": [m for m in _lista("get_warnings") if not m.startswith(_RESUMEN)],
        "resumen": resumen,
    }


def _es_execution_result(resultado: Any) -> bool:
    """``True`` si el resultado es un ``ExecutionResult`` del SDK."""
    return callable(getattr(resultado, "get_errors", None))


def compilar_plc(portal: Any, plc: str) -> dict[str, Any]:
    """Compila todo el software del PLC.

    Args:
        portal: el portal de TIA.
        plc: nombre del PLC.

    Returns:
        ``{"tiene_errores", "errores", "avisos", "resumen"}``.
        ``errores`` y ``avisos`` son los mensajes de TIA.

    Raises:
        OperacionError: si el PLC no existe o TIA rechaza la compilacion.
    """
    objetivo = buscar_plc(portal, plc)
    try:
        resultado = objetivo.compile_software()
    except Exception as exc:
        raise OperacionError(
            f"No se pudo compilar el software del PLC '{plc}': "
            f"{type(exc).__name__}: {exc}"
        ) from exc
    if _es_execution_result(resultado):
        leido = leer_resultado(resultado)
        tiene_errores = bool(leido["errores"]) or bool(leido["estado"])
    else:
        # SDK antiguo: booleano, True si hay errores (manual §2.2.11).
        leido = {"errores": [], "avisos": [], "resumen": ""}
        tiene_errores = bool(resultado)
    return {
        "tiene_errores": tiene_errores,
        "errores": leido["errores"],
        "avisos": leido["avisos"],
        "resumen": leido["resumen"],
    }


def compilar_bloques(portal: Any, plc: str, nombres: list[str]) -> dict[str, Any]:
    """Compila una lista explicita de bloques del PLC.

    Es mas rapido que compilar todo el software cuando solo se han tocado
    unos bloques concretos.

    Args:
        portal: el portal de TIA.
        plc: nombre del PLC.
        nombres: nombres de los bloques a compilar.

    Returns:
        ``{"compilados", "sin_cambios", "no_encontrados", "errores"}``, la
        lista ``con_errores`` (nombres de los compilados con errores) y los
        contadores planos ``n_compilados_ok``, ``n_compilados_error``,
        ``n_sin_cambios``, ``n_no_encontrados`` y ``n_errores``.
        Cada compilado lleva ``nombre``, ``tiene_errores``, ``mensajes``
        (los errores de TIA) y ``avisos``. ``errores`` son los bloques en los
        que ``compile()`` lanzo una excepcion; ``n_compilados_error`` no los
        incluye.

    Raises:
        OperacionError: si el PLC no existe o la lista de bloques esta vacia.
    """
    if not nombres:
        raise OperacionError(
            "Se requiere la lista de bloques a compilar. "
            "Para compilar todo el PLC, usa compilar_plc()."
        )
    objetivo = buscar_plc(portal, plc)

    # Index de bloques por nombre para buscar en O(1). El primero que
    # aparece gana.
    por_nombre: dict[str, Any] = {}
    for bloque in objetivo.get_program_blocks():
        nombre = nombre_bloque(bloque)
        if nombre is not None:
            por_nombre.setdefault(nombre, bloque)

    compilados: list[dict[str, Any]] = []
    sin_cambios: list[str] = []
    no_encontrados: list[str] = []
    errores: list[dict[str, str]] = []

    for nombre in nombres:
        bloque = por_nombre.get(nombre)
        if bloque is None:
            no_encontrados.append(nombre)
            continue
        try:
            consistente = bool(bloque.is_consistent())
        except Exception:
            # Defensivo: si lanza, se asume NO consistente y se compila.
            consistente = False
        if consistente:
            sin_cambios.append(nombre)
            continue
        try:
            resultado = bloque.compile()
        except Exception as exc:
            errores.append({"nombre": nombre, "error": f"{type(exc).__name__}: {exc}"})
            continue
        leido = leer_resultado(resultado)
        logger.debug(
            "compile() de '%s': estado=%s errores=%s avisos=%s",
            nombre, leido["estado"], leido["errores"], leido["avisos"],
        )
        try:
            consistente_despues = bool(bloque.is_consistent())
        except Exception:
            # Defensivo: si no se puede comprobar, se avisa como error.
            consistente_despues = False
        tiene_errores = bool(leido["errores"]) or not consistente_despues
        compilados.append(
            {
                "nombre": nombre,
                "tiene_errores": tiene_errores,
                "mensajes": leido["errores"],
                "avisos": leido["avisos"],
                "era_inconsistente": True,
            }
        )

    return {
        "compilados": compilados,
        "sin_cambios": sin_cambios,
        "no_encontrados": no_encontrados,
        "errores": errores,
        "con_errores": [c["nombre"] for c in compilados if c["tiene_errores"]],
        "n_compilados_ok": sum(1 for c in compilados if not c["tiene_errores"]),
        "n_compilados_error": sum(1 for c in compilados if c["tiene_errores"]),
        "n_sin_cambios": len(sin_cambios),
        "n_no_encontrados": len(no_encontrados),
        "n_errores": len(errores),
    }
