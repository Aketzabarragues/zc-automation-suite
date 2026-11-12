"""zc_suite.tia_ops.bloques — los bloques del PLC: leerlos y editar sus propiedades.

Portado de ``tia_helpers.py`` y ``tia_cmd_blocks.py`` de la version anterior,
sin la capa de comandos: aqui son funciones que reciben el portal y devuelven
primitivos.

Que funciona en cada version de TIA:

- **V18 y posteriores**: listar los bloques del PLC y leer sus propiedades
  (``get_program_blocks``, ``get_user_data_types``, ``get_property``), y
  cambiar el ``Name`` y el ``Number`` de un bloque (``set_property``).
- **Solo V21 en adelante**: exportar e importar en SimaticSD. Es lo que hace
  falta para leer y escribir el **comentario** de un bloque: el comentario no
  existe en ``get_property`` en ninguna version, solo en el XML exportado. Por
  eso el DTO no lleva campo de comentario.

Peculiaridades conservadas:

- ``set_property`` puede devolver 0 (OK) sin aplicar el cambio (fallo
  silencioso de Pythonnet en TIA V21). Por eso toda escritura se **vuelve a
  leer** para confirmar que en TIA el valor ha cambiado de verdad.
- El bloque se localiza **por su nombre**. Por eso, en un bloque con dos
  cambios, el renombrado va el **ultimo**: si fuera antes, el cambio
  siguiente buscaria el bloque por el nombre viejo, no lo encontraria y
  abortaria el lote entero con rollback.
- El SDK devuelve la lista **plana** de bloques: ``get_program_blocks()`` ya
  incluye los que estan dentro de grupos. La jerarquia se lee de
  ``get_path()`` de cada bloque, no del recorrido.
- TIA no expone el tipo del bloque como propiedad: hay que deducirlo de su
  lenguaje de programacion y de las propiedades que declara.
- Cuando una propiedad no tiene valor, el SDK devuelve el texto literal
  ``"no value"``. Se normaliza a ``None``.
- Los tipos de datos de usuario **no tienen numero**: su ``numero`` es
  ``None``. Y su ruta sale mas corta en ``get_path()`` que en los bloques:
  para ellos se usa ``get_path_full()``.
"""
from __future__ import annotations

import re
from typing import Any

from zc_suite.errores import OperacionError
from zc_suite.tia_ops._resolver import (
    bloques_del_plc,
    buscar_bloque,
    buscar_plc,
    nombre_bloque,
    tipos_de_datos_del_plc,
)

#: Propiedades que TIA deja cambiar con ``set_property``.
PROPIEDADES_EDITABLES: frozenset[str] = frozenset({"Name", "Number"})

#: Orden en que se aplican los cambios de un bloque. El renombrado va el
#: ultimo porque el bloque se localiza por su nombre en cada paso.
ORDEN_CAMBIO: tuple[str, ...] = ("Number", "Name")

#: Lenguajes con los que TIA escribe un FC o un FB.
_LENGUAJES_CODIGO = frozenset({"SCL", "LAD", "FBD", "STL", "GRAPH", "CFC"})

#: Texto que el SDK devuelve cuando una propiedad no tiene valor.
SIN_VALOR = "no value"

#: Propiedades extendidas que se leen de cada bloque: nombre de TIA y clave
#: del DTO.
_PROPIEDADES_EXTENDIDAS: tuple[tuple[str, str], ...] = (
    ("HeaderName", "title"),
    ("HeaderAuthor", "author"),
    ("HeaderVersion", "version"),
    ("ProgrammingLanguage", "programming_language"),
    ("MemoryLayout", "memory_layout"),
)


# ── lectura ────────────────────────────────────────────────────────────────


def escanear_bloques(portal: Any, plc: str) -> list[dict[str, Any]]:
    """Los bloques de programa del PLC, con sus propiedades.

    Args:
        portal: el portal de TIA.
        plc: nombre del PLC.

    Returns:
        Lista de ``{"nombre", "numero", "tipo", "ruta", "extended"}``.

        - ``nombre``: el nombre del bloque en TIA.
        - ``numero``: el numero del bloque. ``0`` si TIA no lo expone y el
          nombre no sigue la convencion ``DB12``/``FC3``.
        - ``tipo``: ``DB``, ``FB``, ``OB``, ``FC``, ``UDT`` u ``OTHER``.
        - ``ruta``: la jerarquia de grupos, con ``/`` de separador. Vacia
          para un bloque en la raiz del PLC.
        - ``extended``: ``title``, ``author``, ``version``,
          ``programming_language`` y ``memory_layout``. Lo que TIA no
          expone queda a ``None``.

    Raises:
        OperacionError: si el PLC no existe.
    """
    objetivo = buscar_plc(portal, plc)
    bloques: list[dict[str, Any]] = []
    for bloque in bloques_del_plc(objetivo):
        dto = _dto(bloque, plc)
        if dto is not None:
            bloques.append(dto)
    return bloques


