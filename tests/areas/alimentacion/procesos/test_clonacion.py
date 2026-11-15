"""La clonacion de una plantilla TIA: los diccionarios y el renombrado.

Que reglas se construyen de la copia de la plantilla y como se aplican a
nombres y contenidos. Es logica pura: aqui no hay ni portal de TIA ni
transacciones.
"""
from __future__ import annotations

import shutil
import xml.etree.ElementTree as ET
from pathlib import Path

from zc_suite.areas.alimentacion.procesos.clonacion import (
    proc_aplicar_clonacion,
    proc_construir_diccionarios,
)

#: El desplazamiento de prueba (el offset de main, -50000): la plantilla
#: 50500 -> el proceso nuevo 500.
BASE_VIEJA = 50500
BASE_NUEVA = 500


def _plantilla(tmp_path: Path) -> Path:
    """Una plantilla de proceso 50500 con el layout de una exportacion TIA.

    Incluye el caso stem-only: ``FC50501_CIP1_ORDENES_R_L1`` dentro de
    ``50500_Principal`` (el 50501 solo sale del stem, no de ninguna
    carpeta).
    """
    raiz = tmp_path / "plantilla"
    bloques = raiz / "Bloques de programa" / "50500_Principal"
    bloques.mkdir(parents=True)
    (bloques / "DB50500_CIP1_INTERFAZ.s7dcl").write_bytes(b'S7_BlockNumber := "50500"\r\n')
    (bloques / "DB50500_CIP1_INTERFAZ.s7res").write_bytes(
        b"MultiLingualTexts:\r\n  - es-ES: DB50500_CIP1_INTERFAZ\r\n"
    )
    (bloques / "FC50501_CIP1_ORDENES_R_L1.s7dcl").write_bytes(b"END_FUNCTION_BLOCK\r\n")
    (bloques / "FC50501_CIP1_ORDENES_R_L1.s7res").write_bytes(b"es-ES: FC50501\r\n")
    (bloques / "FB50502_CIP1_LOGICA.s7dcl").write_bytes(b"END_FUNCTION_BLOCK\r\n")
    (bloques / "FB50502_CIP1_LOGICA.s7res").write_bytes(b"es-ES: FB50502\r\n")
    (bloques / "50501_Subproceso").mkdir()
    (bloques / "50501_Subproceso" / "DB50501_CIP1_AUX.s7dcl").write_bytes(
        b"END_DATA_BLOCK\r\n"
    )
    (bloques / "50501_Subproceso" / "DB50501_CIP1_AUX.s7res").write_bytes(b"es-ES: DB\r\n")
    (raiz / "Table1.xml").write_bytes(
        b"<AttributeList><Name>50500_CIP1</Name><Value>3</Value></AttributeList>\r\n"
    )
    (raiz / "nota.txt").write_bytes(b"DB50500_CIP1 no se toca\r\n")
    (raiz / "binario.bin").write_bytes(b"\x00\x01DB50500_CIP1\xff")
    (raiz / "manifest.json").write_bytes(b"{}")
    return raiz


def _copiar_plantilla(origen: Path, destino: Path) -> None:
    """Copia la plantilla a ``destino`` sin el ``manifest.json``."""
    shutil.copytree(origen, destino, ignore=lambda _d, nombres: ["manifest.json"])


def _diccionarios(plantilla: Path) -> tuple[dict[str, str], dict[str, str]]:
    return proc_construir_diccionarios(
        plantilla,
        BASE_VIEJA,
        BASE_NUEVA,
        "CIP1",
        "NUE",
        "Principal",
        "Nuevo",
    )


# ── los diccionarios ─────────────────────────────────────────────────────────


