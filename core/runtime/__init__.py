"""Runtime transversal de la app.

Estado global (AppState), buffers de logs y progreso, y el bus SSE
con sus publishers. No es domain: son piezas compartidas por todos
los entrypoints (Flask, supervisor, FBs).
"""