def leer_bloques(portal: Any, plc: str, nombres: list[str]) -> list[dict[str, Any]]:
    """Las propiedades de los bloques indicados, leidas de TIA.

    Es lo que necesita el editor de bloques: no reescanea el PLC entero,
    solo lee los bloques que el operario ha seleccionado.

    Args:
        portal: el portal de TIA.
        plc: nombre del PLC.
        nombres: nombres de los bloques.

    Returns:
        Lista de ``{"nombre", "numero", "tipo", "ruta", "extended"}``, en el
        orden en que se han pedido. Un bloque que no existe se salta.

    Raises:
        OperacionError: si el PLC no existe.
    """
    objetivo = buscar_plc(portal, plc)
    leidos: list[dict[str, Any]] = []
    for nombre in nombres:
        try:
            nativo = buscar_bloque(objetivo, nombre)
        except OperacionError:
            continue
        dto = _dto(nativo, plc)
        if dto is not None:
            leidos.append(dto)
    return leidos


def escanear_tipos_de_usuario(portal: Any, plc: str) -> list[dict[str, Any]]:
    """Los tipos de datos de usuario (UDT) del PLC.

    Misma forma que ``escanear_bloques``. El ``tipo`` de todos es ``"UDT"``
    y su ``numero`` es ``None``: un tipo de datos de usuario no tiene numero.

    Args:
        portal: el portal de TIA.
        plc: nombre del PLC.

    Returns:
        Lista de ``{"nombre", "numero", "tipo", "ruta", "extended"}``.

    Raises:
        OperacionError: si el PLC no existe.
    """
    objetivo = buscar_plc(portal, plc)
    tipos: list[dict[str, Any]] = []
    for tipo in tipos_de_datos_del_plc(objetivo):
        dto = _dto(tipo, plc)
        if dto is not None:
            tipos.append(dto)
    return tipos


# ── escritura ──────────────────────────────────────────────────────────────


def cambiar_propiedad(
    portal: Any,
    plc: str,
    bloque: str,
    propiedad: str,
    valor: str | int,
) -> dict[str, Any]:
    """Cambia una propiedad de un bloque.

    **Debe llamarse dentro de una transaccion.** Sin transaccion, TIA no
    aplica el cambio.

    Args:
        portal: el portal de TIA.
        plc: nombre del PLC.
        bloque: nombre actual del bloque.
        propiedad: ``"Name"`` o ``"Number"``.
        valor: valor nuevo.

    Returns:
        ``{"bloque", "propiedad", "valor"}``.

    Raises:
        OperacionError: si la propiedad no es editable, si el bloque no
            existe o si TIA no aplica el cambio (y no solo dice que si).
    """
    if propiedad not in PROPIEDADES_EDITABLES:
        raise OperacionError(
            f"La propiedad '{propiedad}' de un bloque no se puede cambiar. "
            f"Editables: {sorted(PROPIEDADES_EDITABLES)}."
        )
    objetivo = buscar_plc(portal, plc)
    nativo = buscar_bloque(objetivo, bloque)
    codigo = nativo.set_property(name=propiedad, value=str(valor))
    if codigo != 0:
        raise OperacionError(
            f"Bloque '{bloque}': TIA rechazo el cambio de {propiedad} a "
            f"'{valor}' (codigo de retorno {codigo})."
        )
    actual = nativo.get_property(name=propiedad)
    if str(actual).strip() != str(valor).strip():
        raise OperacionError(
            f"Bloque '{bloque}': set_property devolvio 0 (OK) pero el valor real "
            f"en TIA de {propiedad} es '{actual}', no '{valor}'. Posible fallo "
            f"silencioso de Pythonnet/TIA V21."
        )
    return {"bloque": bloque, "propiedad": propiedad, "valor": valor}


