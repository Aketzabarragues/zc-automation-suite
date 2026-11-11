"""El vocabulario del modelo del Excel maestro.

Un **campo** es un dato del modelo: su nombre, la cabecera del Excel que lo
alimenta y su tipo. Un **dominio** es una tabla del Excel: donde vive, que
campos tiene y que filas se descartan.

Los nombres de campo son los de ``main`` (los de sus DTO): las fases
siguientes los usan tal cual, sin renombrar nada.
"""
from __future__ import annotations

from dataclasses import dataclass

#: Campo de texto.
TEXTO = "texto"

#: Campo de numero entero.
ENTERO = "entero"

#: Campo de numero decimal.
DECIMAL = "decimal"

#: Campo de indice de lista: numero, o el texto que el operario escribe
#: (``"N/A"``, ``"TODOS"``...).
NUM_LISTA = "num_lista"


@dataclass(frozen=True)
class Campo:
    """Un campo del modelo.

    Attributes:
        nombre: el nombre del campo.
        cabecera: la cabecera del Excel que lo alimenta. Puede ser una tupla
            de cabeceras: gana la primera que este en la fila.
        tipo: el tipo del valor.
    """

    nombre: str
    cabecera: str | tuple[str, ...]
    tipo: str = TEXTO

    def cabeceras(self) -> tuple[str, ...]:
        """Las cabeceras del Excel que alimentan el campo."""
        if isinstance(self.cabecera, tuple):
            return self.cabecera
        return (self.cabecera,)


@dataclass(frozen=True)
class Dominio:
    """Una tabla del Excel: donde vive y que campos tiene.

    Attributes:
        clave: el nombre del dominio (``"DispED"``, ``"Procesos"``...).
        hoja: la hoja donde vive la tabla.
        tabla: el nombre de la tabla nombrada.
        campos: los campos del modelo.
        catalogo: el catalogo del ``config.json`` del que salen las
            etiquetas de las columnas (``"disp"``, ``"proc"``,
            ``"entidades"``). Vacio si no hay.
        descartar_si_vacias: campos que, si **todos** estan vacios,
            descartan la fila.
        exigir_no_vacias: campos que, si alguno esta vacio, descartan la
            fila.
        exigir_no_negativo: campos que, si alguno es negativo, descartan la
            fila.
        exigir_plc: si la fila sin PLC se descarta.
    """

    clave: str
    hoja: str
    tabla: str
    campos: tuple[Campo, ...]
    catalogo: str = ""
    descartar_si_vacias: tuple[str, ...] = ()
    exigir_no_vacias: tuple[str, ...] = ()
    exigir_no_negativo: tuple[str, ...] = ()
    exigir_plc: bool = True


#: Los campos que comparten todos los dispositivos.
CAMPOS_DISPOSITIVO = (
    Campo("numero", "Numero", ENTERO),
    Campo("plc_tag", "PLC.Tag"),
    Campo("plc_comentario", "PLC.Comentario"),
    Campo("descripcion", "Descripcion"),
    Campo("uid", "UID"),
    Campo("tag", "Tag"),
    Campo("fat", "FAT"),
    Campo("plc_tipo", "PLC.Tipo"),
    Campo("plc_index", "PLC.Index", ENTERO),
    Campo("hmi_index", "Hmi.Index", ENTERO),
    Campo("hmi_texto", "Hmi.Texto"),
    Campo("cfg_habilitar", "Cfg.Habilitar"),
    Campo("comentario_db", "ComentarioDB"),
    Campo("plc_name", "PLC"),
)

#: Los campos de la lista canonica de PLCs.
CAMPOS_PLC = (
    Campo("uid", "UID", ENTERO),
    Campo("plc", "PLC"),
)
