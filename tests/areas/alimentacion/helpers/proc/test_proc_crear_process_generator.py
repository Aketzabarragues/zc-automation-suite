"""Tests de las funciones puras absorbidas en los FBs ``proc_crear``.

Las funciones puras viven en los
archivos de los FBs como module-level, debajo del dataclass. Tests
cubren las funciones puras del pipeline (filesystem puro, sin TIA):

  - ``proc_process_leer_manifest``        -> ctx.manifest_plantilla + base_vieja.
  - ``proc_process_validar_minimos``      -> raises si minimos < plantilla.
  - ``proc_process_copiar_a_preview``     -> copia plantilla a staging.
  - ``proc_process_extraer_variables_xml``-> lista UID_NOMBRE en rango.
  - ``proc_process_construir_diccionarios``-> dicc_bloques + dicc_xml
                                            ordenados len desc.
  - ``proc_process_detectar_colisiones``  -> ctx.colisiones poblado.
  - ``proc_process_aplicar_clonacion``    -> escribe dir_nuevo con
                                            BOM .s7res preservado y
                                            <Value> de N_MAX actualizado.
  - ``proc_process_escribir_manifest``    -> manifest.json en dir_nuevo.

Restricciones:
  - NO toca el gateway TIA (helpers son offline).
  - Usa ``tmp_path`` (pytest builtin) para crear una plantilla dummy
    minima + un staging aislado por test.
  - Cada test llama a UNA o MAS funciones puras por vez y valida el
    efecto en el ``ctx``.

Nota: las funciones preview vienen del FB preview, las de apply
del FB sync. ``ProcProcessGenContext`` y los errores se toman del FB
preview por conveniencia (el dataclass es identico en ambos).
"""
from __future__ import annotations

import inspect
import json
import os
from pathlib import Path
from typing import Any

import pytest

from areas.alimentacion.functions.function_proc_crear_generar_preview import (
    ManifestInvalido,
    PlantillaMinimosNoCumplidos,
    ProcProcessGenContext,
    proc_process_copiar_a_preview,
    proc_process_detectar_colisiones,
    proc_process_generar_previstos,
    proc_process_leer_manifest,
    proc_process_validar_dependencias,
    proc_process_validar_minimos,
)
from areas.alimentacion.helpers.proc.proc_process_aplicar_clonacion import (
    proc_process_aplicar_clonacion,
)
from areas.alimentacion.helpers.proc.proc_process_construir_diccionarios import (
    proc_process_construir_diccionarios,
)
from areas.alimentacion.functions.function_proc_crear_sincronizar import (
    proc_process_escribir_manifest,
)


# ── Fixture: plantilla dummy ──────────────────────────────────────────


@pytest.fixture
def plantilla_dummy(tmp_path: Path) -> Path:
    """Crea una plantilla minima en tmp_path con manifest.json + 1
    .s7dcl + 1 .s7res (BOM) + 1 .xml de variables PLC con 6 N_MAX
    canonicas (4 del operario + 1 ETAPA_0 + 1 OTHER que no empieza
    por UID).
    """
    p = tmp_path / "TestPlantilla"
    p.mkdir()
    bloques = p / "Bloques de programa"
    bloques.mkdir()
    (bloques / "FC50010_TEST_INTERFAZ.s7dcl").write_text(
        # Cabecera tipica de TIA: lleva ``S7_BlockNumber := "50010";``.
        # El helper ``_leer_block_number`` lo extrae de ahi para la
        # deteccion de colisiones por numero.
        "S7_BlockNumber := \"50010\";\n"
        "FUNCTION_BLOCK FC50010_TEST_INTERFAZ\n",
        encoding="utf-8",
    )
    # Tambien un DB para verificar el match por tipo+numero.
    (bloques / "DB50010_TEST.s7dcl").write_text(
        "S7_BlockNumber := \"50010\";\n"
        "DATA_BLOCK DB50010_TEST\n",
        encoding="utf-8",
    )
    # .s7res con BOM utf-8-sig (caso real TIA Portal V21).
    # El nombre incluye DB para que el patron_bloques matematico lo
    # renombre numericamente (200 -> 100 en la v2; con patron
    # regex aplicado al stem completo del archivo).
    (bloques / "DB50010_TEST_COMENTARIOS.s7res").write_text(
        "BOM content", encoding="utf-8-sig",
    )

    (p / "Variables PLC" / "003_Procesos").mkdir(parents=True)
    # IMPORTANTE: el orden de las constantes de usuario debe coincidir
    # con ``N_MAX_KEYS`` del helper (``N_MAX_PREAL``, ``N_MAX_PINT``,
    # ``N_MAX_ALM``, ``N_MAX_ALM_HMI``). El algoritmo de
    # ``_reemplazar_nmax_en_xml`` itera los ``<Value>`` en orden de
    # aparicion y los reemplaza en el mismo orden que ``N_MAX_KEYS``;
    # si el XML tiene un orden distinto, no se reemplazan todas.
    xml = (
        '<?xml version="1.0" encoding="utf-8"?>\n'
        "<Document>\n"
        '  <Engineering version="V21" />\n'
        '  <SW.Tags.PlcTagTable ID="0">\n'
        '    <AttributeList><Name>50010_TEST</Name></AttributeList>\n'
        "    <ObjectList>\n"
        # N_MAX_PREAL (debe ir primero, en orden N_MAX_KEYS).
        '      <SW.Tags.PlcUserConstant ID="1">\n'
        "        <AttributeList>"
        "<DataTypeName>Int</DataTypeName>"
        "<Name>50010_N_MAX_PREAL</Name>"
        "<Value>3</Value>"
        "</AttributeList>\n"
        "      </SW.Tags.PlcUserConstant>\n"
        # N_MAX_PINT.
        '      <SW.Tags.PlcUserConstant ID="2">\n'
        "        <AttributeList>"
        "<DataTypeName>Int</DataTypeName>"
        "<Name>50010_N_MAX_PINT</Name>"
        "<Value>15</Value>"
        "</AttributeList>\n"
        "      </SW.Tags.PlcUserConstant>\n"
        # N_MAX_ALM.
        '      <SW.Tags.PlcUserConstant ID="3">\n'
        "        <AttributeList>"
        "<DataTypeName>Int</DataTypeName>"
        "<Name>50010_N_MAX_ALM</Name>"
        "<Value>16</Value>"
        "</AttributeList>\n"
        "      </SW.Tags.PlcUserConstant>\n"
        # N_MAX_ALM_HMI.
        '      <SW.Tags.PlcUserConstant ID="4">\n'
        "        <AttributeList>"
        "<DataTypeName>Int</DataTypeName>"
        "<Name>50010_N_MAX_ALM_HMI</Name>"
        "<Value>3</Value>"
        "</AttributeList>\n"
        "      </SW.Tags.PlcUserConstant>\n"
        # No N_MAX canonicas: ETAPA_0 y OTHER_BLOCK.
        '      <SW.Tags.PlcUserConstant ID="5">\n'
        "        <AttributeList>"
        "<DataTypeName>Int</DataTypeName>"
        "<Name>50010_ETAPA_0</Name>"
        "<Value>0</Value>"
        "</AttributeList>\n"
        "      </SW.Tags.PlcUserConstant>\n"
        '      <SW.Tags.PlcUserConstant ID="6">\n'
        "        <AttributeList>"
        "<DataTypeName>Int</DataTypeName>"
        "<Name>OTHER_BLOCK_UID_NOMBRE</Name>"
        "<Value>99</Value>"
        "</AttributeList>\n"
        "      </SW.Tags.PlcUserConstant>\n"
        "    </ObjectList>\n"
        "  </SW.Tags.PlcTagTable>\n"
        "</Document>\n"
    )
    (p / "Variables PLC" / "003_Procesos" / "50010_TEST.xml").write_text(
        xml, encoding="utf-8",
    )
    (p / "manifest.json").write_text(
        json.dumps({
            "base": 50010,
            "codigo": "TEST",
            "nombre": "ProcesoTest",
            "descripcion": "Proceso de tests con 1 FC y 1 DB",
            "dependencias": [
                "DB1_SYS",
                "FC15151_ZC_MARCHA_PARO_SEC",
            ],
            "minimos": {
                "N_MAX_PREAL": 3, "N_MAX_PINT": 15,
                "N_MAX_ALM": 16, "N_MAX_ALM_HMI": 3,
            },
        }),
        encoding="utf-8",
    )
    return p


@pytest.fixture
def make_ctx(tmp_path: Path, plantilla_dummy: Path):
    """Factory de contextos con plantilla dummy en tmp_path.

    Defaults: el operario cubre los minimos de la plantilla.
    """
    def _make(**overrides: Any) -> ProcProcessGenContext:
        build_cache_root = tmp_path / ".build_cache"
        preview = build_cache_root / "alimentacion" / "ProcesoNuevo" / "Plantilla"
        modified = build_cache_root / "alimentacion" / "ProcesoNuevo" / "Nuevo"
        defaults: dict[str, Any] = {
            "dir_plantilla": plantilla_dummy,
            "dir_plantilla_copia": preview,
            "dir_nuevo": modified,
            "base_nueva": 60010,
            "codigo_nuevo": "EXP",
            "nombre_nuevo": "NuevoProceso",
            "plc_blocks_cache": [],
            "minimos_usuario": {
                "N_MAX_PREAL": 30, "N_MAX_PINT": 30,
                "N_MAX_ALM": 30, "N_MAX_ALM_HMI": 5,
            },
        }
        defaults.update(overrides)
        return ProcProcessGenContext(**defaults)
    return _make


