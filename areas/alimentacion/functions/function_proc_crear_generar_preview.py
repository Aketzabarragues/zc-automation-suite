"""FB de area: preview (read-only) de generar un proceso desde plantilla.

State machine sobre el contexto ``ProcProcessGenContext`` (definido al
final de este archivo). Los 7 stages viven como metodos del FB (mutando
``self._ctx``); las funciones puras del pipeline
(``proc_process_leer_manifest``,
``proc_process_validar_minimos``, ...) viven debajo del dataclass en
el mismo archivo.

El orquestador y la dataclass permanecen en el archivo del FB; los
helpers puros (filesystem puro, sin TIA) se exponen como funciones
module-level debajo del dataclass para que los tests las importen
directamente sin ciclo.

Hereda directo de ``FunctionBase``.

Runtime params via ``start(**kwargs)``:
  - ``plantillas_path`` (str): ruta base donde viven las subcarpetas de
    plantillas TIA. Obligatorio.
  - ``dir_plantilla_nombre`` (str): nombre de la subcarpeta de la
    plantilla concreta. Obligatorio.
  - ``base_nueva`` (int): UID base del proceso nuevo (p. ej. 60010).
    Obligatorio.
  - ``codigo_nuevo`` (str): codigo corto del proceso (p. ej. "EXP").
    Obligatorio.
  - ``nombre_nuevo`` (str): nombre humano del proceso. Obligatorio.
  - ``minimos_usuario`` (dict[str, int]): 4 N_MAX del operario (claves:
    ``N_MAX_PREAL``, ``N_MAX_PINT``, ``N_MAX_ALM``, ``N_MAX_ALM_HMI``).
    Obligatorio.
  - ``plc_blocks_cache`` (list[dict] | None): bloques que ya existen
    en el PLC destino. Cada item es ``{"nombre": str, "numero": int}``.
    Si es None, el FB sigue (warning). Set[str] legacy
    se acepta y se convierte defensivamente a ``[{"nombre": s}]``.
  - ``build_cache_root`` (Path): raiz del BuildCache del area. Si es
    None, usa ``DEFAULT_BUILD_CACHE_ROOT``.

El ``self.result`` se popula con la shape esperada por la SPA::

    {
      "manifest_plantilla": dict | None,
      "archivos_previstos": list[dict],
      "colisiones":         list[str],
      "plantilla_copia_dir": str,
      "success":            bool,
    }

Steps (7):
  - Leer manifiesto         -> proc_process_leer_manifest (inline)
  - Validar mínimos         -> proc_process_validar_minimos (inline)
  - Copiar a vista previa   -> proc_process_copiar_a_preview (inline)
  - Construir diccionarios  -> proc_process_construir_diccionarios (inline)
  - Detectar colisiones     -> proc_process_detectar_colisiones (inline)
  - Generar previstos       -> proc_process_generar_previstos (inline)
  - Componer respuesta      -> proc_process_done_summary (inline)
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

from core.composition.plc_function_base import FunctionBase
from areas.alimentacion.helpers.layout.build_cache import DEFAULT_BUILD_CACHE_ROOT

logger = logging.getLogger(__name__)


# ============================================================================
# Constantes y errores del pipeline (compartidos con apply F22-2).
# ============================================================================

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


@dataclass
class ProcProcessGenContext:
    """Estado compartido entre los 7 stages del FB preview.

    Cada stage del FB muta uno o varios campos con el resultado de su
    trabajo. Los stages posteriores leen los resultados de los
    anteriores.

    El FB ``FunctionProcCrearGenerarPreview`` instancia uno y lo reusa
    entre sus 7 ticks para que los resultados intermedios esten
    disponibles para los stages posteriores.
    """

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
    # ``None`` = cache nunca populado (el FB emite warning).
    plc_blocks_cache: list[dict[str, Any]] | None
    minimos_usuario: dict[str, int]

    # ── Resultado de leer_manifest ──
    manifest_plantilla: dict[str, Any] | None = None
    base_vieja: int = 0
    codigo_viejo: str = ""
    nombre_viejo: str = ""

    # ── Resultado de construir_diccionarios ──
    dicc_bloques: dict[str, str] = field(default_factory=dict)
    dicc_xml: dict[str, str] = field(default_factory=dict)

    # ── Resultado de detectar_colisiones ──
    colisiones: list[str] = field(default_factory=list)
    # Mapa ``nombre_nuevo -> identificador del bloque PLC que
    # colisiona``. La SPA lee este campo para pintar
    # ``DUPLICADO - <identificador>`` en la celda ESTADO.
    colisiones_con: dict[str, str] = field(default_factory=dict)

    # ── Resultado de generar_previstos / aplicar ──
    archivos_previstos: list[dict[str, Any]] = field(default_factory=list)
    archivos_generados: list[str] = field(default_factory=list)

    # ── Resultado final (vuelco a ``self.result``) ──
    result: dict[str, Any] = field(default_factory=dict)


class FunctionProcCrearGenerarPreview(FunctionBase):
    """FB que genera un preview (read-only) de la clonacion de un
    proceso desde una plantilla TIA."""

    # ==================================================================
    # CONFIGURACION ESTATICA DEL FB
    # ==================================================================

    # El preview solo toca disco local (copytree + regex). En PLCs
    # grandes con muchas plantillas puede tardar ~30s. 120s cubre
    # holgadamente el peor caso esperado.
    STEP_TIMEOUT_S: float = 120.0

    # Tabla declarativa de stages. Cada tupla: (idx, "nombre_step",
    # "atributo_metodo_en_el_FB"). El ``run_step`` dispatcha contra
    # esta tabla en vez de un ``match``/``case`` inline.
    #
    # Convencion:
    #   - ``idx`` correlativo, 1-based.
    #   - ``nombre_step`` debe coincidir con ``self.steps[idx]["nombre"]``
    #     (registrado en __init__). Si cambias uno, cambia el otro.
    #   - ``atributo_metodo`` es un metodo del FB (no externo): un cambio
    #     de signatura requiere actualizar este registro.
    STAGES: list[tuple[int, str, str]] = [
        (1, "Leer manifiesto",          "_stage_1_leer_manifest"),
        (2, "Validar mínimos",          "_stage_2_validar_minimos"),
        (3, "Copiar a vista previa",    "_stage_3_copiar_a_preview"),
        (4, "Construir diccionarios",   "_stage_4_construir_diccionarios"),
        (5, "Detectar colisiones",      "_stage_5_detectar_colisiones"),
        (6, "Generar previstos",        "_stage_6_generar_previstos"),
        (7, "Componer respuesta",       "_stage_7_build_response"),
    ]

    # ==================================================================
    # CONSTRUCTOR
    # ==================================================================

    def __init__(
        self,
        nombre: str = "proc_process_crear_preview",
        titulo: str = "Preview: crear proceso desde plantilla",
        steps: list[dict[str, Any]] | None = None,
        tracker: Any = None,
        # ── ZONA 0: deps comunes ──
        # El preview NO toca TIA: ``tia_client`` puede ser None. Se
        # mantiene la firma alineada con el resto de FBs para que el
        # ``register()`` del area sea homogeneo.
        config_manager: Any = None,
        tia_client: Any = None,
        build_cache: Any = None,
    ) -> None:
        super().__init__(
            nombre=nombre,
            titulo=titulo,
            steps=steps if steps is not None else [
                {"nombre": "Leer manifiesto"},
                {"nombre": "Validar mínimos"},
                {"nombre": "Copiar a vista previa"},
                {"nombre": "Construir diccionarios"},
                {"nombre": "Detectar colisiones"},
                {"nombre": "Generar previstos"},
                {"nombre": "Componer respuesta"},
            ],
            tracker=tracker,
        )
        # ZONA 0: deps inyectadas. ``config_manager`` y ``tia_client``
        # NO son obligatorios para este FB; se mantienen en la firma
        # por homogeneidad pero no se usan.
        self._config = config_manager
        self._tia_client = tia_client
        self._build_cache_root: Path = build_cache or DEFAULT_BUILD_CACHE_ROOT
        # ZONA 3: estado entre ticks.
        self._plantillas_path: str = ""
        self._dir_plantilla_nombre: str = ""
        self._base_nueva: int = 0
        self._codigo_nuevo: str = ""
        self._nombre_nuevo: str = ""
        self._minimos_usuario: dict[str, int] = {}
        self._plc_blocks_cache: list[dict[str, Any]] | None = None
        # ProcProcessGenContext compartido entre los 7 ticks. Se
        # reinicializa en cada on_start() para no arrastrar estado del
        # run anterior (el FB es re-arrancable).
        self._ctx: ProcProcessGenContext | None = None

    # ==================================================================
    # HOOK 1: on_start  (ZONA 3: validar params + crear ctx)
    # ==================================================================

    def on_start(self, **params: Any) -> None:
        """Validar params + construir ``ProcProcessGenContext``.

        Todos los params son obligatorios. ``plc_blocks_cache`` puede
        ser None (cache nunca populado) — el helper emite warning y el
        preview sigue (``colisiones`` queda con un mensaje accionable).
        """
        plantillas_path = params.get("plantillas_path", "")
        if not plantillas_path:
            raise ValueError(
                "FunctionProcCrearGenerarPreview.start(plantillas_path=...) "
                "es obligatorio"
            )
        dir_plantilla_nombre = params.get("dir_plantilla_nombre", "")
        if not dir_plantilla_nombre:
            raise ValueError(
                "FunctionProcCrearGenerarPreview.start("
                "dir_plantilla_nombre=...) es obligatorio"
            )
        base_nueva = params.get("base_nueva")
        if base_nueva is None or not isinstance(base_nueva, int):
            raise ValueError(
                "FunctionProcCrearGenerarPreview.start(base_nueva=int) "
                "es obligatorio"
            )
        codigo_nuevo = params.get("codigo_nuevo", "")
        if not codigo_nuevo:
            raise ValueError(
                "FunctionProcCrearGenerarPreview.start(codigo_nuevo=...) "
                "es obligatorio"
            )
        nombre_nuevo = params.get("nombre_nuevo", "")
        if not nombre_nuevo:
            raise ValueError(
                "FunctionProcCrearGenerarPreview.start(nombre_nuevo=...) "
                "es obligatorio"
            )
        minimos_usuario = params.get("minimos_usuario", {})
        if not isinstance(minimos_usuario, dict) or not minimos_usuario:
            raise ValueError(
                "FunctionProcCrearGenerarPreview.start(minimos_usuario=dict) "
                "es obligatorio (N_MAX_PREAL/PINT/ALM/ALM_HMI)"
            )
        plc_blocks_cache = params.get("plc_blocks_cache")
        build_cache_root = params.get(
            "build_cache_root", self._build_cache_root
        )

        self._plantillas_path = str(plantillas_path)
        self._dir_plantilla_nombre = str(dir_plantilla_nombre)
        self._base_nueva = int(base_nueva)
        self._codigo_nuevo = str(codigo_nuevo)
        self._nombre_nuevo = str(nombre_nuevo)
        self._minimos_usuario = dict(minimos_usuario)
        # ``plc_blocks_cache``: shape preferida ``list[dict{nombre,
        # numero}]``. Defensivo: aceptar ``set[str]`` / ``list[str]``
        # legacy convirtiendolo a ``[{"nombre": s, "numero": None}]``
        # para que el helper encuentre matches por nombre.
        self._plc_blocks_cache = (
            _coerce_plc_blocks_cache(plc_blocks_cache)
            if plc_blocks_cache is not None else None
        )
        dir_plantilla = Path(self._plantillas_path) / self._dir_plantilla_nombre
        if not dir_plantilla.exists():
            raise ValueError(
                f"No de la plantilla: {dir_plantilla}. "
                f"Verifica plantillas_path y dir_plantilla_nombre."
            )

        dir_plantilla_copia = (
            Path(build_cache_root) / "alimentacion" / "ProcesoNuevo" / "Plantilla"
        )
        dir_nuevo = (
            Path(build_cache_root) / "alimentacion" / "ProcesoNuevo" / "Nuevo"
        )

        # ``ProcProcessGenContext`` vive en este mismo archivo (debajo
        # de la clase); acceso directo, sin import.
        self._ctx = ProcProcessGenContext(
            dir_plantilla=dir_plantilla,
            dir_plantilla_copia=dir_plantilla_copia,
            dir_nuevo=dir_nuevo,
            base_nueva=self._base_nueva,
            codigo_nuevo=self._codigo_nuevo,
            nombre_nuevo=self._nombre_nuevo,
            plc_blocks_cache=self._plc_blocks_cache,
            minimos_usuario=self._minimos_usuario,
        )

        logger.debug(
            f"[{self.nombre}] Preview crear proceso "
            f"{self._base_nueva}/{self._codigo_nuevo} desde "
            f"{dir_plantilla}"
        )

    # ==================================================================
    # HOOK 2: run_step  (ZONA 4: state machine -> dispatch al stage)
    # ==================================================================

    async def run_step(self, idx: int, **params: Any) -> str:
        """Dispatch del FB step ``idx`` al metodo ``_stage_N_*``.

        Cada handler vive como metodo del FB (no externo); muta
        ``self._ctx`` directamente. Ver tabla ``STAGES`` arriba.
        """
        if self._ctx is None:
            raise RuntimeError(
                "ProcProcessGenContext no inicializado. on_start() no se "
                "ejecuto (params invalidos o ausentes)."
            )

        step_nombre = self.steps[idx]["nombre"]
        for _s_idx, s_nombre, s_attr in self.STAGES:
            if s_nombre == step_nombre:
                handler = getattr(self, s_attr)
                await handler()
                return _step_summary(self._ctx, s_nombre)
        raise ValueError(
            f"step {idx} ({step_nombre!r}) no esta en STAGES "
            f"de FunctionProcCrearGenerarPreview"
        )

    # ==================================================================
    # HOOK 3: on_finish  (ZONA 5: vuelco del result desde el ctx)
    # ==================================================================

    def on_finish(self, **params: Any) -> None:
        """Vuelca ``self.result`` con la shape que la SPA consume."""
        if self._ctx is None:
            self.result = {
                "success": False,
                "archivos_previstos": [],
                "colisiones": [
                    "ProcProcessGenContext no inicializado. "
                    "Verifica los parametros del start()."
                ],
                "plantilla_copia_dir": "",
                "manifest_plantilla": None,
            }
            return

        self.result = self._ctx.result

        n_previstos = len(self._ctx.result.get("archivos_previstos", []))
        n_colisiones = len(self._ctx.result.get("colisiones", []))
        logger.debug(
            f"[{self.nombre}] Preview crear proceso "
            f"{self._base_nueva}/{self._codigo_nuevo}: "
            f"{n_previstos} archivos previstos, "
            f"{n_colisiones} colision(es)."
        )

    # ==================================================================
    # Stages del FB (ZONA 4: 7 metodos privados numerados).
    #
    # Cada ``_stage_N_<nombre>`` corresponde a UNA entrada de la tabla
    # ``STAGES`` arriba. Si cambias el flujo del stage, cambia la
    # tabla tambien. Aqui el stage hace el trabajo inline llamando a
    # la funcion pura correspondiente (definida mas abajo) sobre
    # ``self._ctx``.
    # ==================================================================

    async def _stage_1_leer_manifest(self) -> None:
        """Stage 1: lee el ``manifest.json`` de la plantilla TIA."""
        await proc_process_leer_manifest(self._ctx)

    async def _stage_2_validar_minimos(self) -> None:
        """Stage 2: valida los N_MIN del operario contra la plantilla.

        Si falla, lanza ``PlantillaMinimosNoCumplidos`` y el base va
        a ``n_error`` con ``error_stage``.
        """
        await proc_process_validar_minimos(self._ctx)

    async def _stage_3_copiar_a_preview(self) -> None:
        """Stage 3: copytree de la plantilla al workdir de preview."""
        await proc_process_copiar_a_preview(self._ctx)

    async def _stage_4_construir_diccionarios(self) -> None:
        """Stage 4: parsea bloques + XMLs y construye los diccionarios base."""
        await proc_process_construir_diccionarios(self._ctx)

    async def _stage_5_detectar_colisiones(self) -> None:
        """Stage 5: detecta UIDs/colisiones contra el ``plc_blocks_cache``."""
        await proc_process_detectar_colisiones(self._ctx)

    async def _stage_6_generar_previstos(self) -> None:
        """Stage 6: aplica las reglas y genera ``archivos_previstos``."""
        await proc_process_generar_previstos(self._ctx)

    async def _stage_7_build_response(self) -> None:
        """Stage 7: compone ``ctx.result`` con la shape final del preview."""
        await proc_process_done_summary(self._ctx)


# ============================================================================
# Codigo absorbido de helpers/proc/proc_crear_process_generator.py
# (commit F22-1, sept-2026). Antes era un orquestador separado que el FB
# llamaba via ``match step_nombre``. Ahora los 7 stages viven como
# metodos del FB (mutando ``self._ctx``); las funciones puras del pipeline
# (filesystem puro, sin tocar TIA) viven aqui mismo, debajo del
# dataclass. Los tests pueden importarlas directamente desde este modulo.
# ============================================================================


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
    cada preview parte limpio). Re-arrancable sin intervencion manual
    del operario.
    """
    if ctx.dir_plantilla_copia.exists():
        await asyncio.to_thread(shutil.rmtree, ctx.dir_plantilla_copia)
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
        Renombra SOLO los prefijos canonicos TIA (FC/FB/DB).
      - Variables y carpetas: 3 reglas explicitas por base
        (``base``, ``base + 3000`` = Params, ``base + 5000`` = Alarmas).
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

    bases_viejas = [base_viej, base_viej + 3000, base_viej + 5000]
    bases_nuevas = [base_nuev, base_nuev + 3000, base_nuev + 5000]
    for b_vieja, b_nueva in zip(bases_viejas, bases_nuevas):
        regla_vieja = f"{b_vieja}_"
        regla_nueva = f"{b_nueva}_"
        dicc_xml[regla_vieja] = regla_nueva
        dicc_bloques[regla_vieja] = regla_nueva

    for num in numeros_usados:
        nuevo_num = num - base_viej + base_nuev
        dicc_bloques[f'S7_BlockNumber := "{num}"'] = (
            f'S7_BlockNumber := "{nuevo_num}"'
        )

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
    identificador del bloque del PLC que produjo la colision.

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

    plc_entries: list[dict[str, Any]] = []
    for item in ctx.plc_blocks_cache:
        if isinstance(item, dict):
            plc_entries.append(item)
        elif isinstance(item, str):
            plc_entries.append({"nombre": item, "numero": None})

    plc_nombres: set[str] = set()
    plc_tipo_numero: set[tuple[str, int]] = set()
    id_por_nombre: dict[str, str] = {}
    id_por_tipo_numero: dict[tuple[str, int], str] = {}
    patron_prefijo_num = re.compile(r"^([A-Za-z]+)(\d+)")
    for blk in plc_entries:
        nombre_raw = blk.get("nombre")
        nombre = str(nombre_raw) if nombre_raw else ""
        numero_raw = blk.get("numero")
        if isinstance(numero_raw, bool):
            continue
        if isinstance(numero_raw, int):
            numero: int | None = numero_raw
        elif isinstance(numero_raw, str) and numero_raw.isdigit():
            numero = int(numero_raw)
        else:
            numero = None
        ident = nombre if nombre else (str(numero) if numero is not None else "")
        if not ident:
            continue
        if nombre and nombre not in plc_nombres:
            plc_nombres.add(nombre)
            id_por_nombre[nombre] = ident
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
    for key, val in ctx.dicc_bloques.items():
        if (
            key.startswith("S7_BlockNumber")
            or key.isdigit()
            or key.endswith("_")
        ):
            continue
        if val in colisiones_vistas:
            continue
        if val in plc_nombres:
            ctx.colisiones.append(val)
            ctx.colisiones_con[val] = id_por_nombre[val]
            colisiones_vistas.add(val)
            continue
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
    aplicando ``dicc_bloques``).
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

        rel_out = rel_in.parent / f"{nuevo_stem}{suffix}"

        colisiona_nombre = nuevo_stem in ctx.colisiones
        colisiona_con_sufijo = f"{nuevo_stem}{suffix}" in ctx.colisiones
        colisiona = colisiona_nombre or colisiona_con_sufijo

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