def test_construir_diccionarios_reglas_de_main(tmp_path: Path) -> None:
    """Las reglas de main: bloques, carpetas, stems, S7_BlockNumber, fallbacks."""
    dicc_bloques, dicc_xml = _diccionarios(_plantilla(tmp_path))
    # Bloques: prefijo(num - base_vieja + base_nueva) + fallbacks de codigo.
    assert dicc_bloques["DB50500_CIP1_INTERFAZ"] == "DB500_NUE_INTERFAZ"
    assert dicc_bloques["FC50501_CIP1_ORDENES_R_L1"] == "FC501_NUE_ORDENES_R_L1"
    assert dicc_bloques["FB50502_CIP1_LOGICA"] == "FB502_NUE_LOGICA"
    assert dicc_bloques["DB50501_CIP1_AUX"] == "DB501_NUE_AUX"
    # Prefijo numerico de carpeta: en ambos dicts.
    assert dicc_bloques["50501_"] == "501_"
    assert dicc_xml["50501_"] == "501_"
    # Metadatos S7_BlockNumber: solo dicc_bloques.
    assert dicc_bloques['S7_BlockNumber := "50500"'] == 'S7_BlockNumber := "500"'
    assert not any("S7_BlockNumber" in clave for clave in dicc_xml)
    # Fallbacks de codigo y nombre: en ambos dicts.
    assert dicc_bloques["CIP1"] == "NUE"
    assert dicc_xml["CIP1"] == "NUE"
    assert dicc_bloques["Principal"] == "Nuevo"
    assert dicc_xml["Principal"] == "Nuevo"
    # Las tres bases estandar, aunque no salgan del walk.
    for vieja, nueva in ((50500, 500), (53500, 3500), (55500, 5500)):
        assert dicc_bloques[f"{vieja}_"] == f"{nueva}_"
        assert dicc_xml[f"{vieja}_"] == f"{nueva}_"


def test_construir_diccionarios_orden_por_longitud(tmp_path: Path) -> None:
    """La clave mas larga gana a la del prefijo: DB50500_CIP1_INTERFAZ antes que 50500_."""
    dicc_bloques, dicc_xml = _diccionarios(_plantilla(tmp_path))
    for dicc in (dicc_bloques, dicc_xml):
        claves = list(dicc)
        longitudes = [len(clave) for clave in claves]
        assert longitudes == sorted(longitudes, reverse=True)
    assert list(dicc_bloques).index("DB50500_CIP1_INTERFAZ") < list(
        dicc_bloques
    ).index("50500_")


def test_construir_diccionarios_stem_only_sin_carpeta(tmp_path: Path) -> None:
    """El numero de un stem (FC50501_) aporta su regla aunque no sea carpeta."""
    raiz = tmp_path / "plantilla"
    (raiz / "Bloques de programa" / "50500_Principal").mkdir(parents=True)
    dcl = raiz / "Bloques de programa" / "50500_Principal" / "FC50501_CIP1_ORDENES_R_L1.s7dcl"
    dcl.write_bytes(b"END_FUNCTION_BLOCK\r\n")
    dicc_bloques, dicc_xml = proc_construir_diccionarios(
        raiz, BASE_VIEJA, BASE_NUEVA, "", "", "", ""
    )
    # La regla 50501_ sale del stem del archivo, no de ninguna carpeta.
    assert dicc_bloques["50501_"] == "501_"
    assert dicc_xml["50501_"] == "501_"
    assert dicc_bloques["FC50501_CIP1_ORDENES_R_L1"] == "FC501_CIP1_ORDENES_R_L1"


def test_construir_diccionarios_otro_offset(tmp_path: Path) -> None:
    """Un offset distinto al desplazamiento de bases: la regla es la misma."""
    dicc_bloques, _dicc_xml = proc_construir_diccionarios(
        _plantilla(tmp_path), 50500, 900, "", "", "", ""
    )
    assert dicc_bloques["50501_"] == "901_"
    assert dicc_bloques["FC50501_CIP1_ORDENES_R_L1"] == "FC901_CIP1_ORDENES_R_L1"
    assert dicc_bloques["50500_"] == "900_"


# ── la aplicacion ────────────────────────────────────────────────────────────


