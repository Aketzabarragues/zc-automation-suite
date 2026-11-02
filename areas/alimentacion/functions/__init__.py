"""Function Blocks (FBs) del area Alimentacion.

Unidad de trabajo del runtime de tres pilares (HMI -> pulsador -> OB1
-> FB -> WORKER TIA). Cada FB:
  - hereda de ``core.composition.plc_function_base.FunctionBase``,
  - implementa los hooks SYNC ``on_start`` / ``on_finish`` y un
    metodo por step, declarado con ``@step``,
  - lo ejecuta el dispatcher ``Engine``
    (``core/composition/plc_engine.py``) desde su hilo ``plc-ob1``:
    el router encola el trabajo con ``submit()`` y el dispatcher lo
    ejecuta con ``fb.execute(**params)``,
  - es best-effort: ``execute()`` captura las excepciones de runtime,
    las deja en ``error_msg`` y transiciona a ``n_error``,
  - se nombra con prefijo ``function_`` + PascalCase (p. ej.
    ``function_excel_cargar.py`` -> ``FunctionExcelCargar``).

Cada handler de step devuelve su detail (el texto que ve el
operario). Si devuelve una corrutina, el base lanza ``TypeError``: los
FBs corren en un hilo dedicado, no en un event loop.
"""