def aplicar_cambios(
    portal: Any,
    plc: str,
    bloque: str,
    cambios: dict[str, str | int],
) -> dict[str, Any]:
    """Cambia varias propiedades de un bloque.

    **Debe llamarse dentro de una transaccion.** Sin transaccion, TIA no
    aplica los cambios.

    El renombrado va siempre el **ultimo**. El bloque se localiza por su
    nombre en cada paso: si el nombre se cambiara antes, el paso siguiente
    buscaria el bloque por el nombre viejo, no lo encontraria y el lote
    entero abortaria con rollback, perdiendo tambien el cambio anterior.
    Nombre y Number no dependen entre si, asi que el resultado final es el
    mismo.

    Args:
        portal: el portal de TIA.
        plc: nombre del PLC.
        bloque: nombre actual del bloque.
        cambios: ``{"Name": ..., "Number": ...}``. Solo se aplican las
            propiedades que aparezcan.

    Returns:
        ``{"bloque", "cambios"}``, con la lista de cambios aplicados en el
        orden en que se hicieron.

    Raises:
        OperacionError: si alguna propiedad no es editable, si el bloque no
            existe o si TIA no aplica un cambio (y no solo dice que si).
    """
    desconocidas = sorted(set(cambios) - PROPIEDADES_EDITABLES)
    if desconocidas:
        raise OperacionError(
            f"Propiedades de bloque no editables: {desconocidas}. "
            f"Editables: {sorted(PROPIEDADES_EDITABLES)}."
        )

    nombre_actual = bloque
    aplicados: list[dict[str, Any]] = []
    for propiedad in ORDEN_CAMBIO:
        if propiedad not in cambios:
            continue
        valor = cambios[propiedad]
        resultado = cambiar_propiedad(portal, plc, nombre_actual, propiedad, valor)
        aplicados.append({"propiedad": propiedad, "valor": resultado["valor"]})
        if propiedad == "Name":
            nombre_actual = str(valor)
    return {"bloque": bloque, "cambios": aplicados}


# ── helpers ────────────────────────────────────────────────────────────────


def _dto(bloque: Any, plc: str) -> dict[str, Any] | None:
    """El bloque como DTO. ``None`` si su nombre no se puede leer."""
    nombre = nombre_bloque(bloque)
    if not nombre:
        return None
    return {
        "nombre": str(nombre),
        "numero": _numero(bloque, str(nombre)),
        "tipo": _tipo(bloque, str(nombre)),
        "ruta": _ruta(bloque, plc),
        "extended": _extendidas(bloque),
    }


def _propiedad(bloque: Any, nombre: str) -> Any:
    """El valor de una propiedad del bloque. ``None`` si no se puede leer.

    La lectura es **por propiedad**: algunas lanzan errores de decodificacion
    UTF-8 y no deben tumbar el escaneo entero.
    """
    getter = getattr(bloque, "get_property", None)
    if getter is None:
        return None
    try:
        return getter(name=nombre)
    except Exception:
        return None


def _propiedades(bloque: Any) -> list[str]:
    """Los nombres de las propiedades que declara el bloque."""
    getter = getattr(bloque, "get_properties", None)
    if getter is None:
        return []
    try:
        return [str(propiedad) for propiedad in (getter() or [])]
    except Exception:
        return []


def _texto(valor: Any) -> str | None:
    """El valor como texto. ``None`` si esta vacio o si no tiene valor.

    Cuando una propiedad no tiene valor, el SDK devuelve el texto literal
    ``"no value"``. No es un dato: se normaliza a ``None``.
    """
    if valor is None:
        return None
    texto = str(valor).strip()
    if not texto or texto.casefold() == SIN_VALOR:
        return None
    return texto


def _es_tipo_de_usuario(bloque: Any) -> bool:
    """``True`` si el objeto es un tipo de datos de usuario."""
    return "UserDataType" in type(bloque).__name__


def _numero(bloque: Any, nombre: str) -> int | None:
    """El numero del bloque.

    Los tipos de datos de usuario no tienen numero: su numero es ``None``.

    En los bloques, el orden de resolucion es: la propiedad ``Number`` de
    TIA, el atributo ``Number`` y, como ultimo recurso, el prefijo del
    nombre (``DB12`` -> ``12``). El ultimo no es fuente de verdad: un bloque
    se puede llamar ``Principal`` y tener un numero asignado en TIA.
    """
    if _es_tipo_de_usuario(bloque):
        return None
    bruto = _propiedad(bloque, "Number")
    if bruto is not None:
        try:
            return int(str(bruto).strip())
        except (TypeError, ValueError):
            pass
    try:
        atributo = getattr(bloque, "Number", None)
    except Exception:
        atributo = None
    if atributo is not None:
        try:
            return int(str(atributo).strip())
        except (TypeError, ValueError):
            pass
    coincidencia = re.match(r"^(DB|FB|FC|OB)(\d+)", nombre, re.IGNORECASE)
    if coincidencia:
        return int(coincidencia.group(2))
    return 0


