"""Bounded Context "Alimentación" - Frontend SPA.

Este paquete contiene los componentes Vue 3 y el ``manifest.js``
del área de alimentación. El shell SPA (``core/interfaces/web_server/static/js/main.js``)
los carga dinámicamente vía ``area-loader.js`` sin imports hardcoded.

- ``manifest.js``     — exporta ``build()`` con la lista de loaders
  (``() => import('./components/<X>.js')``) y el shape
  ``{components, views, ...}``.
- ``components/``     — los 4 .js de Vue 3: Sidebar, AreaLanding,
  DefinicionProgramacion, Dispositivos. Cada uno declara ``name:``
  (p. ej. ``AlimentacionSidebar``) y se registra por nombre en
  la app Vue.
"""