def test_aplicar_clonacion_renombra_nombres_y_contenido(tmp_path: Path) -> None:
    """El renombrado completo: nombres de ficheros, de carpetas y contenido."""
    plantilla = _plantilla(tmp_path)
    dir_nuevo = tmp_path / "nuevo"
    _copiar_plantilla(plantilla, dir_nuevo)
    generados = proc_aplicar_clonacion(dir_nuevo, *_diccionarios(plantilla))
    # Nombres de ficheros renombrados.
    base = dir_nuevo / "Bloques de programa" / "500_Nuevo"
    assert (base / "DB500_NUE_INTERFAZ.s7dcl").is_file()
    assert (base / "FC501_NUE_ORDENES_R_L1.s7dcl").is_file()
    assert (base / "FB502_NUE_LOGICA.s7dcl").is_file()
    # Carpeta renombrada con su hijo intacto.
    assert (base / "501_Subproceso" / "DB501_NUE_AUX.s7dcl").is_file()
    # El nombre de carpeta del proceso (50500_Principal -> 500_Nuevo).
    assert not (dir_nuevo / "Bloques de programa" / "50500_Principal").exists()
    # El contenido del .s7dcl: S7_BlockNumber y el nombre del bloque.
    assert (base / "DB500_NUE_INTERFAZ.s7dcl").read_bytes() == (
        b'S7_BlockNumber := "500"\r\n'
    )
    # El contenido del .s7res: el nombre del bloque, con BOM y CRLF.
    assert (base / "DB500_NUE_INTERFAZ.s7res").read_bytes() == (
        b"\xef\xbb\xbfMultiLingualTexts:\r\n"
        b"  - es-ES: DB500_NUE_INTERFAZ\r\n"
    )
    # El contenido del .xml: dicc_xml (la regla de prefijo 50500_).
    assert (dir_nuevo / "Table1.xml").read_bytes() == (
        b"<AttributeList><Name>500_NUE</Name><Value>3</Value></AttributeList>\r\n"
    )
    # Lo no listado no se toca: .txt y .bin quedan byte-identicos.
    assert (dir_nuevo / "nota.txt").read_bytes() == b"DB50500_CIP1 no se toca\r\n"
    assert (dir_nuevo / "binario.bin").read_bytes() == b"\x00\x01DB50500_CIP1\xff"
    # El manifest no esta (no se copio) y no figura en generados.
    assert not (dir_nuevo / "manifest.json").exists()
    assert "manifest.json" not in generados
    # Las rutas son relativas con "/" y cubren todos los ficheros de salida.
    assert set(generados) == {
        "Table1.xml",
        "nota.txt",
        "binario.bin",
        "Bloques de programa/500_Nuevo/DB500_NUE_INTERFAZ.s7dcl",
        "Bloques de programa/500_Nuevo/DB500_NUE_INTERFAZ.s7res",
        "Bloques de programa/500_Nuevo/FC501_NUE_ORDENES_R_L1.s7dcl",
        "Bloques de programa/500_Nuevo/FC501_NUE_ORDENES_R_L1.s7res",
        "Bloques de programa/500_Nuevo/FB502_NUE_LOGICA.s7dcl",
        "Bloques de programa/500_Nuevo/FB502_NUE_LOGICA.s7res",
        "Bloques de programa/500_Nuevo/501_Subproceso/DB501_NUE_AUX.s7dcl",
        "Bloques de programa/500_Nuevo/501_Subproceso/DB501_NUE_AUX.s7res",
    }


def test_aplicar_clonacion_s7dcl_con_bom_y_crlf(tmp_path: Path) -> None:
    """Un .s7dcl con BOM y CRLF sale con BOM y CRLF (no se normaliza)."""
    plantilla = _plantilla(tmp_path)
    dcl = (
        plantilla / "Bloques de programa" / "50500_Principal" / "DB50500_CIP1_INTERFAZ.s7dcl"
    )
    dcl.write_bytes(
        b"\xef\xbb\xbfDATA_BLOCK DB50500_CIP1_INTERFAZ\r\nEND_DATA_BLOCK\r\n"
    )
    dir_nuevo = tmp_path / "nuevo"
    _copiar_plantilla(plantilla, dir_nuevo)
    proc_aplicar_clonacion(dir_nuevo, *_diccionarios(plantilla))
    salida = (
        dir_nuevo / "Bloques de programa" / "500_Nuevo" / "DB500_NUE_INTERFAZ.s7dcl"
    ).read_bytes()
    assert salida == (
        b"\xef\xbb\xbfDATA_BLOCK DB500_NUE_INTERFAZ\r\nEND_DATA_BLOCK\r\n"
    )


