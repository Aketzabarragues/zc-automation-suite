"""Registro de areas operativas del sistema (Catalogo + Manifest).

El Catalogo vive en este modulo; el Manifest vive en cada area
(``areas/<area_id>/manifest.py``). Este modulo es la **unica fuente
de verdad** del Catalogo: las areas se registran al arrancar la app
llamando a ``register(AreaSpec(...))`` desde su ``register(engine, app)``.

Convenciones (.clinerules §5, §6, §9; AGENTS.md §5):
  - ``from __future__ import annotations`` en todo modulo con type hints.
  - Type hints en TODAS las firmas.
  - ``get_areas()`` retorna una **copia defensiva** (nunca la lista
    interna) para que nadie mute el registro desde fuera.
  - ``register()`` es idempotente por ``key``: un re-registro del
    mismo ``key`` SOBREESCRIBE (util en tests que resetean el estado
    entre casos).
  - ``reset()`` SOLO existe para tests. No se usa en produccion.

Anti-decisiones:
  - NO usar ``@dataclass(frozen=True)`` + ``field(default_factory=list)``
    en ``AreaSpec`` para evitar el "gotcha" de Python 3.12 con
    dataclasses frozen + listas mutables. En su lugar, todos los
    campos son inmutables (str, bool).
"""
from __future__ import annotations

from dataclasses import dataclass

# ============================================================================
#  AreaSpec: la "tarjeta" de un area
# ============================================================================


@dataclass(frozen=True)
class AreaSpec:
    """Especificacion de un area operativa.

    Atributos:
        key: Identificador unico (slug, kebab-case o snake_case).
            Ej: ``"tia_conexion"``. Lo usa la SPA como clave de
            routing en ``/areas/{key}``.
        label: Etiqueta humano-legible. Ej: ``"Conexion TIA"``.
        icon: Emoji o vacio. Default ``""``. Lo pinta la SPA en la
            card del Welcome.
        available: Si ``False``, la SPA muestra el area como
            "en desarrollo" (boton disabled, badge "wip").
            Default ``True``.
        description: Texto corto para la card del Welcome.
            Default ``""``. Si esta vacio, la SPA no pinta el parrafo.
    """

    key: str
    label: str
    icon: str = ""
    available: bool = True
    description: str = ""


# ============================================================================
#  Registry: lista en memoria de areas registradas
# ============================================================================


_REGISTRY: list[AreaSpec] = []


def register(spec: AreaSpec) -> None:
    """Registra un area. **Idempotente** por ``key`` (mismo key = sobrescribe).

    Args:
        spec: la especificacion del area a registrar.

    Comportamiento:
        - Si ya hay un ``AreaSpec`` con el mismo ``spec.key``, lo
          SUSTITUYE (util en tests que resetean entre casos).
        - Si no, lo APPEND al final.

    Note:
        No hay deduplicacion adicional: el orden de registro es el
        orden en que la SPA pinta las cards. Si quieres un orden
        concreto, registra las areas en ese orden en
        ``core/web/app.py::create_app()``.
    """
    for i, existing in enumerate(_REGISTRY):
        if existing.key == spec.key:
            _REGISTRY[i] = spec
            return
    _REGISTRY.append(spec)


def get_areas() -> list[AreaSpec]:
    """Snapshot del registro. **Retorna copia defensiva.**

    Returns:
        Lista con los ``AreaSpec`` actualmente registrados. La lista
        es una copia: mutar el retorno NO afecta al registro interno.
        Cada ``AreaSpec`` es ``frozen=True``, asi que tampoco se
        puede mutar sus campos.
    """
    return list(_REGISTRY)


def reset() -> None:
    """Vacia el registro. **SOLO para tests.** No usar en produccion.

    Casos de uso:
      - Limpiar el estado entre tests para que cada caso empiece
        con un registro vacio y registre las areas que necesita.
      - Forzar un re-registro tras un reload.
    """
    _REGISTRY.clear()
