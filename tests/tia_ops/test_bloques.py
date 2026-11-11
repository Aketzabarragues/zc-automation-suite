"""Tests de los bloques del PLC: escaneo y edicion de propiedades."""

from __future__ import annotations

from typing import Any

import pytest

from zc_suite.tia_ops import OperacionError
from zc_suite.tia_ops import bloques as ops

# ── dobles de test ─────────────────────────────────────────────────────────


class BloqueFalso:
    """Bloque de TIA con las propiedades que lee el escaneo."""

    def __init__(
        self,
        nombre: str,
        propiedades: dict[str, Any] | None = None,
        declaradas: list[str] | None = None,
        ruta: str = "",
        ruta_completa: str = "",
        codigo: int = 0,
        aplica: bool = True,
        legible: bool = True,
    ) -> None:
        self._nombre = nombre
        self._propiedades = dict(propiedades or {})
        self._declaradas = declaradas if declaradas is not None else list(self._propiedades)
        self._ruta = ruta
        self._ruta_completa = ruta_completa
        self.codigo = codigo
        self.aplica = aplica
        self.legible = legible
        self.llamadas: list[tuple[str, str]] = []

    def get_name(self) -> str:
        if not self.legible:
            raise UnicodeDecodeError("utf-8", b"\xff", 0, 1, "ilegible")
        return self._nombre

    def get_property(self, name: str) -> Any:
        if name == "Name":
            return self._nombre
        if name == "Number":
            return self._propiedades.get("Number")
        return self._propiedades.get(name)

    def get_properties(self) -> list[str]:
        return list(self._declaradas)

    def get_path(self) -> str:
        return self._ruta

    def get_path_full(self) -> str:
        return self._ruta_completa

    def set_property(self, name: str, value: str) -> int:
        self.llamadas.append((name, value))
        if self.aplica:
            if name == "Name":
                self._nombre = value
            elif name == "Number":
                self._propiedades["Number"] = value
        return self.codigo


class UserDataType(BloqueFalso):
    """Tipo de datos de usuario. La clase es lo que lo delata en TIA."""


class PlcFalso:
    def __init__(
        self,
        bloques: list[BloqueFalso] | None = None,
        tipos: list[BloqueFalso] | None = None,
    ) -> None:
        self.bloques = bloques or []
        self.tipos = tipos or []

    def get_name(self) -> str:
        return "ZC_PLC_STD"

    def get_program_blocks(self) -> list[BloqueFalso]:
        return self.bloques

    def get_user_data_types(self) -> list[BloqueFalso]:
        return self.tipos


class ProyectoFalso:
    def __init__(self, plc: PlcFalso) -> None:
        self.plc = plc

    def get_plcs(self) -> list[PlcFalso]:
        return [self.plc]


class PortalFalso:
    def __init__(self, plc: PlcFalso | None = None) -> None:
        self.proyecto = ProyectoFalso(plc) if plc is not None else None

    def get_project(self) -> ProyectoFalso | None:
        return self.proyecto


def _portal(bloques: list[BloqueFalso] | None = None) -> tuple[PortalFalso, PlcFalso]:
    plc = PlcFalso(bloques or [])
    return PortalFalso(plc), plc


# ── escaneo ────────────────────────────────────────────────────────────────


def test_escanear_bloques_devuelve_el_dto_de_cada_bloque() -> None:
    portal, _plc = _portal([BloqueFalso("OB1_MAIN", ruta="Programa")])

    resultado = ops.escanear_bloques(portal, "ZC_PLC_STD")

    assert resultado == [
        {
            "nombre": "OB1_MAIN",
            "numero": 1,
            "tipo": "OB",
            "ruta": "Programa",
            "extended": {
                "title": None,
                "author": None,
                "version": None,
                "programming_language": None,
                "memory_layout": None,
            },
        }
    ]


