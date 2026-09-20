"""Port de ``clone.py`` a una libreria invocable desde FBs del area
procesos (generar un proceso completo desde plantilla).

Funciones puras independientes. Cada una toma un
``ProcProcessGenContext`` por argumento y muta sus campos con el
resultado de su trabajo.

Este modulo **no contiene state machine**. La orquestacion de las
funciones (orden, dependencias entre etapas, mapeo a steps del FB)
vive exclusivamente en:
  - ``areas/alimentacion/functions/function_ProcProcessCrearPreview.py``
  - ``areas/alimentacion/functions/function_ProcProcessCrearAplicar.py``

El helper **NO llama a TIA**. Toda interaccion contra el PLC vive en
los 2 FBs anteriores (que delegan en ``dispatch_async``). Aqui solo
se manipulan archivos locales (copytree + regex).

Restricciones arquitectonicas (.clinerules):
  - NO importa ``siemens_tia_scripting``.
  - Sin Singletons dentro del helper; todas las deps inyectadas.
  - Cero rutas hardcodeadas: rutas y carpetas se leen del
    ``ProcProcessGenContext`` (que el FB construye con el
    ``build_cache_root`` del area).
  - El helper NO toca ``progress_tracker``; eso es responsabilidad
    del FB wrapper.
  - El helper NO contiene state machine (orden, mapping, dispatch);
    eso vive en los FBs.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
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

# Rango de numeros que se considera "de este proceso" al escanear XML.
# Si una variable empieza con un numero fuera de
# ``[base_vieja, base_vieja + OFFSET_SAFETY_RANGE)``, no se reemplaza.
OFFSET_SAFETY_RANGE: int = 10_000

# Solo las 4 N_MAX del estandar: las mismas que valida el manifest de
# plantilla y las que el operario rellena en el form.
N_MAX_KEYS: tuple[str, ...] = (
    "N_MAX_PREAL", "N_MAX_PINT", "N_MAX_ALM", "N_MAX_ALM_HMI",
)

# Regex para extraer el ``<Name>UID_NOMBRE</Name>`` exacto del XML de
# variables. Filtra los numeros que estan dentro del rango del proceso.
PATRON_XML_VARIABLE = re.compile(r"<Name>(\d+_[a-zA-Z0-9_]+)</Name>")

# Regex para extraer todos los <Value>NN</Value> numericos del XML de
# variables. Usado para re-mapear los 4 N_MAX del manifest.
PATRON_XML_VALUE = re.compile(r"<Value>(\d+)</Value>")


class PlantillaMinimosNoCumplidos(ValueError):
    """Lanzada por ``proc_process_validar_minimos`` si los N_MAX del
    usuario son menores que los de la plantilla.

    El operario tiene que subir sus N_MAX (en el form) hasta cubrir los
    minimos que exige la plantilla, o seleccionar otra plantilla.
    """


class ManifestInvalido(ValueError):
    """Lanzada por ``proc_process_leer_manifest`` si el manifest.json
    de la plantilla no existe o le faltan campos criticos (base o
    codigo). El nombre puede ser ``""`` (algunas plantillas lo dejan
    vacio a proposito)."""


# ===========================================================================
# Contexto mutable (estado compartido entre las funciones del helper)
# ===========================================================================

@dataclass
class ProcProcessGenContext:
    """Estado compartido entre las funciones de ``proc_process_generator``.

    Cada funcion toma un ``ProcProcessGenContext`` por argumento, lee las
    deps inyectadas y los resultados de funciones previas, y muta los
    campos que representan resultados de su trabajo. Los 2 FBs
    (``FunctionProcSincronizar`` solo los FB de crear) instancian uno y
    lo reusan entre sus ticks para que los resultados intermedios esten
    disponibles para las funciones posteriores.

    Diferencia con ``ProcSyncContext``: este contexto NO toca TIA. Solo
    opera sobre directorios locales (preview/, modified/). El FB que
    llama es el responsable de despachar ``import_*`` al PLC cuando
    aplique.
    """

    # ── Deps inyectadas ──
    dir_plantilla: Path
    dir_preview: Path
    dir_modified: Path
    base_nueva: int
    codigo_nuevo: str
    nombre_nuevo: str
    plc_blocks_cache: set[str] | None
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

    # ── Resultado de proc_process_generar_previstos / aplicar ──
    archivos_previstos: list[dict[str, Any]] = field(default_factory=list)
    archivos_generados: list[str] = field(default_factory=list)

    # ── Resultado final (vuelco a ``ctx.result``) ──
    result: dict[str, Any] = field(default_factory=dict)


# ===========================================================================
# Funciones puras/async (cada una muta ``ctx``; sin state machine aqui)
# ===========================================================================

async def proc_process_leer_manifest(ctx: ProcProcessGenContext) -> None:
    """Lee ``<dir_plantilla>/manifest.json`` y popula el contexto.

    Fija ``ctx.manifest_plantilla`` y extrae ``base`` (int obligatorio),
    ``codigo`` (str obligatorio) y ``nombre`` (str, opcional ``""``).
    Tolerante a claves desconocidas (loggea debug y sigue).

    Raises:
        ManifestInvalido: si el manifest no existe o faltan ``base`` o
            ``codigo``.
    """
    manifest_path = ctx.dir_plantilla / "manifest.json"
    if not manifest_path.exists():
        raise ManifestInvalido(
            f"No se encontro manifest.json en la plantilla: "
            f"{ctx.dir_plantilla}"
        )

    try:
        manifest_text = await asyncio.to_thread(
            manifest_path.read_text, encoding="utf-8"
        )
        manifest = json.loads(manifest_text)
    except (OSError, json.JSONDecodeError) as exc:
        raise ManifestInvalido(
            f"manifest.json invalido en {manifest_path}: {exc}"
        ) from exc

    if "base" not in manifest or not isinstance(manifest["base"], int):
        raise ManifestInvalido(
            f"manifest.json debe contener 'base' (int). "
            f"Campos encontrados: {sorted(manifest.keys())}"
        )
    if "codigo" not in manifest or not str(manifest["codigo"]).strip():
        raise ManifestInvalido(
            f"manifest.json debe contener 'codigo' (str no vacio). "
            f"Campos encontrados: {sorted(manifest.keys())}"
        )

    ctx.manifest_plantilla = manifest
    ctx.base_vieja = int(manifest["base"])
    ctx.codigo_viejo = str(manifest["codigo"])
    ctx.nombre_viejo = str(manifest.get("nombre", "") or "")

    logger.debug(
        f"[proc_process_leer_manifest] manifest leido: "
        f"base={ctx.base_vieja} codigo={ctx.codigo_viejo} "
        f"nombre={ctx.nombre_viejo!r} minimos="
        f"{manifest.get('minimos', {})}"
    )


async def proc_process_validar_minimos(
    ctx: ProcProcessGenContext,
) -> None:
    """Valida que los N_MAX del operario cubren los de la plantilla.

    Solo verifica las 4 claves canonicas (``N_MAX_KEYS``). Si el
    operario relleno menos de las que pide la plantilla en alguna de
    ellas, lanza ``PlantillaMinimosNoCumplidos`` y el FB aborta con un
    mensaje accionable.

    Las claves que el operario NO relleno se interpretan como ``0``
    (peor caso).
    """
    if ctx.manifest_plantilla is None:
        raise RuntimeError(
            "proc_process_validar_minimos requiere "
            "proc_process_leer_manifest previo."
        )

    minimos_plantilla = (
        ctx.manifest_plantilla.get("minimos", {}) or {}
    )
    problemas: list[str] = []

    for key in N_MAX_KEYS:
        plantilla_val = int(minimos_plantilla.get(key, 0))
        usuario_val = int(ctx.minimos_usuario.get(key, 0))
        if usuario_val < plantilla_val:
            problemas.append(
                f"{key}: usuario={usuario_val} < "
                f"plantilla={plantilla_val}"
            )

    if problemas:
        raise PlantillaMinimosNoCumplidos(
            "Los N_MAX del operario no cubren los minimos de la "
            "plantilla:\n  - " + "\n  - ".join(problemas) +
            "\nSube los N_MAX del proceso o elige otra plantilla."
        )


async def proc_process_copiar_a_preview(
    ctx: ProcProcessGenContext,
) -> None:
    """Copia la plantilla ``dir_plantilla`` a ``dir_preview``.

    Raises:
        RuntimeError: si ``dir_preview`` ya existe (el operario debe
            limpiar el staging antes de reintentar).
    """
    if ctx.dir_preview.exists():
        raise RuntimeError(
            f"dir_preview ya existe: {ctx.dir_preview}. "
            f"Limpia el staging de "
            f"{ctx.dir_preview.parent.parent} antes de reintentar."
        )

    await asyncio.to_thread(
        shutil.copytree,
        ctx.dir_plantilla,
        ctx.dir_preview,
        dirs_exist_ok=False,
    )


async def proc_process_extraer_variables_xml(
    ctx: ProcProcessGenContext,
) -> None:
    """Escanea los XML del preview para encontrar variables exactas
    ``UID_NOMBRE`` cuyo UID este en ``[base_vieja, base_vieja + 10_000)``.

    Devuelve la lista como lista auxiliar (ordenada por orden de
    aparicion, sin duplicados exactos via ``dict.fromkeys``). La funcion
    ``proc_process_construir_diccionarios`` es quien la consume.

    Encoding: utf-8-sig (los XML exportados por TIA llevan BOM); fallback
    a latin-1 si utf-8 falla.
    """
    patron = PATRON_XML_VARIABLE
    rango_bajo = ctx.base_vieja
    rango_alto = ctx.base_vieja + OFFSET_SAFETY_RANGE

    def _walk() -> list[str]:
        result: dict[str, None] = {}
        for f in ctx.dir_preview.rglob("*.xml"):
            if not f.is_file():
                continue
            try:
                texto = f.read_text(encoding="utf-8-sig", errors="strict")
            except UnicodeDecodeError:
                texto = f.read_text(encoding="latin-1", errors="ignore")
            for nombre_var in patron.findall(texto):
                num_str = nombre_var.split("_", 1)[0]
                if not num_str.isdigit():
                    continue
                num = int(num_str)
                if rango_bajo <= num < rango_alto:
                    result[nombre_var] = None
        return list(result.keys())

    variables = await asyncio.to_thread(_walk)
    # Las guardamos en el ctx para que ``construir_diccionarios`` las
    # consuma sin volver a recorrer los XMLs.
    ctx.__dict__.setdefault("_variables_xml_exactas", variables)


async def proc_process_construir_diccionarios(
    ctx: ProcProcessGenContext,
) -> None:
    """Construye ``dicc_bloques`` (codigo fuente) y ``dicc_xml``
    (prefijos numericos para XML) en cascada, ordenados por ``len(key)``
    descendente.

    Misma logica que ``clone.py::construir_diccionarios``: el orden
    descendente garantiza que los reemplazos mas especificos (``50010_``)
    se aplican antes que los mas genericos (``50010``).
    """
    base_viej = ctx.base_vieja
    base_nuev = ctx.base_nueva
    cod_viej = ctx.codigo_viejo
    cod_nuev = ctx.codigo_nuevo
    nom_viej = ctx.nombre_viejo
    nom_nuev = ctx.nombre_nuevo

    offset = base_nuev - base_viej
    dicc_bloques: dict[str, str] = {}
    dicc_xml: dict[str, str] = {}
    numeros_usados: set[int] = set()

    # Variables exactas del XML (UID_NOMBRE). ``construir_diccionarios``
    # necesita esta lista — si no se ha llamado a
    # ``extraer_variables_xml`` antes, la extraemos ahora en sync (modo
    # tolerante: si falla, lista vacia).
    variables_xml = ctx.__dict__.get("_variables_xml_exactas") or []

    def _walk_and_build() -> None:
        for item in ctx.dir_preview.rglob("*"):
            if not item.exists():
                continue
            nombre_base = item.stem if item.is_file() else item.name

            def _repl_num(m: re.Match[str]) -> str:
                num = int(m.group(0))
                if base_viej <= num < base_viej + OFFSET_SAFETY_RANGE:
                    return str(num + offset)
                return m.group(0)

            nuevo_nombre_base = re.sub(r"\d+", _repl_num, nombre_base)
            if cod_viej:
                nuevo_nombre_base = nuevo_nombre_base.replace(
                    cod_viej, cod_nuev
                )

            if nombre_base != nuevo_nombre_base:
                dicc_bloques[nombre_base] = nuevo_nombre_base

            for num_str in re.findall(r"\d+", nombre_base):
                num = int(num_str)
                if base_viej <= num < base_viej + OFFSET_SAFETY_RANGE:
                    numeros_usados.add(num)

    await asyncio.to_thread(_walk_and_build)

    # Variables exactas extraidas del XML.
    for var_vieja in variables_xml:
        num_viejo_str = var_vieja.split("_", 1)[0]
        if not num_viejo_str.isdigit():
            continue
        num_viejo = int(num_viejo_str)
        num_nuevo = num_viejo + offset
        var_nueva = var_vieja.replace(
            f"{num_viejo}_", f"{num_nuevo}_", 1
        )
        dicc_bloques[var_vieja] = var_nueva
        numeros_usados.add(num_viejo)

    # Metadatos internos TIA Portal: ``S7_BlockNumber := "50010"``.
    for num in numeros_usados:
        nuevo_num = num + offset
        dicc_bloques[
            f'S7_BlockNumber := "{num}"'
        ] = f'S7_BlockNumber := "{nuevo_num}"'
        dicc_xml[f"{num}_"] = f"{nuevo_num}_"

    # Prefijos de base completa (cubre ``50010_PRO_STD_xxx`` y similares).
    if nom_viej and nom_nuev:
        dicc_bloques[f"{base_viej}_{nom_viej}"] = (
            f"{base_nuev}_{nom_nuev}"
        )
        dicc_xml[f"{base_viej}_{nom_viej}"] = f"{base_nuev}_{nom_nuev}"
    dicc_bloques[str(base_viej)] = str(base_nuev)
    dicc_xml[str(base_viej)] = str(base_nuev)

    # Fallbacks: codigo y nombre (siempre; los bloques que solo cambian
    # de nombre/codigo sin tocar numeros siguen entrando aqui).
    if cod_viej:
        dicc_bloques[cod_viej] = cod_nuev
        dicc_xml[cod_viej] = cod_nuev
    if nom_viej and nom_nuev:
        dicc_bloques[nom_viej] = nom_nuev
        dicc_xml[nom_viej] = nom_nuev

    # Orden por longitud descendente: clave mas larga primero, para
    # que ``50010_PRO_STD_xxx`` se reemplace antes que ``50010``.
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


async def proc_process_detectar_colisiones(
    ctx: ProcProcessGenContext,
) -> None:
    """Cruza ``dicc_bloques`` contra el cache de bloques del PLC.

    Para cada ``val`` del diccionario que ya exista como bloque en el
    PLC (``plc_blocks_cache``), añade ``key`` a ``ctx.colisiones``.
    Asi el FB puede abortar antes de generar archivos que TIA no
    podra importar (UPDATE fail -> "object already exists").

    Si ``plc_blocks_cache`` es ``None`` (cache nunca populado), emite
    un warning unico en ``ctx.colisiones`` y devuelve sin abortar
    (el FB decide si abortar o seguir).
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

    colisiones_vistas: set[str] = set()
    for key, val in ctx.dicc_bloques.items():
        # Solo nos interesan las claves que parecen nombres de bloque
        # (empiezan por ``DB`` o ``FC`` o contienen ``_`` y son de
        # tamano razonable). Filtramos ``S7_BlockNumber`` y los
        # ``str(base)`` que NO son nombres de bloque pero aparecen en
        # ``dicc_bloques``.
        if key.startswith("S7_BlockNumber") or key.isdigit():
            continue
        if val in ctx.plc_blocks_cache and val not in colisiones_vistas:
            ctx.colisiones.append(key)
            colisiones_vistas.add(val)


