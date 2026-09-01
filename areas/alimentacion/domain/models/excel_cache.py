"""DTOs derivados del Excel corporativo del subdominio alimentación.

Este archivo agrupa, **en fases** (ver plan
``_plan/04_excel_cache_phased_plan.md``), las dataclasses ``frozen=True``
que representan las entidades del Excel que el PLC consume:

    * **Fase 1**: ``ProcesoPLC``.
    * **Fase 2**: ``ParamRealPLC``.
    * **Fase 3**: ``ParamIntPLC``.
    * **Fase 4**: ``AlarmaPLC`` (este commit).
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


# ── Fase 2: Parámetros Reales ────────────────────────────────────────────


@dataclass(frozen=True)
class ParamRealPLC:
    """DTO de un parámetro real del PLC (hoja ``P_REAL`` → ``Tabla_PReal``).

    Un **parámetro real** es una variable ``REAL`` (32 bits, IEEE 754)
    que el PLC expone al HMI y que el operario puede ajustar en
    runtime (típicamente un setpoint, un límite o un factor de
    escalado). Se agrupa en un DB por proceso:

        * ``DB{num_db}_{codigo}_PREAL`` (uno por proceso, contiene
          varios ``ParamRealPLC`` consecutivos).

    Diferencia con ``ProcesoPLC``: ``ParamRealPLC`` **NO** tiene
    properties derivadas (``db_*_numero``, ``db_*_nombre``). La
    razón es que cada ``ParamRealPLC`` tiene ya su ``num_db``
    explícito en el Excel (no se infiere de un ``uid``), así que la
    lógica de derivación de nombres de DB vive en el caller
    (``ProcesoPLC`` agrupa los ``ParamRealPLC`` y conoce su
    ``num_db`` raíz). Esta separación se documenta explícitamente
    en el plan §6.3.

    Campos:
        * ``uid``: identificador único **str** (``'PR_1_001'``, etc.).
          A diferencia de ``ProcesoPLC.uid`` (int), el UID de los
          parámetros es str porque así lo emite el corporativo.
        * ``numero``: nº lógico del parámetro dentro del proceso
          (``"001"``, ``"002"``, …) tal como aparece en el Excel.
        * ``proceso``: nombre del proceso al que pertenece
          (referencia lógica a ``ProcesoPLC.nombre``).
        * ``codigo``: código corto del proceso, reutilizado para
          componer el nombre del DB.
        * ``num_db``: nº del DB donde se mapea este parámetro
          (``int``). Provisto por el Excel; el parser lo lee con
          ``_safe_int``.
        * ``producto``: nombre del producto / línea donde se
          consume el parámetro.
        * ``tipo``: clasificación funcional (``"Setpoint"``,
          ``"Limite"``, …).
        * ``descripcion``: descripción legible para el operario.
        * ``comentario_db``: comentario que se vuelca como
          PlcComment del DB (no del tag).
        * ``visibilidad``: flag que indica si el parámetro es
          visible en el HMI (``"Si"`` / ``"No"``).
        * ``num_lista``: índice de la lista HMI donde el operario
          puede elegir valores predefinidos. **CRÍTICO**: este
          campo es ``int | str`` (no solo ``int``). Valores como
          ``"N/A"`` o ``"TODOS"`` son marcadores semánticos que el
          operario usa para listas de selección; el helper
          ``_safe_num_lista`` los preserva literalmente. Ver plan
          §6.4 y §2.2.
        * ``txt_lista``: texto libre asociado a ``num_lista``
          (etiqueta visible en el HMI, o descripción de la lista).
    """

    uid: str
    numero: str
    proceso: str
    codigo: str
    num_db: int
    producto: str
    tipo: str
    descripcion: str
    comentario_db: str
    visibilidad: str
    num_lista: int | str
    txt_lista: str


# ── Fase 3: Parámetros Enteros ────────────────────────────────────────────


@dataclass(frozen=True)
class ParamIntPLC:
    """DTO de un parámetro entero del PLC (hoja ``P_INT`` → ``Tabla_PInt``).

    Un **parámetro entero** es una variable ``DINT``/``INT`` (32/16 bits)
    que el PLC expone al HMI y que el operario puede ajustar en
    runtime (típicamente un contador, un índice o un factor de
    escalado discreto). Se agrupa en un DB por proceso:

        * ``DB{num_db}_{codigo}_PINT`` (uno por proceso, contiene
          varios ``ParamIntPLC`` consecutivos).

    Shape idéntico a ``ParamRealPLC`` (12 campos, mismos nombres,
    mismos defaults), pero **tipo distinto en Python** (R4 del plan,
    resuelto por el operario el 2026-09-01): ``ParamIntPLC`` y
    ``ParamRealPLC`` son nominalmente dos dataclasses separadas.
    ``isinstance(ParamIntPLC(...), ParamRealPLC) == False``.

    Razón de la separación (R4): si en el futuro se quiere añadir
    ``rango_min``/``rango_max`` solo a ``ParamRealPLC`` (derivados
    de ``DispEA.RII``/``DispEA.RSI``), se hace sin tocar
    ``ParamIntPLC``. Mantener los DTOs como tipos nominales
    distintos en Python garantiza que ``isinstance`` los trate por
    separado y que extender uno no obligue a extender el otro
    aunque hoy coincidan en campos.

    Diferencia con ``ProcesoPLC``: ``ParamIntPLC`` **NO** tiene
    properties derivadas (igual que ``ParamRealPLC``). La razón es
    la misma: cada ``ParamIntPLC`` tiene ya su ``num_db`` explícito
    en el Excel (no se infiere de un ``uid``), así que la lógica de
    derivación de nombres de DB vive en el caller
    (``ProcesoPLC`` agrupa los ``ParamIntPLC`` y conoce su
    ``num_db`` raíz).

    Campos:
        * ``uid``: identificador único **str** (``'PI_1_001'``, etc.).
          A diferencia de ``ProcesoPLC.uid`` (int), el UID de los
          parámetros es str porque así lo emite el corporativo.
        * ``numero``: nº lógico del parámetro dentro del proceso
          (``"001"``, ``"002"``, …) tal como aparece en el Excel.
        * ``proceso``: nombre del proceso al que pertenece
          (referencia lógica a ``ProcesoPLC.nombre``).
        * ``codigo``: código corto del proceso, reutilizado para
          componer el nombre del DB.
        * ``num_db``: nº del DB donde se mapea este parámetro
          (``int``). Provisto por el Excel; el parser lo lee con
          ``_safe_int``.
        * ``producto``: nombre del producto / línea donde se
          consume el parámetro.
        * ``tipo``: clasificación funcional (``"Contador"``,
          ``"Indice"``, …).
        * ``descripcion``: descripción legible para el operario.
        * ``comentario_db``: comentario que se vuelca como
          PlcComment del DB (no del tag).
        * ``visibilidad``: flag que indica si el parámetro es
          visible en el HMI (``"Si"`` / ``"No"``).
        * ``num_lista``: índice de la lista HMI donde el operario
          puede elegir valores predefinidos. **CRÍTICO**: este
          campo es ``int | str`` (no solo ``int``). Valores como
          ``"N/A"`` o ``"TODOS"`` son marcadores semánticos que el
          operario usa para listas de selección; el helper
          ``_safe_num_lista`` los preserva literalmente. Mismo
          contrato que ``ParamRealPLC.num_lista``.
        * ``txt_lista``: texto libre asociado a ``num_lista``
          (etiqueta visible en el HMI, o descripción de la lista).
    """

    uid: str
    numero: str
    proceso: str
    codigo: str
    num_db: int
    producto: str
    tipo: str
    descripcion: str
    comentario_db: str
    visibilidad: str
    num_lista: int | str
    txt_lista: str


# ── Fase 4: Alarmas ───────────────────────────────────────────────────────


@dataclass(frozen=True)
class AlarmaPLC:
    """DTO de una alarma del PLC (hoja ``ALARMAS`` → ``Tabla_Alarmas``).

    Una **alarma** es un bit de un DB de alarmas (``DB{num_db}``) que
    el HMI monitoriza para señalizar un evento. Las alarmas se
    agrupan en un DB por proceso:

        * ``DB{num_db}_{proceso_codigo}_ALM`` (uno por proceso,
          contiene varios ``AlarmaPLC`` consecutivos en una
          ``ARRAY[0..N] OF BOOL`` o similar).

    Diferencia con ``ParamRealPLC`` / ``ParamIntPLC``: ``AlarmaPLC``
    es **más simple** (7 campos, sin ``Visibilidad``/``Producto``/
    ``Tipo``/``num_lista``/``txt_lista``). La razón es histórica: el
    legacy TUI (``_legacy_reference/ZC_ALM_TOOLS/core/models/
    software.py``) define ``Alarma`` con solo 6 columnas en la
    ``ListObject`` (``UID``, ``Numero``, ``Proceso``, ``Num.DB``,
    ``Descripcion``, ``ComentarioDB``); ``Visibilidad`` no existe en
    esta tabla.

    Diferencia con ``ProcesoPLC``: ``AlarmaPLC`` **NO** tiene
    properties derivadas (``db_*_numero``, ``db_*_nombre``) — igual
    que ``ParamRealPLC`` y ``ParamIntPLC``. La razón es la misma:
    cada ``AlarmaPLC`` tiene ya su ``num_db`` explícito en el Excel
    (no se infiere de un ``uid``), así que la lógica de derivación
    de nombres de DB vive en el caller (``ProcesoPLC`` agrupa las
    ``AlarmaPLC`` y conoce su ``num_db`` raíz).

    Esta dataclass forma parte del cache del Excel (ver Fase 5 del
    plan) y es la **implementación de referencia** que los 6 mini
    parsers de dispositivos (Fase 5.3) imitarán en estructura
    (1:1 respecto a ``PRealParser``/``PIntParser`` pero con menos
    campos y DTO específico).

    Campos:
        * ``uid``: identificador único **str** (``'AL_1_001'``, etc.).
          A diferencia de ``ProcesoPLC.uid`` (int), el UID de las
          alarmas es str porque así lo emite el corporativo.
        * ``numero``: nº lógico de la alarma dentro del proceso
          (``"001"``, ``"002"``, …) tal como aparece en el Excel.
        * ``proceso``: nombre del proceso al que pertenece la alarma
          (referencia lógica a ``ProcesoPLC.nombre``).
        * ``num_db``: nº del DB de alarmas donde se mapea este bit
          (``int``). Provisto por el Excel; el parser lo lee con
          ``_safe_int``. Coherente con
          ``ProcesoPLC.db_alm_numero = 5000 + uid``.
        * ``descripcion``: descripción legible de la alarma (visible
          en el HMI cuando se activa).
        * ``comentario_db``: comentario que se vuelca como
          ``PlcComment`` del DB de alarmas (no del bit individual).

    R-F4.1 (defensa contra schema drift): si el Excel del
    corporativo incluye en el futuro una columna ``Visibilidad`` en
    ``Tabla_Alarmas``, el parser la **ignora silenciosamente** (no
    la recoge, no rompe la carga). El DTO ``AlarmaPLC`` NO tiene
    atributo ``visibilidad`` por diseño — esta es una invariante
    contractual que el test ``test_sin_visibilidad_en_dto`` y
    ``test_columna_visibilidad_en_excel_se_ignora`` verifican.
    """

    uid: str
    numero: str
    proceso: str
    num_db: int
    descripcion: str
    comentario_db: str


__all__ = ["ProcesoPLC", "ParamRealPLC", "ParamIntPLC", "AlarmaPLC"]
