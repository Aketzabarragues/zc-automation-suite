<script setup>
/**
 * Shell de la SPA: menu lateral, barra superior, columna central y consola de
 * trazabilidad.
 */
import ConsolaLogs from "./components/ConsolaLogs.vue";
import ShellSidebar from "./components/ShellSidebar.vue";
import ShellTopbar from "./components/ShellTopbar.vue";
import VistaInicio from "./vistas/VistaInicio.vue";
</script>

<template>
  <div class="flex h-screen overflow-hidden bg-surface text-ink">
    <ShellSidebar />

    <div class="flex flex-1 flex-col min-w-0">
      <ShellTopbar />

      <main class="flex-1 min-h-0 overflow-y-auto p-5">
        <VistaInicio />
      </main>

      <ConsolaLogs />
    </div>
  </div>
</template>