async def proc_process_generar_previstos(
    ctx: ProcProcessGenContext,
) -> None:
    """Walk ``dir_preview`` y construye la lista de archivos que se
    generarian en ``dir_modified``.

    No escribe nada en disco — solo popula ``ctx.archivos_previstos``
    con ``[{rel_in, rel_out, kind, colisiona}, ...]`` para que la SPA
    muestre el preview al operario antes del apply.

    Layout canonico de salida: ``dir_modified/{variables,bloques}/``.
    El helper reorganiza los archivos en funcion de su extension
    (``kind="xml"`` -> ``variables/``, ``kind="text"`` -> ``bloques/``,
    resto -> ``otros/``). El nombre de cada archivo se obtiene
    aplicando ``dicc_bloques`` al nombre y a cada path-part del
    origen; la SPA ve el ``rel_out`` en este layout canonico.

    ``kind``:
      - ``"xml"`` para ``.xml`` (aplica ``dicc_xml`` en el apply).
      - ``"text"`` para el resto de ``EXTENSIONES_TEXTO`` (``.s7dcl``,
        ``.s7res``, ``.scl``, ``.awl`` — aplica ``dicc_bloques``).
      - ``"binary"`` para todo lo demas (se copia tal cual en el apply).

    ``colisiona`` se calcula intersectando ``ctx.colisiones`` con las
    claves que se aplicaron al ``rel_out``.
    """
    archivos_previstos: list[dict[str, Any]] = []

    def _walk() -> list[Path]:
        return [p for p in ctx.dir_preview.rglob("*") if p.is_file()]

    paths = await asyncio.to_thread(_walk)

    for in_path in paths:
        rel_in = in_path.relative_to(ctx.dir_preview)
        # Si es el manifest, lo recrea ``proc_process_escribir_manifest``
        # en el apply (no se transporta como archivo "previsto").
        if rel_in.name == "manifest.json":
            continue

        # Aplica ``dicc_bloques`` al nombre y a cada path-part.
        # El ``rel_out`` final se aplana a ``{variables|bloques|otros}/<file>``
        # para que el apply pueda hacer ``import_plc_tags_xml(dir_modified/"variables")``
        # o ``import_blocks_sd(dir_modified/"bloques")`` directamente.
        nuevo_stem = _aplicar_diccionario(
            in_path.stem, ctx.dicc_bloques
        )
        suffix = in_path.suffix.lower()
        if suffix == ".xml":
            kind = "xml"
            subdir = "variables"
        elif suffix in EXTENSIONES_TEXTO:
            kind = "text"
            subdir = "bloques"
        else:
            kind = "binary"
            subdir = "otros"

        rel_out = Path(subdir) / f"{nuevo_stem}{suffix}"

        # Deteccion de colision: si la clave nueva del archivo o el
        # ``nuevo_stem`` estan en ``ctx.colisiones``, marca como colision.
        colisiona = (
            nuevo_stem in ctx.colisiones
            or f"{nuevo_stem}{suffix}" in ctx.colisiones
        )

        archivos_previstos.append({
            "rel_in": str(rel_in),
            "rel_out": str(rel_out),
            "kind": kind,
            "colisiona": colisiona,
        })

    ctx.archivos_previstos = archivos_previstos


