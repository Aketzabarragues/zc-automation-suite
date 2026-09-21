"""Tests del helper ``proc_process_generator``.

Cubre las funciones puras/async del helper (preview + apply):

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
  - NO toca el gateway TIA (helper es offline).
  - Usa ``tmp_path`` (pytest builtin) para crear una plantilla dummy
    minima + un staging aislado por test.
  - El helper es **libre de state machine**: cada test llama a UNA o
    MAS funciones del helper por vez y valida el efecto en el ``ctx``.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from areas.alimentacion.helpers.proc.proc_process_generator import (
    ManifestInvalido,
    PlantillaMinimosNoCumplidos,
    ProcProcessGenContext,
    proc_process_aplicar_clonacion,
    proc_process_construir_diccionarios,
    proc_process_copiar_a_preview,
    proc_process_detectar_colisiones,
    proc_process_escribir_manifest,
    proc_process_extraer_variables_xml,
    proc_process_generar_previstos,
    proc_process_leer_manifest,
    proc_process_validar_minimos,
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
    # .s7res con BOM utf-8-sig (caso real TIA Portal V21).
    (bloques / "50010_TEST_COMENTARIOS.s7res").write_text(
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
            "plc_blocks_cache": set(),
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
    await proc_process_leer_manifest(ctx)

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
        await proc_process_leer_manifest(ctx)


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
        await proc_process_leer_manifest(ctx)


# ── proc_process_validar_minimos ──────────────────────────────────────


@pytest.mark.asyncio
async def test_validar_minimos_ok(make_ctx: Any) -> None:
    """minimos_usuario >= plantilla -> no raise."""
    ctx = make_ctx()
    await proc_process_leer_manifest(ctx)

    # No raise.
    await proc_process_validar_minimos(ctx)


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
    await proc_process_leer_manifest(ctx)

    with pytest.raises(PlantillaMinimosNoCumplidos) as exc:
        await proc_process_validar_minimos(ctx)
    # El mensaje identifica la clave conflictiva.
    assert "N_MAX_PREAL" in str(exc.value)


# ── proc_process_copiar_a_preview ─────────────────────────────────────


@pytest.mark.asyncio
async def test_copiar_a_preview_ok(make_ctx: Any) -> None:
    """Copia la plantilla a ``dir_plantilla_copia`` preservando estructura."""
    ctx = make_ctx()
    await proc_process_copiar_a_preview(ctx)

    assert ctx.dir_plantilla_copia.exists()
    # El .s7dcl y el .s7res deberian estar en preview/...
    assert (ctx.dir_plantilla_copia / "Bloques de programa" / "FC50010_TEST_INTERFAZ.s7dcl").is_file()
    assert (ctx.dir_plantilla_copia / "Bloques de programa" / "50010_TEST_COMENTARIOS.s7res").is_file()
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
    await proc_process_copiar_a_preview(ctx)
    assert (ctx.dir_plantilla_copia / "manifest.json").is_file()

    # Ensuciamos la copia con un archivo fantasma que no deberia
    # sobrevivir a la 2da corrida.
    basura = ctx.dir_plantilla_copia / "basura_de_corrida_previa.tmp"
    basura.write_text("hola", encoding="utf-8")

    # 2da corrida: debe limpiar antes de copiar.
    await proc_process_copiar_a_preview(ctx)

    assert ctx.dir_plantilla_copia.exists()
    # El archivo fantasma desaparecio (limpieza OK).
    assert not basura.exists()
    # La plantilla volvio a quedar copiada limpia.
    assert (ctx.dir_plantilla_copia / "manifest.json").is_file()


# ── proc_process_extraer_variables_xml ────────────────────────────────


@pytest.mark.asyncio
async def test_extraer_variables_xml_filtra_rango(make_ctx: Any) -> None:
    """Extrae unicamente variables con UID en [base_vieja, base_vieja+10000).

    - Variables con UID 50010 (en rango) -> extraidas.
    - ``OTHER_BLOCK_UID_NOMBRE`` no tiene UID numerico prefijo -> no matchea
      la regex y por tanto no aparece.
    """
    ctx = make_ctx()
    await proc_process_copiar_a_preview(ctx)
    await proc_process_leer_manifest(ctx)
    await proc_process_extraer_variables_xml(ctx)

    vars_extraidas = ctx.__dict__.get("_variables_xml_exactas") or []

    # Las 6 con prefijo 50010 (tag table + 5 PlcUserConstants con UID 50010).
    assert "50010_TEST" in vars_extraidas
    assert "50010_N_MAX_PINT" in vars_extraidas
    assert "50010_N_MAX_PREAL" in vars_extraidas
    assert "50010_N_MAX_ALM" in vars_extraidas
    assert "50010_N_MAX_ALM_HMI" in vars_extraidas
    assert "50010_ETAPA_0" in vars_extraidas
    # OTHER_BLOCK_UID_NOMBRE no empieza por UID numerico -> no matchea
    # la regex ``\\d+_[a-zA-Z0-9_]+``.
    assert "OTHER_BLOCK_UID_NOMBRE" not in vars_extraidas
    # Sin duplicados (la funcion usa ``dict.fromkeys`` para dedupe).
    assert len(vars_extraidas) == len(set(vars_extraidas))


# ── proc_process_construir_diccionarios ───────────────────────────────


@pytest.mark.asyncio
async def test_construir_diccionarios_orden_len_desc(make_ctx: Any) -> None:
    """Construye diccionarios con claves ordenadas por ``len(key)``
    descendente (los reemplazos mas especificos ganan).
    """
    ctx = make_ctx()
    await proc_process_copiar_a_preview(ctx)
    await proc_process_leer_manifest(ctx)
    await proc_process_extraer_variables_xml(ctx)
    await proc_process_construir_diccionarios(ctx)

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

    # Las claves mas largas que `50010_` (prefijo numerico) aparecen antes
    # que `50010` (la base completa, mas corta).
    if "50010_" in ctx.dicc_xml:
        idx_largo = list(ctx.dicc_xml.keys()).index("50010_")
        idx_corto = list(ctx.dicc_xml.keys()).index("50010")
        assert idx_largo < idx_corto


# ── proc_process_detectar_colisiones ──────────────────────────────────


@pytest.mark.asyncio
async def test_detectar_colisiones_match_plc_cache(make_ctx: Any) -> None:
    """Si el cache del PLC contiene un nombre nuevo generado por el
    helper (``val`` de dicc_bloques), se anade a ``ctx.colisiones``
    con el nombre NUEVO (no la clave original) — asi la SPA puede
    cruzar ``colisiones`` con ``archivos_previstos[i].rel_out``.
    """
    ctx = make_ctx(
        # El valor ``val`` de ``dicc_bloques`` para
        # ``50010_TEST_COMENTARIOS`` es ``60010_EXP_COMENTARIOS``
        # (sustituye 50010->60010 y TEST->EXP).
        plc_blocks_cache={"60010_EXP_COMENTARIOS"},
    )
    await proc_process_copiar_a_preview(ctx)
    await proc_process_leer_manifest(ctx)
    await proc_process_extraer_variables_xml(ctx)
    await proc_process_construir_diccionarios(ctx)
    await proc_process_detectar_colisiones(ctx)

    # ``60010_EXP_COMENTARIOS`` ya estaba en PLC -> colision detectada.
    assert len(ctx.colisiones) >= 1
    # Appendeamos ``val`` (nombre NUEVO del bloque que colisionaria)
    # para que la SPA pueda cruzar ``colisiones`` con
    # ``archivos_previstos[i].rel_out`` sin replicar el cruce.
    assert "60010_EXP_COMENTARIOS" in ctx.colisiones


@pytest.mark.asyncio
async def test_detectar_colisiones_cache_none_emite_warning(
    make_ctx: Any,
) -> None:
    """Si ``plc_blocks_cache=None``, el helper anade un mensaje
    accionable a ``ctx.colisiones`` (NO aborta; el FB decide).
    """
    ctx = make_ctx(plc_blocks_cache=None)
    await proc_process_copiar_a_preview(ctx)
    await proc_process_leer_manifest(ctx)
    await proc_process_extraer_variables_xml(ctx)
    await proc_process_construir_diccionarios(ctx)
    await proc_process_detectar_colisiones(ctx)

    assert len(ctx.colisiones) == 1
    assert "Cache de bloques PLC" in ctx.colisiones[0]


@pytest.mark.asyncio
async def test_detectar_colisiones_por_numero(make_ctx: Any) -> None:
    """Si el PLC tiene un bloque con el mismo numero que el que
    importariamos (aunque el nombre sea distinto), colision detectada.

    Caso: el PLC tiene FB60010. La plantilla intenta importar DB60010_X.
    Mismo numero, distinto nombre -> TIA choca. El helper debe
    emitir una colision con el token ``#60010``.

    ``dicc_xml`` mapea ``str(50010)`` -> ``str(60010)``, asi
    el numero destino del bloque de plantilla es 60010.
    """
    ctx = make_ctx(
        plc_blocks_cache={"FB60010"},       # NOMBRE distinto
        plc_blocks_numeros={60010},         # NUMERO que coincide
    )
    await proc_process_copiar_a_preview(ctx)
    await proc_process_leer_manifest(ctx)
    await proc_process_extraer_variables_xml(ctx)
    await proc_process_construir_diccionarios(ctx)
    await proc_process_detectar_colisiones(ctx)

    # El match por NUMERO detecta la colision aunque el nombre
    # NO coincida (cross-type: FB vs DB).
    assert "#60010" in ctx.colisiones


@pytest.mark.asyncio
async def test_generar_previstos_pobla_nombre_y_numero(
    make_ctx: Any,
) -> None:
    """Cada item de ``archivos_previstos`` lleva nombre_original,
    nombre_nuevo, numero_original y numero_nuevo. El numero
    se extrae del ``S7_BlockNumber := "X"`` del XML de plantilla,
    NO del stem (puede que el stem no contenga numeros para
    bloques tipo ``FC_INTERFAZ``).
    """
    ctx = make_ctx()  # plc_blocks_cache = set() vacio
    await proc_process_copiar_a_preview(ctx)
    await proc_process_leer_manifest(ctx)
    await proc_process_extraer_variables_xml(ctx)
    await proc_process_construir_diccionarios(ctx)
    await proc_process_detectar_colisiones(ctx)
    await proc_process_generar_previstos(ctx)

    assert ctx.archivos_previstos
    # Cada item lleva los 4 campos nuevos.
    for item in ctx.archivos_previstos:
        if item["kind"] != "xml" and item["kind"] != "text":
            continue  # binarios (manifest.json procesado aparte)
        # Para .s7dcl / .scl, el numero debe estar presente (>0)
        # porque el archivo lleva la cabecera S7_BlockNumber.
        if item["kind"] == "text" and Path(str(item["rel_in"])).suffix in (
            ".s7dcl", ".scl", ".awl"
        ):
            assert "nombre_original" in item
            assert "nombre_nuevo" in item
            assert "numero_original" in item
            assert "numero_nuevo" in item
            assert item["numero_original"] > 0, item
            # numero_nuevo != numero_original (el dicc lo renombro).
            assert item["numero_nuevo"] > 0, item
            assert item["numero_nuevo"] != item["numero_original"]


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
        plc_blocks_cache=set(),
        minimos_usuario={
            "N_MAX_PREAL": 30, "N_MAX_PINT": 30,
            "N_MAX_ALM": 30, "N_MAX_ALM_HMI": 5,
        },
    )
    await proc_process_copiar_a_preview(ctx)
    await proc_process_leer_manifest(ctx)
    await proc_process_extraer_variables_xml(ctx)
    await proc_process_construir_diccionarios(ctx)
    await proc_process_aplicar_clonacion(ctx)

    # El output .s7res: nombre nuevo es 60010 (base nueva) + EXP
    # (codigo nuevo, reemplazo de "TEST") + _COMENTARIOS (sufijo
    # preservado del .s7res original).
    out_s7res = modified / "bloques" / "60010_EXP_COMENTARIOS.s7res"
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
        plc_blocks_cache=set(),
        minimos_usuario={
            # 4 N_MAX del operario. Distintos para verificar que se
            # aplicaron los valores correctos en el orden esperado.
            "N_MAX_PREAL": 30, "N_MAX_PINT": 30,
            "N_MAX_ALM": 30, "N_MAX_ALM_HMI": 5,
        },
    )
    await proc_process_copiar_a_preview(ctx)
    await proc_process_leer_manifest(ctx)
    await proc_process_extraer_variables_xml(ctx)
    await proc_process_construir_diccionarios(ctx)
    await proc_process_aplicar_clonacion(ctx)

    # El XML clonado: 50010_TEST.xml -> 60010_EXP.xml (sustituye
    # 50010->60010 y TEST->EXP).
    out_xml = modified / "variables" / "60010_EXP.xml"
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
    """Output estructurado en ``{variables,bloques,otros}/``.

    - ``.xml`` -> ``variables/``
    - ``.s7dcl``/``.s7res``/``.scl``/``.awl`` -> ``bloques/``
    - resto (no hay en este dummy) -> ``otros/``
    - ``manifest.json`` se ignora (lo escribe
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
        plc_blocks_cache=set(),
        minimos_usuario={
            "N_MAX_PREAL": 30, "N_MAX_PINT": 30,
            "N_MAX_ALM": 30, "N_MAX_ALM_HMI": 5,
        },
    )
    await proc_process_copiar_a_preview(ctx)
    await proc_process_leer_manifest(ctx)
    await proc_process_extraer_variables_xml(ctx)
    await proc_process_construir_diccionarios(ctx)
    await proc_process_aplicar_clonacion(ctx)

    # Layout canonico.
    assert (modified / "variables").is_dir()
    assert (modified / "bloques").is_dir()
    # archivos_generados poblado con paths relativos a modified/.
    # Los paths usan el separador del OS (``\\`` en Windows); usamos
    # ``os.sep`` o ``in`` con el nombre del archivo final.
    assert any(
        "60010_EXP.xml" in rel for rel in ctx.archivos_generados
    )
    assert any(
        "60010_EXP_COMENTARIOS.s7res" in rel for rel in ctx.archivos_generados
    )
    # manifest.json NO entra como archivo generado del apply (lo escribe
    # la siguiente funcion ``proc_process_escribir_manifest``).
    assert not any(
        rel.endswith("manifest.json") for rel in ctx.archivos_generados
    )


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
        plc_blocks_cache=set(),
        minimos_usuario={
            "N_MAX_PREAL": 30, "N_MAX_PINT": 30,
            "N_MAX_ALM": 30, "N_MAX_ALM_HMI": 5,
        },
    )
    await proc_process_escribir_manifest(ctx)

    manifest_path = modified / "manifest.json"
    assert manifest_path.is_file()
    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert data["base"] == 60010
    assert data["codigo"] == "EXP"
    assert data["nombre"] == "NuevoProceso"
    assert data["minimos"]["N_MAX_PINT"] == 30
    assert data["minimos"]["N_MAX_ALM_HMI"] == 5
    assert "manifest.json" in ctx.archivos_generados
