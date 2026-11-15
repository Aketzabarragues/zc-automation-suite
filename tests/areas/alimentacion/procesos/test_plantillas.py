"""El manifest y las validaciones de una plantilla de proceso.

El ``manifest.json`` de una plantilla TIA y las validaciones previas a la
clonacion (N_MAX del operario, colisiones con los bloques del PLC y
dependencias externas). Es logica pura: aqui no hay ni portal de TIA ni
transacciones.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from zc_suite.areas.alimentacion.procesos.plantillas import (
    ManifestInvalidoError,
    PlantillaMinimosNoCumplidosError,
    proc_detectar_colisiones,
    proc_generar_previstos,
    proc_leer_manifest,
    proc_validar_dependencias,
    proc_validar_minimos,
)
from zc_suite.errores import ZCError

#: Un manifest completo y valido, base para los tests.
MANIFEST_VALIDO: dict[str, object] = {
    "base": 50500,
    "codigo": "CIP1",
    "nombre": "Principal",
    "descripcion": "Plantilla de proceso de alimentacion.",
    "dependencias": ["DB1_SYS", "FC15151_ZC_MARCHA_PARO_SEC"],
    "minimos": {"N_MAX_PREAL": 10, "N_MAX_PINT": 5},
}


def _escribir_manifest(tmp_path: Path, manifest: dict[str, object]) -> Path:
    (tmp_path / "manifest.json").write_text(
        json.dumps(manifest), encoding="utf-8"
    )
    return tmp_path


def _manifest_sin(campo: str) -> dict[str, object]:
    manifest = dict(MANIFEST_VALIDO)
    del manifest[campo]
    return manifest


# ── proc_leer_manifest ──────────────────────────────────────────────────────


def test_leer_manifest_valido(tmp_path: Path) -> None:
    """Un manifest completo devuelve su dict tal cual."""
    dir_plantilla = _escribir_manifest(tmp_path, MANIFEST_VALIDO)
    manifest = proc_leer_manifest(dir_plantilla)
    assert manifest["base"] == 50500
    assert manifest["codigo"] == "CIP1"
    assert manifest["descripcion"] == "Plantilla de proceso de alimentacion."
    assert manifest["dependencias"] == ["DB1_SYS", "FC15151_ZC_MARCHA_PARO_SEC"]
    assert manifest["minimos"] == {"N_MAX_PREAL": 10, "N_MAX_PINT": 5}


def test_leer_manifest_sin_fichero(tmp_path: Path) -> None:
    """Sin manifest.json: error con la ruta de la carpeta."""
    with pytest.raises(ManifestInvalidoError) as excinfo:
        proc_leer_manifest(tmp_path)
    assert str(excinfo.value) == f"No se encontro manifest.json en: {tmp_path}"


def test_leer_manifest_json_roto(tmp_path: Path) -> None:
    """JSON no parseable: 'manifest.json invalido'."""
    (tmp_path / "manifest.json").write_text("{no es json", encoding="utf-8")
    with pytest.raises(ManifestInvalidoError) as excinfo:
        proc_leer_manifest(tmp_path)
    assert str(excinfo.value).startswith("manifest.json invalido")


@pytest.mark.parametrize(
    "campo",
    ["base", "codigo", "descripcion", "dependencias"],
)
def test_leer_manifest_campo_falta(tmp_path: Path, campo: str) -> None:
    """Cada campo obligatorio produce su error propio (texto exacto de main)."""
    dir_plantilla = _escribir_manifest(tmp_path, _manifest_sin(campo))
    with pytest.raises(ManifestInvalidoError) as excinfo:
        proc_leer_manifest(dir_plantilla)
    texto_esperado = {
        "base": "manifest.json debe contener 'base' (int).",
        "codigo": "manifest.json debe contener 'codigo' (str).",
        "descripcion": (
            "manifest.json debe contener 'descripcion' (str no vacio). "
            "Es obligatorio para mostrar la plantilla en la SPA."
        ),
        "dependencias": (
            "manifest.json debe contener 'dependencias' (list[str]). "
            "Es obligatorio para validar bloques externos en el PLC."
        ),
    }[campo]
    assert str(excinfo.value) == texto_esperado


def test_leer_manifest_base_no_int(tmp_path: Path) -> None:
    """'base' como str no vale (debe ser int)."""
    manifest = dict(MANIFEST_VALIDO, base="50500")
    dir_plantilla = _escribir_manifest(tmp_path, manifest)
    with pytest.raises(ManifestInvalidoError, match="debe contener 'base'"):
        proc_leer_manifest(dir_plantilla)


def test_leer_manifest_dependencias_elemento_vacio(tmp_path: Path) -> None:
    """'dependencias' con un string vacio no vale."""
    manifest = dict(MANIFEST_VALIDO, dependencias=["DB1_SYS", "  "])
    dir_plantilla = _escribir_manifest(tmp_path, manifest)
    with pytest.raises(
        ManifestInvalidoError, match="debe ser una lista de strings no vacios"
    ):
        proc_leer_manifest(dir_plantilla)


# ── proc_validar_minimos ────────────────────────────────────────────────────


def test_validar_minimos_suficientes() -> None:
    """Los minimos del operario cubren los de la plantilla: no lanza."""
    proc_validar_minimos(
        MANIFEST_VALIDO,
        {
            "N_MAX_PREAL": 10,
            "N_MAX_PINT": 5,
            "N_MAX_ALM": 0,
            "N_MAX_ALM_HMI": 0,
        },
    )


def test_validar_minimos_sin_clave_en_manifest() -> None:
    """Sin 'minimos' en el manifest (o con minimos vacios) no hay minimo."""
    manifest = {k: v for k, v in MANIFEST_VALIDO.items() if k != "minimos"}
    proc_validar_minimos(manifest, {})
    proc_validar_minimos({"minimos": {}}, {})


def test_validar_minimos_insuficientes_lista_todas_las_claves() -> None:
    """El error lista TODAS las claves que fallan, con el texto de main."""
    manifest = {
        **MANIFEST_VALIDO,
        "minimos": {
            "N_MAX_PREAL": 10,
            "N_MAX_PINT": 5,
            "N_MAX_ALM": 20,
            "N_MAX_ALM_HMI": 3,
        },
    }
    with pytest.raises(PlantillaMinimosNoCumplidosError) as excinfo:
        proc_validar_minimos(manifest, {})
    mensaje = str(excinfo.value)
    assert mensaje.startswith(
        "Los N_MAX del operario no cubren los minimos de la plantilla:\n"
    )
    assert "N_MAX_PREAL: usuario=0 < plantilla=10" in mensaje
    assert "N_MAX_PINT: usuario=0 < plantilla=5" in mensaje
    assert "N_MAX_ALM: usuario=0 < plantilla=20" in mensaje
    assert "N_MAX_ALM_HMI: usuario=0 < plantilla=3" in mensaje
    # El orden es el de N_MAX_KEYS.
    assert mensaje.index("N_MAX_PREAL") < mensaje.index("N_MAX_PINT")
    assert mensaje.index("N_MAX_PINT") < mensaje.index("N_MAX_ALM")
    assert mensaje.index("N_MAX_ALM") < mensaje.index("N_MAX_ALM_HMI")


def test_validar_minimos_cubre_justo() -> None:
    """Igual al minimo (no menor) vale: no lanza."""
    proc_validar_minimos(
        MANIFEST_VALIDO,
        {"N_MAX_PREAL": 10, "N_MAX_PINT": 5},
    )


def test_excepciones_cuelgan_de_zcerror() -> None:
    """Las dos excepciones son fallos esperados (ZCError), no ValueError."""
    assert issubclass(ManifestInvalidoError, ZCError)
    assert issubclass(PlantillaMinimosNoCumplidosError, ZCError)
    assert not issubclass(ManifestInvalidoError, ValueError)
    assert not issubclass(PlantillaMinimosNoCumplidosError, ValueError)


# ── proc_detectar_colisiones ────────────────────────────────────────────────


def test_detectar_colisiones_por_nombre() -> None:
    """Un nombre post-rename ya presente en el PLC: colision por nombre."""
    dicc = {"DB500_CIP1_INTERFAZ": "DB600_EXP_INTERFAZ"}
    colisiones, colisiones_con = proc_detectar_colisiones(
        dicc, [{"nombre": "DB600_EXP_INTERFAZ", "numero": 60001}]
    )
    assert colisiones == ["DB600_EXP_INTERFAZ"]
    assert colisiones_con == {"DB600_EXP_INTERFAZ": "DB600_EXP_INTERFAZ"}


def test_detectar_colisiones_por_numero_mismo_prefijo() -> None:
    """Mismo numero y mismo prefijo alfabetico: colision por (prefijo, num)."""
    dicc = {"FC50501_CIP1_ORDENES": "FC601_EXP_ORDENES"}
    colisiones, colisiones_con = proc_detectar_colisiones(
        dicc, [{"nombre": "FC601_OTRO", "numero": 601}]
    )
    assert colisiones == ["FC601_EXP_ORDENES"]
    assert colisiones_con == {"FC601_EXP_ORDENES": "FC601_OTRO"}


def test_detectar_sin_colision_mismo_numero_distinto_prefijo() -> None:
    """FC100 y OB100 son bloques distintos: sin colision."""
    dicc = {"FC50501_CIP1": "FC100_EXP"}
    colisiones, colisiones_con = proc_detectar_colisiones(
        dicc, [{"nombre": "OB100_CICLO", "numero": 100}]
    )
    assert colisiones == []
    assert colisiones_con == {}


def test_detectar_colisiones_bloques_plc_none() -> None:
    """Cache no inicializada: mensaje accionable, sin abortar."""
    dicc = {"FC50501_CIP1": "FC100_EXP"}
    colisiones, colisiones_con = proc_detectar_colisiones(dicc, None)
    assert colisiones == [
        "Cache de bloques PLC no inicializado "
        "(escanea primero con 'Escanear bloques PLC')"
    ]
    assert colisiones_con == {}


def test_detectar_colisiones_str_legacy() -> None:
    """Entradas str de la cache legacy se normalizan a {'nombre': s}."""
    dicc = {"FC50501_CIP1": "FC100_EXP"}
    colisiones, colisiones_con = proc_detectar_colisiones(
        dicc, ["FC100_EXP"]
    )
    assert colisiones == ["FC100_EXP"]
    assert colisiones_con == {"FC100_EXP": "FC100_EXP"}


def test_detectar_colisiones_ignora_claves_de_prefijo_y_s7() -> None:
    """Claves S7_BlockNumber, numericas o con '_' final no se cruzan."""
    dicc = {
        'S7_BlockNumber := "50501"': 'S7_BlockNumber := "60001"',
        "50500_": "60000_",
        "DB50500_CIP1": "DB60001_EXP",
    }
    colisiones, _ = proc_detectar_colisiones(
        dicc, [{"nombre": "DB60001_EXP", "numero": 60001}]
    )
    assert colisiones == ["DB60001_EXP"]


def test_detectar_colisiones_vacio() -> None:
    """Sin entradas en ninguna parte: no hay colisiones."""
    assert proc_detectar_colisiones({}, []) == ([], {})


# ── proc_validar_dependencias ───────────────────────────────────────────────


def test_validar_dependencias_presente_y_ausente() -> None:
    """Devuelve solo las dependencias que no estan en el PLC."""
    bloques_plc = [
        {"nombre": "DB1_SYS", "numero": 1},
        {"nombre": "FC15151_ZC_MARCHA_PARO_SEC", "numero": 15151},
    ]
    faltantes = proc_validar_dependencias(
        ["DB1_SYS", "FC15151_ZC_MARCHA_PARO_SEC", "FC99999_NO_EXISTE"],
        bloques_plc,
    )
    assert faltantes == ["FC99999_NO_EXISTE"]


def test_validar_dependencias_bloques_plc_none() -> None:
    """Cache no inicializada: todas las dependencias faltan."""
    dependencias = ["DB1_SYS", "FC15151_ZC_MARCHA_PARO_SEC"]
    assert proc_validar_dependencias(dependencias, None) == list(dependencias)


def test_validar_dependencias_vacias() -> None:
    """Sin dependencias declaradas: lista vacia, ni aunque la cache sea None."""
    assert proc_validar_dependencias([], None) == []
    assert proc_validar_dependencias([], []) == []


def test_validar_dependencias_str_legacy() -> None:
    """Entradas str de la cache legacy cuentan para el match por nombre."""
    faltantes = proc_validar_dependencias(
        ["DB1_SYS", "FC99999_NO_EXISTE"], ["DB1_SYS"]
    )
    assert faltantes == ["FC99999_NO_EXISTE"]


def test_validar_dependencias_match_exacto_no_prefijo() -> None:
    """El match es por nombre completo, no por tipo+numero."""
    # DB15151 y DB15151_OTRO comparten numero pero no nombre: no coincide.
    faltantes = proc_validar_dependencias(
        ["DB15151_ZC"], [{"nombre": "DB15151_OTRO", "numero": 15151}]
    )
    assert faltantes == ["DB15151_ZC"]


# ── proc_generar_previstos ──────────────────────────────────────────────────


def _copia_previstos(tmp_path: Path, ficheros: dict[str, bytes]) -> Path:
    """Una copia de plantilla con los ``ficheros`` (ruta relativa -> bytes)."""
    raiz = tmp_path / "copia"
    raiz.mkdir()
    for rel, contenido in ficheros.items():
        path = raiz / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(contenido)
    return raiz


def test_previstos_agrupa_dcl_res_y_ignora_no_bloques(tmp_path: Path) -> None:
    """dcl+res del mismo stem = 1 entry; manifest/.xml/.scl no aparecen."""
    raiz = _copia_previstos(
        tmp_path,
        {
            "Bloques/DB50500_CIP1_INTERFAZ.s7dcl": b"END_DATA_BLOCK",
            "Bloques/DB50500_CIP1_INTERFAZ.s7res": b"es-ES",
            "Bloques/FC50501_CIP1_ORDENES.s7dcl": b"END_FUNCTION_BLOCK",
            "Bloques/FC50501_CIP1_ORDENES.s7res": b"es-ES",
            "Bloques/FC50501_CIP1_ORDENES.scl": b"(* scl no es bloque *)",
            "Table1.xml": b"<AttributeList/>",
            "manifest.json": b"{}",
        },
    )
    dicc = {
        "DB50500_CIP1_INTERFAZ": "DB600_EXP_INTERFAZ",
        "FC50501_CIP1_ORDENES": "FC601_EXP_ORDENES",
    }
    previstos = proc_generar_previstos(raiz, dicc, [], {})
    assert len(previstos) == 2
    assert previstos[0] == {
        "nombre_original": "DB50500_CIP1_INTERFAZ",
        "nombre_nuevo": "DB600_EXP_INTERFAZ",
        "estado": "OK",
    }
    assert previstos[1]["nombre_nuevo"] == "FC601_EXP_ORDENES"
    assert previstos[1]["estado"] == "OK"


def test_previstos_duplicado_con_id(tmp_path: Path) -> None:
    """nombre_nuevo en colisiones: 'DUPLICADO - <id>'."""
    raiz = _copia_previstos(
        tmp_path,
        {"Bloques/FC50501_CIP1.s7dcl": b"END_FUNCTION_BLOCK"},
    )
    previstos = proc_generar_previstos(
        raiz,
        {"FC50501_CIP1": "FC601_EXP_ORDENES"},
        ["FC601_EXP_ORDENES"],
        {"FC601_EXP_ORDENES": "FC601_OTRO"},
    )
    assert previstos == [
        {
            "nombre_original": "FC50501_CIP1",
            "nombre_nuevo": "FC601_EXP_ORDENES",
            "estado": "DUPLICADO - FC601_OTRO",
        }
    ]


def test_previstos_duplicado_sin_id(tmp_path: Path) -> None:
    """Colision sin identificador: 'DUPLICADO' (sin ' - <id>')."""
    raiz = _copia_previstos(
        tmp_path,
        {"Bloques/FC50501_CIP1.s7dcl": b"END_FUNCTION_BLOCK"},
    )
    previstos = proc_generar_previstos(
        raiz,
        {"FC50501_CIP1": "FC601_EXP_ORDENES"},
        ["FC601_EXP_ORDENES"],
        {},
    )
    assert previstos[0]["estado"] == "DUPLICADO"


def test_previstos_orden_casefold(tmp_path: Path) -> None:
    """El orden es por stem viejo casefold: 'a1' antes de 'B2' (mayusculas)."""
    raiz = _copia_previstos(
        tmp_path,
        {
            "Bloques/b2_aux.s7dcl": b"END_DATA_BLOCK",
            "Bloques/a1_base.s7dcl": b"END_DATA_BLOCK",
            "Bloques/C3_capital.s7dcl": b"END_DATA_BLOCK",
        },
    )
    previstos = proc_generar_previstos(raiz, {}, [], {})
    assert [p["nombre_original"] for p in previstos] == [
        "a1_base",
        "b2_aux",
        "C3_capital",
    ]


def test_previstos_plantilla_vacia(tmp_path: Path) -> None:
    """Copia sin ficheros de bloque (o vacia): lista vacia."""
    raiz = _copia_previstos(tmp_path, {"manifest.json": b"{}"})
    assert proc_generar_previstos(raiz, {}, [], {}) == []
    raiz_vacia = tmp_path / "vacia"
    raiz_vacia.mkdir()
    assert proc_generar_previstos(raiz_vacia, {}, [], {}) == []