async def proc_process_aplicar_clonacion(
    ctx: ProcProcessGenContext,
) -> None:
    """Aplica la clonacion: walk ``dir_preview`` -> ``dir_modified``.

    Layout canonico de salida: ``dir_modified/{variables,bloques,otros}/``.
    Los archivos se reorganizan en funcion de su extension:
      - ``.xml``  -> ``variables/`` (TAG tables, importa con
        ``import_plc_tags_xml``).
      - ``.s7dcl/.s7res/.scl/.awl`` -> ``bloques/`` (program blocks,
        importa con ``import_blocks_sd``).
      - resto -> ``otros/`` (se copia tal cual, no se importa a TIA).

    Por extension:
      - ``.s7res``: encoding utf-8-sig (BOM), ``dicc_bloques``.
      - ``.s7dcl`` / ``.scl`` / ``.xml`` / ``.awl``: encoding utf-8
        puro (NO ``utf-8-sig``). ``.xml`` usa ``dicc_xml`` (prefijos
        numericos) y el resto usa ``dicc_bloques``. ``newline=''``
        para preservar ``\r\n``.
      - Otros: ``shutil.copy2`` en binario.

    Para los ``.xml`` del proceso (los de la tabla de variables)
    ademas reemplaza los ``<Value>`` de los 4 N_MAX del manifest de
    plantilla por los del operario (``ctx.minimos_usuario``).

    ``manifest.json`` se ignora en el walk (lo regenera
    ``proc_process_escribir_manifest`` justo despues).
    """
    ctx.dir_modified.mkdir(parents=True, exist_ok=True)
    minimos_plantilla = (
        ctx.manifest_plantilla.get("minimos", {}) if ctx.manifest_plantilla else {}
    )

    def _walk() -> list[Path]:
        return [p for p in ctx.dir_preview.rglob("*") if p.is_file()]

    paths = await asyncio.to_thread(_walk)
    generados: list[str] = []

    for in_path in paths:
        rel_in = in_path.relative_to(ctx.dir_preview)
        if rel_in.name == "manifest.json":
            continue

        suffix = in_path.suffix.lower()
        nuevo_stem = _aplicar_diccionario(
            in_path.stem, ctx.dicc_bloques
        )

        if suffix == ".xml":
            subdir = "variables"
        elif suffix in EXTENSIONES_TEXTO:
            subdir = "bloques"
        else:
            subdir = "otros"

        out_path = ctx.dir_modified / subdir / f"{nuevo_stem}{suffix}"
        out_path.parent.mkdir(parents=True, exist_ok=True)

        if suffix == ".s7res":
            enc = "utf-8-sig"
            contenido = _leer_texto(in_path, enc)
            nuevo = _aplicar_diccionario(contenido, ctx.dicc_bloques)
            _escribir_texto(out_path, nuevo, enc)
        elif suffix == ".xml":
            enc = "utf-8"
            contenido = _leer_texto(in_path, enc)
            # Primero aplica ``dicc_xml`` (prefijos numericos).
            nuevo = _aplicar_diccionario(contenido, ctx.dicc_xml)
            # Despues reemplaza los ``<Value>`` de los N_MAX por los
            # del operario si este XML contiene constantes de usuario.
            if "PlcUserConstant" in nuevo and minimos_plantilla:
                nuevo = _reemplazar_nmax_en_xml(
                    nuevo, ctx.base_nueva, ctx.minimos_usuario
                )
            _escribir_texto(out_path, nuevo, enc)
        elif suffix in (".s7dcl", ".scl", ".awl"):
            enc = "utf-8"
            contenido = _leer_texto(in_path, enc)
            nuevo = _aplicar_diccionario(contenido, ctx.dicc_bloques)
            _escribir_texto(out_path, nuevo, enc)
        else:
            await asyncio.to_thread(shutil.copy2, in_path, out_path)

        generados.append(str(out_path.relative_to(ctx.dir_modified)))

    ctx.archivos_generados = generados


