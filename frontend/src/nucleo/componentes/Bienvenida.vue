<script setup>
/**
 * Pantalla de inicio: selector de area.
 *
 * Fondo navy a pantalla completa, sin barra lateral. El logo va en una
 * tarjeta blanca y debajo una tarjeta por area. Clic en un area: entra en
 * su vista de inicio.
 */
import { useAreasStore } from "../stores/areas.js";

const areas = useAreasStore();
</script>

<template>
  <section
    class="flex-1 w-full flex flex-col items-center justify-center bg-shell text-white p-6 md:p-12 overflow-y-auto"
    data-testid="bienvenida"
  >
    <div class="w-full max-w-6xl mx-auto flex flex-col items-center">
      <div class="text-center mb-6">
        <div class="bg-white inline-block p-7 md:p-9 rounded-xl shadow-sm mb-10">
          <img
            src="/logo-zeus-control.png"
            alt="Zeus Control"
            class="h-28 md:h-36 object-contain"
          />
        </div>

        <h1 class="text-4xl md:text-5xl font-bold mb-4 tracking-tight text-white">Zeus Control</h1>
        <p class="text-on-shell-muted text-lg max-w-2xl mx-auto mb-2 font-light">
          Plataforma de Ingeniería, Sincronización y Generación de Código TIA Portal.
        </p>

        <div class="flex items-center justify-center gap-4 mt-8 opacity-80">
          <div class="h-px w-8 bg-white/30"></div>
          <p class="text-on-shell-muted text-sm font-semibold tracking-widest uppercase">
            Selecciona un área para comenzar
          </p>
          <div class="h-px w-8 bg-white/30"></div>
        </div>
      </div>

      <div
        class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-5 w-full mt-10"
        data-testid="bienvenida-areas"
      >
        <button
          v-for="area in areas.areas"
          :key="area.id"
          type="button"
          :aria-label="'Acceder a ' + area.nombre"
          :data-area-key="area.id"
          class="bg-white text-left p-5 rounded-lg border border-line transition-all duration-200 focus:outline-none focus:ring-2 focus:ring-accent focus:ring-offset-2 focus:ring-offset-white hover:border-accent hover:shadow-lg cursor-pointer"
          @click="areas.entrar(area.id)"
        >
          <div class="text-3xl mb-3 text-accent">{{ area.icono }}</div>
          <h3 class="text-shell font-bold text-lg mb-1">{{ area.nombre }}</h3>
          <p class="text-ink-muted text-sm leading-relaxed">{{ area.descripcion }}</p>
        </button>

        <div
          v-if="areas.areas.length === 0"
          class="col-span-full text-center mt-4 p-8 border-2 border-dashed border-white/20 rounded-lg bg-white/5"
        >
          <p class="text-on-shell-muted text-xl font-semibold mb-2">No hay áreas configuradas</p>
          <p class="text-on-shell-faint text-sm">
            Verifica el catálogo del backend para habilitar los módulos.
          </p>
        </div>
      </div>

      <footer class="mt-16 text-on-shell-faint/60 text-xs font-mono tracking-widest text-center">
        v1.0.0 • Zeus Control
      </footer>
    </div>
  </section>
</template>
