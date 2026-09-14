"""Shell web Flask para el modelo OB1.

El modulo expone ``create_app(tia_client, engine, event_bus, ...)``
como factory de la ``Flask``. Carga:

  - 3 endpoints base en la raiz (``/ping``, ``/cycle_count``, ``/stream``).
  - 7 blueprints registrados en ``app_flask._register_blueprints``
    (areas, area_manifests, catalog, diagnostics, plc, portal,
    tia_connection) bajo ``/api/v1/...``.
  - SPA Vue 3 servida desde ``static/`` (raiz + catch-all client-side).
  - Estaticos de areas desde ``/static/areas/<area>/...``
    (apunta a ``<repo_root>/areas/<area>/...``).

Las dependencias se inyectan por argumento o se resuelven lazy al
primer acceso desde un endpoint (via ``current_app.config['_LAZY_*']``).
El werkzeug se levanta con ``threaded=True`` desde
``core.launcher.main_supervisor``: el SSE de larga vida no bloquea
las demas requests HTTP.
"""