# ── proc_process_leer_manifest ────────────────────────────────────────


@pytest.mark.asyncio
async def test_leer_manifest_happy(make_ctx: Any) -> None:
    """Lee manifest.json valido y popula ``ctx.manifest_plantilla`` +
    ``ctx.base_vieja`` + ``ctx.codigo_viejo``.
    """
    ctx = make_ctx()
    proc_process_leer_manifest(ctx)

    assert ctx.manifest_plantilla is not None
    assert ctx.manifest_plantilla["base"] == 50010
    assert ctx.base_vieja == 50010
    assert ctx.codigo_viejo == "TEST"
    assert ctx.nombre_viejo == "ProcesoTest"


@pytest.mark.asyncio
async def test_leer_manifest_no_existe(make_ctx: Any) -> None:
    """Si falta manifest.json, lanza ``ManifestInvalido``.
    """
    ctx = make_ctx()
    # Borramos el manifest del dummy.
    (ctx.dir_plantilla / "manifest.json").unlink()

    with pytest.raises(ManifestInvalido):
        proc_process_leer_manifest(ctx)


@pytest.mark.asyncio
async def test_leer_manifest_sin_base(
    tmp_path: Path,
    make_ctx: Any,
) -> None:
    """Si el manifest no tiene ``base`` (int), lanza ``ManifestInvalido``.
    """
    p = tmp_path / "TestPlantilla2"
    p.mkdir()
    (p / "manifest.json").write_text(
        json.dumps({"codigo": "X", "nombre": "Y"}),
        encoding="utf-8",
    )
    ctx = make_ctx(dir_plantilla=p)

    with pytest.raises(ManifestInvalido):
        proc_process_leer_manifest(ctx)


@pytest.mark.asyncio
async def test_leer_manifest_sin_descripcion_raises(
    tmp_path: Path,
    make_ctx: Any,
) -> None:
    """``descripcion`` es obligatorio. Sin el, ``ManifestInvalido``.
    La SPA lo usa para mostrar la plantilla en el selector.
    """
    p = tmp_path / "TestSinDescripcion"
    p.mkdir()
    (p / "manifest.json").write_text(
        json.dumps({
            "base": 50010,
            "codigo": "TEST",
            "nombre": "X",
            "dependencias": ["DB1_SYS"],
            "minimos": {
                "N_MAX_PREAL": 3, "N_MAX_PINT": 15,
                "N_MAX_ALM": 16, "N_MAX_ALM_HMI": 3,
            },
        }),
        encoding="utf-8",
    )
    ctx = make_ctx(dir_plantilla=p)

    with pytest.raises(ManifestInvalido, match="descripcion"):
        proc_process_leer_manifest(ctx)


@pytest.mark.asyncio
async def test_leer_manifest_descripcion_vacia_raises(
    tmp_path: Path,
    make_ctx: Any,
) -> None:
    """``descripcion`` debe ser string no vacio. Cadena vacia
    o solo-whitespace tambien falla (no aporta nada a la SPA).
    """
    p = tmp_path / "TestDescVacia"
    p.mkdir()
    (p / "manifest.json").write_text(
        json.dumps({
            "base": 50010,
            "codigo": "TEST",
            "nombre": "X",
            "descripcion": "   ",
            "dependencias": ["DB1_SYS"],
            "minimos": {
                "N_MAX_PREAL": 3, "N_MAX_PINT": 15,
                "N_MAX_ALM": 16, "N_MAX_ALM_HMI": 3,
            },
        }),
        encoding="utf-8",
    )
    ctx = make_ctx(dir_plantilla=p)

    with pytest.raises(ManifestInvalido, match="descripcion"):
        proc_process_leer_manifest(ctx)


@pytest.mark.asyncio
async def test_leer_manifest_sin_dependencias_raises(
    tmp_path: Path,
    make_ctx: Any,
) -> None:
    """``dependencias`` es obligatorio. Sin el, ``ManifestInvalido``.
    El check contra el PLC lo requiere (bloqueante si falta).
    """
    p = tmp_path / "TestSinDeps"
    p.mkdir()
    (p / "manifest.json").write_text(
        json.dumps({
            "base": 50010,
            "codigo": "TEST",
            "nombre": "X",
            "descripcion": "Test",
            "minimos": {
                "N_MAX_PREAL": 3, "N_MAX_PINT": 15,
                "N_MAX_ALM": 16, "N_MAX_ALM_HMI": 3,
            },
        }),
        encoding="utf-8",
    )
    ctx = make_ctx(dir_plantilla=p)

    with pytest.raises(ManifestInvalido, match="dependencias"):
        proc_process_leer_manifest(ctx)


@pytest.mark.asyncio
async def test_leer_manifest_dependencias_no_lista_raises(
    tmp_path: Path,
    make_ctx: Any,
) -> None:
    """``dependencias`` debe ser ``list``. Strings, dicts, ints
    fallan con ``ManifestInvalido``.
    """
    p = tmp_path / "TestDepsNoLista"
    p.mkdir()
    (p / "manifest.json").write_text(
        json.dumps({
            "base": 50010,
            "codigo": "TEST",
            "nombre": "X",
            "descripcion": "Test",
            "dependencias": "DB1_SYS",
            "minimos": {
                "N_MAX_PREAL": 3, "N_MAX_PINT": 15,
                "N_MAX_ALM": 16, "N_MAX_ALM_HMI": 3,
            },
        }),
        encoding="utf-8",
    )
    ctx = make_ctx(dir_plantilla=p)

    with pytest.raises(ManifestInvalido, match="dependencias"):
        proc_process_leer_manifest(ctx)


@pytest.mark.asyncio
async def test_leer_manifest_dependencias_strings_vacias_raises(
    tmp_path: Path,
    make_ctx: Any,
) -> None:
    """Items de ``dependencias`` deben ser strings no vacios.
    ``[""]`` o ``["  "]`` fallan (un nombre vacio no es un bloque).
    """
    p = tmp_path / "TestDepsVacios"
    p.mkdir()
    (p / "manifest.json").write_text(
        json.dumps({
            "base": 50010,
            "codigo": "TEST",
            "nombre": "X",
            "descripcion": "Test",
            "dependencias": ["DB1_SYS", "   "],
            "minimos": {
                "N_MAX_PREAL": 3, "N_MAX_PINT": 15,
                "N_MAX_ALM": 16, "N_MAX_ALM_HMI": 3,
            },
        }),
        encoding="utf-8",
    )
    ctx = make_ctx(dir_plantilla=p)

    with pytest.raises(ManifestInvalido, match="dependencias"):
        proc_process_leer_manifest(ctx)


@pytest.mark.asyncio
async def test_leer_manifest_happy_campos_nuevos(
    make_ctx: Any,
) -> None:
    """Happy path: ``descripcion`` y ``dependencias`` se populan en el
    ctx. ``dependencias`` se trimea por entrada.
    """
    ctx = make_ctx()
    proc_process_leer_manifest(ctx)

    assert ctx.descripcion == "Proceso de tests con 1 FC y 1 DB"
    assert ctx.dependencias == [
        "DB1_SYS",
        "FC15151_ZC_MARCHA_PARO_SEC",
    ]


# ── proc_process_validar_dependencias ────────────────────────────────


@pytest.mark.asyncio
async def test_validar_dependencias_ok(make_ctx: Any) -> None:
    """``plc_blocks_cache`` contiene TODAS las deps del manifest -> ok.

    La plantilla dummy declara ``["DB1_SYS", "FC15151_ZC_MARCHA_PARO_SEC"]``.
    Si la cache los tiene ambos, ``dependencias_ok`` los contiene y
    ``dependencias_faltantes`` queda vacia.
    """
    ctx = make_ctx(
        plc_blocks_cache=[
            {"nombre": "DB1_SYS", "numero": 1},
            {"nombre": "FC15151_ZC_MARCHA_PARO_SEC", "numero": 15151},
        ],
    )
    proc_process_leer_manifest(ctx)
    proc_process_validar_dependencias(ctx)

    assert ctx.dependencias_ok == [
        "DB1_SYS", "FC15151_ZC_MARCHA_PARO_SEC",
    ]
    assert ctx.dependencias_faltantes == []


@pytest.mark.asyncio
async def test_validar_dependencias_mitad(make_ctx: Any) -> None:
    """``plc_blocks_cache`` solo tiene la mitad -> mitad OK, mitad
    faltantes.

    Verifica que el cruce es exacto: una dependencia en la cache va
    a OK, la otra a faltantes. La SPA pinta SOLO las faltantes en
    rojo, asi que esta separacion es la regla de bloqueo.
    """
    ctx = make_ctx(
        plc_blocks_cache=[
            {"nombre": "DB1_SYS", "numero": 1},
        ],
    )
    proc_process_leer_manifest(ctx)
    proc_process_validar_dependencias(ctx)

    assert ctx.dependencias_ok == ["DB1_SYS"]
    assert ctx.dependencias_faltantes == ["FC15151_ZC_MARCHA_PARO_SEC"]


@pytest.mark.asyncio
async def test_validar_dependencias_todas_faltan(make_ctx: Any) -> None:
    """``plc_blocks_cache`` sin ninguna dep -> todas a faltantes."""
    ctx = make_ctx(
        plc_blocks_cache=[
            {"nombre": "OTRO_BLOQUE", "numero": 99},
        ],
    )
    proc_process_leer_manifest(ctx)
    proc_process_validar_dependencias(ctx)

    assert ctx.dependencias_ok == []
    assert set(ctx.dependencias_faltantes) == {
        "DB1_SYS", "FC15151_ZC_MARCHA_PARO_SEC",
    }


