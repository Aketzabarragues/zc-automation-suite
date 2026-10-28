"""Materializa los archivos del proceso nuevo en ``dir_nuevo``.

Helper puro del flujo ``proc_process_crear``: toma la copia de
la plantilla (``dir_plantilla_copia``, ya con prefijo numerico
re-escrito) y produce el workdir final (``dir_nuevo``) aplicando
el resto del dicc a nombres de path y a contenidos de archivos.

Usado por el FB ``function_proc_crear_sincronizar`` (stage 5 del
apply). El preview no lo invoca: su stage 5 es ``generar_previstos``
que solo lista lo que se generaria, sin escribir.

Pipeline (3 pasos):

1. ``shutil.copytree(dir_plantilla_copia, dir_nuevo)``: copia bulk
   preservando la estructura. ``manifest.json`` se excluye via
   el ``ignore`` (lo regenera ``proc_process_escribir_manifest``
   justo despues).
2. Walk de ``dir_nuevo``: para cada path (file O folder) se
   aplica el rename al nombre del componente con el dicc de
   bloques. Orden de profundidad DESCENDENTE (mas profundo
   primero) para no romper paths de hijos cuando movemos el
   padre.
3. Walk final para rewrite de contenido segun extension:
     - ``.s7res``:           ``dicc_bloques``, encoding utf-8-sig.
     - ``.xml``:             ``dicc_xml``, encoding utf-8. Si el
                              XML contiene ``PlcUserConstant`` se
                              aplica ademas el override de N_MAX
                              con los valores del operario.
     - ``.s7dcl/.scl/.awl``: ``dicc_bloques``, encoding utf-8.
     - Resto (binarios):     sin tocar (ya copiados por copytree).

Notas:

- ``ctx`` se trata con duck typing: cualquier objeto con los
  campos ``dir_plantilla_copia``/``dir_nuevo`` (Path), ``base_nueva``
  (int), ``minimos_usuario`` (dict[str, int]), ``dicc_bloques``/
  ``dicc_xml`` (dict[str, str]) funciona. Asi el helper no depende
  del ``ProcProcessGenContext`` local del FB.
- Los 4 helpers internos (``_aplicar_diccionario``, ``_leer_texto``,
  ``_escribir_texto``, ``_reemplazar_nmax_en_xml``) viven aqui
  porque solo esta funcion los usa. Si en el futuro otra
  funcion del pipeline los necesita, se extraen a su propio
  modulo para evitar duplicacion.
- ``N_MAX_KEYS`` esta duplicado intencionalmente con el del
  preview FB: contiene 4 strings canonicos. Cuando se extraiga
  ``proc_process_validar_minimos`` (otro commit futuro), ese
  modulo pasara a ser el source of truth y el preview importara
  de ahi.
"""
from __future__ import annotations

import re
import shutil
from pathlib import Path
from typing import Any

__all__ = ["proc_process_aplicar_clonacion"]


_N_MAX_KEYS: tuple[str, ...] = (
    "N_MAX_PREAL", "N_MAX_PINT", "N_MAX_ALM", "N_MAX_ALM_HMI",
)


def _aplicar_diccionario(texto: str, dicc: dict[str, str]) -> str:
    """Aplica los reemplazos en cascada."""
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
    """
    for key in _N_MAX_KEYS:
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


def proc_process_aplicar_clonacion(ctx: Any) -> None:
    """Aplica la clonacion: ``dir_plantilla_copia`` -> ``dir_nuevo``.

    Borra ``dir_nuevo/`` antes de aplicar (regla de retencion: cada
    apply parte limpio). Ver docstring del modulo para el pipeline
    completo.
    """
    if ctx.dir_nuevo.exists():
        shutil.rmtree(ctx.dir_nuevo)

    def _ignore_manifest(_dir: str, names: list[str]) -> list[str]:
        return [n for n in names if n == "manifest.json"]

    shutil.copytree(
        str(ctx.dir_plantilla_copia),
        str(ctx.dir_nuevo),
        ignore=_ignore_manifest,
    )

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

        renames.sort(key=lambda pair: -len(pair[0].parts))
        for old, new in renames:
            new.parent.mkdir(parents=True, exist_ok=True)
            old.rename(new)

    _rename_paths()

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

            generated.append(str(path.relative_to(ctx.dir_nuevo)))
        return generated

    ctx.archivos_generados = _rewrite_contents()
