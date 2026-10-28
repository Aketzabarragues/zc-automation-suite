"""Construccion del diccionario de renombrado (compartido por preview y sync).

Helper puro del flujo ``proc_process_crear``: tanto el FB de preview
(``function_proc_crear_generar_preview``) como el de sync
(``function_proc_crear_sincronizar``) llaman a esta misma funcion
para construir el ``dicc_bloques`` y ``dicc_xml`` que
``proc_process_aplicar_clonacion`` luego aplica a ``.s7dcl`` / ``.s7res``
/ ``.scl`` / ``.awl``.

Estrategia (en este orden):

- Bloques: walk del directorio ``dir_plantilla_copia`` con un regex
  matematico ``(FC|FB|DB)(\\d+)`` -> ``prefijo(num - base_vieja +
  base_nueva)``. Renombra SOLO los prefijos canonicos TIA
  (FC/FB/DB).
- Carpetas: data-driven. Por cada carpeta con prefijo numerico
  ``r"^(\\d+)_"`` se anade una regla ``{prefijo}_`` ->
  ``{prefijo - base_vieja + base_nueva}_`` a ``dicc_bloques`` y
  ``dicc_xml``. Cubre cualquier offset (las 3 bases estandar del
  proyecto y las custom de la plantilla).
- Stems de archivos (oct-2026): ademas de las carpetas, cualquier
  archivo con stem ``(FC|FB|DB)(\\d+)_`` aporta su numero al set
  de prefijos. Esto cubre bloques cuyo numero no aparece como
  prefijo de carpeta (e.g. ``FC50501_CIP1_ORDENES_R_L1.s7dcl``
  dentro de ``50500_Principal\\``): sin esta entrada no hay regla
  ``50501_ -> 501_`` en el dicc y el numero se queda intacto en
  el contenido de ``.s7dcl`` / ``.s7res``. TIA Portal muestra
  el nombre del bloque desde el mapeo ``MLC_<id> -> es-ES: ...``
  del ``.s7res``, asi que una regla faltante deja el FC50501
  visible en TIA aunque el resto este bien renombrado.
- Metadatos TIA: ``S7_BlockNumber := "X"`` de las cabeceras de
  los bloques del proceso.
- Fallbacks: codigo y nombre del proceso (siempre).

Todo se ordena por ``len(key)`` descendente para que las claves
mas especificas (e.g. ``DB50500_CIP1_INTERFAZ``) ganen antes que
las del prefijo (``50500_``).

Notas:

- ``ctx`` se trata con duck typing: cualquier objeto con los campos
  ``dir_plantilla_copia`` (Path), ``base_vieja``/``base_nueva``
  (int), ``codigo_viejo``/``codigo_nuevo``/``nombre_viejo``/
  ``nombre_nuevo`` (str), ``dicc_bloques``/``dicc_xml``
  (dict[str, str]) funciona. Asi el helper no depende del
  dataclass local de cada FB.
- El walk es sync y corre en el hilo del llamante: el shell
  ejecuta un unico hilo, sin event loop.
- Si en el futuro los dos FBs divergen en sus necesidades,
  pasar el ctx a kwargs explicitos y romper en helpers mas
  pequenos. Hoy mismo, el contrato es lo bastante estable
  como para compartir.
"""
from __future__ import annotations

import re
from typing import Any

__all__ = ["proc_process_construir_diccionarios"]


def proc_process_construir_diccionarios(ctx: Any) -> None:
    base_viej = ctx.base_vieja
    base_nuev = ctx.base_nueva
    cod_viej = ctx.codigo_viejo
    cod_nuev = ctx.codigo_nuevo
    nom_viej = ctx.nombre_viejo
    nom_nuev = ctx.nombre_nuevo

    dicc_bloques: dict[str, str] = {}
    dicc_xml: dict[str, str] = {}
    numeros_usados: set[int] = set()
    prefijos_walk: set[int] = set()

    patron_bloques = re.compile(r"(FC|FB|DB)(\d+)")
    patron_prefijo_carpeta = re.compile(r"^(\d+)_")
    patron_prefijo_stem = re.compile(r"^(FC|FB|DB)(\d+)_")

    def _walk_and_build() -> None:
        bloques_raiz = ctx.dir_plantilla_copia / "Bloques de programa"
        for item in ctx.dir_plantilla_copia.rglob("*"):
            if not item.exists():
                continue
            nombre_base = item.stem if item.is_file() else item.name

            if (
                item.is_dir()
                and bloques_raiz in item.parents
                and item != bloques_raiz
            ):
                m_prefijo = patron_prefijo_carpeta.match(item.name)
                if m_prefijo:
                    prefijos_walk.add(int(m_prefijo.group(1)))

            # Prefijos numericos de stems de archivos (FC/FB/DB).
            # Ver docstring del modulo: cubre bloques cuyo numero no
            # aparece como prefijo de carpeta.
            if item.is_file():
                m_stem = patron_prefijo_stem.match(item.stem)
                if m_stem:
                    prefijos_walk.add(int(m_stem.group(2)))

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

    _walk_and_build()

    for prefijo_v in sorted(prefijos_walk):
        prefijo_n = prefijo_v - base_viej + base_nuev
        if prefijo_v == prefijo_n:
            continue
        regla_vieja = f"{prefijo_v}_"
        regla_nueva = f"{prefijo_n}_"
        dicc_xml[regla_vieja] = regla_nueva
        dicc_bloques[regla_vieja] = regla_nueva

    for b_vieja, b_nueva in zip(
        [base_viej, base_viej + 3000, base_viej + 5000],
        [base_nuev, base_nuev + 3000, base_nuev + 5000],
    ):
        regla_vieja = f"{b_vieja}_"
        regla_nueva = f"{b_nueva}_"
        dicc_xml.setdefault(regla_vieja, regla_nueva)
        dicc_bloques.setdefault(regla_vieja, regla_nueva)

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