@pytest.mark.asyncio
async def test_validar_dependencias_sin_cache(make_ctx: Any) -> None:
    """``plc_blocks_cache is None`` -> todas las deps a faltantes.

    Misma regla que ``detectar_colisiones``: si el operario no ha
    escaneado el PLC todavia, las dependencias se reportan como
    faltantes para que la SPA pueda bloquear "Aplicar" hasta que
    se escanee.
    """
    ctx = make_ctx(plc_blocks_cache=None)
    proc_process_leer_manifest(ctx)
    proc_process_validar_dependencias(ctx)

    assert ctx.dependencias_ok == []
    assert set(ctx.dependencias_faltantes) == {
        "DB1_SYS", "FC15151_ZC_MARCHA_PARO_SEC",
    }


# ── proc_process_validar_minimos ──────────────────────────────────────


@pytest.mark.asyncio
async def test_validar_minimos_ok(make_ctx: Any) -> None:
    """minimos_usuario >= plantilla -> no raise."""
    ctx = make_ctx()
    proc_process_leer_manifest(ctx)

    # No raise.
    proc_process_validar_minimos(ctx)


@pytest.mark.asyncio
async def test_validar_minimos_menor_raises(make_ctx: Any) -> None:
    """Si minimos_usuario < plantilla en alguna clave canonica,
    lanza ``PlantillaMinimosNoCumplidos``.
    """
    ctx = make_ctx(minimos_usuario={
        "N_MAX_PREAL": 1,  # menor que 3
        "N_MAX_PINT": 30,
        "N_MAX_ALM": 30,
        "N_MAX_ALM_HMI": 5,
    })
    proc_process_leer_manifest(ctx)

    with pytest.raises(PlantillaMinimosNoCumplidos) as exc:
        proc_process_validar_minimos(ctx)
    # El mensaje identifica la clave conflictiva.
    assert "N_MAX_PREAL" in str(exc.value)


# ── proc_process_copiar_a_preview ─────────────────────────────────────


@pytest.mark.asyncio
async def test_copiar_a_preview_ok(make_ctx: Any) -> None:
    """Copia la plantilla a ``dir_plantilla_copia`` preservando estructura."""
    ctx = make_ctx()
    proc_process_copiar_a_preview(ctx)

    assert ctx.dir_plantilla_copia.exists()
    # El .s7dcl y el .s7res deberian estar en preview/...
    assert (ctx.dir_plantilla_copia / "Bloques de programa" / "FC50010_TEST_INTERFAZ.s7dcl").is_file()
    assert (ctx.dir_plantilla_copia / "Bloques de programa" / "DB50010_TEST_COMENTARIOS.s7res").is_file()
    # El manifest.json tambien se copia.
    assert (ctx.dir_plantilla_copia / "manifest.json").is_file()
    # El XML de variables PLC.
    assert (ctx.dir_plantilla_copia / "Variables PLC" / "003_Procesos" / "50010_TEST.xml").is_file()


@pytest.mark.asyncio
async def test_copiar_a_preview_limpia_si_existe(make_ctx: Any) -> None:
    """Re-arrancable: si ``dir_plantilla_copia`` ya existe de una
    corrida previa, la borra antes de re-copiar (regla de retencion
    2.x, mismo patron que ``ContextCache.clean_preview()``).
    """
    ctx = make_ctx()
    # 1ra corrida: deja la carpeta poblada.
    proc_process_copiar_a_preview(ctx)
    assert (ctx.dir_plantilla_copia / "manifest.json").is_file()

    # Ensuciamos la copia con un archivo fantasma que no deberia
    # sobrevivir a la 2da corrida.
    basura = ctx.dir_plantilla_copia / "basura_de_corrida_previa.tmp"
    basura.write_text("hola", encoding="utf-8")

    # 2da corrida: debe limpiar antes de copiar.
    proc_process_copiar_a_preview(ctx)

    assert ctx.dir_plantilla_copia.exists()
    # El archivo fantasma desaparecio (limpieza OK).
    assert not basura.exists()
    # La plantilla volvio a quedar copiada limpia.
    assert (ctx.dir_plantilla_copia / "manifest.json").is_file()




# ── contrato sync (hilo unico OB1) ────────────────────────────────────


def test_helpers_proc_crear_no_son_corrutinas() -> None:
    """Los 2 helpers compartidos son funciones sync.

    El shell los invoca desde el hilo unico, sin event loop: un
    ``await`` sobre ellos dejaria la corrutina sin ejecutar
    ("coroutine was never awaited") y los diccionarios / archivos
    nunca se escribirian.
    """
    assert not inspect.iscoroutinefunction(proc_process_construir_diccionarios), (
        "proc_process_construir_diccionarios debe ser sync"
    )
    assert not inspect.iscoroutinefunction(proc_process_aplicar_clonacion), (
        "proc_process_aplicar_clonacion debe ser sync"
    )


# ── proc_process_construir_diccionarios ───────────────────────────────


@pytest.mark.asyncio
async def test_construir_diccionarios_orden_len_desc(make_ctx: Any) -> None:
    """Construye diccionarios con claves ordenadas por ``len(key)``
    descendente (los reemplazos mas especificos ganan).
    """
    ctx = make_ctx()
    proc_process_copiar_a_preview(ctx)
    proc_process_leer_manifest(ctx)
    proc_process_construir_diccionarios(ctx)

    # El primer item debe ser la clave mas larga.
    longest_key = max(ctx.dicc_bloques, key=len)
    first_key = next(iter(ctx.dicc_bloques))
    assert first_key == longest_key, (
        f"dicc_bloques no esta ordenado len desc: "
        f"primer={first_key!r} ({len(first_key)}) "
        f"vs max={longest_key!r} ({len(longest_key)})"
    )

    # Lo mismo en dicc_xml.
    longest_xml_key = max(ctx.dicc_xml, key=len)
    first_xml_key = next(iter(ctx.dicc_xml))
    assert first_xml_key == longest_xml_key

    # dicc_xml lleva solo 3 reglas (proceso, params +3000, alarmas
    # +5000), todas con prefijo ``base_``. La regla ``{base}`` (sin
    # sufijo _) ya no se genera; ``str.replace`` se hace con la
    # clave mas larga disponible y eso basta para el matching.
    assert "50010_" in ctx.dicc_xml
    assert "50010" not in ctx.dicc_xml  # v2 ya no genera la regla sin _


# ── proc_process_detectar_colisiones ──────────────────────────────────


@pytest.mark.asyncio
async def test_detectar_colisiones_match_plc_cache(make_ctx: Any) -> None:
    """Si el cache del PLC contiene un nombre post-rename del helper,
    se anade a ``ctx.colisiones`` y se popula ``ctx.colisiones_con``
    con el identificador del bloque que colisiona. La SPA lo cruza
    con ``archivos_previstos[i].rel_out`` para marcar el item como
    ``DUPLICADO - <id>`` en la columna ESTADO.
    """
    ctx = make_ctx(
        plc_blocks_cache=[{
            "nombre": "DB60010_EXP_COMENTARIOS",
            "numero": None,
        }],
    )
    proc_process_copiar_a_preview(ctx)
    proc_process_leer_manifest(ctx)
    proc_process_construir_diccionarios(ctx)
    proc_process_detectar_colisiones(ctx)

    # ``DB60010_EXP_COMENTARIOS`` ya estaba en PLC -> colision detectada.
    assert "DB60010_EXP_COMENTARIOS" in ctx.colisiones
    # ``colisiones_con`` mapea el nombre nuevo al identificador del PLC.
    assert ctx.colisiones_con["DB60010_EXP_COMENTARIOS"] == (
        "DB60010_EXP_COMENTARIOS"
    )


@pytest.mark.asyncio
async def test_detectar_colisiones_match_por_tipo_numero(make_ctx: Any) -> None:
    """Match por ``(prefijo, numero)``: el nuevo proceso genera
    ``FC60010_EXP_INTERFAZ``. El PLC cache tiene
    ``FC60010_OTRO_NOMBRE`` con prefijo FC y numero 60010 (mismo
    tipo, mismo numero, distinto nombre). Esto ES colision en TIA
    Portal: dos FC con el mismo numero no pueden coexistir aunque
    los nombres difieran.
    """
    ctx = make_ctx(
        plc_blocks_cache=[{
            "nombre": "FC60010_OTRO_NOMBRE",
            "numero": 60010,
        }],
    )
    proc_process_copiar_a_preview(ctx)
    proc_process_leer_manifest(ctx)
    proc_process_construir_diccionarios(ctx)
    proc_process_detectar_colisiones(ctx)

    # Match por (FC, 60010): colision con el bloque FC60010_OTRO_NOMBRE
    # del PLC.
    assert "FC60010_EXP_INTERFAZ" in ctx.colisiones, (
        f"Esperaba colision FC60010_EXP_INTERFAZ (match por tipo+numero); "
        f"colisiones={ctx.colisiones}"
    )
    # ``colisiones_con`` debe apuntar al identificador del PLC.
    assert ctx.colisiones_con["FC60010_EXP_INTERFAZ"] == (
        "FC60010_OTRO_NOMBRE"
    ), f"colisiones_con={ctx.colisiones_con}"


