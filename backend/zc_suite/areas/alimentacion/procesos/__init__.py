"""El subdominio de procesos: la prevision contra el Excel.

- ``mapa.py``  los nombres canonicos TIA, los mapas de slots y los N_MAX
  de un proceso (funciones puras).
- ``diferencias.py``  el diff entre TIA y el Excel (funciones puras).
- ``sincronizacion.py``  las operaciones que hay que aplicar y la edicion
  offline de los ficheros.
- ``clonacion.py``  el renombrado de una plantilla TIA para crear un
  proceso nuevo (funciones puras).
- ``plantillas.py``  el manifest de una plantilla TIA y sus validaciones
  (funciones puras).

Los trabajos que exportan y calculan no viven aqui: estan en
``../funciones/procesos/`` (``generar_prevision.py`` y
``generar_prevision_crear.py``).
"""
from __future__ import annotations

#: Clave de la ultima prevision de procesos en la sesion del backend.
#: Se guarda al generarla y se borra al subir otro Excel, al cambiar de PLC
#: y al perder TIA (como ``preview_disp`` en main).
CLAVE_PREVISION = "prevision_procesos"

#: Clave de la ultima prevision de CREAR un proceso desde plantilla en la
#: sesion del backend. Como ``CLAVE_PREVISION``: se guarda al generarla y se
#: borra al subir otro Excel, al cambiar de PLC y al perder TIA.
CLAVE_PREVISION_CREAR = "prevision_crear_proceso"
