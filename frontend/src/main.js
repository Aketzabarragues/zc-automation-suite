import { createApp } from "vue";
import { createPinia } from "pinia";
import App from "./App.vue";
import "./style.css";
import { arrancarEventos } from "./eventos.js";

const app = createApp(App);
app.use(createPinia());
app.mount("#app");

/**
 * Modo demo: `?demo=1` en la URL. No se abre el stream de eventos: se
 * simulan, para poder ver el shell sin TIA Portal ni backend.
 */
const demo = new URLSearchParams(window.location.search).get("demo") === "1";

arrancarEventos({ demo });