@pytest.mark.asyncio
async def test_detectar_colisiones_mismo_numero_distinto_prefijo_no_colisiona(
    make_ctx: Any,
) -> None:
    """Mismo numero pero distinto prefijo NO es colision.

    En TIA Portal, FC100 y OB100 pueden coexistir (namespaces
    separados por tipo de bloque: FC, FB, DB, OB viven cada uno
    en su propio espacio de numeros). Por tanto, un nuevo
    ``FC100`` no debe marcarse como duplicado solo porque exista
    un ``OB100`` en el PLC. Solo choca si el tipo Y el numero
    coinciden (o si el nombre completo coincide).
    """
    ctx = make_ctx(
        plc_blocks_cache=[{
            "nombre": "OB100_Startup",  # prefijo OB, numero 100
            "numero": 100,
        }],
    )
    proc_process_copiar_a_preview(ctx)
    proc_process_leer_manifest(ctx)
    proc_process_construir_diccionarios(ctx)
    proc_process_detectar_colisiones(ctx)

    # ``FC100`` (o ``FC100_<sufijo>``) del nuevo proceso NO debe
    # colisionar con ``OB100_Startup`` del PLC: mismo numero pero
    # distinto prefijo (FC vs OB).
    fc_items = [c for c in ctx.colisiones if c.startswith("FC1")]
    assert fc_items == [], (
        f"FC100 no debe colisionar con OB100_Startup (distinto prefijo); "
        f"colisiones={ctx.colisiones}"
    )
    # Y ``DB100`` tampoco (DB vs OB).
    db_items = [c for c in ctx.colisiones if c.startswith("DB1")]
    assert db_items == [], (
        f"DB100 no debe colisionar con OB100_Startup (distinto prefijo); "
        f"colisiones={ctx.colisiones}"
    )
    # Ninguna colision debe quedar (el cache solo tiene OB100_Startup
    # y los nombres nuevos son distintos).
    assert ctx.colisiones == [], (
        f"No esperaba colisiones; obtuve {ctx.colisiones}"
    )


@pytest.mark.asyncio
async def test_detectar_colisiones_cache_none_emite_warning(
    make_ctx: Any,
) -> None:
    """Si ``plc_blocks_cache=None``, el helper anade un mensaje
    accionable a ``ctx.colisiones`` (NO aborta; el FB decide).
    """
    ctx = make_ctx(plc_blocks_cache=None)
    proc_process_copiar_a_preview(ctx)
    proc_process_leer_manifest(ctx)
    proc_process_construir_diccionarios(ctx)
    proc_process_detectar_colisiones(ctx)

    assert len(ctx.colisiones) == 1
    assert "Cache de bloques PLC" in ctx.colisiones[0]






# ── proc_process_aplicar_clonacion ────────────────────────────────────


@pytest.mark.asyncio
async def test_aplicar_clonacion_preserva_bom_s7res(
    tmp_path: Path,
    plantilla_dummy: Path,
) -> None:
    """El ``.s7res`` clonado mantiene el BOM utf-8-sig (escritura con
    encoding ``utf-8-sig`` lo reintroduce tras el round-trip).
    """
    build_cache_root = tmp_path / ".build_cache"
    preview = build_cache_root / "alimentacion" / "ProcesoNuevo" / "Plantilla"
    modified = build_cache_root / "alimentacion" / "ProcesoNuevo" / "Nuevo"
    ctx = ProcProcessGenContext(
        dir_plantilla=plantilla_dummy,
        dir_plantilla_copia=preview,
        dir_nuevo=modified,
        base_nueva=60010,
        codigo_nuevo="EXP",
        nombre_nuevo="NuevoProceso",
        plc_blocks_cache=[],
        minimos_usuario={
            "N_MAX_PREAL": 30, "N_MAX_PINT": 30,
            "N_MAX_ALM": 30, "N_MAX_ALM_HMI": 5,
        },
    )
    proc_process_copiar_a_preview(ctx)
    proc_process_leer_manifest(ctx)
    proc_process_construir_diccionarios(ctx)
    proc_process_aplicar_clonacion(ctx)

    # El output .s7res: nombre nuevo es 60010 (base nueva) + EXP
    # (codigo nuevo, reemplazo de "TEST") + _COMENTARIOS (sufijo
    # preservado del .s7res original). La estructura de carpetas se
    # preserva: vive bajo ``Bloques de programa/`` (igual que la
    # plantilla), NO bajo un ``bloques/`` aplanado.
    out_s7res = (
        modified / "Bloques de programa"
        / "DB60010_EXP_COMENTARIOS.s7res"
    )
    assert out_s7res.is_file(), f"Output .s7res no existe: {out_s7res}"
    # BOM utf-8-sig == b"\xef\xbb\xbf" en los primeros 3 bytes.
    raw = out_s7res.read_bytes()
    assert raw[:3] == b"\xef\xbb\xbf", (
        f"BOM no preservado en .s7res clonado. "
        f"Primeros 4 bytes: {raw[:4]!r}"
    )


@pytest.mark.asyncio
async def test_aplicar_clonacion_xml_value_update(
    tmp_path: Path,
    plantilla_dummy: Path,
) -> None:
    """El ``.xml`` clonado tiene los ``<Value>NN</Value>`` de los 4 N_MAX
    del operario (los 4 canonicos), no los de la plantilla.
    """
    build_cache_root = tmp_path / ".build_cache"
    preview = build_cache_root / "alimentacion" / "ProcesoNuevo" / "Plantilla"
    modified = build_cache_root / "alimentacion" / "ProcesoNuevo" / "Nuevo"
    ctx = ProcProcessGenContext(
        dir_plantilla=plantilla_dummy,
        dir_plantilla_copia=preview,
        dir_nuevo=modified,
        base_nueva=60010,
        codigo_nuevo="EXP",
        nombre_nuevo="NuevoProceso",
        plc_blocks_cache=[],
        minimos_usuario={
            # 4 N_MAX del operario. Distintos para verificar que se
            # aplicaron los valores correctos en el orden esperado.
            "N_MAX_PREAL": 30, "N_MAX_PINT": 30,
            "N_MAX_ALM": 30, "N_MAX_ALM_HMI": 5,
        },
    )
    proc_process_copiar_a_preview(ctx)
    proc_process_leer_manifest(ctx)
    proc_process_construir_diccionarios(ctx)
    proc_process_aplicar_clonacion(ctx)

    # El XML clonado: 50010_TEST.xml -> 60010_EXP.xml (sustituye
    # 50010->60010 y TEST->EXP). La estructura de carpetas se
    # preserva: vive bajo ``Variables PLC/003_Procesos/`` (igual
    # que la plantilla), NO bajo un ``variables/`` aplanado.
    out_xml = (
        modified / "Variables PLC" / "003_Procesos" / "60010_EXP.xml"
    )
    assert out_xml.is_file(), f"Output .xml no existe: {out_xml}"

    contenido = out_xml.read_text(encoding="utf-8")

    # N_MAX_PINT del operario: 30 (la plantilla tenia 15).
    assert "<Value>30</Value>" in contenido, (
        f"<Value>30</Value> no presente en el XML clonado.\n"
        f"Contenido:\n{contenido}"
    )
    # El valor de plantilla (15) ya NO debe aparecer (fueron sustituidos).
    assert "<Value>15</Value>" not in contenido
    # Y los <Value> que NO son N_MAX (ETAPA_0=0, OTHER=99) NO se tocan.
    assert "<Value>0</Value>" in contenido  # ETAPA_0 sin cambio
    assert "<Value>99</Value>" in contenido  # OTHER_BLOCK_UID_NOMBRE


@pytest.mark.asyncio
async def test_aplicar_clonacion_genera_layout_canonico(
    tmp_path: Path,
    plantilla_dummy: Path,
) -> None:
    """Preserva la estructura de carpetas de la plantilla.

    La plantilla dummy tiene:
      ``Bloques de programa/{FC50010_TEST_INTERFAZ.s7dcl,
        50010_TEST_COMENTARIOS.s7res}``
      ``Variables PLC/003_Procesos/{50010_TEST.xml}``

    Tras el rename (base 50010 -> 60010, codigo TEST -> EXP) el
    output debe mantener la misma estructura, solo con los
    filenames renombrados. Esto permite que el dispatch contra la
    raiz de ``dir_nuevo`` (``import_plc_tags_xml`` y
    ``import_blocks_sd`` apuntando a ``dir_nuevo``) haga UPDATE
    recursivo preservando el subpath en el PLC.

    ``manifest.json`` se ignora (lo regenera
    ``proc_process_escribir_manifest`` justo despues).
    """
    build_cache_root = tmp_path / ".build_cache"
    preview = build_cache_root / "alimentacion" / "ProcesoNuevo" / "Plantilla"
    modified = build_cache_root / "alimentacion" / "ProcesoNuevo" / "Nuevo"
    ctx = ProcProcessGenContext(
        dir_plantilla=plantilla_dummy,
        dir_plantilla_copia=preview,
        dir_nuevo=modified,
        base_nueva=60010,
        codigo_nuevo="EXP",
        nombre_nuevo="NuevoProceso",
        plc_blocks_cache=[],
        minimos_usuario={
            "N_MAX_PREAL": 30, "N_MAX_PINT": 30,
            "N_MAX_ALM": 30, "N_MAX_ALM_HMI": 5,
        },
    )
    proc_process_copiar_a_preview(ctx)
    proc_process_leer_manifest(ctx)
    proc_process_construir_diccionarios(ctx)
    proc_process_aplicar_clonacion(ctx)

    # Estructura preservada: las subcarpetas originales viven en el
    # output (NO aplanadas en ``variables/`` o ``bloques/``).
    assert (modified / "Bloques de programa").is_dir()
    assert (modified / "Variables PLC" / "003_Procesos").is_dir()
    # Y NO existen las carpetas aplanadas que se usaban antes del
    # fix.
    assert not (modified / "variables").exists()
    assert not (modified / "bloques").exists()
    # archivos_generados poblado con paths que respetan el subpath
    # original (relativos a modified/).
    rels = ctx.archivos_generados
    assert any(
        rel.endswith("Bloques de programa" + os.sep + "FC60010_EXP_INTERFAZ.s7dcl")
        for rel in rels
    ), f"Falta FC60010_EXP_INTERFAZ.s7dcl en subpath correcto: {rels}"
    assert any(
        rel.endswith(
            "Bloques de programa" + os.sep + "DB60010_EXP_COMENTARIOS.s7res"
        )
        for rel in rels
    ), f"Falta DB60010_EXP_COMENTARIOS.s7res en subpath correcto: {rels}"
    assert any(
        rel.endswith(
            "Variables PLC" + os.sep + "003_Procesos" + os.sep + "60010_EXP.xml"
        )
        for rel in rels
    ), f"Falta 60010_EXP.xml en subpath correcto: {rels}"
    # manifest.json NO entra como archivo generado del apply (lo
    # escribe la siguiente funcion ``proc_process_escribir_manifest``).
    assert not any(
        rel.endswith("manifest.json") for rel in rels
    )


