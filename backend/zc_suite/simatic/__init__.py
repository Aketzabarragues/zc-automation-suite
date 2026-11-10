"""simatic — ficheros exportados por TIA Portal, leidos y modificados offline.

- ``simatic_sd/``  bloques exportados en SimaticSD (``.s7dcl`` + ``.s7res``).
- ``simatic_ml/``  tags, tablas y datos exportados en SimaticML (``.xml``).

Este paquete es offline: no habla con el portal y no importa
``siemens_tia_scripting``. Recibe rutas de fichero y devuelve datos.
"""