# ============================================================================
# Helpers internos (sync, compartidos con apply).
# ============================================================================


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


def _step_summary(ctx: ProcProcessGenContext, step_nombre: str) -> str:
    """Resumen legible del step que acaba de correr (aparece en la SPA)."""
    if step_nombre == "leer_manifest":
        if ctx.manifest_plantilla is None:
            return f"{step_nombre}: sin manifest"
        return (
            f"{step_nombre}: base={ctx.base_vieja} "
            f"codigo={ctx.codigo_viejo}"
        )
    if step_nombre == "validar_minimos":
        return f"{step_nombre}: N_MAX OK"
    if step_nombre == "copiar_a_preview":
        return f"{step_nombre}: plantilla copiada a {ctx.dir_plantilla_copia}"
    if step_nombre == "construir_diccionarios":
        return (
            f"{step_nombre}: "
            f"{len(ctx.dicc_bloques)} reglas bloques + "
            f"{len(ctx.dicc_xml)} reglas XML"
        )
    if step_nombre == "detectar_colisiones":
        return f"{step_nombre}: {len(ctx.colisiones)} colision(es)"
    if step_nombre == "generar_previstos":
        return f"{step_nombre}: {len(ctx.archivos_previstos)} archivos"
    if step_nombre == "Componer respuesta":
        return f"{step_nombre}: preview compuesto"
    return f"{step_nombre}: OK"


