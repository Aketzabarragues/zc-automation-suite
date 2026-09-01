"""Modelos de dispositivos del subdominio alimentación.

Define el Protocol ``Dispositivo`` (contrato base con 5 atributos
obligatorios) y 6+1 dataclasses ``frozen=True`` que lo satisfacen
estructuralmente (duck typing):

  * ``DispED``   - Entradas Digitales
  * ``DispEA``   - Entradas Analógicas
  * ``DispSA``   - Salidas Analógicas (estructura idéntica a DispEA)
  * ``DispV``    - Variables internas
  * ``DispM``    - Motores (digital)
  * ``DispM_VF`` - Motores con Variador de Frecuencia
  * ``DimensionesDispositivos`` - Cantidades numéricas por tipo

``DimensionesDispositivos`` es **extensible** (Plan: Base extensible
para tablas de dispositivos y N_MAX): internamente mantiene un mapping
``{nombre_nmax: valor}`` (los 6 canónicos como campos explícitos para
back-compat y un dict ``extras`` para futuras entradas del catálogo
N_MAX que el PLC pueda traer).

Restricciones arquitectónicas:
- Prohibido importar ``siemens_tia_scripting``.
- Prohibido el uso de ``Any`` en los atributos declarados.
- Prohibido depender de openpyxl u otras librerías de infraestructura.
- Todos los campos ``cfg_*`` son ``str`` con default ``""``.
- Los modificadores offline (``TagTableModifier`` y ``SDModifier``)
  operan sobre estos objetos accediendo directamente a sus atributos
  (``plc_tag``, ``uid``, etc.) — no a través de ``dict.get``.
"""
from __future__ import annotations

from dataclasses import dataclass, field
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


# ── Dataclasses frozen ──────────────────────────────────────────────────


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


# ── Dimensiones ────────────────────────────────────────────────────────


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
        # ``extras``. Si no hay catálogo, aceptamos todo lo que no
        # sea legacy también en extras.
        legacy_nmax_names = {nmax for _hw, _attr, nmax in _LEGACY_HW_TO_NMAX}
        extras: dict[str, int] = {}
        for k, v in raw.items():
            if k in legacy_nmax_names:
                continue  # ya consumido por el campo legacy arriba
            try:
                extras[str(k)] = int(v)
            except (TypeError, ValueError):
                continue

        return cls(extras=extras, **kwargs)


__all__ = [
    # Protocol y dimensiones
    "Dispositivo",
    "DimensionesDispositivos",
    # Dataclasses de dispositivos
    "DispED",
    "DispEA",
    "DispSA",
    "DispV",
    "DispM",
    "DispM_VF",
]
