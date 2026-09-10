"""Constantes y helpers para rutas de export/modificación de TIA Portal.

Convención de la app (NO config del proyecto):
  * Sufijos de archivos SD/XML que genera TIA Portal al exportar
    Source Documents y tablas de tags.
  * Encodings de lectura/escritura de esos archivos.
  * Límite práctico de longitud de comentario (S7_MLC).
  * Texto vacío de placeholder (".") que TIA usa cuando un campo
    está sin comentar.

Estas constantes estaban duplicadas en
``areas/alimentacion/infrastructure/sd/disp_comment_updater.py`` y
``areas/alimentacion/infrastructure/sd/proc_comment_updater.py``. Se
centralizan aquí para que cualquier área futura (trazabilidad, etc.)
pueda consumirlas sin reescribirlas.

Helpers de paths (``SdPair`` y ``XmlTarget``) son genéricos por
naturaleza: no saben de áreas ni de dominios, solo resuelven el par
``.s7dcl``/``.s7res`` o el ``.xml`` de una tabla. Cualquier área puede
usarlos.

Si en el futuro un proyecto necesitase override (p. ej. otro encoding),
se añade a ``infrastructure/config.json`` y los consumidores lo leen
vía ``ConfigManager``. Por ahora YAGNI: la convención es fija.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

# ── Sufijos de archivos (generados por TIA Portal al exportar) ────────────

SD_SUFFIX: str = ".s7dcl"
SD_RES_SUFFIX: str = ".s7res"
XML_SUFFIX: str = ".xml"

# ── Encodings ─────────────────────────────────────────────────────────────
# ``.s7dcl`` se exporta sin BOM; ``.s7res`` con BOM (utf-8-sig).
# Mantener el encoding explícito evita ``UnicodeDecodeError`` en
# sistemas con code page ANSI (Windows) y protege la ``\ufeff`` del BOM.

SD_ENCODING: str = "utf-8"
SD_RES_ENCODING: str = "utf-8-sig"

# ── Comentarios ───────────────────────────────────────────────────────────
# Límite práctico S7_MLC (254 chars). Truncar con warning si se supera.
MAX_COMMENT_LEN: int = 254

# Texto que TIA escribe cuando un campo está "sin comentario".
# Aparecerá como ``.`` en el .s7res y como string vacío en el .s7dcl.
EMPTY_TEXT: str = "."


# ── Helpers de paths ──────────────────────────────────────────────────────


@dataclass(frozen=True)
class SdPair:
    """Resuelve el par ``(.s7dcl, .s7res)`` a partir del work_dir y db_name.

    Convención de la app: ambos archivos van juntos en el mismo
    ``work_dir`` (la exportación de TIA los deposita en el mismo
    directorio). Los modificadores leen el ``.s7dcl`` + ``.s7res`` y
    escriben la versión modificada en otro work_dir (mismo shape).

    Genérico: no sabe de áreas ni de dominios. Los consumers lo usan
    desde ``areas/alimentacion/infrastructure/sd/`` hoy, y desde
    cualquier otra área que exporte SD mañana.

    Example:
        >>> pair = SdPair(Path("/tmp/exp"), "DB2000_ED")
        >>> pair.dcl
        PosixPath('/tmp/exp/DB2000_ED.s7dcl')
        >>> pair.res
        PosixPath('/tmp/exp/DB2000_ED.s7res')
    """

    work_dir: Path
    db_name: str

    @property
    def dcl(self) -> Path:
        return self.work_dir / f"{self.db_name}{SD_SUFFIX}"

    @property
    def res(self) -> Path:
        return self.work_dir / f"{self.db_name}{SD_RES_SUFFIX}"


@dataclass(frozen=True)
class XmlTarget:
    """Resuelve la ruta de un ``.xml`` de tabla de tags.

    TIA Portal, al exportar con ``keep_folder_structure=True`` (V21+),
    deposita el ``.xml`` en un subdirectorio ``Tags/`` o similar. Este
    helper:

      1. Intenta la ruta directa ``<work_dir>/<table_name>.xml``.
      2. Si no existe, busca con ``rglob`` en subdirectorios.
      3. Si hay 1 match, lo devuelve.
      4. Si no hay ninguno, lanza ``FileNotFoundError``.
      5. Si hay varios, devuelve el primero (caso defensivo; el
         operario debería revisar el work_dir si pasa).

    Genérico: no sabe de áreas ni de dominios. Los consumers lo usan
    desde ``areas/alimentacion/infrastructure/xml/`` hoy.

    Example:
        >>> target = XmlTarget(Path("/tmp/exp"), "000_Config_Dispositivos")
        >>> target.path  # /tmp/exp/000_Config_Dispositivos.xml si existe
    """

    work_dir: Path
    table_name: str

    @property
    def path(self) -> Path:
        direct = self.work_dir / f"{self.table_name}{XML_SUFFIX}"
        if direct.exists():
            return direct
        # Fallback: TIA puede haber creado subdirs (Tags/, etc.).
        matches = list(self.work_dir.rglob(f"{self.table_name}{XML_SUFFIX}"))
        if not matches:
            raise FileNotFoundError(
                f"No se encontró {self.table_name}{XML_SUFFIX} en {self.work_dir} "
                f"(ni directo ni con rglob)."
            )
        # Si hay varios, devolvemos el primero (defensivo). El operario
        # puede revisar el work_dir si esto ocurre.
        return matches[0]


__all__ = [
    "SD_SUFFIX",
    "SD_RES_SUFFIX",
    "XML_SUFFIX",
    "SD_ENCODING",
    "SD_RES_ENCODING",
    "MAX_COMMENT_LEN",
    "EMPTY_TEXT",
    "SdPair",
    "XmlTarget",
]