def test_escanear_bloques_lee_las_propiedades_extendidas() -> None:
    bloque = BloqueFalso(
        "DB10",
        propiedades={
            "HeaderName": "Datos de proceso",
            "HeaderAuthor": "Aketza",
            "HeaderVersion": "1.2",
            "ProgrammingLanguage": "DB",
            "MemoryLayout": "Optimized",
        },
    )
    portal, _plc = _portal([bloque])

    extendidas = ops.escanear_bloques(portal, "ZC_PLC_STD")[0]["extended"]

    assert extendidas["title"] == "Datos de proceso"
    assert extendidas["author"] == "Aketza"
    assert extendidas["version"] == "1.2"
    assert extendidas["programming_language"] == "DB"
    assert extendidas["memory_layout"] == "Optimized"


def test_el_dto_no_lleva_comentario() -> None:
    """El comentario no sale de TIA: sale del XML exportado."""
    portal, _plc = _portal([BloqueFalso("DB10")])

    extendidas = ops.escanear_bloques(portal, "ZC_PLC_STD")[0]["extended"]

    assert "comment" not in extendidas


def test_un_valor_que_no_existe_se_normaliza() -> None:
    """El SDK devuelve el texto literal 'no value' cuando no hay valor."""
    bloque = BloqueFalso(
        "DB10",
        propiedades={
            "HeaderName": "no value",
            "HeaderAuthor": "no value",
            "ProgrammingLanguage": "no value",
        },
    )
    portal, _plc = _portal([bloque])

    extendidas = ops.escanear_bloques(portal, "ZC_PLC_STD")[0]["extended"]

    assert extendidas["title"] is None
    assert extendidas["author"] is None
    assert extendidas["programming_language"] is None


def test_una_propiedad_que_falla_no_tumba_el_escaneo() -> None:
    """Algunas propiedades lanzan errores de decodificacion UTF-8."""
    bloque = BloqueFalso("DB10", propiedades={"HeaderName": "titulo"})
    original = bloque.get_property

    def get_property(name: str) -> Any:
        if name == "HeaderAuthor":
            raise UnicodeDecodeError("utf-8", b"\xff", 0, 1, "ilegible")
        return original(name)

    bloque.get_property = get_property  # type: ignore[method-assign]
    portal, _plc = _portal([bloque])

    extendidas = ops.escanear_bloques(portal, "ZC_PLC_STD")[0]["extended"]

    assert extendidas["title"] == "titulo"
    assert extendidas["author"] is None


def test_un_bloque_con_el_nombre_ilegible_no_aparece() -> None:
    portal, _plc = _portal([BloqueFalso("OCULTO", legible=False)])

    assert ops.escanear_bloques(portal, "ZC_PLC_STD") == []


def test_escanear_bloques_falla_si_el_plc_no_existe() -> None:
    portal, _plc = _portal([])

    with pytest.raises(OperacionError, match="No se encontro ningun PLC"):
        ops.escanear_bloques(portal, "OTRO_PLC")


def test_escanear_tipos_de_usuario_devuelve_los_udt() -> None:
    portal = PortalFalso(PlcFalso(tipos=[UserDataType("MiTipo")]))

    resultado = ops.escanear_tipos_de_usuario(portal, "ZC_PLC_STD")

    assert resultado[0]["nombre"] == "MiTipo"
    assert resultado[0]["tipo"] == "UDT"


def test_un_tipo_de_usuario_no_tiene_numero() -> None:
    portal = PortalFalso(PlcFalso(tipos=[UserDataType("MiTipo")]))

    assert ops.escanear_tipos_de_usuario(portal, "ZC_PLC_STD")[0]["numero"] is None


