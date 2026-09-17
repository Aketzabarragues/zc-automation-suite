"""Actualizador offline de comentarios por instancia para DBs de procesos.

Modifica un par de archivos ``.s7dcl`` + ``.s7res`` exportados por
TIA Portal para escribir el comentario de cada slot de los arrays
``PReal[]``, ``PInt[]`` y ``ALM[]`` de un DB de proceso. Es el
hermano "procesos" de ``DispCommentUpdater`` (DBs de dispositivos
ED/EA/SA/V/M/M_VF); admite propagacion del comentario a arrays
satelite del mismo DB.

Este modulo es el orquestador: delega en los helpers de ``simatic_sd/``
para el parseo, la mutacion y la gestion del .s7res.

Convencion de archivos
----------------------
El ``.s7dcl`` anota cada slot del array con
``{ S7_MLC := "MLC_xxx" }`` y el ``.s7res`` mapea cada
``MLC_xxx`` a su ``es-ES``. El cruce entre ambos es el ID
``MLC_xxx``.

Uso tipico
----------

::

    updater = ProcCommentUpdater(
        s7dcl_path=Path("DB53100_CPR_PARAM.s7dcl"),
        s7res_path=Path("DB53100_CPR_PARAM.s7res"),
        slot_map={1: "Bomba 1", 2: "Bomba 2", 3: "Bomba 3"},
        array_name="PReal",
        satellite_arrays={"PReal_Vis", "Aux.PReal_ValorAnterior"},
        registry=MLCRegistry(),
    )
    updater.update()
    updater.save()

Restriccion arquitectonica: este modulo es OFFLINE; no importa
``siemens_tia_scripting``.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from pathlib import Path

from areas.alimentacion.helpers.simatic_sd.simatic_sd_mlc_registry import MLCRegistry
from areas.alimentacion.helpers.simatic_sd.simatic_sd_s7dcl_mutator import (
    build_mlc_assignment_block,
    upsert_s7dcl_block,
)
from areas.alimentacion.helpers.simatic_sd.simatic_sd_s7dcl_parser import (
    extract_all_mlcs_from_s7dcl,
    extract_existing_mlcs_from_s7res,
    find_array_slots,
    find_assignment,
    find_assignment_mlc,
)
from areas.alimentacion.helpers.simatic_sd.simatic_sd_s7res_manager import (
    count_s7res_entries,
    prune_s7res,
    upsert_s7res_entry,
)
from areas.alimentacion.helpers.simatic_sd.simatic_sd_text_utils import (
    sanitize_comment_text,
    strip_enclosing_quotes,
)
from core.infrastructure.tia.tia_export_paths import SD_ENCODING, SD_RES_ENCODING


# Asegura que ``Logger.web/ok`` existen tambien fuera del arranque.
from core.infrastructure.log_web_bridge import install_web_level
install_web_level()


_logger: logging.Logger = logging.getLogger(f"{__name__}.ProcCommentUpdater")


# ── Resultado del update ───────────────────────────────────────────────────


@dataclass(frozen=True)
class ProcCommentResult:
    """Resumen de la actualizacion de un bloque de proceso.

    Attributes:
        reused: ``{slot: mlc_id}`` para slots cuyo MLC ya existia
                (en el array principal, no en los satelites).
        inserted: ``{slot: mlc_id}`` para slots con MLC nuevo
                generado (en el array principal).
        satellite_reused: ``{slot: mlc_id}`` para MLCs de satelites
                que ya existian y se actualizaron.
        satellite_inserted: ``{slot: mlc_id}`` para MLCs de satelites
                nuevos generados.
        total_mlcs_in_res: numero de entradas MultiLingualTexts en
                el ``.s7res`` resultante (post-update).
    """

    reused: dict[int, str]
    inserted: dict[int, str]
    satellite_reused: dict[int, str]  # slot -> mlc_id (uno por satelite)
    satellite_inserted: dict[int, str]
    total_mlcs_in_res: int


# ── Entry point ────────────────────────────────────────────────────────────


class ProcCommentUpdater:
    """Actualiza los comentarios por instancia de un DB de proceso.

    Attributes:
        s7dcl_path: ruta al archivo ``.s7dcl``.
        s7res_path: ruta al archivo ``.s7res``.
        slot_map: ``{slot: texto}`` 1-based. Slots que no estan
                  en el map se dejan intactos (comentario historico
                  del operario conservado).
        array_name: nombre del array principal en el DB
                  (p. ej. ``"PReal"``, ``"PInt"``, ``"ALM"``).
        satellite_arrays: set de nombres de arrays satelite del
                  mismo proceso (p. ej. ``{"PReal_Vis",
                  "Aux.PReal_ValorAnterior"}``). Para cada slot
                  actualizado en el array principal, el updater
                  propaga el texto a los MLCs de los satelites del
                  mismo indice (si existen en el ``.s7dcl``).
        registry: ``MLCRegistry`` con los MLCs ya presentes en el
                  ``.s7res`` reservados.

    Raises:
        ValueError: si ``update()`` se llama con ``array_name`` vacio.
        FileNotFoundError: si los archivos no existen.
    """

    def __init__(
        self,
        s7dcl_path: str | Path,
        s7res_path: str | Path,
        slot_map: dict[int, str],
        array_name: str = "",
        satellite_arrays: set[str] | None = None,
        registry: MLCRegistry | None = None,
    ) -> None:
        self._s7dcl_path = Path(s7dcl_path)
        self._s7res_path = Path(s7res_path)

        if not self._s7dcl_path.is_file():
            raise FileNotFoundError(f"No se encontró .s7dcl: '{self._s7dcl_path}'")
        if not self._s7res_path.is_file():
            raise FileNotFoundError(f"No se encontró .s7res: '{self._s7res_path}'")

        # ``array_name`` es opcional en construccion: solo es obligatorio
        # cuando se llama a ``update()`` (modo escritura).
        self._array_name: str = (array_name or "").strip()

        # Filtrar el slot 0 (no aplica a procesos).
        filtered = {
            int(k): v for k, v in slot_map.items() if int(k) >= 1
        }
        if 0 in slot_map:
            _logger.warning(
                f"ProcCommentUpdater: slot_map contiene slot 0, "
                f"se ignora (los arrays de procesos empiezan en 1)."
            )
        self._slot_map: dict[int, str] = filtered

        self._satellite_arrays: set[str] = set(satellite_arrays or ())

        # Carga en memoria.
        self._s7dcl: str = self._s7dcl_path.read_text(encoding=SD_ENCODING)
        self._s7res: str = self._s7res_path.read_text(encoding=SD_RES_ENCODING)

        # Estado mutable.
        self._modified: bool = False
        # Inicializa el registry con los MLCs ya presentes en el
        # .s7res (para que next_mlc_id no colisione con ellos).
        if registry is None:
            existing = extract_existing_mlcs_from_s7res(self._s7res)
            self._registry: MLCRegistry = MLCRegistry(used_ids=existing)
        else:
            registry.reserve(extract_existing_mlcs_from_s7res(self._s7res))
            self._registry = registry
        self._result: ProcCommentResult | None = None

    # ── API publica ─────────────────────────────────────────────────────────

    def update(self) -> ProcCommentResult:
        """Orquesta la actualizacion. Retorna ``ProcCommentResult``.

        Algoritmo:
          1. Para cada slot del slot_map, localizar el MLC existente
             del array principal o generar uno nuevo.
          2. Para cada slot actualizado, propagar el texto a los
             MLCs de los satelites del mismo indice.
          3. Restaurar MLCs huerfanos referenciados por el .s7dcl.
          4. Equilibrar el .s7res (conservar solo MLCs referenciados).
        """
        if not self._array_name:
            raise ValueError(
                "array_name es obligatorio para update() (no para "
                "read_current_comments)."
            )
        _logger.debug(
            f"ProcCommentUpdater: array={self._array_name!r}, "
            f"{len(self._slot_map)} slots, "
            f"file='{self._s7dcl_path.name}'"
        )
        reused: dict[int, str] = {}
        inserted: dict[int, str] = {}
        satellite_reused: dict[int, str] = {}
        satellite_inserted: dict[int, str] = {}

        # 1) Para cada slot del map, asegurar asignacion + MLC.
        for slot, raw_text in self._slot_map.items():
            text = sanitize_comment_text(raw_text, slot)
            existing_mlc = find_assignment_mlc(
                self._s7dcl, self._array_name, slot
            )
            if existing_mlc is not None:
                # MLC ya estaba en el .s7dcl; lo respetamos.
                self._registry.reserve([existing_mlc])
                reused[slot] = existing_mlc
                # Si el .s7res perdio esta entrada, la restauramos.
                self._s7res, mod = upsert_s7res_entry(
                    self._s7res, existing_mlc, text
                )
                if mod:
                    self._modified = True
            else:
                # Crear MLC nuevo y asignacion.
                new_mlc = self._registry.next_mlc_id()
                self._inject_mlc_block_or_assignment(
                    self._array_name, slot, new_mlc
                )
                self._s7res, mod = upsert_s7res_entry(
                    self._s7res, new_mlc, text
                )
                if mod:
                    self._modified = True
                inserted[slot] = new_mlc

            # 2) Propagacion a satelites del mismo slot.
            for sat_array in self._satellite_arrays:
                sat_mlc = find_assignment_mlc(self._s7dcl, sat_array, slot)
                if sat_mlc is None:
                    continue
                # El satelite ya tenia MLC: lo actualizamos.
                self._registry.reserve([sat_mlc])
                self._s7res, mod = upsert_s7res_entry(
                    self._s7res, sat_mlc, text
                )
                if mod:
                    self._modified = True
                satellite_reused[slot] = sat_mlc

        # 3) Calcular el conjunto de MLCs referenciados por el .s7dcl
        # (cabecera + array principal + todos los satelites) para
        # equilibrar el .s7res. TIA exige que el nº de MLCs en
        # .s7dcl coincida EXACTAMENTE con el del .s7res.
        referenced: set[str] = (
            set(reused.values())
            | set(inserted.values())
            | set(satellite_reused.values())
            | extract_all_mlcs_from_s7dcl(self._s7dcl)
        )

        # 3.bis) Si el .s7dcl referencia MLCs que el .s7res no tiene
        # (caso tipico: la exportacion de TIA omite los MLCs de
        # cabecera), los añadimos con texto "." (convencion TIA).
        existing_in_res = extract_existing_mlcs_from_s7res(self._s7res)
        for mlc_id in referenced:
            if mlc_id not in existing_in_res:
                self._s7res, mod = upsert_s7res_entry(self._s7res, mlc_id, ".")
                if mod:
                    self._modified = True

        # 4) Podar el .s7res.
        new_res, removed = prune_s7res(self._s7res, referenced)
        if removed:
            self._s7res = new_res
            self._modified = True

        total_mlcs = count_s7res_entries(self._s7res)
        self._result = ProcCommentResult(
            reused=reused,
            inserted=inserted,
            satellite_reused=satellite_reused,
            satellite_inserted=satellite_inserted,
            total_mlcs_in_res=total_mlcs,
        )
        _logger.debug(
            f"ProcCommentUpdater: array={self._array_name!r}, "
            f"reused={len(reused)}, inserted={len(inserted)}, "
            f"satellites (reused={len(satellite_reused)}, inserted={len(satellite_inserted)}), "
            f"total_mlcs_in_res={total_mlcs}, modified={self._modified}"
        )
        return self._result

    def was_modified(self) -> bool:
        return self._modified

    def save(
        self,
        output_s7dcl_path: str | Path | None = None,
        output_s7res_path: str | Path | None = None,
    ) -> None:
        """Escribe los archivos (in-place si no se pasan rutas)."""
        out_dcl = Path(output_s7dcl_path) if output_s7dcl_path else self._s7dcl_path
        out_res = Path(output_s7res_path) if output_s7res_path else self._s7res_path
        out_dcl.parent.mkdir(parents=True, exist_ok=True)
        out_res.parent.mkdir(parents=True, exist_ok=True)
        out_dcl.write_text(self._s7dcl, encoding=SD_ENCODING)
        out_res.write_text(self._s7res, encoding=SD_RES_ENCODING)

    def find_array_slots(self, array_name: str) -> set[int]:
        """Delega en el helper de parser."""
        return find_array_slots(self._s7dcl, array_name)

    def read_current_comments(
        self, slot_indices: "list[int] | tuple[int, ...]", array_name: str
    ) -> "dict[int, str | None]":
        """Lee el ``es-ES`` actual de los slots del array principal.

        Solo expone los MLCs del array principal; los satelites son
        copias del mismo texto y se actualizan al aplicar cambios.
        Si el archivo no existe, devuelve ``{slot: None}`` para
        todos los slots.
        """
        if not self._s7res_path.is_file():
            return {slot: None for slot in slot_indices}
        mlc_to_text = self._build_mlc_text_map()
        result: dict[int, str | None] = {}
        for slot in slot_indices:
            mlc = find_assignment_mlc(self._s7dcl, array_name, slot)
            if mlc is None:
                result[slot] = None
            else:
                # Si el MLC existe en el .s7dcl pero no en el .s7res,
                # devolvemos string vacio (caso TIA degenerado).
                result[slot] = mlc_to_text.get(mlc, "")
        return result

    # ── Internals: orquestacion con state ───────────────────────────────────

    def _build_mlc_text_map(self) -> dict[str, str]:
        """Devuelve ``{MLC_id: es-ES_text}`` con todas las entradas
        del ``.s7res``.

        Esta funcion es la inversa de ``upsert_s7res_entry`` y se
        usa para leer el estado actual de TIA (sin modificar nada)
        durante la fase de preview / diff.

        Nota sobre comillas envolventes:
          TIA Portal exporta algunos comentarios entre comillas
          literales en el ``.s7res`` (caso tipico: texto con
          espacios al final, comillas internas, o caracteres que
          YAML considera "no seguros"). Las quitamos
          conservadoramente solo si el texto capturado empieza Y
          termina con la MISMA comilla.
        """
        result: dict[str, str] = {}
        pattern = re.compile(
            r"(?xm)^(?P<indent>\s*-\s*id:\s*(?P<mlc>\S+)\s*\n)"
            r"(?P<inner>(?:\s+[^\n]*\n)*?)"
            r"(?=\s*-\s*id:|\s*MultiLingualTexts:|\Z)"
        )
        for m in pattern.finditer(self._s7res):
            mlc_id = m.group("mlc")
            inner = m.group("inner")
            es_match = re.search(r"es-ES:\s*([^\n]*)", inner)
            if es_match is None:
                result[mlc_id] = ""
            else:
                raw = es_match.group(1)
                result[mlc_id] = strip_enclosing_quotes(raw)
        return result

    def _inject_mlc_block_or_assignment(
        self, array_name: str, slot: int, mlc_id: str
    ) -> None:
        """Inserta la asignacion y/o su bloque S7_MLC.

        - Si existe ``<ARRAY>[slot] := ...;`` sin bloque MLC → añade el bloque antes.
        - Si no existe la asignación → añade bloque + asignación al final del bloque
          de inicialización (última asignación del array). Si no hay inicialización,
          la añade justo antes de ``END_DATA_BLOCK``.
        """
        match = find_assignment(self._s7dcl, array_name, slot)
        if match is not None:
            existing = find_assignment_mlc(self._s7dcl, array_name, slot)
            if existing is None:
                indent = match.group("indent")
                block = build_mlc_assignment_block(indent, mlc_id)
                self._s7dcl, mod = upsert_s7dcl_block(self._s7dcl, match, block)
                if mod:
                    self._modified = True
            return

        # No existe la asignación. Insertar bloque + asignación.
        # Para una asignación nueva de procesos, el array NO lleva comillas
        # (formato TIA para procesos: ``PReal[3] := ();``, no ``"PReal"[3]``).
        new_block = (
            build_mlc_assignment_block("        ", mlc_id)
            + f"        {array_name}[{slot}] := ();\n"
        )
        marker = "END_DATA_BLOCK"
        idx = self._s7dcl.rfind(marker)
        if idx < 0:
            self._s7dcl = self._s7dcl.rstrip() + "\n\n" + new_block
        else:
            self._s7dcl = self._s7dcl[:idx] + new_block + self._s7dcl[idx:]
        self._modified = True
