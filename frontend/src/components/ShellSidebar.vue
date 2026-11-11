<script setup>
/**
 * Menu lateral del shell.
 *
 * El menu lo aportan las areas: cada una registra sus vistas y el shell las
 * recoge. Todavia no hay ninguna area registrada, asi que el menu esta
 * vacio.
 *
 * Al pie va el faceplate de progreso, como en la version anterior.
 */
import FaceplateProgreso from "./FaceplateProgreso.vue";
</script>

<template>
  <aside class="w-72 shrink-0 bg-shell-deep text-on-shell flex flex-col">
    <div class="px-4 py-4 border-b border-shell-border">
      <div class="text-[10px] uppercase tracking-widest text-on-shell-faint">ZC Suite</div>
      <div class="text-base font-bold">Automatización TIA</div>
    </div>

    <nav class="flex-1 min-h-0 overflow-y-auto p-3" aria-label="Menú" data-testid="sidebar-menu">
      <p class="text-xs text-on-shell-faint leading-relaxed">
        Todavía no hay áreas registradas. En cuanto se registre la primera, su menú aparecerá
        aquí.
      </p>
    </nav>

    <FaceplateProgreso />
  </aside>
</template>
