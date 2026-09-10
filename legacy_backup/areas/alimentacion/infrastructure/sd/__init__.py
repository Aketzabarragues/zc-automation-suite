"""Subpaquete `sd` del área de alimentación.

Pieza offline (sin imports de ``siemens_tia_scripting``) responsable
de actualizar los comentarios por instancia de los DBs de dispositivos
(ED, EA, SA, V, M, M_VF) en formato Simatic Source Documents
(``.s7dcl`` / ``.s7res``).

Convención: el prefijo ``disp_`` marca todo lo específico del dominio
"dispositivos" (no del dominio "recetas", "alarmas", etc.).
"""
