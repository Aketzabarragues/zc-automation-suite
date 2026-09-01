"""DTOs derivados del Excel corporativo del subdominio alimentación.

Este archivo agrupa, **en fases** (ver plan
``_plan/04_excel_cache_phased_plan.md``), las dataclasses ``frozen=True``
que representan las entidades del Excel que el PLC consume:

    * **Fase 1**: ``ProcesoPLC`` (este commit).
    * **Fases 2-4**: ``ParamRealPLC``, ``ParamIntPLC``, ``AlarmaPLC``.
    * **Fase 5**: consolidación de los 6 DTOs de dispositivos
      (``DispED/EA/SA/V/M/M_VF``) + ``DimensionesDispositivos`` +
      ``ExcelCache`` (DTO raíz con los 10 dominios del Excel +
      lookups precomputados por código).

¿Por qué un solo archivo para todos los DTOs del Excel?
    * El Excel corporativo es **una sola fuente de verdad**: todos los
      DTOs describen el mismo workbook desde ángulos distintos. Tenerlos
      juntos facilita razonar sobre su coherencia (ej. que
      ``ProcesoPLC.uid`` esté alineado con el ``uid`` de los
      ``ParamRealPLC`` de su proceso).
    * El ``ExcelCache`` raíz (Fase 5) contendrá tuplas con TODOS estos
      DTOs, así que ya estarán importados en el mismo módulo.
    * El test ``test_excel_cache_dto.py`` (Fase 5) puede cubrir los
      11 DTOs en un solo archivo, sin imports cruzados.

Restricciones arquitectónicas del subdominio (se respetan aquí):
    * Sin imports de ``siemens_tia_scripting``.
    * Sin imports de openpyxl u otras librerías de infraestructura.
    * Sin uso de ``Any`` en los atributos declarados.
    * Todos los ``str`` tienen default ``""``.
    * Todos los ``int`` tienen default ``0``.
    * ``frozen=True`` (más estricto que ``BloqueCache`` mutable — el
      Excel es más estable que un escaneo de PLC).
"""
from __future__ import annotations

from dataclasses import dataclass


# ── Fase 1: Procesos ─────────────────────────────────────────────────────


@dataclass(frozen=True)
class ProcesoPLC:
    """DTO de un proceso del PLC (hoja ``CONFIGURACION`` → ``Tabla_Procesos``).

    Un **proceso** es la unidad organizativa del Excel: agrupa un
    conjunto de parámetros reales, parámetros enteros y alarmas que
    se generan juntos en el PLC. Cada proceso tiene 3 DBs asociados:

        * ``DB{db_preal_numero}_{codigo}_PREAL`` — parámetros reales.
        * ``DB{db_pint_numero}_{codigo}_PINT``  — parámetros enteros.
        * ``DB{db_alm_numero}_{codigo}_ALM``    — alarmas.

    Campos (todos enteros/str con defaults tolerantes a celdas
    vacías del Excel):
        * ``uid``: identificador entero único (1, 2, 3, …).
        * ``nombre``: nombre legible del proceso.
        * ``codigo``: código corto usado en el nombre de los DBs.
        * ``preal`` / ``index_preal``: nº de parámetros reales y su
          offset dentro del DB PREAL.
        * ``pint`` / ``index_pint``: análogo para parámetros enteros.
        * ``alarmas``: nº de alarmas del proceso. Se usa para
          calcular ``alm_hmi`` (nº de palabra HMI necesaria para
          mostrarlas en el panel).

    Properties (derivadas, no almacenadas — coherentes con el legacy
    TUI ``_legacy_reference/ZC_ALM_TOOLS/core/models/software.py``):
        * ``db_preal_numero``: ``3000 + uid``.
        * ``db_pint_numero``:  ``3000 + uid + 1``.
        * ``db_alm_numero``:   ``5000 + uid``.
        * ``db_preal_nombre`` / ``db_pint_nombre`` / ``db_alm_nombre``:
          strings ``"DB{numero}_{codigo}_SUFIJO"``.
        * ``alm_hmi``: ``max(0, alarmas // 16 - 1)``. Nº de palabra
          HMI de 16 bits en la que se muestra el bit-array de
          alarmas del proceso (0 si no hay alarmas).

    Esta dataclass forma parte del cache del Excel (ver Fase 5 del
    plan) y es consumida por los flujos de generación de procesos
    que ya existían en el legacy.
    """

    uid: int
    nombre: str
    codigo: str
    preal: int = 0
    index_preal: int = 0
    pint: int = 0
    index_pint: int = 0
    alarmas: int = 0

    # ── Properties: nº de DB ──────────────────────────────────────────
    @property
    def db_preal_numero(self) -> int:
        """Número del DB de parámetros reales: ``3000 + uid``."""
        return 3000 + self.uid

    @property
    def db_pint_numero(self) -> int:
        """Número del DB de parámetros enteros: ``3000 + uid + 1``.

        Se conserva aunque el plan no lo destaque explícitamente
        porque el legacy ya lo usaba (ver ``db_pint_numero`` en
        ``_legacy_reference/ZC_ALM_TOOLS/core/models/software.py``).
        """
        return 3000 + self.uid + 1

    @property
    def db_alm_numero(self) -> int:
        """Número del DB de alarmas: ``5000 + uid``."""
        return 5000 + self.uid

    # ── Properties: nombre simbólico del DB ───────────────────────────
    @property
    def db_preal_nombre(self) -> str:
        """Nombre simbólico del DB de parámetros reales."""
        return f"DB{self.db_preal_numero}_{self.codigo}_PREAL"

    @property
    def db_pint_nombre(self) -> str:
        """Nombre simbólico del DB de parámetros enteros."""
        return f"DB{self.db_pint_numero}_{self.codigo}_PINT"

    @property
    def db_alm_nombre(self) -> str:
        """Nombre simbólico del DB de alarmas."""
        return f"DB{self.db_alm_numero}_{self.codigo}_ALM"

    # ── Properties: nº de palabra HMI para alarmas ────────────────────
    @property
    def alm_hmi(self) -> int:
        """Índice de la palabra HMI de 16 bits donde se mapean las alarmas.

        Regla legacy (preservada): ``max(0, alarmas // 16 - 1)``.

        Casos borde:
            * ``alarmas = 0``  → ``0`` (sin alarmas, sin palabra HMI).
            * ``alarmas = 1``  → ``0`` (entra en la palabra 0).
            * ``alarmas = 16`` → ``0`` (siguen entrando en la palabra 0).
            * ``alarmas = 17`` → ``1`` (saltan a la palabra 1).
            * ``alarmas = 32`` → ``1``.
            * ``alarmas = 100`` → ``5``.
        """
        return max(0, (self.alarmas // 16) - 1)


__all__ = ["ProcesoPLC"]