@pytest.fixture
def plantilla_dummy_nested(tmp_path: Path) -> Path:
    """Plantilla con estructura anidada tipo PROCESO_ESTANDAR.

    Layout:
      Bloques de programa/
        200_Expedicion/
          200_Proceso/
            FC200_EXP_INTERFAZ.s7dcl
            FC200_EXP_INTERFAZ.s7res
          3200_Parametros/
            DB3200_EXP_PARAM.s7dcl
          5200_Alarmas/
            DB5200_EXP_ALM.s7dcl
      Variables PLC/
        003_Procesos/
          200_EXP.xml
      manifest.json (codigo=EXP, nombre=Expedicion)
    """
    p = tmp_path / "PROC_ESTANDAR"
    p.mkdir()
    bloques = p / "Bloques de programa"
    bloques.mkdir()
    # Top folder del proceso (se renombra a 100_CPR tras el apply).
    proc_folder = bloques / "200_Expedicion"
    proc_folder.mkdir()
    # Inner subfolders (se renombran numericamente: 200_Proceso ->
    # 100_Proceso, etc.; el sufijo NO cambia).
    (proc_folder / "200_Proceso").mkdir()
    (proc_folder / "3200_Parametros").mkdir()
    (proc_folder / "5200_Alarmas").mkdir()
    # Blocks.
    (proc_folder / "200_Proceso" / "FC200_EXP_INTERFAZ.s7dcl").write_text(
        "S7_BlockNumber := \"200\";\n"
        "FUNCTION_BLOCK FC200_EXP_INTERFAZ\n",
        encoding="utf-8",
    )
    (proc_folder / "200_Proceso" / "FC200_EXP_INTERFAZ.s7res").write_text(
        "BOM content", encoding="utf-8-sig",
    )
    (proc_folder / "3200_Parametros" / "DB3200_EXP_PARAM.s7dcl").write_text(
        "S7_BlockNumber := \"3200\";\n"
        "DATA_BLOCK DB3200_EXP_PARAM\n",
        encoding="utf-8",
    )
    (proc_folder / "5200_Alarmas" / "DB5200_EXP_ALM.s7dcl").write_text(
        "S7_BlockNumber := \"5200\";\n"
        "DATA_BLOCK DB5200_EXP_ALM\n",
        encoding="utf-8",
    )
    # Variables PLC.
    (p / "Variables PLC" / "003_Procesos").mkdir(parents=True)
    (p / "Variables PLC" / "003_Procesos" / "200_EXP.xml").write_text(
        "<Document><Value>1</Value></Document>\n",
        encoding="utf-8",
    )
    # manifest con codigo y nombre que el helper usa para el rename
    # de folder names (el sufijo ``Expedicion`` -> ``CPR``).
    (p / "manifest.json").write_text(
        json.dumps({
            "base": 200,
            "codigo": "EXP",
            "nombre": "Expedicion",
            "descripcion": "Proceso estandar de expedicion con subcarpetas anidadas",
            "dependencias": [
                "DB1_SYS",
                "DB2000_ED",
                "FC15151_ZC_MARCHA_PARO_SEC",
            ],
            "minimos": {
                "N_MAX_PREAL": 3, "N_MAX_PINT": 15,
                "N_MAX_ALM": 16, "N_MAX_ALM_HMI": 3,
            },
        }),
        encoding="utf-8",
    )
    return p


@pytest.mark.asyncio
async def test_aplicar_clonacion_renombra_carpetas_anidadas(
    tmp_path: Path,
    plantilla_dummy_nested: Path,
) -> None:
    """El apply renombra TANTO archivos como carpetas, preservando
    la estructura anidada de la plantilla.

    Caso real: PROCESO_ESTANDAR tiene
    ``Bloques de programa/200_Expedicion/{200_Proceso,
    3200_Parametros, 5200_Alarmas}/...``. Tras el apply (base
    50010 -> 100, codigo EXP -> CPR, nombre Expedicion -> CPR)
    el resultado debe ser::

        Bloques de programa/
          100_CPR/                  <- antes 200_Expedicion
            100_Proceso/            <- antes 200_Proceso
              FC100_CPR_INTERFAZ.s7dcl
              FC100_CPR_INTERFAZ.s7res
            3100_Parametros/        <- antes 3200_Parametros
              DB3100_CPR_PARAM.s7dcl
            5100_Alarmas/           <- antes 5200_Alarmas
              DB5100_CPR_ALM.s7dcl
        Variables PLC/
          003_Procesos/
            100_CPR.xml             <- antes 200_EXP.xml

    Las reglas clave:
      - Folder top (id_proceso + _ + nombre_proceso): 200_Expedicion
        -> 100_CPR. El sufijo ``Expedicion`` se reemplaza por
        ``CPR`` (regla de nombre). El prefijo ``200_`` se renumera
        a ``100_`` (regla de base).
      - Inner folders: solo renumerar. ``200_Proceso`` ->
        ``100_Proceso`` (prefijo base, sufijo intacto).
        ``3200_Parametros`` -> ``3100_Parametros``.
      - Filenames: mismo patron que carpetas (200_EXP_* -> 100_CPR_*).

    Bug pre-fix: el helper solo renombraba filenames, dejando los
    folder names con el nombre antiguo. Esto provocaba que el
    import UPDATE de TIA Portal creara los bloques en el subpath
    con el nombre viejo (e.g. ``Bloques de programa/200_Expedicion/
    FC100_CPR_INTERFAZ``) en lugar del esperado
    (``Bloques de programa/100_CPR/FC100_CPR_INTERFAZ``).
    """
    build_cache_root = tmp_path / ".build_cache"
    preview = build_cache_root / "alimentacion" / "ProcesoNuevo" / "Plantilla"
    modified = build_cache_root / "alimentacion" / "ProcesoNuevo" / "Nuevo"
    ctx = ProcProcessGenContext(
        dir_plantilla=plantilla_dummy_nested,
        dir_plantilla_copia=preview,
        dir_nuevo=modified,
        base_nueva=100,
        codigo_nuevo="CPR",
        nombre_nuevo="CPR",
        plc_blocks_cache=[],
        minimos_usuario={
            "N_MAX_PREAL": 10, "N_MAX_PINT": 20,
            "N_MAX_ALM": 30, "N_MAX_ALM_HMI": 5,
        },
    )
    proc_process_copiar_a_preview(ctx)
    proc_process_leer_manifest(ctx)
    proc_process_construir_diccionarios(ctx)
    proc_process_aplicar_clonacion(ctx)

    # 1) Folder top renombrado: 200_Expedicion -> 100_CPR
    assert (modified / "Bloques de programa" / "100_CPR").is_dir(), (
        f"Top folder no renombrado a 100_CPR; "
        f"contenido de Bloques de programa: "
        f"{list((modified / 'Bloques de programa').iterdir())}"
    )
    assert not (modified / "Bloques de programa" / "200_Expedicion").exists(), (
        "200_Expedicion no deberia existir despues del rename"
    )

    # 2) Inner folders renumerados: solo el prefijo cambia, sufijo intacto.
    assert (modified / "Bloques de programa" / "100_CPR" / "100_Proceso").is_dir()
    assert (modified / "Bloques de programa" / "100_CPR" / "3100_Parametros").is_dir()
    assert (modified / "Bloques de programa" / "100_CPR" / "5100_Alarmas").is_dir()
    assert not (modified / "Bloques de programa" / "100_CPR" / "200_Proceso").exists()
    assert not (modified / "Bloques de programa" / "100_CPR" / "3200_Parametros").exists()
    assert not (modified / "Bloques de programa" / "100_CPR" / "5200_Alarmas").exists()

    # 3) Filenames renombrados dentro de cada subfolder.
    assert (
        modified / "Bloques de programa" / "100_CPR" / "100_Proceso"
        / "FC100_CPR_INTERFAZ.s7dcl"
    ).is_file(), (
        f"FC100_CPR_INTERFAZ.s7dcl no encontrado; "
        f"contenido del dir: "
        f"{list((modified / 'Bloques de programa' / '100_CPR' / '100_Proceso').iterdir())}"
    )
    assert (
        modified / "Bloques de programa" / "100_CPR" / "3100_Parametros"
        / "DB3100_CPR_PARAM.s7dcl"
    ).is_file()
    assert (
        modified / "Bloques de programa" / "100_CPR" / "5100_Alarmas"
        / "DB5100_CPR_ALM.s7dcl"
    ).is_file()

    # 4) Variables PLC (no cambia porque el nombre "200_EXP" no tiene
    # el patron "200_" como prefijo de base — solo es el filename del
    # tag table que SI se renombra a "100_CPR").
    assert (
        modified / "Variables PLC" / "003_Procesos" / "100_CPR.xml"
    ).is_file()

    # 5) ``archivos_generados`` poblado con paths relativos que ya
    # tienen el subpath renombrado completo.
    rels = ctx.archivos_generados
    assert any(
        rel.endswith(
            "Bloques de programa" + os.sep + "100_CPR" + os.sep
            + "100_Proceso" + os.sep + "FC100_CPR_INTERFAZ.s7dcl"
        )
        for rel in rels
    ), f"Falta FC100_CPR_INTERFAZ.s7dcl con subpath completo: {rels}"
    assert any(
        rel.endswith(
            "Variables PLC" + os.sep + "003_Procesos" + os.sep + "100_CPR.xml"
        )
        for rel in rels
    ), f"Falta 100_CPR.xml: {rels}"