async def proc_process_escribir_manifest(
    ctx: ProcProcessGenContext,
) -> None:
    """Escribe ``<dir_modified>/manifest.json`` con los datos del
    proceso nuevo.

    Encoding utf-8 puro, ``indent=2`` (legible por el operario si
    abre el archivo a mano). NO incluye ``requireiments.txt`` ni
    archivos auxiliares: solo el manifest canonico con
    ``base``/``codigo``/``nombre``/``minimos``.
    """
    ctx.dir_modified.mkdir(parents=True, exist_ok=True)
    manifest_path = ctx.dir_modified / "manifest.json"
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


async def proc_process_done_summary(
    ctx: ProcProcessGenContext,
) -> dict[str, Any]:
    """Compone ``ctx.result`` con la shape que el FB vuelca a
    ``self.result``.

    Diferencia preview vs apply:
      - preview (``archivos_previstos`` poblado) -> vuelca la lista de
        previstos + el ``preview_dir``.
      - apply (``archivos_generados`` poblado) -> vuelca la lista de
        generados + el ``modified_dir``.

    ``success=True`` solo si no hubo colisiones. Si las hubo,
    ``success=False`` y ``colisiones`` queda como lista para que la
    SPA muestre los bloques que ya existen en el PLC.
    """
    if ctx.archivos_generados:
        dir_salida = ctx.dir_modified
        archivos = list(ctx.archivos_generados)
        campo_archivos = "archivos_generados"
    else:
        dir_salida = ctx.dir_preview
        archivos = list(ctx.archivos_previstos)
        campo_archivos = "archivos_previstos"

    success = len(ctx.colisiones) == 0
    ctx.result = {
        "manifest_plantilla": ctx.manifest_plantilla,
        campo_archivos: archivos,
        "colisiones": list(ctx.colisiones),
        "preview_dir" if campo_archivos == "archivos_previstos"
            else "modified_dir": str(dir_salida),
        "success": success,
    }
    return ctx.result