def _ruta(bloque: Any, plc: str) -> str:
    """La jerarquia de grupos del bloque. ``/`` de separador.

    TIA da dos caminos: ``get_path()`` llega hasta la carpeta de sistema del
    padre y ``get_path_full()`` hasta el proyecto. En los tipos de datos de
    usuario el primero se queda corto, asi que se usa el segundo cuando
    aporta mas.
    """
    corta = _ruta_corta(bloque)
    completa = _ruta_completa(bloque, plc, corta)
    return completa if len(completa) > len(corta) else corta


def _ruta_corta(bloque: Any) -> str:
    """La ruta segun ``get_path()``: hasta la carpeta de sistema del padre."""
    try:
        if hasattr(bloque, "get_path"):
            return str(bloque.get_path())
        if hasattr(bloque, "Path"):
            return str(bloque.Path)
    except Exception:
        return ""
    return ""


def _ruta_completa(bloque: Any, plc: str, corta: str) -> str:
    """La ruta segun ``get_path_full()``, sin lo anterior al PLC.

    Se separa por ``.`` o ``/``, se quita todo lo anterior al nombre del PLC
    y se vuelve a juntar con ``/``. Si el PLC no aparece, se supone que el
    primer segmento es el proyecto, pero solo se acepta si el resto encaja
    con la ruta corta.
    """
    getter = getattr(bloque, "get_path_full", None)
    if getter is None:
        return ""
    try:
        bruto = getter()
    except Exception:
        return ""
    if not bruto:
        return ""
    segmentos = [parte for parte in re.split(r"[./]", str(bruto)) if parte]
    for indice, segmento in enumerate(segmentos):
        if segmento.casefold() == plc.casefold():
            return "/".join(segmentos[indice + 1 :])
    if len(segmentos) > 1:
        resto = "/".join(segmentos[1:])
        if not corta or resto.endswith(corta):
            return resto
    return ""


def _extendidas(bloque: Any) -> dict[str, str | None]:
    """Las propiedades extendidas del bloque.

    El comentario no sale de aqui: no existe en ``get_property`` en ninguna
    version de TIA, solo en el XML exportado. Por eso el DTO no lo lleva.
    """
    extendidas: dict[str, str | None] = {
        clave: None for _, clave in _PROPIEDADES_EXTENDIDAS
    }
    for nombre, clave in _PROPIEDADES_EXTENDIDAS:
        extendidas[clave] = _texto(_propiedad(bloque, nombre))
    return extendidas


def _tipo(bloque: Any, nombre: str) -> str:
    """La familia del bloque.

    TIA no expone el tipo del bloque como propiedad, asi que se deduce:

    - UDT: la clase del objeto.
    - DB: su ``ProgrammingLanguage`` vale ``DB``.
    - FB: declara la propiedad ``ISMultiInstanceCapable``.
    - OB: declara ``SecondaryType`` o su nombre empieza por ``OB``.
    - FC: su lenguaje de programacion es uno de codigo.
    - OTHER: sin clasificar.
    """
    if _es_tipo_de_usuario(bloque):
        return "UDT"
    lenguaje = _propiedad(bloque, "ProgrammingLanguage")
    if lenguaje is not None and str(lenguaje).upper() == "DB":
        return "DB"
    return _clasificar(lenguaje, _propiedades(bloque), nombre)


def _clasificar(lenguaje: Any, propiedades: list[str], nombre: str) -> str:
    """La familia del bloque a partir de sus caracteristicas. No toca el SDK."""
    if lenguaje is not None and str(lenguaje).upper() == "DB":
        return "DB"
    declaradas = set(propiedades)
    if "ISMultiInstanceCapable" in declaradas:
        return "FB"
    if "SecondaryType" in declaradas or nombre.upper().startswith("OB"):
        return "OB"
    if lenguaje is not None and str(lenguaje).upper() in _LENGUAJES_CODIGO:
        return "FC"
    return "OTHER"