# ── proc_process_escribir_manifest ────────────────────────────────────


@pytest.mark.asyncio
async def test_escribir_manifest(tmp_path: Path, plantilla_dummy: Path) -> None:
    """Escribe ``<dir_nuevo>/manifest.json`` con los datos del
    proceso nuevo (base_nueva, codigo_nuevo, nombre_nuevo, minimos_usuario).
    """
    build_cache_root = tmp_path / ".build_cache"
    preview = build_cache_root / "alimentacion" / "ProcesoNuevo" / "Plantilla"
    modified = build_cache_root / "alimentacion" / "ProcesoNuevo" / "Nuevo"
    ctx = ProcProcessGenContext(
        dir_plantilla=plantilla_dummy,
        dir_plantilla_copia=preview,
        dir_nuevo=modified,
        base_nueva=60010,
        codigo_nuevo="EXP",
        nombre_nuevo="NuevoProceso",
        plc_blocks_cache=[],
        minimos_usuario={
            "N_MAX_PREAL": 30, "N_MAX_PINT": 30,
            "N_MAX_ALM": 30, "N_MAX_ALM_HMI": 5,
        },
    )
    proc_process_escribir_manifest(ctx)

    manifest_path = modified / "manifest.json"
    assert manifest_path.is_file()
    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert data["base"] == 60010
    assert data["codigo"] == "EXP"
    assert data["nombre"] == "NuevoProceso"
    assert data["minimos"]["N_MAX_PINT"] == 30
    assert data["minimos"]["N_MAX_ALM_HMI"] == 5
    assert "manifest.json" in ctx.archivos_generados


# ── proc_process_generar_previstos ────────────────────────────────────


@pytest.mark.asyncio
async def test_generar_previstos_1_entry_por_bloque(make_ctx: Any) -> None:
    """Cada bloque TIA vive en 2 archivos (.s7dcl + .s7res, mismo
    stem); el helper emite 1 sola entry por bloque agrupando ambos.

    El dummy tiene 3 stems de bloque: ``FC50010_TEST_INTERFAZ``,
    ``DB50010_TEST``, ``DB50010_TEST_COMENTARIOS``. Esperado: 3
    entries (no 4 archivos sueltos).
    """
    ctx = make_ctx()
    proc_process_copiar_a_preview(ctx)
    proc_process_leer_manifest(ctx)
    proc_process_construir_diccionarios(ctx)
    proc_process_generar_previstos(ctx)

    # 3 stems de bloque en el dummy -> 3 entries (no 4 archivos).
    assert len(ctx.archivos_previstos) == 3, (
        f"esperaba 3 entries (1 por bloque), "
        f"obtuve {len(ctx.archivos_previstos)}: {ctx.archivos_previstos}"
    )
    # Cada entry lleva exactamente 3 keys canonicas.
    for entry in ctx.archivos_previstos:
        assert set(entry.keys()) == {
            "nombre_original", "nombre_nuevo", "estado"
        }, f"keys inesperadas: {set(entry.keys())}"
    # Los stems del dummy estan todos presentes.
    originales = {e["nombre_original"] for e in ctx.archivos_previstos}
    assert originales == {
        "FC50010_TEST_INTERFAZ",
        "DB50010_TEST",
        "DB50010_TEST_COMENTARIOS",
    }


@pytest.mark.asyncio
async def test_generar_previstos_filtra_no_bloque(make_ctx: Any) -> None:
    """El XML de variables PLC, .scl y .awl NO aparecen en el
    preview: no son bloques TIA.

    El dummy tiene 1 ``.xml`` (``50010_TEST.xml``) en
    ``Variables PLC/003_Procesos/``. Tras el helper, ese archivo
    no debe figurar en ``archivos_previstos``.
    """
    ctx = make_ctx()
    proc_process_copiar_a_preview(ctx)
    proc_process_leer_manifest(ctx)
    proc_process_construir_diccionarios(ctx)
    proc_process_generar_previstos(ctx)

    for entry in ctx.archivos_previstos:
        # Ningun nombre contiene ``.xml`` ni ``.scl`` ni ``.awl``.
        nombre = entry["nombre_original"]
        assert not nombre.endswith(".xml"), f"XML filtrado: {nombre!r}"
        assert not nombre.endswith(".scl"), f"SCL filtrado: {nombre!r}"
        assert not nombre.endswith(".awl"), f"AWL filtrado: {nombre!r}"


@pytest.mark.asyncio
async def test_generar_previstos_estado_ok_sin_colision(make_ctx: Any) -> None:
    """Si ``plc_blocks_cache`` esta vacia, todos los bloques quedan
    con ``estado="OK"``.
    """
    ctx = make_ctx(plc_blocks_cache=[])
    proc_process_copiar_a_preview(ctx)
    proc_process_leer_manifest(ctx)
    proc_process_construir_diccionarios(ctx)
    proc_process_detectar_colisiones(ctx)
    proc_process_generar_previstos(ctx)

    assert ctx.colisiones == []
    assert all(
        e["estado"] == "OK" for e in ctx.archivos_previstos
    ), f"alguno no es OK: {ctx.archivos_previstos}"


@pytest.mark.asyncio
async def test_generar_previstos_estado_duplicado_con_ident(make_ctx: Any) -> None:
    """Si el cache del PLC tiene un bloque que matchea por
    (prefijo, numero) con uno de los bloques post-rename, su
    entry queda con ``estado="DUPLICADO - <id>"`` donde ``<id>``
    es el identificador del bloque del PLC que colisiona.

    Cache del PLC: ``FC60010_OTRO_NOMBRE`` con prefijo FC y
    numero 60010. Solo colisiona el ``FC60010_EXP_INTERFAZ`` del
    dummy (por (FC, 60010)); los DB no se ven afectados porque
    usan prefijo DB (namespaces distintos en TIA Portal).
    """
    ctx = make_ctx(plc_blocks_cache=[{
        "nombre": "FC60010_OTRO_NOMBRE", "numero": 60010,
    }])
    proc_process_copiar_a_preview(ctx)
    proc_process_leer_manifest(ctx)
    proc_process_construir_diccionarios(ctx)
    proc_process_detectar_colisiones(ctx)
    proc_process_generar_previstos(ctx)

    # Solo 1 bloque colisiona: el ``FC60010_EXP_INTERFAZ``.
    colisionados = [
        e for e in ctx.archivos_previstos
        if e["estado"].startswith("DUPLICADO")
    ]
    assert len(colisionados) == 1, (
        f"esperaba 1 colision, obtuve {len(colisionados)}: "
        f"{ctx.archivos_previstos}"
    )
    assert colisionados[0]["nombre_nuevo"] == "FC60010_EXP_INTERFAZ"
    assert colisionados[0]["estado"] == (
        "DUPLICADO - FC60010_OTRO_NOMBRE"
    )


@pytest.mark.asyncio
async def test_generar_previstos_orden_por_nombre_nuevo(
    make_ctx: Any,
) -> None:
    """Los entries salen ordenados por ``nombre_nuevo`` ascendente
    (casefold) para que la SPA los pinte estables entre renders.
    """
    ctx = make_ctx()
    proc_process_copiar_a_preview(ctx)
    proc_process_leer_manifest(ctx)
    proc_process_construir_diccionarios(ctx)
    proc_process_generar_previstos(ctx)

    nombres = [e["nombre_nuevo"] for e in ctx.archivos_previstos]
    assert nombres == sorted(nombres, key=str.casefold), (
        f"orden no estable: {nombres}"
    )


# ── proc_process_construir_diccionarios: folder rename con base custom ──


