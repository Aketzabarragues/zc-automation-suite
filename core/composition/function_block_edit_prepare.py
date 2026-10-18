"""FB core: preparar los 10 campos extendidos del DTO ``DataBloquePLC``.

Operacion READ-ONLY. Para cada path seleccionado:

  1. Resuelve el bloque en TIA via ``_find_block_in_plc``.
  2. Lee las 5 props extendidas via ``get_property(name=...)``
     (``HeaderName`` / ``HeaderAuthor`` / ``HeaderVersion`` /
     ``ProgrammingLanguage`` / ``MemoryLayout``) y la prop ``Number``.
  3. Exporta el bloque a ``.s7dcl`` en un tempdir (via dispatch del
     comando OT ``export_block``).
  4. Parsea el header SCL del ``.s7dcl`` para extraer ``S7_BlockTitle``
     y ``S7_BlockComment`` (NO expuestos por ``get_property``).
  5. Cruza las 2 fuentes en un ``DataBloquePLC`` de 10 campos y lo
     guarda en ``app_cache.block_edit_prepared[plc_name][block_path]``.

El tempdir se elimina en ``on_finish`` (best-effort). No hay
transaccion: si TIA falla en cualquier punto del lote, los bloques
ya preparados siguen en ``app_cache`` (la SPA los muestra aunque el
batch no haya completado).

Runtime params via ``start(**kwargs)``:

  - ``plc_name`` (str): nombre del PLC. Obligatorio.
  - ``selected_block_paths`` (list[str]): rutas TIA tipo
    ``"2000_Dispositivos/DB2000_ED"`` (separador ``"/"``). El ultimo
    segmento es el nombre del bloque; el resto es la jerarquia de
    grupos. Obligatorio (no vacio).

``self.result`` se popula con la shape::

    {
        "ok": bool,
        "plc_name": str,
        "n_blocks": int,
        "n_with_title": int,
        "n_with_comment": int,
    }
"""
from __future__ import annotations

import logging
import shutil
import tempfile
from pathlib import Path
from typing import Any

from core.composition.plc_function_base import FunctionBase
from core.data.data_block_plc import DataBloquePLC
from core.runtime.app_cache import AppCache, get_app_cache

logger = logging.getLogger(__name__)


