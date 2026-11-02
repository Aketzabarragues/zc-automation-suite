"""areas.alimentacion.state.proc_process_gen_context - ctx de clonacion de proceso.

Estado compartido entre los steps de los FBs que clonan un proceso TIA
desde una plantilla: ``FunctionProcCrearGenerarPreview`` (preview) y
``FunctionProcCrearSincronizar`` (commit).

Cada step muta uno o varios campos con el resultado de su trabajo y los
steps siguientes leen lo que dejaron los anteriores. El FB instancia un
ctx en ``on_start()`` y lo reutiliza durante todo el run.

El dataclass vive aqui y no duplicado en cada FB: los dos FBs comparten
exactamente los mismos campos, en el mismo orden y con los mismos
defaults, asi que una sola definicion evita que las dos copias
divergen.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class ProcProcessGenContext:
    """Estado compartido entre los steps de clonacion de un proceso."""

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
    descripcion: str = ""
    dependencias: list[str] = field(default_factory=list)

    # ── Resultado de validar_dependencias ──
    # ``dependencias`` declaradas en el manifest cruzadas contra el
    # ``plc_blocks_cache``. La SPA pinta en rojo las faltantes y
    # bloquea el boton "Aplicar" si la lista no esta vacia.
    dependencias_ok: list[str] = field(default_factory=list)
    dependencias_faltantes: list[str] = field(default_factory=list)

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
    # Una entry por BLOQUE (no por archivo): un bloque TIA vive en
    # 2 archivos (.s7dcl + .s7res, mismo stem). Cada dict lleva
    # ``nombre_original``, ``nombre_nuevo`` y ``estado`` ("OK" |
    # "DUPLICADO - <id>" | "DUPLICADO").
    archivos_previstos: list[dict[str, str]] = field(default_factory=list)
    archivos_generados: list[str] = field(default_factory=list)

    # ── Resultado final (vuelco a ``self.result``) ──
    result: dict[str, Any] = field(default_factory=dict)


__all__ = ["ProcProcessGenContext"]