@pytest.mark.asyncio
async def test_construir_diccionarios_renombra_carpeta_base_custom(
    tmp_path: Path,
) -> None:
    """Una carpeta con prefijo numerico que NO es ninguna de las 3
    bases hardcoded (``base``, ``base+3000``, ``base+5000``) debe
    recibir su propia regla de rename, derivada del walk.

    Caso real (CIP): el proyecto tiene 12 subcarpetas
    con bases 50500, 50510, 50520, 50530, 50540, 50560, 50565,
    50570, 50575, 50590, 53500, 55500. Solo las 3 estandar se
    renombraban; las 9 custom quedaban intactas, con bloques
    renombrados dentro (mismatch estructural con TIA Portal al
    hacer import UPDATE).

    Este test cubre el caso custom. La subcarpeta ``600_Custom``
    (offset +400 sobre base=200) debe recibir una regla
    ``600_`` -> ``500_`` (offset preservado tras el shift
    base 200 -> 100).
    """
    build_cache_root = tmp_path / ".build_cache"
    preview = build_cache_root / "alimentacion" / "ProcesoNuevo" / "Plantilla"
    modified = build_cache_root / "alimentacion" / "ProcesoNuevo" / "Nuevo"
    plantilla = tmp_path / "PROC_CUSTOM_BASES"
    plantilla.mkdir()
    (plantilla / "Bloques de programa").mkdir()
    (plantilla / "Variables PLC").mkdir()
    (plantilla / "manifest.json").write_text(
        json.dumps({
            "base": 200,
            "codigo": "EXP",
            "nombre": "Expedicion",
            "descripcion": "Proceso estandar de expedicion (dummy)",
            "dependencias": [
                "DB1_SYS",
                "DB2000_ED",
                "FC15151_ZC_MARCHA_PARO_SEC",
            ],
            "minimos": {
                "N_MAX_PREAL": 3, "N_MAX_PINT": 15,
                "N_MAX_ALM": 16, "N_MAX_ALM_HMI": 3,
            },
        }),
        encoding="utf-8",
    )
    # Subcarpeta con base custom (offset +400; no es ninguno de
    # los 3 estandar 0/3000/5000) y un bloque dentro.
    custom_folder = plantilla / "Bloques de programa" / "600_Custom"
    custom_folder.mkdir()
    (custom_folder / "DB600_EXP_CUSTOM.s7dcl").write_text(
        'S7_BlockNumber := "600";\n'
        "DATA_BLOCK DB600_EXP_CUSTOM\n",
        encoding="utf-8",
    )

    ctx = ProcProcessGenContext(
        dir_plantilla=plantilla,
        dir_plantilla_copia=preview,
        dir_nuevo=modified,
        base_nueva=100,
        codigo_nuevo="CPR",
        nombre_nuevo="CPR",
        plc_blocks_cache=[],
        minimos_usuario={
            "N_MAX_PREAL": 10, "N_MAX_PINT": 20,
            "N_MAX_ALM": 30, "N_MAX_ALM_HMI": 5,
        },
    )
    proc_process_copiar_a_preview(ctx)
    proc_process_leer_manifest(ctx)
    proc_process_construir_diccionarios(ctx)
    proc_process_aplicar_clonacion(ctx)

    # La subcarpeta custom debe haberse renombrado: 600_ -> 500_
    # (offset +400 preservado tras el shift base 200 -> 100).
    assert (modified / "Bloques de programa" / "500_Custom").is_dir(), (
        "La subcarpeta con base custom (600_) no se renombro. "
        "dicc_bloques deberia contener la regla '600_' -> '500_'."
    )
    assert not (modified / "Bloques de programa" / "600_Custom").exists(), (
        "La subcarpeta con el nombre viejo no deberia existir tras el apply."
    )
    # El bloque dentro tambien se renombra via la regex de bloques.
    assert (
        modified / "Bloques de programa" / "500_Custom"
        / "DB500_CPR_CUSTOM.s7dcl"
    ).is_file(), (
        "El bloque dentro de la subcarpeta custom no se renombro "
        "consistentemente con el prefijo del folder."
    )


@pytest.mark.asyncio
async def test_construir_diccionarios_renombra_subcarpeta_anidada_custom(
    tmp_path: Path,
) -> None:
    """Una subcarpeta con prefijo custom en nivel 2 (dentro de la
    carpeta de proceso) tambien debe recibir su regla de rename.

    Cubre el caso CIP donde cada subcarpeta (Linea_1, Linea_2, ...)
    vive anidada bajo ``50500_CIP1``. Si el ``rglob`` no recoge
    carpetas anidadas, la regla no se genera y la subcarpeta
    queda intacta.
    """
    build_cache_root = tmp_path / ".build_cache"
    preview = build_cache_root / "alimentacion" / "ProcesoNuevo" / "Plantilla"
    modified = build_cache_root / "alimentacion" / "ProcesoNuevo" / "Nuevo"
    plantilla = tmp_path / "PROC_NESTED"
    plantilla.mkdir()
    (plantilla / "Bloques de programa").mkdir()
    (plantilla / "Variables PLC").mkdir()
    (plantilla / "manifest.json").write_text(
        json.dumps({
            "base": 200,
            "codigo": "EXP",
            "nombre": "Expedicion",
            "descripcion": "Proceso estandar de expedicion (dummy)",
            "dependencias": [
                "DB1_SYS",
                "DB2000_ED",
                "FC15151_ZC_MARCHA_PARO_SEC",
            ],
            "minimos": {
                "N_MAX_PREAL": 3, "N_MAX_PINT": 15,
                "N_MAX_ALM": 16, "N_MAX_ALM_HMI": 3,
            },
        }),
        encoding="utf-8",
    )
    # Top folder + subcarpeta custom anidada.
    proc_folder = plantilla / "Bloques de programa" / "200_Expedicion"
    proc_folder.mkdir()
    nested_custom = proc_folder / "700_Nested_Custom"
    nested_custom.mkdir()
    (nested_custom / "DB700_EXP_NESTED.s7dcl").write_text(
        'S7_BlockNumber := "700";\n',
        encoding="utf-8",
    )

    ctx = ProcProcessGenContext(
        dir_plantilla=plantilla,
        dir_plantilla_copia=preview,
        dir_nuevo=modified,
        base_nueva=100,
        codigo_nuevo="CPR",
        nombre_nuevo="CPR",
        plc_blocks_cache=[],
        minimos_usuario={
            "N_MAX_PREAL": 10, "N_MAX_PINT": 20,
            "N_MAX_ALM": 30, "N_MAX_ALM_HMI": 5,
        },
    )
    proc_process_copiar_a_preview(ctx)
    proc_process_leer_manifest(ctx)
    proc_process_construir_diccionarios(ctx)
    proc_process_aplicar_clonacion(ctx)

    # Subcarpeta anidada con base custom (offset +500) debe
    # quedar como ``600_Nested_Custom`` (offset preservado). El
    # top folder ``200_Expedicion`` se renombra a ``100_CPR``.
    assert (
        modified / "Bloques de programa" / "100_CPR" / "600_Nested_Custom"
    ).is_dir(), (
        "La subcarpeta anidada con prefijo custom (700_) no se renombro."
    )


@pytest.mark.asyncio
async def test_construir_diccionarios_sin_carpetas_prefijadas(
    tmp_path: Path,
) -> None:
    """Si la plantilla no tiene carpetas con prefijo numerico
    bajo ``Bloques de programa/``, el dicc solo lleva las 3
    reglas estandar y las del walk de archivos (sanity, no-op
    para folder rules).
    """
    build_cache_root = tmp_path / ".build_cache"
    preview = build_cache_root / "alimentacion" / "ProcesoNuevo" / "Plantilla"
    modified = build_cache_root / "alimentacion" / "ProcesoNuevo" / "Nuevo"
    plantilla = tmp_path / "PROC_NO_FOLDERS"
    plantilla.mkdir()
    (plantilla / "Bloques de programa").mkdir()
    (plantilla / "Variables PLC").mkdir()
    (plantilla / "manifest.json").write_text(
        json.dumps({
            "base": 200,
            "codigo": "EXP",
            "nombre": "Expedicion",
            "descripcion": "Proceso estandar de expedicion (dummy)",
            "dependencias": [
                "DB1_SYS",
                "DB2000_ED",
                "FC15151_ZC_MARCHA_PARO_SEC",
            ],
            "minimos": {
                "N_MAX_PREAL": 3, "N_MAX_PINT": 15,
                "N_MAX_ALM": 16, "N_MAX_ALM_HMI": 3,
            },
        }),
        encoding="utf-8",
    )
    # Solo archivos directamente bajo Bloques de programa/, sin
    # subcarpetas prefijadas.
    (plantilla / "Bloques de programa" / "DB200_EXP.s7dcl").write_text(
        'S7_BlockNumber := "200";\n',
        encoding="utf-8",
    )

    ctx = ProcProcessGenContext(
        dir_plantilla=plantilla,
        dir_plantilla_copia=preview,
        dir_nuevo=modified,
        base_nueva=100,
        codigo_nuevo="CPR",
        nombre_nuevo="CPR",
        plc_blocks_cache=[],
        minimos_usuario={
            "N_MAX_PREAL": 10, "N_MAX_PINT": 20,
            "N_MAX_ALM": 30, "N_MAX_ALM_HMI": 5,
        },
    )
    proc_process_copiar_a_preview(ctx)
    proc_process_leer_manifest(ctx)
    proc_process_construir_diccionarios(ctx)

    # Las 3 reglas estandar siguen en dicc_xml (XML puede
    # referenciarlas aunque no haya carpeta con ese prefijo).
    assert "200_" in ctx.dicc_xml
    assert "3200_" in ctx.dicc_xml
    assert "5200_" in ctx.dicc_xml