class FunctionBlockEditPrepare(FunctionBase):
    """FB core: preparar los 10 campos extendidos del DTO de bloques."""

    # Cada export ``export_block`` puede tardar ~5-10s en cold-start.
    # Holgura generosa para un lote de N bloques.
    STEP_TIMEOUT_S: float = 60.0

    def __init__(
        self,
        nombre: str = "block_edit_prepare",
        titulo: str = "Preparar datos de edicion de bloques TIA",
        steps: list[dict[str, Any]] | None = None,
        tracker: Any = None,
        # ── ZONA 0: deps comunes ──
        config_manager: Any = None,
        tia_client: Any = None,
        build_cache: Any = None,
        # ── Deps especificas de este FB ──
        app_cache: AppCache | None = None,
    ) -> None:
        super().__init__(
            nombre=nombre,
            titulo=titulo,
            steps=steps if steps is not None else [
                {"nombre": "validar"},
                {"nombre": "leer_tia"},
                {"nombre": "exportar_sd"},
                {"nombre": "parsear_scl"},
                {"nombre": "merge_cache"},
            ],
            tracker=tracker,
        )
        # ZONA 0: deps inyectadas.
        self._config = config_manager  # No usado en este FB.
        self._tia_client = tia_client
        self._build_cache = build_cache  # No usado en este FB.
        # Deps especificas.
        self._app_cache: AppCache = (
            app_cache if app_cache is not None else get_app_cache()
        )
        # ZONA 3: estado entre ticks.
        self._plc_name: str = ""
        self._selected_block_paths: list[str] = []
        self._blocks_data: list[dict[str, Any]] = []
        self._prepared_dir: Path | None = None

    # ==================================================================
    # HOOK 1: on_start  (ZONA 3: validar params)
    # ==================================================================

    def on_start(self, **params: Any) -> None:
        """Pre-flight: capturar y validar ``plc_name`` y ``selected_block_paths``."""
        plc_name = params.get("plc_name")
        if not plc_name:
            raise ValueError(
                "FunctionBlockEditPrepare.start(plc_name=...) es obligatorio"
            )
        selected_block_paths = params.get("selected_block_paths") or []
        if not selected_block_paths:
            raise ValueError(
                "FunctionBlockEditPrepare.start(selected_block_paths=...) "
                "debe ser una lista no vacia"
            )
        self._plc_name = str(plc_name)
        self._selected_block_paths = [
            str(p) for p in selected_block_paths
        ]
        logger.debug(
            f"[{self.nombre}] Iniciando preparacion de "
            f"{len(self._selected_block_paths)} bloques en '{self._plc_name}'"
        )

    # ==================================================================
    # HOOK 2: run_step  (ZONA 4: CASE por etapa)
    # ==================================================================

    async def run_step(self, idx: int, **params: Any) -> str:
        """CASE de los 5 pasos."""
        # Lazy imports para evitar ciclos con core.infrastructure.tia.
        from core.infrastructure.tia.tia_helpers import (
            _find_plc,
            _get_active_project,
            parse_extended_props_from_sd,
        )

        if self._tia_client is None:
            raise RuntimeError(
                "FunctionBlockEditPrepare requiere tia_client explicito. "
                "Inyectalo en el constructor al registrar el FB."
            )
        if self._tia_client.wrapper is None:
            raise RuntimeError(
                "FunctionBlockEditPrepare requiere tia_client con portal "
                "attached. Llama a attach_portal antes de ejecutar el FB."
            )

        step_nombre = self.steps[idx]["nombre"]
        match step_nombre:
            case "validar":
                # Validacion ya en on_start (fuerza fail-fast antes de
                # tocar TIA). Aqui solo retornamos un detalle.
                return (
                    f"seleccion valida: {len(self._selected_block_paths)} "
                    f"bloques en PLC '{self._plc_name}'"
                )

            case "leer_tia":
                portal = self._tia_client.wrapper
                project = _get_active_project(portal)
                plc = _find_plc(project, self._plc_name)

                read_count = 0
                for path in self._selected_block_paths:
                    entry = self._read_one_block(path, plc)
                    if entry is not None:
                        # ``tipo`` se deriva del nombre (prefijo DB/FB/
                        # FC/OB/UDT) via ``DataBloquePLC.detect_tipo``.
                        # Evita guardar referencias .NET en ``entry``.
                        entry["tipo"] = classify_block_for_entry(entry)
                        self._blocks_data.append(entry)
                        read_count += 1

                return f"leidos {read_count} bloques via get_property"

            case "exportar_sd":
                # Crear tempdir una sola vez; reusar si ya existe
                # (p. ej. re-arranque del FB a mitad de lote).
                if self._prepared_dir is None:
                    self._prepared_dir = Path(
                        tempfile.mkdtemp(prefix="bep_")
                    )
                elif not self._prepared_dir.exists():
                    self._prepared_dir.mkdir(parents=True, exist_ok=True)

                exported_count = 0
                for entry in self._blocks_data:
                    block_name = entry.get("name") or ""
                    if not block_name:
                        continue
                    try:
                        dispatch_result = self._tia_client.dispatch(
                            "export_block",
                            {
                                "plc_name": self._plc_name,
                                "block_name": block_name,
                                "target_dir": str(self._prepared_dir),
                                "keep_folder_structure": False,
                            },
                        )
                    except Exception as exc:
                        logger.warning(
                            f"[{self.nombre}] export_block exception "
                            f"para '{block_name}': {type(exc).__name__}: {exc}"
                        )
                        continue
                    if not isinstance(dispatch_result, dict) or not dispatch_result.get("ok"):
                        logger.warning(
                            f"[{self.nombre}] export_block fallo para "
                            f"'{block_name}': "
                            f"{dispatch_result.get('error') if isinstance(dispatch_result, dict) else dispatch_result}"
                        )
                        continue
                    entry["sd_path"] = self._prepared_dir / f"{block_name}.s7dcl"
                    exported_count += 1

                return f"exportados {exported_count} bloques SD"

            case "parsear_scl":
                parsed_count = 0
                for entry in self._blocks_data:
                    sd_path = entry.get("sd_path")
                    base_props = entry.get("base_props") or {
                        "title": None,
                        "comment": None,
                        "author": None,
                        "version": None,
                        "programming_language": None,
                        "memory_layout": None,
                    }
                    try:
                        extended = parse_extended_props_from_sd(
                            sd_path, base_props,
                        )
                    except Exception as exc:
                        logger.warning(
                            f"[{self.nombre}] parse_extended_props_from_sd "
                            f"exception para '{entry.get('name')}': "
                            f"{type(exc).__name__}: {exc}"
                        )
                        extended = dict(base_props)
                    entry["extended_props"] = extended
                    parsed_count += 1

                return f"parseados {parsed_count} headers SCL"

            case "merge_cache":
                # Inicializar el slot global en app_cache si no existe.
                if not hasattr(self._app_cache, "block_edit_prepared"):
                    self._app_cache.block_edit_prepared = {}
                target = self._app_cache.block_edit_prepared.setdefault(
                    self._plc_name, {},
                )

                merged_count = 0
                for entry in self._blocks_data:
                    ext = entry.get("extended_props") or {}
                    dto = DataBloquePLC(
                        nombre=entry.get("name", "") or "",
                        numero=int(entry.get("number", 0) or 0),
                        tipo=entry.get("tipo", "OTHER") or "OTHER",
                        ruta=entry.get("path", "") or "",
                        title=ext.get("title"),
                        comment=ext.get("comment"),
                        author=ext.get("author"),
                        version=ext.get("version"),
                        programming_language=ext.get("programming_language"),
                        memory_layout=ext.get("memory_layout"),
                    )
                    target[entry["path"]] = dto
                    merged_count += 1

                self._stats["merge_cache"] = {
                    "n_blocks": merged_count,
                    "n_with_title": sum(
                        1 for e in self._blocks_data
                        if (e.get("extended_props") or {}).get("title")
                    ),
                    "n_with_comment": sum(
                        1 for e in self._blocks_data
                        if (e.get("extended_props") or {}).get("comment")
                    ),
                }
                return f"merge OK: {merged_count} bloques en app_cache"

            case _:
                raise ValueError(f"step no soportado: {step_nombre!r}")

    # ==================================================================
    # Helpers internos
    # ==================================================================

    def _read_one_block(
        self, path: str, plc: Any,
    ) -> dict[str, Any] | None:
        """Lee las props TIA de UN bloque. None si falla alguna lectura.

        Si ``get_property(name=...)`` lanza para CUALQUIER prop extendida
        (HeaderAuthor, HeaderVersion, ProgrammingLanguage, MemoryLayout,
        Number) o para ``get_name()``, el bloque se skipea entero. Asi
        la SPA nunca ve un DTO a medio poblar: o todo, o nada.
        """
        from core.infrastructure.tia.tia_helpers import (
            _find_block_in_plc,
        )

        # Parsear path: ultimo segmento = nombre; resto = jerarquia.
        parts = path.split("/")
        block_name = parts[-1].strip('"') if parts else ""
        block_path = "/".join(parts[:-1]).replace("/", "\\")

        try:
            block = _find_block_in_plc(plc, block_name, block_path)
        except Exception as exc:
            logger.warning(
                f"[{self.nombre}] _find_block_in_plc no encontro "
                f"'{path}': {type(exc).__name__}: {exc}"
            )
            return None

        # Nombre del bloque (sin try/except: si falla, skip).
        try:
            bname = block.get_name()
        except Exception as exc:
            logger.warning(
                f"[{self.nombre}] get_name() fallo para '{path}': "
                f"{type(exc).__name__}: {exc}"
            )
            return None
        bname = (str(bname).strip('"') if bname else block_name) or ""

        # Numero (skip si falla).
        bnumber = 0
        try:
            raw = block.get_property(name="Number")
            bnumber = int(raw) if raw is not None else 0
        except Exception as exc:
            logger.warning(
                f"[{self.nombre}] get_property(Number) fallo para '{path}': "
                f"{type(exc).__name__}: {exc}"
            )
            return None

        # 4 props extendidas criticas. Cualquier raise -> skip del bloque.
        # ``title`` y ``comment`` NO se leen aqui (vienen del SCL).
        field_map = {
            "HeaderAuthor": "author",
            "HeaderVersion": "version",
            "ProgrammingLanguage": "programming_language",
            "MemoryLayout": "memory_layout",
        }
        base_props = {
            "title": None,
            "comment": None,
            "author": None,
            "version": None,
            "programming_language": None,
            "memory_layout": None,
        }
        for tia_name, py_name in field_map.items():
            try:
                raw = block.get_property(name=tia_name)
            except Exception as exc:
                logger.warning(
                    f"[{self.nombre}] get_property({tia_name}) fallo "
                    f"para '{path}': {type(exc).__name__}: {exc} -- skip"
                )
                return None
            if raw is None or raw == "":
                continue
            try:
                base_props[py_name] = str(raw).strip() or None
            except Exception:
                continue

        return {
            "path": path,
            "name": bname,
            "number": bnumber,
            "base_props": base_props,
        }

    # ==================================================================
    # HOOK 3: on_finish  (ZONA 5: vuelco del result + cleanup)
    # ==================================================================

    def on_finish(self, **params: Any) -> None:
        """Vuelca ``self.result`` y limpia el tempdir (best-effort)."""
        merge_stats = self._stats.get("merge_cache", {})
        n_blocks = merge_stats.get("n_blocks", len(self._blocks_data))
        self.result = {
            "ok": True,
            "plc_name": self._plc_name,
            "n_blocks": n_blocks,
            "n_with_title": merge_stats.get("n_with_title", 0),
            "n_with_comment": merge_stats.get("n_with_comment", 0),
        }
        # Cleanup del tempdir de exports SD.
        if self._prepared_dir is not None:
            try:
                shutil.rmtree(self._prepared_dir, ignore_errors=True)
            except Exception as exc:
                logger.debug(
                    f"[{self.nombre}] cleanup tempdir fallo: {exc}"
                )
            finally:
                self._prepared_dir = None


# ==================================================================
# Helper libre (evita un mock-block proxy dentro de run_step)
# ==================================================================
def classify_block_for_entry(entry: dict[str, Any]) -> str:
    """Devuelve ``tipo`` derivandolo del nombre del bloque.

    No toca el SDK .NET (el bloque original se ha liberado tras
    ``_read_one_block``): usa el patron del prefijo del nombre,
    identico a ``DataBloquePLC.detect_tipo``.
    """
    nombre = entry.get("name") or ""
    return DataBloquePLC.detect_tipo(nombre)


__all__ = ["FunctionBlockEditPrepare"]