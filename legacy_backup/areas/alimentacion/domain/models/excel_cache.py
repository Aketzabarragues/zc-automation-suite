"""DTOs derivados del Excel corporativo del subdominio alimentación.

Este archivo agrupa las dataclasses ``frozen=True`` que representan
las entidades del Excel que el PLC consume (ver plan
``_plan/04_excel_cache_phased_plan.md``):

    * **Fase 1**: ``ProcesoPLC``.
    * **Fase 2**: ``ParamRealPLC``.
    * **Fase 3**: ``ParamIntPLC``.
    * **Fase 4**: ``AlarmaPLC``.
    * **Fase 5**: consolidación de los 6 DTOs de dispositivos
      (``DispED/EA/SA/V/M/M_VF``) + ``Dispositivo`` (Protocol) +
      ``DimensionesDispositivos`` + ``ExcelCache`` (DTO raíz con los
      10 dominios del Excel + lookups precomputados por código).

¿Por qué un solo archivo para todos los DTOs del Excel?
    * El Excel corporativo es **una sola fuente de verdad**: todos los
      DTOs describen el mismo workbook desde ángulos distintos. Tenerlos
      juntos facilita razonar sobre su coherencia (ej. que
      ``ProcesoPLC.uid`` esté alineado con el ``uid`` de los
      ``ParamRealPLC`` de su proceso).
    * El ``ExcelCache`` raíz contiene tuplas con TODOS estos DTOs,
      así que ya estarán importados en el mismo módulo.
    * El test ``test_excel_cache_dto.py`` puede cubrir los 11 DTOs
      en un solo archivo, sin imports cruzados.

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

import dataclasses
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Mapping, Protocol, runtime_checkable


# ── Protocol base ────────────────────────────────────────────────────────


@runtime_checkable
class Dispositivo(Protocol):
    """Contrato común a todo dispositivo instanciable del subdominio.

    Atributos obligatorios (mínimo denominador común):
      - ``numero``: índice secuencial dentro de su hoja Excel.
      - ``plc_tag``: nombre simbólico del PlcTag en TIA Portal.
      - ``plc_comentario``: comentario del PlcTag en TIA Portal.
      - ``descripcion``: descripción legible para el operario.
      - ``uid``: clave de identidad inmutable a través de renombres.

    El modificador offline (``TagTableModifier.remove_tags``) usa ``uid``
    para borrar PlcTags preservando referencias cruzadas del PLC.
    """

    numero: int
    plc_tag: str
    plc_comentario: str
    descripcion: str
    uid: str


# ── Dataclasses frozen de dispositivos (Fase 5) ─────────────────────────


@dataclass(frozen=True)
class DispED:
    """Display Entradas Digitales.

    Representa una instancia discreta de entradas digitales (bits)
    que se inyecta como PlcTag en el PLC.
    """

    # ── Protocol Dispositivo ─────────────────────────────────────────
    numero: int
    plc_tag: str
    plc_comentario: str
    descripcion: str
    uid: str
    # ── Atributos específicos ────────────────────────────────────────
    tag: str = ""
    fat: str = ""
    e_byte: int = 0
    e_bit: int = 0
    gr_alarma: int = 0
    cuadro: str = ""
    observaciones: str = ""
    plc_tipo: str = ""
    plc_index: int = 0
    hmi_index: int = 0
    hmi_texto: str = ""
    # ── Campos SCL (línea completa ``cfg_* := ...;``) ───────────────
    cfg_habilitar: str = ""
    cfg_byte_entrada: str = ""
    cfg_bit_entrada: str = ""
    cfg_grupo_alarma: str = ""
    comentario_db: str = ""


@dataclass(frozen=True)
class DispEA:
    """Display Entradas Analógicas.

    Representa una instancia de entradas analógicas (palabras)
    que se inyecta como PlcTag en el PLC.
    """

    # ── Protocol Dispositivo ─────────────────────────────────────────
    numero: int
    plc_tag: str
    plc_comentario: str
    descripcion: str
    uid: str
    # ── Atributos específicos ────────────────────────────────────────
    tag: str = ""
    fat: str = ""
    e_byte: int = 0
    unidades: str = ""
    rii: float = 0.0  # rango inferior de escalado
    rsi: float = 0.0  # rango superior de escalado
    gr_alarma: int = 0
    cuadro: str = ""
    observaciones: str = ""
    plc_tipo: str = ""
    plc_index: int = 0
    hmi_index: int = 0
    hmi_texto: str = ""
    # ── Campos SCL ──────────────────────────────────────────────────
    cfg_habilitar: str = ""
    cfg_byte_entrada: str = ""
    cfg_escaladomin: str = ""
    cfg_escaladomax: str = ""
    cfg_grupo_alarma: str = ""
    comentario_db: str = ""


@dataclass(frozen=True)
class DispSA:
    """Display Salidas Analógicas.

    Estructura IDÉNTICA a ``DispEA`` (mismos campos y semántica; solo
    cambia el sentido de la variable: salida vs entrada).
    """

    # ── Protocol Dispositivo ─────────────────────────────────────────
    numero: int
    plc_tag: str
    plc_comentario: str
    descripcion: str
    uid: str
    # ── Atributos específicos (idénticos a DispEA) ──────────────────
    tag: str = ""
    fat: str = ""
    e_byte: int = 0
    unidades: str = ""
    rii: float = 0.0
    rsi: float = 0.0
    gr_alarma: int = 0
    cuadro: str = ""
    observaciones: str = ""
    plc_tipo: str = ""
    plc_index: int = 0
    hmi_index: int = 0
    hmi_texto: str = ""
    # ── Campos SCL ──────────────────────────────────────────────────
    cfg_habilitar: str = ""
    cfg_byte_entrada: str = ""
    cfg_escaladomin: str = ""
    cfg_escaladomax: str = ""
    cfg_grupo_alarma: str = ""
    comentario_db: str = ""


@dataclass(frozen=True)
class DispV:
    """Display Variables internas (sin E/S física asociada)."""

    # ── Protocol Dispositivo ─────────────────────────────────────────
    numero: int
    plc_tag: str
    plc_comentario: str
    descripcion: str
    uid: str
    # ── Atributos específicos ────────────────────────────────────────
    tag: str = ""
    fat: str = ""
    s_byte: int = 0
    s_bit: int = 0
    rr_byte: int = 0
    rr_bit: int = 0
    rt_byte: int = 0
    rt_bit: int = 0
    gr_alarma: int = 0
    cuadro: str = ""
    observaciones: str = ""
    plc_tipo: str = ""
    plc_index: int = 0
    hmi_index: int = 0
    hmi_texto: str = ""
    # ── Campos SCL ──────────────────────────────────────────────────
    cfg_habilitar: str = ""
    cfg_byteretornoreposo: str = ""
    cfg_bitretornoreposo: str = ""
    cfg_byteretornotrabajo: str = ""
    cfg_bitretornotrabajo: str = ""
    cfg_byteactivacion: str = ""
    cfg_bitactivacion: str = ""
    cfg_habitreposo: str = ""
    cfg_habitrtrabajo: str = ""
    cfg_grupoalarma: str = ""
    comentario_db: str = ""


@dataclass(frozen=True)
class DispM:
    """Display Motor (digital)."""

    # ── Protocol Dispositivo ─────────────────────────────────────────
    numero: int
    plc_tag: str
    plc_comentario: str
    descripcion: str
    uid: str
    # ── Atributos específicos ────────────────────────────────────────
    tag: str = ""
    fat: str = ""
    s_byte: int = 0
    s_bit: int = 0
    rt_byte: int = 0
    rt_bit: int = 0
    rm_byte: int = 0
    rm_bit: int = 0
    gr_alarma: int = 0
    cuadro: str = ""
    observaciones: str = ""
    plc_tipo: str = ""
    plc_index: int = 0
    hmi_index: int = 0
    hmi_texto: str = ""
    # ── Campos SCL ──────────────────────────────────────────────────
    cfg_habilitar: str = ""
    cfg_byteretornotermico: str = ""
    cfg_bitretornotermico: str = ""
    cfg_byteconfmarcha: str = ""
    cfg_bitconfmarcha: str = ""
    cfg_byteactivacion: str = ""
    cfg_bitactivacion: str = ""
    cfg_habrettermico: str = ""
    cfg_habretconfmarcha: str = ""
    cfg_grupoalarma: str = ""
    comentario_db: str = ""


@dataclass(frozen=True)
class DispM_VF:
    """Display Motor con Variador de Frecuencia (VFD).

    Hereda todos los campos de ``DispM`` y añade ``sa_byte`` y
    ``cfg_byteanalogica`` para el control analógico del variador.
    """

    # ── Protocol Dispositivo ─────────────────────────────────────────
    numero: int
    plc_tag: str
    plc_comentario: str
    descripcion: str
    uid: str
    # ── Atributos heredados de DispM ───────────────────────────────
    tag: str = ""
    fat: str = ""
    s_byte: int = 0
    s_bit: int = 0
    rt_byte: int = 0
    rt_bit: int = 0
    rm_byte: int = 0
    rm_bit: int = 0
    gr_alarma: int = 0
    cuadro: str = ""
    observaciones: str = ""
    plc_tipo: str = ""
    plc_index: int = 0
    hmi_index: int = 0
    hmi_texto: str = ""
    cfg_habilitar: str = ""
    cfg_byteretornotermico: str = ""
    cfg_bitretornotermico: str = ""
    cfg_byteconfmarcha: str = ""
    cfg_bitconfmarcha: str = ""
    cfg_byteactivacion: str = ""
    cfg_bitactivacion: str = ""
    cfg_habrettermico: str = ""
    cfg_habretconfmarcha: str = ""
    cfg_grupoalarma: str = ""
    comentario_db: str = ""
    # ── Campos exclusivos VFD ──────────────────────────────────────
    sa_byte: int = 0
    cfg_byteanalogica: str = ""


# ── Dimensiones (Fase 5) ────────────────────────────────────────────────


# Tabla canónica (hw_type, attr, nmax_name) para los 6 tipos del
# legacy. Mantener como constante de módulo para que el wrapper
# ``DimensionesDispositivos`` pueda traducir entre los nombres que
# el código legacy usa (``num_disp_ed``) y los nombres canónicos del
# PLC (``N_MAX_DISP_ED``).
_LEGACY_HW_TO_NMAX: tuple[tuple[str, str, str], ...] = (
    ("ed",    "num_disp_ed",   "N_MAX_DISP_ED"),
    ("ea",    "num_disp_ea",   "N_MAX_DISP_EA"),
    ("sa",    "num_disp_sa",   "N_MAX_DISP_SA"),
    ("v",     "num_disp_v",    "N_MAX_DISP_V"),
    ("m",     "num_disp_m",    "N_MAX_DISP_M"),
    ("m_vf",  "num_disp_m_vf", "N_MAX_DISP_M_VF"),
)


@dataclass(frozen=True)
class DimensionesDispositivos:
    """Cantidades numéricas de dispositivos por tipo.

    Diseño **extensible** (data-driven):

      - Los **6 tipos canónicos** (``ed/ea/sa/v/m/m_vf``) se exponen
        como campos explícitos ``num_disp_*`` para preservar la API
        legacy y los tests que construyen el dataclass por kwargs.
      - El campo ``extras: dict[str, int]`` almacena N_MAX adicionales
        que vengan del ``n_max_catalog`` del config (futuro:
        ``N_MAX_DISP_FF``, ``N_MAX_DISP_SD``, etc.).
      - El método ``values()`` aplana ambos en un dict
        ``{nombre_nmax: valor}`` listo para alimentar el sync
        unificado y para serializar.
      - ``from_catalog(catalog, raw)`` construye desde el catálogo
        del ``ConfigManager`` y un dict raw (p.ej. del Excel).

    Back-compat:
      - ``DimensionesDispositivos(num_disp_ed=15, num_disp_v=20)`` →
        sigue funcionando idéntico.
      - ``d.num_disp_ed`` → sigue devolviendo ``int``.
      - ``dataclasses.asdict(d)`` → sigue produciendo
        ``{"num_disp_ed": ..., ..., "extras": {...}}``. La SPA ya
        consume ese shape.
    """

    num_disp_ed: int = 0
    num_disp_ea: int = 0
    num_disp_sa: int = 0
    num_disp_v: int = 0
    num_disp_m: int = 0
    num_disp_m_vf: int = 0
    # N_MAX adicionales que no están en los 6 legacy. Las claves son
    # los nombres canónicos del PLC (``N_MAX_DISP_*``). Vacío por
    # defecto para no contaminar la salida de ``asdict`` en configs
    # que aún no tienen extras.
    extras: Mapping[str, int] = field(default_factory=dict)

    # ── Vista unificada (canónica) ────────────────────────────────────

    def values(self) -> dict[str, int]:
        """Devuelve ``{nombre_nmax: valor}`` para los 6 canónicos.

        NO incluye ``extras``: esa es información auxiliar que se
        serializa por separado. Para tener TODO (legacy + extras),
        usar ``all_nmax()``.
        """
        result: dict[str, int] = {}
        for _hw, attr, nmax_name in _LEGACY_HW_TO_NMAX:
            result[nmax_name] = int(getattr(self, attr) or 0)
        return result

    def all_nmax(self) -> dict[str, int]:
        """``values()`` ∪ ``extras``. ``extras`` gana si hay colisión
        (defensa: en un config bien formado, no debería haberla porque
        los nombres legacy ya están como campos)."""
        merged = self.values()
        for k, v in self.extras.items():
            merged[str(k)] = int(v)
        return merged

    def to_api_dict(self) -> dict[str, int]:
        """Serialización para la API pública (SPA, diagnostics).

        Devuelve **solo** los 6 campos legacy ``num_disp_*`` (los
        que la SPA muestra hoy en "Definición programación"): oculta
        el campo ``extras`` (que es interno / futuro) y no expone
        el shape del dataclass crudo. Pensado para sustituir
        ``dataclasses.asdict(self)`` en routers que vuelcan el
        ``AppState`` al frontend.

        Si en el futuro la SPA quiere ver los N_MAX adicionales,
        se expondrá un endpoint nuevo (p.ej. ``/state/nmax_extras``)
        en lugar de contaminar este.
        """
        return {
            attr: int(getattr(self, attr) or 0)
            for _hw, attr, _nmax in _LEGACY_HW_TO_NMAX
        }

    def get(self, nmax_name: str) -> int | None:
        """Lee por nombre canónico (``N_MAX_DISP_*``). ``None`` si no existe.

        Acepta también los nombres legacy ``num_disp_*`` por tolerancia
        a código que aún no haya migrado.
        """
        for _hw, attr, nmax in _LEGACY_HW_TO_NMAX:
            if nmax_name == nmax or nmax_name == attr:
                return int(getattr(self, attr) or 0)
        if nmax_name in self.extras:
            return int(self.extras[nmax_name])
        return None

    # ── Constructores / factorías ──────────────────────────────────────

    @classmethod
    def from_catalog(
        cls,
        catalog: list[dict[str, Any]] | None,
        raw: Mapping[str, int] | None,
    ) -> "DimensionesDispositivos":
        """Construye desde el ``n_max_catalog`` del ConfigManager y un raw.

        Args:
            catalog: lista de entradas del catálogo
                (``{"name", "hw_type", ...}``) o ``None``.
            raw: mapping con valores ``{nombre_nmax_o_legacy: int}``
                (p.ej. lo que devuelve ``ExcelParser.extraer_dimensiones``).

        Returns:
            Instancia con los 6 legacy completados desde raw (si el
            nombre legacy o el ``N_MAX_DISP_*`` aparece) y el resto
            en ``extras``.

        Política:
          - Si el catálogo está vacío o ``None``, se acepta el raw
            tal cual: las claves que coincidan con los nombres legacy
            van a su campo; el resto va a ``extras``.
          - Si el catálogo está presente, las claves del raw que NO
            estén en el catálogo se descartan con ``debug`` (defensa
            contra typos en el Excel).
        """
        raw = dict(raw or {})
        catalog_names: set[str] = set()
        hw_to_attr: dict[str, str] = {}
        if catalog:
            for entry in catalog:
                name = str(entry.get("name", "")).strip()
                hw = str(entry.get("hw_type", "")).strip()
                if name:
                    catalog_names.add(name)
                if hw:
                    # Mapeo hw_type → attr legacy para los 6 conocidos.
                    for _h, attr, nmax in _LEGACY_HW_TO_NMAX:
                        if _h == hw:
                            hw_to_attr[hw] = attr
                            catalog_names.add(nmax)
                            break

        # 1. Rellenar los 6 campos legacy desde raw.
        kwargs: dict[str, Any] = {}
        for _hw, attr, nmax in _LEGACY_HW_TO_NMAX:
            v: int | None = None
            if nmax in raw:
                v = int(raw[nmax])
            elif attr in raw:
                v = int(raw[attr])
            if v is not None:
                kwargs[attr] = v

        # 2. El resto (las claves que NO son los 6 legacy) van a
        # ``extras``. Si hay catálogo, las claves no listadas se
        # descartan (defensa contra typos en el Excel). Si no hay
        # catálogo, aceptamos todo lo que no sea legacy en extras.
        legacy_nmax_names = {nmax for _hw, _attr, nmax in _LEGACY_HW_TO_NMAX}
        extras: dict[str, int] = {}
        for k, v in raw.items():
            if k in legacy_nmax_names:
                continue  # ya consumido por el campo legacy arriba
            if catalog and k not in catalog_names:
                continue  # catálogo presente → descarta claves no listadas
            try:
                extras[str(k)] = int(v)
            except (TypeError, ValueError):
                continue

        return cls(extras=extras, **kwargs)


# ── Fase 1: Procesos ─────────────────────────────────────────────────────


@dataclass(frozen=True)
class ProcesoPLC:
    """DTO de un proceso del PLC (hoja ``CONFIGURACION`` → ``Tabla_Procesos``).

    Un **proceso** es la unidad organizativa del Excel: agrupa un
    conjunto de parámetros reales, parámetros enteros y alarmas que
    se generan juntos en el PLC.

    Campos (todos enteros/str con defaults tolerantes a celdas
    vacías del Excel):
        * ``uid``: identificador entero único (1, 2, 3, …).
        * ``nombre``: nombre legible del proceso.
        * ``codigo``: código corto usado en el nombre de los DBs.
        * ``preal`` / ``index_preal``: nº de parámetros reales y su
          offset dentro del DB PREAL.
        * ``pint`` / ``index_pint``: análogo para parámetros enteros.
        * ``alarmas``: nº de alarmas del proceso.

    Este DTO contiene exclusivamente los 8 campos del Excel
    corporativo. Los nombres de DB y otros valores derivados se
    computan en el consumidor (frontend para mostrar, backend futuro
    para generar XML).

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
          ``_safe_int``. El DB de alarmas de un proceso se nombra
          ``DB{num_db}_{proceso.codigo}_ALM`` donde ``num_db`` viene
          del campo ``num_db`` de cada fila de la tabla ``Alarmas``
          del Excel.
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


