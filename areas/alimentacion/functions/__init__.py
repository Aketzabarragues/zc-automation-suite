"""Function Blocks (FBs) del área Alimentación.

Encapsulan los use cases legacy de
``areas/alimentacion/application/use_cases/`` con un state machine
discreto (nStep=10→20→30→99/98) ejecutado por el Engine de
``core/plc/engine.py`` (OB1).

Cada FB:
  - hereda de ``core.plc.function_base.FunctionBase``,
  - overridea ``_tick_locked()`` con la lógica del use case legacy,
  - es best-effort: cada ``await`` se traga excepciones vía el
    wrapper ``tick()`` de la base, transita a ``n_error`` con
    ``error_msg`` poblado,
  - se nombra con prefijo ``function_`` + PascalCase (p. ej.
    ``function_excel_cargar.py`` → ``FunctionExcelCargar``).
"""