@pytest.mark.asyncio
async def test_construir_diccionarios_carpeta_prefijo_fc_db(
    tmp_path: Path,
) -> None:
    """Una carpeta con prefijo FC/FB/DB (raro pero posible, e.g.
    ``FC100_Grouping``) genera DOS entradas en el dicc: la del
    prefijo numerico (``100_``) y la del bloque si hay un
    ``FC100_*.s7dcl`` dentro. El sort ``len(key) DESC`` del
    dicc garantiza que la regla especifica del bloque (mas
    larga) gana al aplicar.
    """
    build_cache_root = tmp_path / ".build_cache"
    preview = build_cache_root / "alimentacion" / "ProcesoNuevo" / "Plantilla"
    modified = build_cache_root / "alimentacion" / "ProcesoNuevo" / "Nuevo"
    plantilla = tmp_path / "PROC_FC_FOLDER"
    plantilla.mkdir()
    (plantilla / "Bloques de programa").mkdir()
    (plantilla / "Variables PLC").mkdir()
    (plantilla / "manifest.json").write_text(
        json.dumps({
            "base": 200,
            "codigo": "EXP",
            "nombre": "Expedicion",
            "descripcion": "Proceso estandar de expedicion (dummy)",
            "dependencias": [
                "DB1_SYS",
                "DB2000_ED",
                "FC15151_ZC_MARCHA_PARO_SEC",
            ],
            "minimos": {
                "N_MAX_PREAL": 3, "N_MAX_PINT": 15,
                "N_MAX_ALM": 16, "N_MAX_ALM_HMI": 3,
            },
        }),
        encoding="utf-8",
    )
    # Carpeta con prefijo FC y un bloque dentro.
    fc_folder = plantilla / "Bloques de programa" / "FC100_Grouping"
    fc_folder.mkdir()
    (fc_folder / "FC100_EXP_GRP.s7dcl").write_text(
        'S7_BlockNumber := "100";\n',
        encoding="utf-8",
    )

    # base_nuev=400 para evitar prefijos negativos (100 - 200 + 400 = 300).
    ctx = ProcProcessGenContext(
        dir_plantilla=plantilla,
        dir_plantilla_copia=preview,
        dir_nuevo=modified,
        base_nueva=400,
        codigo_nuevo="CPR",
        nombre_nuevo="CPR",
        plc_blocks_cache=[],
        minimos_usuario={
            "N_MAX_PREAL": 10, "N_MAX_PINT": 20,
            "N_MAX_ALM": 30, "N_MAX_ALM_HMI": 5,
        },
    )
    proc_process_copiar_a_preview(ctx)
    proc_process_leer_manifest(ctx)
    proc_process_construir_diccionarios(ctx)
    proc_process_aplicar_clonacion(ctx)

    # FC folder (sin top folder): FC100_Grouping -> FC300_Grouping
    # (offset +100 preservado). El bloque dentro se renombra por
    # la regex FC/FB/DB + la regla del prefijo del dicc.
    target_folder = modified / "Bloques de programa" / "FC300_Grouping"
    assert target_folder.is_dir(), (
        f"La carpeta FC100_Grouping no se renombro a FC300_Grouping. "
        f"Existe el viejo: {(modified / 'Bloques de programa' / 'FC100_Grouping').exists()}"
    )
    assert (target_folder / "FC300_CPR_GRP.s7dcl").is_file(), (
        "El bloque dentro de la carpeta FC no se renombro "
        "consistentemente con el prefijo del folder."
    )


@pytest.mark.asyncio
async def test_construir_diccionarios_prefijo_num_en_stem_de_archivo(
    tmp_path: Path,
) -> None:
    """Archivos FC/FB/DB con un prefijo numerico que NO es prefijo de
    carpeta deben generar una regla ``<num>_ -> <num_nuevo>_`` en
    el dicc, para que el helper renombre ese numero en el contenido
    de ``.s7dcl`` / ``.s7res`` / ``.scl`` / ``.awl``.

    Caso real: la plantilla CIP tiene
    ``FC50501_CIP1_ORDENES_R_L1.s7dcl`` dentro de la carpeta
    ``50500_Principal\\``. El nombre de archivo lleva el sufijo
    ``_L1`` al final; el ``FUNCTION "FC50501_CIP1_L1_ORDENES_R"``
    del cuerpo lo lleva en medio (formato distinto). Sin la regla
    ``50501_ -> 501_`` en el dicc, el ``str.replace`` falla en esa
    cadena y TIA Portal muestra ``FC50501_*`` en lugar del nombre
    renombrado (lo lee del ``.s7res`` por la entrada
    ``MLC_<id> -> es-ES: ...``).
    """
    build_cache_root = tmp_path / ".build_cache"
    preview = build_cache_root / "alimentacion" / "ProcesoNuevo" / "Plantilla"
    modified = build_cache_root / "alimentacion" / "ProcesoNuevo" / "Nuevo"
    plantilla = tmp_path / "PROC_STEM_PREFIX"
    plantilla.mkdir()
    (plantilla / "Bloques de programa" / "50500_CIP1" / "50500_Principal").mkdir(
        parents=True,
    )
    (plantilla / "Variables PLC").mkdir()
    (plantilla / "manifest.json").write_text(
        json.dumps({
            "base": 50500,
            "codigo": "CIP1",
            "nombre": "CIP1",
            "descripcion": "Proceso CIP dummy",
            "dependencias": ["DB1_SYS"],
            "minimos": {
                "N_MAX_PREAL": 3, "N_MAX_PINT": 15,
                "N_MAX_ALM": 16, "N_MAX_ALM_HMI": 3,
            },
        }),
        encoding="utf-8",
    )
    s7dcl = (
        plantilla / "Bloques de programa" / "50500_CIP1"
        / "50500_Principal" / "FC50501_CIP1_ORDENES_R_L1.s7dcl"
    )
    s7dcl.write_text(
        'S7_BlockNumber := "5501";\n'
        'FUNCTION "FC50501_CIP1_L1_ORDENES_R" : Void\n',
        encoding="utf-8",
    )
    s7res = s7dcl.with_suffix(".s7res")
    s7res.write_text(
        "MultiLingualTexts:\n"
        "  - id: MLC_X\n"
        "    es-ES: FC50501_CIP1_L1_ORDENES_R\n",
        encoding="utf-8",
    )

    # base_nueva=500 (offset -50000). El prefijo 50501 es de archivo,
    # no de carpeta: si no se anade al walk, no hay regla 50501_ ->
    # 501_ y el contenido del .s7dcl/.s7res conserva el 50501.
    ctx = ProcProcessGenContext(
        dir_plantilla=plantilla,
        dir_plantilla_copia=preview,
        dir_nuevo=modified,
        base_nueva=500,
        codigo_nuevo="ENTRADA",
        nombre_nuevo="ENTRADA",
        plc_blocks_cache=[],
        minimos_usuario={
            "N_MAX_PREAL": 10, "N_MAX_PINT": 20,
            "N_MAX_ALM": 30, "N_MAX_ALM_HMI": 5,
        },
    )
    proc_process_copiar_a_preview(ctx)
    proc_process_leer_manifest(ctx)
    proc_process_construir_diccionarios(ctx)
    proc_process_aplicar_clonacion(ctx)

    # Regla del prefijo de archivo presente en el dicc.
    assert ctx.dicc_bloques.get("50501_") == "501_", (
        "Falta la regla 50501_ -> 501_ en el dicc de renombre. "
        f"Entradas actuales: {sorted(ctx.dicc_bloques.keys())!r}"
    )

    # Contenido del .s7dcl reescrito: 50501 -> 501 y codigo -> nuevo.
    # El output conserva la estructura interna del bloque (L1 en
    # medio, como en el ``FUNCTION "..."``); el helper reemplaza
    # tokens, no reordena.
    s7dcl_nuevo = (
        modified / "Bloques de programa" / "500_ENTRADA"
        / "500_Principal" / "FC501_ENTRADA_ORDENES_R_L1.s7dcl"
    )
    assert s7dcl_nuevo.is_file(), (
        f"El .s7dcl renombrado no existe en la ruta esperada. "
        f"Dir nuevo contiene: {sorted(p.name for p in modified.rglob('*'))!r}"
    )
    contenido = s7dcl_nuevo.read_text(encoding="utf-8")
    assert "FC501_ENTRADA_L1_ORDENES_R" in contenido, (
        "El .s7dcl conserva FC50501 en su FUNCTION \"...\", "
        f"el rename no alcanzo el contenido. Contenido: {contenido!r}"
    )
    assert "FC50501" not in contenido, (
        f"Todavia quedan referencias a FC50501 en el .s7dcl: {contenido!r}"
    )

    # Contenido del .s7res reescrito (mismo bug historico: TIA
    # Portal lee el nombre del bloque de aqui, via el mapeo
    # ``MLC_<id> -> es-ES: ...``).
    s7res_nuevo = s7dcl_nuevo.with_suffix(".s7res")
    contenido_res = s7res_nuevo.read_text(encoding="utf-8")
    assert "FC501_ENTRADA_L1_ORDENES_R" in contenido_res, (
        "El .s7res conserva FC50501 en su mapeo MLC_<id>, "
        f"el rename no alcanzo el contenido. Contenido: {contenido_res!r}"
    )
    assert "FC50501" not in contenido_res, (
        f"Todavia quedan referencias a FC50501 en el .s7res: {contenido_res!r}"
    )
