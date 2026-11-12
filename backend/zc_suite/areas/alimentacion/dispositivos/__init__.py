"""El subdominio de dispositivos: la prevision contra el Excel.

- ``diferencias.py``  el diff entre TIA y el Excel (funciones puras).
- ``catalogo.py``  las pestañas y las tarjetas de N_MAX del area.

El trabajo que exporta y calcula el diff no vive aqui: esta en
``../funciones/dispositivos/generar_prevision.py``.
"""
from __future__ import annotations

#: Clave de la ultima prevision de dispositivos en la sesion del backend.
#: Se guarda al generarla y se borra al subir otro Excel, al cambiar de PLC
#: y al perder TIA (como ``preview_disp`` en main).
CLAVE_PREVISION = "prevision_dispositivos"