# ── los N_MAX en el XML ──────────────────────────────────────────────────────


def _xml_tabla(base: int) -> bytes:
    """El XML de la tabla de un proceso ``base``, con las cuatro N_MAX."""
    return (
        '<?xml version="1.0" encoding="utf-8"?>\r\n'
        "<Document>\r\n"
        "  <ObjectList>\r\n"
        f'    <SW.Tags.PlcUserConstant ID="1">\r\n'
        f'      <AttributeList><Name>{base}_N_MAX_PREAL</Name>'
        "<Value>1</Value></AttributeList>\r\n"
        '    </SW.Tags.PlcUserConstant>\r\n'
        f'    <SW.Tags.PlcUserConstant ID="2">\r\n'
        f'      <AttributeList><Name>{base}_N_MAX_PINT</Name>'
        "<Value>1</Value></AttributeList>\r\n"
        '    </SW.Tags.PlcUserConstant>\r\n'
        f'    <SW.Tags.PlcUserConstant ID="3">\r\n'
        f'      <AttributeList><Name>{base}_N_MAX_ALM</Name>'
        "<Value>1</Value></AttributeList>\r\n"
        '    </SW.Tags.PlcUserConstant>\r\n'
        f'    <SW.Tags.PlcUserConstant ID="4">\r\n'
        f'      <AttributeList><Name>{base}_N_MAX_ALM_HMI</Name>'
        "<Value>1</Value></AttributeList>\r\n"
        '    </SW.Tags.PlcUserConstant>\r\n'
        '    <SW.Tags.PlcUserConstant ID="5">\r\n'
        f'      <AttributeList><Name>{base}_OTRA</Name>'
        "<Value>9</Value></AttributeList>\r\n"
        '    </SW.Tags.PlcUserConstant>\r\n'
        "  </ObjectList>\r\n"
        "</Document>\r\n"
    ).encode()


MINIMOS_COMPLETOS = {
    "N_MAX_PREAL": 10,
    "N_MAX_PINT": 20,
    "N_MAX_ALM": 30,
    "N_MAX_ALM_HMI": 5,
}


def test_aplicar_clonacion_fija_los_nmax_del_operario(tmp_path: Path) -> None:
    """El <Value> de las cuatro N_MAX pasa al valor del operario."""
    plantilla = _plantilla(tmp_path)
    (plantilla / "Table1.xml").write_bytes(_xml_tabla(50500))
    dir_nuevo = tmp_path / "nuevo"
    _copiar_plantilla(plantilla, dir_nuevo)
    proc_aplicar_clonacion(
        dir_nuevo,
        *_diccionarios(plantilla),
        base_nueva=BASE_NUEVA,
        minimos_usuario=MINIMOS_COMPLETOS,
    )
    salida = (dir_nuevo / "Table1.xml").read_text(encoding="utf-8")
    assert f"<Name>{BASE_NUEVA}_N_MAX_PREAL</Name>" in salida
    for clave, valor in MINIMOS_COMPLETOS.items():
        assert f"<Name>{BASE_NUEVA}_{clave}</Name><Value>{valor}</Value>" in salida
    # Una constante no N_MAX de la tabla no se toca.
    assert f"<Name>{BASE_NUEVA}_OTRA</Name><Value>9</Value>" in salida


