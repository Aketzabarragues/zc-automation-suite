"""zc_suite.tia_ops.compilar — compilar el software del PLC.

Portado de ``core/infrastructure/tia/tia_cmd_compile.py`` de la version
anterior. Peculiaridades conservadas:

- ``compile_software()`` y ``block.compile()`` devuelven **True si hay
  errores**: es la semantica de Siemens, no "ha compilado bien".
- Al compilar bloques, uno que ya esta consistente se **salta**: no se
  recompila lo que no ha cambiado.
- Un bloque que no existe no hace fallar el lote: se anota.
- Si ``is_consistent()`` falla, se asume que el bloque NO es consistente y
  se compila igualmente.
- Si ``compile()`` falla en un bloque, se anota y se sigue con los demas.

La compilacion se hace **fuera** de la transaccion: TIA no la admite
dentro.

No se porta ``compile_hardware``: no tiene ningun llamador.
"""
from __future__ import annotations

from typing import Any

from zc_suite.tia_ops import OperacionError
from zc_suite.tia_ops._resolver import buscar_plc, nombre_bloque


def compilar_plc(portal: Any, plc: str) -> dict[str, Any]:
    """Compila todo el software del PLC.

    Args:
        portal: el portal de TIA.
        plc: nombre del PLC.

    Returns:
        ``{"tiene_errores": bool}``. ``True`` si la compilacion ha tenido
        errores.

    Raises:
        OperacionError: si el PLC no existe o TIA rechaza la compilacion.
    """
    objetivo = buscar_plc(portal, plc)
    try:
        tiene_errores = bool(objetivo.compile_software())
    except Exception as exc:
        raise OperacionError(
            f"No se pudo compilar el software del PLC '{plc}': "
            f"{type(exc).__name__}: {exc}"
        ) from exc
    return {"tiene_errores": tiene_errores}


def compilar_bloques(portal: Any, plc: str, nombres: list[str]) -> dict[str, Any]:
    """Compila una lista explicita de bloques del PLC.

    Es mas rapido que compilar todo el software cuando solo se han tocado
    unos bloques concretos.

    Args:
        portal: el portal de TIA.
        plc: nombre del PLC.
        nombres: nombres de los bloques a compilar.

    Returns:
        ``{"compilados", "sin_cambios", "no_encontrados", "errores"}`` y los
        contadores planos ``n_compilados_ok``, ``n_compilados_error``,
        ``n_sin_cambios``, ``n_no_encontrados`` y ``n_errores``.

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
            # ``compile()`` devuelve True si hay errores (semantica Siemens).
            tiene_errores = bool(bloque.compile())
        except Exception as exc:
            errores.append({"nombre": nombre, "error": f"{type(exc).__name__}: {exc}"})
            continue
        compilados.append(
            {
                "nombre": nombre,
                "tiene_errores": tiene_errores,
                "era_inconsistente": True,
            }
        )

    return {
        "compilados": compilados,
        "sin_cambios": sin_cambios,
        "no_encontrados": no_encontrados,
        "errores": errores,
        "n_compilados_ok": sum(1 for c in compilados if not c["tiene_errores"]),
        "n_compilados_error": (
            sum(1 for c in compilados if c["tiene_errores"]) + len(errores)
        ),
        "n_sin_cambios": len(sin_cambios),
        "n_no_encontrados": len(no_encontrados),
        "n_errores": len(errores),
    }