def test_la_ruta_de_un_tipo_de_usuario_es_la_jerarquia_entera() -> None:
    """get_path() se queda corto en los UDT: se usa get_path_full()."""
    tipo = UserDataType(
        "MiTipo",
        ruta="1_Documentado",
        ruta_completa="ZC_PLC_STD.ZC_Controles.1_Documentado",
    )
    portal = PortalFalso(PlcFalso(tipos=[tipo]))

    assert ops.escanear_tipos_de_usuario(portal, "ZC_PLC_STD")[0]["ruta"] == (
        "ZC_Controles/1_Documentado"
    )


def test_la_ruta_de_un_tipo_de_usuario_usa_barras() -> None:
    tipo = UserDataType(
        "MiTipo",
        ruta="1_Documentado",
        ruta_completa="ZC_PLC_STD/ZC_Controles/1_Documentado",
    )
    portal = PortalFalso(PlcFalso(tipos=[tipo]))

    assert ops.escanear_tipos_de_usuario(portal, "ZC_PLC_STD")[0]["ruta"] == (
        "ZC_Controles/1_Documentado"
    )


def test_si_la_ruta_completa_no_aporta_nada_se_queda_la_corta() -> None:
    tipo = UserDataType("MiTipo", ruta="1_Documentado", ruta_completa="")
    portal = PortalFalso(PlcFalso(tipos=[tipo]))

    assert ops.escanear_tipos_de_usuario(portal, "ZC_PLC_STD")[0]["ruta"] == "1_Documentado"


def test_la_ruta_de_un_bloque_no_cambia() -> None:
    bloque = BloqueFalso(
        "DB10",
        ruta="ZC_Controles/1_Documentado",
        ruta_completa="ZC_PLC_STD.ZC_Controles.1_Documentado",
    )
    portal, _plc = _portal([bloque])

    assert ops.escanear_bloques(portal, "ZC_PLC_STD")[0]["ruta"] == (
        "ZC_Controles/1_Documentado"
    )


# ── clasificacion ──────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("lenguaje", "declaradas", "nombre", "esperado"),
    [
        ("DB", [], "DB10", "DB"),
        ("SCL", ["ISMultiInstanceCapable"], "FB20", "FB"),
        ("SCL", ["SecondaryType"], "Cyclic", "OB"),
        ("SCL", [], "OB1_MAIN", "OB"),
        ("SCL", [], "FC30", "FC"),
        ("LAD", [], "FC31", "FC"),
        ("STL", [], "FC32", "FC"),
        ("GRAPH", [], "FC33", "FC"),
        ("CFC", [], "FC34", "FC"),
        (None, [], "Principal", "OTHER"),
    ],
)
def test_la_familia_del_bloque_se_deduce(
    lenguaje: str | None,
    declaradas: list[str],
    nombre: str,
    esperado: str,
) -> None:
    assert ops._clasificar(lenguaje, declaradas, nombre) == esperado


def test_el_lenguaje_se_compara_sin_importar_mayusculas() -> None:
    assert ops._clasificar("scl", [], "FC1") == "FC"


def test_un_udt_se_reconoce_por_su_clase() -> None:
    portal = PortalFalso(PlcFalso(tipos=[UserDataType("MiTipo")]))

    assert ops.escanear_tipos_de_usuario(portal, "ZC_PLC_STD")[0]["tipo"] == "UDT"


# ── el numero del bloque ───────────────────────────────────────────────────


def test_el_numero_se_lee_de_la_propiedad_de_tia() -> None:
    portal, _plc = _portal([BloqueFalso("Bloque", propiedades={"Number": "42"})])

    assert ops.escanear_bloques(portal, "ZC_PLC_STD")[0]["numero"] == 42


def test_el_numero_se_deduce_del_nombre_si_tia_no_lo_da() -> None:
    portal, _plc = _portal([BloqueFalso("DB12")])

    assert ops.escanear_bloques(portal, "ZC_PLC_STD")[0]["numero"] == 12


def test_un_bloque_sin_numero_vale_cero() -> None:
    portal, _plc = _portal([BloqueFalso("Principal")])

    assert ops.escanear_bloques(portal, "ZC_PLC_STD")[0]["numero"] == 0


