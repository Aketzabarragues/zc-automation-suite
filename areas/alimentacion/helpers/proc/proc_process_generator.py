"""Helper para generar un proceso completo desde una plantilla.

Funciones puras independientes. Cada una toma un
``ProcProcessGenContext`` por argumento y muta sus campos con el
resultado de su trabajo.

La orquestacion de las funciones vive en los FBs del area:
  - ``areas/alimentacion/functions/function_proc_crear_generar_preview.py``
  - ``areas/alimentacion/functions/function_ProcProcessCrearAplicar.py``

El helper no llama a TIA. Solo manipula archivos locales
(copytree + regex).
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger("zc.areas.alimentacion.proc_process_generator")


# ===========================================================================
# Constantes y errores
# ===========================================================================

# Extensiones de texto que se procesan (no se copian en binario).
EXTENSIONES_TEXTO: frozenset[str] = frozenset({
    ".s7dcl", ".s7res", ".scl", ".xml", ".awl",
})

# Las 4 N_MAX del estandar que valida el manifest y rellena el operario.
N_MAX_KEYS: tuple[str, ...] = (
    "N_MAX_PREAL", "N_MAX_PINT", "N_MAX_ALM", "N_MAX_ALM_HMI",
)


class PlantillaMinimosNoCumplidos(ValueError):
    """Lanzada si los N_MAX del operario son menores que los de la plantilla."""


class ManifestInvalido(ValueError):
    """Lanzada si el manifest.json de la plantilla no existe o le faltan campos."""


# ===========================================================================
# Contexto mutable (estado compartido entre las funciones)
# ===========================================================================

@dataclass
class ProcProcessGenContext:
    """Estado compartido entre las funciones del helper."""

    # ── Deps inyectadas ──
    dir_plantilla: Path
    dir_plantilla_copia: Path
    dir_nuevo: Path
    base_nueva: int
    codigo_nuevo: str
    nombre_nuevo: str
    # Lista de bloques existentes en el PLC destino. Cada item es
    # ``{"nombre": str, "numero": int | None}``; permite cruzar por
    # nombre O por numero en ``proc_process_detectar_colisiones``.
    # ``None`` = cache nunca populado (el helper emite warning).
    plc_blocks_cache: list[dict[str, Any]] | None
    minimos_usuario: dict[str, int]

    # ── Resultado de proc_process_leer_manifest ──
    manifest_plantilla: dict[str, Any] | None = None
    base_vieja: int = 0
    codigo_viejo: str = ""
    nombre_viejo: str = ""

    # ── Resultado de proc_process_construir_diccionarios ──
    dicc_bloques: dict[str, str] = field(default_factory=dict)
    dicc_xml: dict[str, str] = field(default_factory=dict)

    # ── Resultado de proc_process_detectar_colisiones ──
    colisiones: list[str] = field(default_factory=list)
    # Mapa ``nombre_nuevo -> identificador del bloque PLC que
    # colisiona``. La SPA lee este campo para pintar
    # ``DUPLICADO - <identificador>`` en la celda ESTADO. Si un nombre
    # no aparece aqui, la SPA solo muestra ``DUPLICADO``.
    colisiones_con: dict[str, str] = field(default_factory=dict)

    # ── Resultado de proc_process_generar_previstos / aplicar ──
    archivos_previstos: list[dict[str, Any]] = field(default_factory=list)
    archivos_generados: list[str] = field(default_factory=list)

    # ── Resultado final (vuelco a ``ctx.result``) ──
    result: dict[str, Any] = field(default_factory=dict)


# ===========================================================================
# Funciones puras/async (cada una muta ``ctx``)
# ===========================================================================

async def proc_process_leer_manifest(ctx: ProcProcessGenContext) -> None:
    manifest_path = ctx.dir_plantilla / "manifest.json"
    if not manifest_path.exists():
        raise ManifestInvalido(
            f"No se encontro manifest.json en: {ctx.dir_plantilla}"
        )

    try:
        manifest_text = await asyncio.to_thread(
            manifest_path.read_text, encoding="utf-8"
        )
        manifest = json.loads(manifest_text)
    except (OSError, json.JSONDecodeError) as exc:
        raise ManifestInvalido(f"manifest.json invalido: {exc}") from exc

    if "base" not in manifest or not isinstance(manifest["base"], int):
        raise ManifestInvalido("manifest.json debe contener 'base' (int).")
    if "codigo" not in manifest or not str(manifest["codigo"]).strip():
        raise ManifestInvalido("manifest.json debe contener 'codigo' (str).")

    ctx.manifest_plantilla = manifest
    ctx.base_vieja = int(manifest["base"])
    ctx.codigo_viejo = str(manifest["codigo"])
    ctx.nombre_viejo = str(manifest.get("nombre", "") or "")


async def proc_process_validar_minimos(ctx: ProcProcessGenContext) -> None:
    if ctx.manifest_plantilla is None:
        raise RuntimeError("Requiere proc_process_leer_manifest previo.")

    minimos_plantilla = ctx.manifest_plantilla.get("minimos", {}) or {}
    problemas: list[str] = []

    for key in N_MAX_KEYS:
        plantilla_val = int(minimos_plantilla.get(key, 0))
        usuario_val = int(ctx.minimos_usuario.get(key, 0))
        if usuario_val < plantilla_val:
            problemas.append(
                f"{key}: usuario={usuario_val} < plantilla={plantilla_val}"
            )

    if problemas:
        raise PlantillaMinimosNoCumplidos(
            "Los N_MAX del operario no cubren los minimos de la plantilla:\n"
            "  - " + "\n  - ".join(problemas)
        )


async def proc_process_copiar_a_preview(ctx: ProcProcessGenContext) -> None:
    """Copia ``dir_plantilla`` a ``dir_plantilla_copia``.

    Borra ``dir_plantilla_copia`` antes de copiar (regla de retencion:
    cada preview parte limpio, mismo patron que
    ``ContextCache.clean_preview()`` en dispositivos y que
    ``proc_process_aplicar_clonacion`` aplica a ``dir_nuevo/``).
    Re-arrancable sin intervencion manual del operario.
    """
    if ctx.dir_plantilla_copia.exists():
        await asyncio.to_thread(shutil.rmtree, ctx.dir_plantilla_copia)
    # shutil.copytree crea el destino el solo (``dirs_exist_ok=False``
    # requiere que NO exista).
    await asyncio.to_thread(
        shutil.copytree,
        ctx.dir_plantilla,
        ctx.dir_plantilla_copia,
        dirs_exist_ok=False,
    )


async def proc_process_construir_diccionarios(ctx: ProcProcessGenContext) -> None:
    """Construye los diccionarios de renombrado.

    Estrategia:
      - Bloques: walk del directorio ``dir_plantilla_copia`` con un regex
        matematico ``(FC|FB|DB)(\\d+)`` -> ``prefijo(num - base_vieja + base_nueva)``.
        Renombra SOLO los prefijos canonicos TIA (FC/FB/DB), no
        cualquier secuencia de digitos. Asi referencias a bloques
        MAESTROS como ``DB1000_ED`` no se tocan (no estan en la
        lista de prefijos ni matchean las reglas de base).
      - Variables y carpetas: 3 reglas explicitas por base
        (``base``, ``base + 3000`` = Params, ``base + 5000`` = Alarmas).
        NO rango. Cada base genera UNA regla global de prefijo.
      - Metadatos TIA: ``S7_BlockNumber := "X"`` de las cabeceras de
        los bloques del proceso.
      - Fallbacks: codigo y nombre del proceso (siempre).

    Todo se ordena por ``len(key)`` descendente para que las claves
    mas especificas (e.g. ``200_PRO_STD``) ganen antes que las mas
    cortas (``200``).
    """
    base_viej = ctx.base_vieja
    base_nuev = ctx.base_nueva
    cod_viej = ctx.codigo_viejo
    cod_nuev = ctx.codigo_nuevo
    nom_viej = ctx.nombre_viejo
    nom_nuev = ctx.nombre_nuevo

    dicc_bloques: dict[str, str] = {}
    dicc_xml: dict[str, str] = {}
    numeros_usados: set[int] = set()

    patron_bloques = re.compile(r"(FC|FB|DB)(\d+)")

    def _walk_and_build() -> None:
        for item in ctx.dir_plantilla_copia.rglob("*"):
            if not item.exists():
                continue
            nombre_base = item.stem if item.is_file() else item.name

            # Bloques: reemplaza SOLO prefijos canonicos (FC/FB/DB).
            # Las referencias como ``DB1000_ED`` no se tocan en esta
            # pasada (DB1000 no es del proceso; aparece en codigo SCL
            # pero el archivo es del proceso, y DC1000 ya esta en el
            # PLC destino sin necesidad de crearlo).
            def _repl_bloque(m: re.Match[str]) -> str:
                prefijo = m.group(1)
                num_viejo = int(m.group(2))
                num_nuevo = num_viejo - base_viej + base_nuev
                return f"{prefijo}{num_nuevo}"

            nuevo_nombre_base = patron_bloques.sub(_repl_bloque, nombre_base)

            if cod_viej:
                nuevo_nombre_base = nuevo_nombre_base.replace(cod_viej, cod_nuev)
            if nom_viej and nom_nuev:
                nuevo_nombre_base = nuevo_nombre_base.replace(nom_viej, nom_nuev)

            if nombre_base != nuevo_nombre_base:
                dicc_bloques[nombre_base] = nuevo_nombre_base

            for match in patron_bloques.finditer(nombre_base):
                numeros_usados.add(int(match.group(2)))

    await asyncio.to_thread(_walk_and_build)

    # Variables y carpetas: solo 3 bases (proceso principal + params
    # +3000 + alarmas +5000). NO rango, NO por cada numero.
    bases_viejas = [base_viej, base_viej + 3000, base_viej + 5000]
    bases_nuevas = [base_nuev, base_nuev + 3000, base_nuev + 5000]
    for b_vieja, b_nueva in zip(bases_viejas, bases_nuevas):
        regla_vieja = f"{b_vieja}_"
        regla_nueva = f"{b_nueva}_"
        dicc_xml[regla_vieja] = regla_nueva
        dicc_bloques[regla_vieja] = regla_nueva

    # Metadatos TIA Portal: ``S7_BlockNumber := "X"`` en la cabecera
    # de los archivos .s7dcl / .scl / .awl. ``numeros_usados`` viene
    # del walk anterior (solo matchea prefijos FC/FB/DB).
    for num in numeros_usados:
        nuevo_num = num - base_viej + base_nuev
        dicc_bloques[f'S7_BlockNumber := "{num}"'] = (
            f'S7_BlockNumber := "{nuevo_num}"'
        )

    # Fallbacks: codigo y nombre (siempre; los bloques que solo
    # cambian de nombre/codigo sin tocar numeros siguen entrando).
    if cod_viej:
        dicc_xml[cod_viej] = cod_nuev
        dicc_bloques[cod_viej] = cod_nuev
    if nom_viej and nom_nuev:
        dicc_xml[nom_viej] = nom_nuev
        dicc_bloques[nom_viej] = nom_nuev

    ctx.dicc_bloques = dict(
        sorted(dicc_bloques.items(), key=lambda x: len(x[0]), reverse=True)
    )
    ctx.dicc_xml = dict(
        sorted(dicc_xml.items(), key=lambda x: len(x[0]), reverse=True)
    )

    logger.debug(
        f"[proc_process_construir_diccionarios] "
        f"{len(ctx.dicc_bloques)} reglas bloques + "
        f"{len(ctx.dicc_xml)} reglas XML."
    )


async def proc_process_detectar_colisiones(ctx: ProcProcessGenContext) -> None:
    """Cruza ``dicc_bloques`` contra ``plc_blocks_cache`` por nombre
    O por numero.

    Cualquier nombre post-rename del diccionario que ya exista como
    bloque en el PLC es una colision (match por nombre). Tambien
    detecta colision si el numero del bloque nuevo coincide con un
    numero de la cache del PLC (match por numero — util cuando el
    PLC cache tiene dicts ``{nombre, numero}`` y el nombre del
    nuevo bloque usa un prefijo distinto al que el PLC esperaba).
    TIA Portal fallaria el import en ambos casos (UPDATE fallido ->
    "object already exists").

    Adicionalmente popula ``ctx.colisiones_con`` con el
    identificador del bloque del PLC que produjo la colision
    (nombre preferred, fallback a ``"<numero>"``). La SPA lo usa
    para pintar ``DUPLICADO - <id>``.

    IMPORTANTE: el match por numero SIEMPRE requiere que el prefijo
    alfabetico del nombre coincida (e.g. ``FC100`` y ``OB100`` son
    bloques distintos en TIA Portal: FC/FB/DB/OB/UDT pueden
    coexistir con el mismo numero porque viven en namespaces
    distintos). El match real es por la tupla
    ``(prefijo_upper, numero)``.

    Si ``plc_blocks_cache`` es ``None`` (cache nunca populado),
    emite un mensaje accionable y devuelve sin abortar.
    """
    if ctx.plc_blocks_cache is None:
        ctx.colisiones.append(
            "Cache de bloques PLC no inicializado "
            "(escanea primero con 'Escanear bloques PLC')"
        )
        logger.warning(
            "[proc_process_detectar_colisiones] "
            "plc_blocks_cache=None; el FB deberia abortar."
        )
        return

    # Normalizar la cache: tolerar tanto ``list[dict{nombre, numero}]``
    # (shape nuevo) como ``set[str]`` legacy (defensivo: si llega un
    # set, lo convertimos a lista de dicts con solo ``nombre``).
    plc_entries: list[dict[str, Any]] = []
    for item in ctx.plc_blocks_cache:
        if isinstance(item, dict):
            plc_entries.append(item)
        elif isinstance(item, str):
            plc_entries.append({"nombre": item, "numero": None})

    # Sets de lookup rapido + mapas inversos:
    #   - plc_nombres: match exacto por nombre.
    #   - plc_tipo_numero: match por ``(prefijo_upper, numero)``.
    #     El prefijo es lo que viene del scanner (``FC100``,
    #     ``OB100_Startup``, ``DB50010``, ...); uppercased para que
    #     ``fc100`` y ``FC100`` matcheen identico.
    plc_nombres: set[str] = set()
    plc_tipo_numero: set[tuple[str, int]] = set()
    id_por_nombre: dict[str, str] = {}
    id_por_tipo_numero: dict[tuple[str, int], str] = {}
    patron_prefijo_num = re.compile(r"^([A-Za-z]+)(\d+)")
    for blk in plc_entries:
        nombre_raw = blk.get("nombre")
        nombre = str(nombre_raw) if nombre_raw else ""
        numero_raw = blk.get("numero")
        if isinstance(numero_raw, bool):  # bool es subclass de int
            continue
        if isinstance(numero_raw, int):
            numero: int | None = numero_raw
        elif isinstance(numero_raw, str) and numero_raw.isdigit():
            numero = int(numero_raw)
        else:
            numero = None
        # Identificador visible: nombre preferred, fallback a numero.
        ident = nombre if nombre else (str(numero) if numero is not None else "")
        if not ident:
            continue
        if nombre and nombre not in plc_nombres:
            plc_nombres.add(nombre)
            id_por_nombre[nombre] = ident
        # Para el match (prefijo, numero) necesitamos ambos campos
        # del bloque PLC. Los bloques sin ``numero`` explicito lo
        # extraemos del nombre (e.g. ``OB100_Startup`` -> ("OB", 100)).
        # Esto cubre bloques que el scanner emite como string sin
        # numero separado, que es lo tipico.
        num_para_tipo = numero
        prefijo_para_tipo: str | None = None
        if nombre:
            m_plc = patron_prefijo_num.match(nombre)
            if m_plc:
                prefijo_para_tipo = m_plc.group(1).upper()
                if num_para_tipo is None:
                    num_para_tipo = int(m_plc.group(2))
        if prefijo_para_tipo and num_para_tipo is not None:
            key_tipo_num = (prefijo_para_tipo, num_para_tipo)
            if key_tipo_num not in plc_tipo_numero:
                plc_tipo_numero.add(key_tipo_num)
                id_por_tipo_numero[key_tipo_num] = ident

    colisiones_vistas: set[str] = set()
    # Filtramos solo nombres post-rename reales (excluimos
    # metadatos TIA, prefijos de base y fallbacks cod/nombre
    # sin prefijo bloque).
    for key, val in ctx.dicc_bloques.items():
        if (
            key.startswith("S7_BlockNumber")
            or key.isdigit()
            or key.endswith("_")  # prefijos de base (200_, 3200_, 5200_)
        ):
            continue
        if val in colisiones_vistas:
            continue
        # Match por nombre (rapido y comun).
        if val in plc_nombres:
            ctx.colisiones.append(val)
            ctx.colisiones_con[val] = id_por_nombre[val]
            colisiones_vistas.add(val)
            continue
        # Match por ``(prefijo_upper, numero)``. Crucial: FC100 y
        # OB100 son bloques distintos en TIA Portal (namespaces
        # separados por tipo de bloque), asi que el match por numero
        # aislado seria incorrecto.
        m = patron_prefijo_num.match(val)
        if m:
            prefijo = m.group(1).upper()
            num = int(m.group(2))
            key_tipo_num = (prefijo, num)
            if key_tipo_num in plc_tipo_numero:
                ctx.colisiones.append(val)
                ctx.colisiones_con[val] = id_por_tipo_numero[key_tipo_num]
                colisiones_vistas.add(val)


async def proc_process_generar_previstos(ctx: ProcProcessGenContext) -> None:
    """Walk ``dir_plantilla_copia`` y construye la lista de archivos
    que se generarian en ``dir_nuevo``.

    No escribe en disco — solo popula ``ctx.archivos_previstos``
    para que la SPA muestre el preview.

    PRESERVA LA ESTRUCTURA DE CARPETAS de la plantilla. Para cada
    archivo calcula ``rel_in`` y ``rel_out`` con el mismo subpath
    relativo (la unica diferencia es el filename, que se renombra
    aplicando ``dicc_bloques``). Esto es lo que permite que el
    import posterior en TIA Portal (``import_plc_tags_xml`` y
    ``import_blocks_sd`` apuntando a la raiz de ``dir_nuevo``)
    mantenga la jerarquia del proceso en el PLC.

    ``kind`` indica el tipo de archivo (``xml``, ``text``, ``binary``)
    para que el apply use el ``diccionario`` y ``encoding``
    correctos:
      - ``.xml``: dicc_xml, encoding utf-8.
      - resto de ``EXTENSIONES_TEXTO``: dicc_bloques, encoding utf-8
        (utf-8-sig para ``.s7res``).
      - resto: copia binaria sin tocar.
    """
    archivos_previstos: list[dict[str, Any]] = []

    def _walk() -> list[Path]:
        return [p for p in ctx.dir_plantilla_copia.rglob("*") if p.is_file()]

    paths = await asyncio.to_thread(_walk)

    for in_path in paths:
        rel_in = in_path.relative_to(ctx.dir_plantilla_copia)
        if rel_in.name == "manifest.json":
            continue

        nuevo_stem = _aplicar_diccionario(in_path.stem, ctx.dicc_bloques)
        suffix = in_path.suffix.lower()
        if suffix == ".xml":
            kind = "xml"
        elif suffix in EXTENSIONES_TEXTO:
            kind = "text"
        else:
            kind = "binary"

        # rel_out = misma estructura de carpetas, solo cambia el
        # nombre del archivo (post-rename). El parent path se
        # preserva tal cual para que el subpath en el PLC coincida
        # con el de la plantilla.
        rel_out = rel_in.parent / f"{nuevo_stem}{suffix}"

        # Match contra colisiones post-rename (con y sin sufijo).
        colisiona_nombre = nuevo_stem in ctx.colisiones
        colisiona_con_sufijo = f"{nuevo_stem}{suffix}" in ctx.colisiones
        colisiona = colisiona_nombre or colisiona_con_sufijo

        # ``colision_con``: identificador del bloque PLC que produjo
        # la colision (nombre o numero). Se resuelve desde
        # ``ctx.colisiones_con`` que pobló
        # ``proc_process_detectar_colisiones``. La SPA lo lee para
        # pintar ``DUPLICADO - <id>``. Si no hay match especifico,
        # queda ``None`` (la SPA pinta ``DUPLICADO`` plano).
        colision_con: str | None = None
        if colisiona_nombre:
            colision_con = ctx.colisiones_con.get(nuevo_stem)
        elif colisiona_con_sufijo:
            colision_con = ctx.colisiones_con.get(f"{nuevo_stem}{suffix}")

        archivos_previstos.append({
            "rel_in": str(rel_in),
            "rel_out": str(rel_out),
            "kind": kind,
            "colisiona": colisiona,
            "colision_con": colision_con,
        })

    ctx.archivos_previstos = archivos_previstos


async def proc_process_aplicar_clonacion(ctx: ProcProcessGenContext) -> None:
    """Aplica la clonacion: ``dir_plantilla_copia`` -> ``dir_nuevo``.

    Borra ``dir_nuevo/`` antes de aplicar (regla de retencion: cada
    apply parte limpio, mismo patron que ``ContextCache.clean()`` en
    dispositivos).

    Pipeline:
      1. ``shutil.copytree(dir_plantilla_copia, dir_nuevo,
         ignore=manifest)``: copia bulk preservando la estructura de
         carpetas. Es la primitiva canonica de la stdlib para esto;
         no reinventamos mkdir + write por archivo.
      2. Walk de ``dir_nuevo``: para cada path (file O folder) se
         aplica el rename al nombre del componente aplicando
         ``_aplicar_diccionario(nombre, dicc_bloques)``. Los folder
         names siguen las mismas reglas que los file stems porque el
         helper ya popula ``dicc_bloques`` con las substituciones de
         base (``200_`` -> ``100_``), codigo (``EXP`` -> ``CPR``) y
         nombre completo (``Expedicion`` -> ``CPR``). Las dos
         pasadas se aplican en cascada (sorted by ``len(key)`` desc),
         asi que ``200_Expedicion`` se resuelve correctamente a
         ``100_CPR``: primero la base (``200_`` -> ``100_Expedicion``)
         y luego el codigo/nombre (``Expedicion`` -> ``CPR``).
      3. Walk final para rewrite de contenido segun extension. Solo
         los archivos de texto se reescriben; los binarios copiados
         por copytree quedan tal cual.

    Por extension (paso 3):
      - ``.s7res``:           ``dicc_bloques``, encoding utf-8-sig.
      - ``.xml``:             ``dicc_xml``, encoding utf-8 (con
                              override de N_MAX si el XML contiene
                              PlcUserConstant).
      - ``.s7dcl``/``.scl``/``.awl``: ``dicc_bloques``, encoding utf-8.
      - Resto (binarios):     sin tocar (ya copiados por copytree).

    ``manifest.json`` se excluye via el ``ignore`` de copytree (lo
    regenera ``proc_process_escribir_manifest`` justo despues).

    Para los renames de folder, se procesan en orden de profundidad
    DESCENDENTE (mas profundo primero) para no romper paths de hijos
    cuando movemos el padre. Si dos carpetas hermanas tienen el
    mismo nombre pre-rename, los paths absolutos son distintos asi
    que no hay colision.

    El FB Apply dispara luego ``import_plc_tags_xml`` y
    ``import_blocks_sd`` apuntando a la RAIZ de ``dir_nuevo``: TIA
    Portal recurse sobre los subdirectorios preservando el layout
    en el PLC. NO hace falta (ni se debe) pasar
    ``target_folder_path``; el handler usa el default ``None`` para
    que TIA haga UPDATE recursivo (ver
    ``tia_handlers._h_import_block``).
    """
    if ctx.dir_nuevo.exists():
        await asyncio.to_thread(shutil.rmtree, ctx.dir_nuevo)

    # 1) Copia bulk preservando estructura. ``ignore`` se invoca
    # una vez por directorio con la lista de entries; devolvemos
    # ``manifest.json`` para que NO se copie (lo regenera
    # ``proc_process_escribir_manifest``).
    def _ignore_manifest(_dir: str, names: list[str]) -> list[str]:
        return [n for n in names if n == "manifest.json"]

    await asyncio.to_thread(
        shutil.copytree,
        str(ctx.dir_plantilla_copia),
        str(ctx.dir_nuevo),
        ignore=_ignore_manifest,
    )

    # 2) Rename de filenames Y folder names. Construimos el mapa
    # completo primero (old_path -> new_path) y aplicamos en orden
    # de profundidad descendente para no invalidar paths hijos al
    # mover el padre.
    def _rename_paths() -> None:
        renames: list[tuple[Path, Path]] = []
        for path in list(ctx.dir_nuevo.rglob("*")):
            if path == ctx.dir_nuevo:
                continue
            if path.is_file():
                suffix = path.suffix.lower()
                nuevo_stem = _aplicar_diccionario(
                    path.stem, ctx.dicc_bloques
                )
                new_name = f"{nuevo_stem}{suffix}"
            else:
                new_name = _aplicar_diccionario(
                    path.name, ctx.dicc_bloques
                )
            if path.name != new_name:
                renames.append((path, path.with_name(new_name)))

        # Profundidad descendente: hojas primero, raiz la ultima.
        # ``len(parts)`` cuenta los componentes del path absoluto;
        # mas profundidad = mas parts = mas prioritario.
        renames.sort(key=lambda pair: -len(pair[0].parts))
        for old, new in renames:
            new.parent.mkdir(parents=True, exist_ok=True)
            old.rename(new)

    await asyncio.to_thread(_rename_paths)

    # 3) Rewrite de contenido segun extension. ``rglob`` sobre el
    # destino ya con filenames + folder names renombrados.
    def _rewrite_contents() -> list[str]:
        generated: list[str] = []
        for path in ctx.dir_nuevo.rglob("*"):
            if not path.is_file():
                continue
            suffix = path.suffix.lower()
            if suffix == ".s7res":
                enc = "utf-8-sig"
                contenido = _leer_texto(path, enc)
                nuevo = _aplicar_diccionario(contenido, ctx.dicc_bloques)
                _escribir_texto(path, nuevo, enc)
            elif suffix == ".xml":
                enc = "utf-8"
                contenido = _leer_texto(path, enc)
                nuevo = _aplicar_diccionario(contenido, ctx.dicc_xml)
                if "PlcUserConstant" in nuevo and ctx.minimos_usuario:
                    nuevo = _reemplazar_nmax_en_xml(
                        nuevo, ctx.base_nueva, ctx.minimos_usuario
                    )
                _escribir_texto(path, nuevo, enc)
            elif suffix in (".s7dcl", ".scl", ".awl"):
                enc = "utf-8"
                contenido = _leer_texto(path, enc)
                nuevo = _aplicar_diccionario(contenido, ctx.dicc_bloques)
                _escribir_texto(path, nuevo, enc)
            # else: binarios, ya copiados por shutil.copytree tal cual.

            generated.append(str(path.relative_to(ctx.dir_nuevo)))
        return generated

    ctx.archivos_generados = await asyncio.to_thread(_rewrite_contents)


async def proc_process_escribir_manifest(ctx: ProcProcessGenContext) -> None:
    """Escribe ``<dir_nuevo>/manifest.json`` con los datos del
    proceso nuevo (usa la plantilla como base, override con
    ``base_nueva/codigo/nombre/minimos`` del ctx).
    """
    ctx.dir_nuevo.mkdir(parents=True, exist_ok=True)
    manifest_path = ctx.dir_nuevo / "manifest.json"
    payload = {
        "base": ctx.base_nueva,
        "codigo": ctx.codigo_nuevo,
        "nombre": ctx.nombre_nuevo,
        "minimos": dict(ctx.minimos_usuario),
    }

    def _write() -> None:
        manifest_path.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False),
            encoding="utf-8",
            newline="\n",
        )

    await asyncio.to_thread(_write)
    ctx.archivos_generados.append("manifest.json")


async def proc_process_done_summary(ctx: ProcProcessGenContext) -> dict[str, Any]:
    """Compone ``ctx.result`` con la shape que el FB vuelca a
    ``self.result``.

    Diferencia preview vs apply:
      - preview (``archivos_previstos`` poblado) -> vuelca la lista de
        previstos + el ``plantilla_copia_dir``.
      - apply (``archivos_generados`` poblado) -> vuelca la lista de
        generados + el ``nuevo_dir``.

    ``success=True`` solo si no hubo colisiones.
    """
    if ctx.archivos_generados:
        dir_salida = ctx.dir_nuevo
        archivos = list(ctx.archivos_generados)
        campo_archivos = "archivos_generados"
    else:
        dir_salida = ctx.dir_plantilla_copia
        archivos = list(ctx.archivos_previstos)
        campo_archivos = "archivos_previstos"

    success = len(ctx.colisiones) == 0
    ctx.result = {
        "manifest_plantilla": ctx.manifest_plantilla,
        campo_archivos: archivos,
        "colisiones": list(ctx.colisiones),
        (
            "plantilla_copia_dir"
            if campo_archivos == "archivos_previstos"
            else "nuevo_dir"
        ): str(dir_salida),
        "success": success,
    }
    return ctx.result


# ===========================================================================
# Helpers internos (sync)
# ===========================================================================

def _aplicar_diccionario(texto: str, dicc: dict[str, str]) -> str:
    """Aplica los reemplazos en cascada — el caller garantiza el orden
    descendente por ``len(key)`` para que los mas especificos ganen.
    """
    for viejo, nuevo in dicc.items():
        texto = texto.replace(viejo, nuevo)
    return texto


def _leer_texto(path: Path, encoding: str) -> str:
    """Lee texto con fallback latin-1 si utf-8 falla (caso TIA V21)."""
    try:
        with open(path, "r", encoding=encoding, newline="") as f:
            return f.read()
    except UnicodeDecodeError:
        with open(path, "r", encoding="latin-1", newline="") as f:
            return f.read()


def _escribir_texto(path: Path, contenido: str, encoding: str) -> None:
    """Escribe texto preservando retornos de carro (``newline=""``)."""
    with open(path, "w", encoding=encoding, newline="") as f:
        f.write(contenido)


def _reemplazar_nmax_en_xml(
    contenido: str,
    base_nueva: int,
    minimos_usuario: dict[str, int],
) -> str:
    """Sustituye los ``<Value>`` de las constantes N_MAX del proceso
    nuevo de forma segura, vinculandolos a su ``<Name>``.

    Asume que ``contenido`` ya paso por ``_aplicar_diccionario(contenido,
    dicc_xml)``, asi ``<Name>{base_nueva}_{N_MAX_KEY}</Name>`` esta
    presente en el XML destino.

    Usa regex DOTALL para saltar de ``<Name>`` a ``<Value>`` adyacente,
    robusto frente a XML con comentarios / anidamientos.
    """
    for key in N_MAX_KEYS:
        val_usuario = minimos_usuario.get(key)
        if val_usuario is None:
            continue

        patron = rf"(<Name>{base_nueva}_{key}</Name>.*?<Value>)(\d+)(</Value>)"
        contenido = re.sub(
            patron,
            lambda m: f"{m.group(1)}{val_usuario}{m.group(3)}",
            contenido,
            flags=re.DOTALL,
        )
    return contenido


__all__ = [
    "EXTENSIONES_TEXTO",
    "ManifestInvalido",
    "N_MAX_KEYS",
    "PlantillaMinimosNoCumplidos",
    "ProcProcessGenContext",
    "proc_process_aplicar_clonacion",
    "proc_process_construir_diccionarios",
    "proc_process_copiar_a_preview",
    "proc_process_detectar_colisiones",
    "proc_process_done_summary",
    "proc_process_escribir_manifest",
    "proc_process_generar_previstos",
    "proc_process_leer_manifest",
    "proc_process_validar_minimos",
]