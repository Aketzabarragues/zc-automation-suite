"""El subdominio de entidades: la prevision contra el Excel.

- ``diferencias.py``  el diff entre TIA y el Excel (funciones puras).
- ``sincronizacion.py``  las operaciones que hay que aplicar y la edicion
  offline de los ficheros.

El trabajo que exporta y calcula el diff no vive aqui: esta en
``../funciones/entidades/generar_prevision.py``.
"""
from __future__ import annotations

#: Clave de la ultima prevision de entidades en la sesion del backend.
#: Se guarda al generarla y se borra al subir otro Excel, al cambiar de PLC
#: y al perder TIA (como ``preview_disp`` en main).
CLAVE_PREVISION = "prevision_entidades"