# ── leer solo algunos bloques ──────────────────────────────────────────────


def test_leer_bloques_devuelve_solo_los_pedidos() -> None:
    portal, _plc = _portal([BloqueFalso("OB1_MAIN"), BloqueFalso("DB10")])

    resultado = ops.leer_bloques(portal, "ZC_PLC_STD", ["DB10"])

    assert [bloque["nombre"] for bloque in resultado] == ["DB10"]


def test_leer_bloques_salta_los_que_no_existen() -> None:
    portal, _plc = _portal([BloqueFalso("OB1_MAIN")])

    resultado = ops.leer_bloques(portal, "ZC_PLC_STD", ["OB1_MAIN", "NO_EXISTE"])

    assert [bloque["nombre"] for bloque in resultado] == ["OB1_MAIN"]


# ── cambiar una propiedad ──────────────────────────────────────────────────


def test_cambiar_propiedad_cambia_el_valor() -> None:
    bloque = BloqueFalso("OB1_MAIN")
    portal, _plc = _portal([bloque])

    resultado = ops.cambiar_propiedad(portal, "ZC_PLC_STD", "OB1_MAIN", "Name", "NUEVO")

    assert resultado == {"bloque": "OB1_MAIN", "propiedad": "Name", "valor": "NUEVO"}
    assert bloque.get_name() == "NUEVO"


def test_cambiar_propiedad_cambia_el_numero() -> None:
    bloque = BloqueFalso("DB10", propiedades={"Number": "10"})
    portal, _plc = _portal([bloque])

    ops.cambiar_propiedad(portal, "ZC_PLC_STD", "DB10", "Number", 25)

    assert bloque.get_property(name="Number") == "25"


def test_cambiar_propiedad_rechaza_una_propiedad_no_editable() -> None:
    portal, _plc = _portal([BloqueFalso("OB1_MAIN")])

    with pytest.raises(OperacionError, match="no se puede cambiar"):
        ops.cambiar_propiedad(portal, "ZC_PLC_STD", "OB1_MAIN", "Comment", "hola")


def test_cambiar_propiedad_falla_si_el_bloque_no_existe() -> None:
    portal, _plc = _portal([BloqueFalso("OB1_MAIN")])

    with pytest.raises(OperacionError, match="No se encontro el bloque"):
        ops.cambiar_propiedad(portal, "ZC_PLC_STD", "NO_EXISTE", "Name", "X")


def test_cambiar_propiedad_falla_si_tia_rechaza() -> None:
    bloque = BloqueFalso("OB1_MAIN", codigo=20)
    portal, _plc = _portal([bloque])

    with pytest.raises(OperacionError, match="TIA rechazo el cambio"):
        ops.cambiar_propiedad(portal, "ZC_PLC_STD", "OB1_MAIN", "Name", "X")


def test_cambiar_propiedad_detecta_el_fallo_silencioso() -> None:
    """set_property devuelve 0 pero el valor no cambia: hay que avisar."""
    bloque = BloqueFalso("OB1_MAIN", aplica=False)
    portal, _plc = _portal([bloque])

    with pytest.raises(OperacionError, match="set_property devolvio 0"):
        ops.cambiar_propiedad(portal, "ZC_PLC_STD", "OB1_MAIN", "Name", "X")


# ── aplicar varios cambios ─────────────────────────────────────────────────


def test_aplicar_cambios_cambia_el_numero_y_el_nombre() -> None:
    bloque = BloqueFalso("DB10", propiedades={"Number": "10"})
    portal, _plc = _portal([bloque])

    resultado = ops.aplicar_cambios(
        portal,
        "ZC_PLC_STD",
        "DB10",
        {"Name": "DB10_NUEVO", "Number": 25},
    )

    assert resultado["cambios"] == [
        {"propiedad": "Number", "valor": 25},
        {"propiedad": "Name", "valor": "DB10_NUEVO"},
    ]
    assert bloque.get_name() == "DB10_NUEVO"