# ===========================================================================
# Helpers internos (sync, solo se envuelven en ``asyncio.to_thread``)
# ===========================================================================

def _aplicar_diccionario(texto: str, dicc: dict[str, str]) -> str:
    """Aplica los reemplazos en cascada — el caller garantiza el orden
    descendente por ``len(key)`` para que los mas especificos ganen."""
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
    """Escribe texto preservando retornos de carro (``newline=''``)."""
    with open(path, "w", encoding=encoding, newline="") as f:
        f.write(contenido)


def _reemplazar_nmax_en_xml(
    contenido: str,
    base_nueva: int,
    minimos_usuario: dict[str, int],
) -> str:
    """Sustituye los <Value> de las constantes N_MAX de forma segura vinculándolos a su <Name>."""
    for key in N_MAX_KEYS:
        val_usuario = minimos_usuario.get(key)
        if val_usuario is None:
            continue
        
        # Busca la constante exacta (ej: <Name>60010_N_MAX_PINT</Name>) y captura su <Value>
        # re.DOTALL permite que haya saltos de línea y otras etiquetas entre Name y Value
        patron = rf"(<Name>{base_nueva}_{key}</Name>.*?<Value>)(\d+)(</Value>)"
        
        contenido = re.sub(
            patron,
            lambda m: f"{m.group(1)}{val_usuario}{m.group(3)}",
            contenido,
            flags=re.DOTALL
        )
        
    return contenido


__all__ = [
    "EXTENSIONES_TEXTO",
    "ManifestInvalido",
    "N_MAX_KEYS",
    "OFFSET_SAFETY_RANGE",
    "PATRON_XML_VARIABLE",
    "PATRON_XML_VALUE",
    "PlantillaMinimosNoCumplidos",
    "ProcProcessGenContext",
    "proc_process_aplicar_clonacion",
    "proc_process_construir_diccionarios",
    "proc_process_copiar_a_preview",
    "proc_process_detectar_colisiones",
    "proc_process_done_summary",
    "proc_process_escribir_manifest",
    "proc_process_extraer_variables_xml",
    "proc_process_generar_previstos",
    "proc_process_leer_manifest",
    "proc_process_validar_minimos",
]