def test_aplicar_clonacion_nmax_clave_ausente_no_se_toca(tmp_path: Path) -> None:
    """Una clave sin valor del operario queda con el valor de la plantilla."""
    plantilla = _plantilla(tmp_path)
    (plantilla / "Table1.xml").write_bytes(_xml_tabla(50500))
    dir_nuevo = tmp_path / "nuevo"
    _copiar_plantilla(plantilla, dir_nuevo)
    proc_aplicar_clonacion(
        dir_nuevo,
        *_diccionarios(plantilla),
        base_nueva=BASE_NUEVA,
        minimos_usuario={"N_MAX_PREAL": 10},
    )
    salida = (dir_nuevo / "Table1.xml").read_text(encoding="utf-8")
    assert f"<Name>{BASE_NUEVA}_N_MAX_PREAL</Name><Value>10</Value>" in salida
    for clave in ("N_MAX_PINT", "N_MAX_ALM", "N_MAX_ALM_HMI"):
        assert f"<Name>{BASE_NUEVA}_{clave}</Name><Value>1</Value>" in salida


def test_aplicar_clonacion_xml_sin_plcuserconstant_no_se_toca(tmp_path: Path) -> None:
    """Un XML sin PlcUserConstant no recibe el override de N_MAX."""
    plantilla = _plantilla(tmp_path)
    (plantilla / "Table1.xml").write_bytes(
        b"<Document><Value>7</Value></Document>\r\n"
    )
    dir_nuevo = tmp_path / "nuevo"
    _copiar_plantilla(plantilla, dir_nuevo)
    proc_aplicar_clonacion(
        dir_nuevo,
        *_diccionarios(plantilla),
        base_nueva=BASE_NUEVA,
        minimos_usuario=MINIMOS_COMPLETOS,
    )
    salida = (dir_nuevo / "Table1.xml").read_bytes()
    assert b"<Value>7</Value>" in salida


def test_aplicar_clonacion_sin_nmax_como_antes(tmp_path: Path) -> None:
    """Sin base_nueva/minimos_usuario el XML solo recibe dicc_xml."""
    plantilla = _plantilla(tmp_path)
    (plantilla / "Table1.xml").write_bytes(_xml_tabla(50500))
    dir_nuevo = tmp_path / "nuevo"
    _copiar_plantilla(plantilla, dir_nuevo)
    proc_aplicar_clonacion(dir_nuevo, *_diccionarios(plantilla))
    salida = (dir_nuevo / "Table1.xml").read_text(encoding="utf-8")
    # Renombrado de nombres por dicc_xml...
    assert f"<Name>{BASE_NUEVA}_N_MAX_PREAL</Name>" in salida
    # ... pero los valores quedan los de la plantilla (1).
    assert f"<Name>{BASE_NUEVA}_N_MAX_PREAL</Name><Value>1</Value>" in salida


def test_aplicar_clonacion_nmax_preserva_crlf_y_encoding(tmp_path: Path) -> None:
    """El XML con CRLF sale con CRLF y el override no rompe la estructura."""
    plantilla = _plantilla(tmp_path)
    (plantilla / "Table1.xml").write_bytes(_xml_tabla(50500))
    dir_nuevo = tmp_path / "nuevo"
    _copiar_plantilla(plantilla, dir_nuevo)
    proc_aplicar_clonacion(
        dir_nuevo,
        *_diccionarios(plantilla),
        base_nueva=BASE_NUEVA,
        minimos_usuario=MINIMOS_COMPLETOS,
    )
    salida = (dir_nuevo / "Table1.xml").read_bytes()
    assert b"\r\n" in salida
    assert b"\n<Name>" not in salida
    assert b"\n  </ObjectList>\r\n" in salida
    # El XML sigue siendo parseable con los cuatro valores fijados.
    arbol = ET.fromstring(salida.decode("utf-8"))
    valores = {
        nombre.text: valor.text
        for nombre, valor in (
            (elemento.find("./AttributeList/Name"), elemento.find("./AttributeList/Value"))
            for elemento in arbol.iter("SW.Tags.PlcUserConstant")
        )
        if nombre is not None and valor is not None
        and nombre.text is not None and "N_MAX" in nombre.text
    }
    assert valores == {
        f"{BASE_NUEVA}_N_MAX_PREAL": "10",
        f"{BASE_NUEVA}_N_MAX_PINT": "20",
        f"{BASE_NUEVA}_N_MAX_ALM": "30",
        f"{BASE_NUEVA}_N_MAX_ALM_HMI": "5",
    }