def test_el_renombrado_va_el_ultimo() -> None:
    """El bloque se busca por su nombre: renombrar antes rompe el lote.

    Con el nombre cambiado antes, el paso del numero buscaria el bloque por
    el nombre viejo, no lo encontraria y abortaria el lote con rollback.
    """
    bloque = BloqueFalso("DB10", propiedades={"Number": "10"})
    portal, _plc = _portal([bloque])

    ops.aplicar_cambios(
        portal,
        "ZC_PLC_STD",
        "DB10",
        {"Name": "DB10_NUEVO", "Number": 25},
    )

    assert [nombre for nombre, _valor in bloque.llamadas] == ["Number", "Name"]


def test_el_renombrado_va_el_ultimo_aunque_llegue_primero() -> None:
    """El orden de las claves del diccionario no manda: manda el de TIA."""
    bloque = BloqueFalso("DB10", propiedades={"Number": "10"})
    portal, _plc = _portal([bloque])

    ops.aplicar_cambios(
        portal,
        "ZC_PLC_STD",
        "DB10",
        {"Name": "DB10_NUEVO", "Number": 25},
    )

    assert bloque.get_property(name="Number") == "25"
    assert bloque.get_name() == "DB10_NUEVO"


def test_aplicar_cambios_solo_toca_las_propiedades_pedidas() -> None:
    bloque = BloqueFalso("DB10", propiedades={"Number": "10"})
    portal, _plc = _portal([bloque])

    ops.aplicar_cambios(portal, "ZC_PLC_STD", "DB10", {"Number": 25})

    assert bloque.llamadas == [("Number", "25")]
    assert bloque.get_name() == "DB10"


def test_aplicar_cambios_rechaza_una_propiedad_no_editable() -> None:
    portal, _plc = _portal([BloqueFalso("DB10")])

    with pytest.raises(OperacionError, match="no editables"):
        ops.aplicar_cambios(portal, "ZC_PLC_STD", "DB10", {"Comment": "hola"})


def test_aplicar_cambios_aborta_si_un_cambio_falla() -> None:
    bloque = BloqueFalso("DB10", propiedades={"Number": "10"}, codigo=20)
    portal, _plc = _portal([bloque])

    with pytest.raises(OperacionError, match="TIA rechazo el cambio"):
        ops.aplicar_cambios(
            portal,
            "ZC_PLC_STD",
            "DB10",
            {"Name": "DB10_NUEVO", "Number": 25},
        )

    assert bloque.get_name() == "DB10"


# ── fronteras ──────────────────────────────────────────────────────────────


def test_lo_publico_devuelve_solo_primitivos() -> None:
    bloque = BloqueFalso("DB10", propiedades={"Number": "10"})
    portal, _plc = _portal([bloque])

    resultado = ops.escanear_bloques(portal, "ZC_PLC_STD")

    assert isinstance(resultado, list)
    assert all(isinstance(bloque, dict) for bloque in resultado)
    assert all(
        isinstance(valor, (str, int, type(None)))
        for bloque in resultado
        for clave, valor in bloque.items()
        if clave != "extended"
    )
    assert all(
        isinstance(valor, (str, type(None)))
        for bloque in resultado
        for valor in bloque["extended"].values()
    )


def test_los_mensajes_hablan_de_bloques() -> None:
    """El mensaje nombra el bloque y la propiedad, en idioma de TIA."""
    portal, _plc = _portal([BloqueFalso("OB1_MAIN")])

    with pytest.raises(OperacionError) as fallo:
        ops.cambiar_propiedad(portal, "ZC_PLC_STD", "OB1_MAIN", "Comment", "hola")

    error = str(fallo.value)
    assert "Comment" in error
    assert "Name" in error
    assert "Number" in error