# ── Fase 5: ExcelCache (DTO raíz) ───────────────────────────────────────


@dataclass(frozen=True)
class ExcelCache:
    """Raíz del cache IT del Excel corporativo.

    Esta dataclass ``frozen=True`` agrupa TODOS los datos derivados
    del Excel (10 dominios: 6 dispositivos + N_MAX + 4 software) en
    una sola estructura inmutable. Es la **única fuente de verdad**
    que ``ExcelCacheManager`` cachea por proceso.

    Diseño:
        * ``dispositivos``: ``dict[hw_type, tuple[Dispositivo, ...]]``
          (los 6 tipos legacy como ``tuple`` para preservar
          ``frozen=True``).
        * ``n_max``: ``DimensionesDispositivos`` con los 6 contadores
          canónicos + ``extras`` para N_MAX adicionales.
        * ``procesos`` / ``parametros_real`` / ``parametros_int`` /
          ``alarmas``: las 4 listas de software (también ``tuple``).
        * ``*_by_codigo``: lookups ``Mapping[str, DTO]`` precomputados
          en ``ExcelLoader.load`` para evitar O(n) por cada acceso.
        * ``software_parsers_implemented``: flag ``True`` para que la
          SPA detecte si el backend expone los 4 dominios nuevos.

    Atributos:
        excel_path: Ruta absoluta del Excel actualmente cacheado.
        excel_mtime_ns: ``st_mtime_ns`` del Excel (R3 del plan:
            resolución Windows-safe para la invalidación por mtime).
        parsed_at: ``datetime`` UTC del momento del parseo.
        dispositivos: ``{hw_type: tuple[Dispositivo, ...]}``.
        n_max: Cantidades de dispositivos por tipo.
        procesos / parametros_real / parametros_int / alarmas: Listas
            de los 4 dominios de software.
        procesos_by_codigo / parametros_real_by_codigo /
            parametros_int_by_codigo: Lookups precomputados por
            ``codigo`` (Mapping para preservar ``frozen=True``).
        software_parsers_implemented: Flag para la SPA.
    """

    excel_path: str
    excel_mtime_ns: int
    parsed_at: datetime
    dispositivos: dict[str, tuple[Dispositivo, ...]]
    n_max: DimensionesDispositivos
    procesos: tuple[ProcesoPLC, ...]
    parametros_real: tuple[ParamRealPLC, ...]
    parametros_int: tuple[ParamIntPLC, ...]
    alarmas: tuple[AlarmaPLC, ...]
    procesos_by_codigo: Mapping[str, ProcesoPLC]
    parametros_real_by_codigo: Mapping[str, ParamRealPLC]
    parametros_int_by_codigo: Mapping[str, ParamIntPLC]
    software_parsers_implemented: bool = True

    def to_dict(self) -> dict:
        """Serializa las 4 listas a JSON (lookups omitidos, son derivables).

        Returns:
            ``dict`` con ``excel_path``, ``excel_mtime_ns``,
            ``parsed_at`` (ISO), ``n_max`` (vía ``to_api_dict``),
            las 4 listas de software vía ``dataclasses.asdict``, y el
            flag ``software_parsers_implemented``. Los lookups
            precomputados NO se serializan: son derivables iterando
            las listas y son redundantes en la respuesta.
        """
        return {
            "excel_path": self.excel_path,
            "excel_mtime_ns": self.excel_mtime_ns,
            "parsed_at": self.parsed_at.isoformat(),
            "n_max": self.n_max.to_api_dict(),
            "procesos": [dataclasses.asdict(p) for p in self.procesos],
            "parametros_real": [dataclasses.asdict(p) for p in self.parametros_real],
            "parametros_int": [dataclasses.asdict(p) for p in self.parametros_int],
            "alarmas": [dataclasses.asdict(a) for a in self.alarmas],
            "software_parsers_implemented": self.software_parsers_implemented,
        }


__all__ = [
    # Protocol y dimensiones
    "Dispositivo",
    "DimensionesDispositivos",
    # Dataclasses de dispositivos (Fase 5)
    "DispED",
    "DispEA",
    "DispSA",
    "DispV",
    "DispM",
    "DispM_VF",
    # DTOs del Excel (Fases 1-4)
    "ProcesoPLC",
    "ParamRealPLC",
    "ParamIntPLC",
    "AlarmaPLC",
    # DTO raíz (Fase 5)
    "ExcelCache",
]