def _coerce_plc_blocks_cache(raw: Any) -> list[dict[str, Any]]:
    """Normaliza ``plc_blocks_cache`` a ``list[dict{nombre, numero}]``.

    Acepta las 3 shapes que pueden llegar al FB:
      - ``list[dict]`` (shape preferida; el dict tiene al menos
        ``nombre`` y opcionalmente ``numero``).
      - ``list[str]`` / ``set[str]`` (legacy: solo nombres). Se
        convierte a ``[{"nombre": s, "numero": None}]``.

    Items invalidos (None, tipos raros) se descartan silenciosamente.
    """
    out: list[dict[str, Any]] = []
    if isinstance(raw, (list, tuple, set, frozenset)):
        for item in raw:
            if isinstance(item, dict):
                # Aceptar tanto "nombre" como "name" (compat scanner).
                nombre = item.get("nombre") or item.get("name") or ""
                numero = item.get("numero")
                out.append({"nombre": str(nombre), "numero": numero})
            elif isinstance(item, str) and item:
                out.append({"nombre": item, "numero": None})
    elif isinstance(raw, str) and raw:
        out.append({"nombre": raw, "numero": None})
    return out


__all__ = [
    "EXTENSIONES_TEXTO",
    "ManifestInvalido",
    "N_MAX_KEYS",
    "PlantillaMinimosNoCumplidos",
    "ProcProcessGenContext",
    "FunctionProcCrearGenerarPreview",
    "_coerce_plc_blocks_cache",
    "_step_summary",
    # Funciones puras absorbidas (F22-1). Re-exportadas para que los
    # tests las importen directamente desde este modulo sin pasar por
    # el helper.
    "proc_process_leer_manifest",
    "proc_process_validar_minimos",
    "proc_process_copiar_a_preview",
    "proc_process_construir_diccionarios",
    "proc_process_detectar_colisiones",
    "proc_process_generar_previstos",
    "proc_process_done_summary",
    # Helpers internos (puros).
    "_aplicar_diccionario",
    "_leer_texto",
    "_escribir_texto",
]
