"""Declaracion de los steps de un Function Block.

Un step se declara UNA vez, encima de su propio codigo, con su nombre
visible (la etiqueta que ve el operario en la barra de progreso) y su
descripcion (que hace):

    @step("Exportar etiquetas", descripcion="Exporta las tablas de tags")
    def _stage_1_exportar_etiquetas(self) -> str:
        ...
        return "Exportar etiquetas: 13 tablas exportadas"

El motor (``core/composition/plc_function_base.py``) recoge esos pasos
en **orden de definicion**, que es el orden del flujo, y hace el
dispatch. El FB no declara los pasos en ninguna otra lista: no hay
tabla de stages, ni ``steps=``, ni dispatch propio.

Contrato de la declaracion:
  - ``nombre``: etiqueta visible del step. Cambiarla es un cambio de UX
    (la ve el operario), no un refactor.
  - ``descripcion``: que hace el paso. Va al log del runtime y al
    diagrama SFC del FB.
  - ``metodo``: nombre del metodo que lo implementa. El motor lo
    invoca por nombre, asi que debe ser un metodo de la propia clase.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

# Atributo con el que se marca un metodo como paso del FB.
STEP_ATTR = "_step_spec"


@dataclass(frozen=True)
class StepSpec:
    """Lo que un paso declara sobre si mismo."""

    nombre: str
    descripcion: str
    metodo: str

    def as_dict(self) -> dict[str, Any]:
        """Shape interno del step (``self.steps``).

        ``handler`` es el metodo que el motor invoca; ``nombre`` es la
        etiqueta que ve el operario.
        """
        return {
            "nombre": self.nombre,
            "descripcion": self.descripcion,
            "handler": self.metodo,
        }


def step(nombre: str, descripcion: str = "") -> Callable[[Callable], Callable]:
    """Declara un metodo como paso del FB.

    Args:
        nombre: etiqueta del paso. Es lo que ve el operario en la barra
            de progreso, asi que no se renombra a la ligera.
        descripcion: que hace el paso. Va al log y al diagrama del FB.

    El orden de los pasos es el de definicion de los metodos: el flujo
    se lee de arriba abajo, como un SFC.
    """

    def deco(fn: Callable) -> Callable:
        setattr(
            fn,
            STEP_ATTR,
            StepSpec(
                nombre=nombre,
                descripcion=descripcion,
                metodo=fn.__name__,
            ),
        )
        return fn

    return deco


__all__ = ["STEP_ATTR", "StepSpec", "step"]
