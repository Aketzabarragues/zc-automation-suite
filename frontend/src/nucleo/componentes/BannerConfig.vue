<script setup>
/**
 * Banner rojo de configuracion incompatible.
 *
 * Sale cuando el `config.json` del operario no vale: le falta la seccion de
 * un area registrada. El config **no** se sustituye nunca, asi que el aviso
 * dice que hacer en vez de arreglarlo solo.
 */
import { onMounted } from "vue";
import { useConfigStore } from "../stores/config.js";

const config = useConfigStore();

onMounted(() => {
  config.cargar();
});
</script>

<template>
  <div
    v-if="config.incompatible"
    class="bg-red-500 text-ink-inverse px-6 py-2 text-sm flex items-start gap-3 shrink-0"
    data-testid="banner-config"
    role="alert"
  >
    <span class="font-bold uppercase tracking-wider shrink-0">Configuración</span>
    <span class="min-w-0">{{ config.motivo }}</span>
  </div>
</template>
