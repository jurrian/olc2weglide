import { createApp } from 'vue';
import App from './App.vue';
import router from '../router';
import './assets/main.css';
import './assets/autocomplete.css';
import * as Sentry from "@sentry/vue";
import packageJson from '../package.json';
import PrimeVue from 'primevue/config';
import '@fortawesome/fontawesome-free/css/all.css';
import '@fortawesome/fontawesome-free/js/all.js';

const app = createApp(App);


Sentry.init({
  app,
  dsn: import.meta.env.PROD ? import.meta.env.VITE_SENTRY_DSN : "",
  release: packageJson.version,
  integrations: [
    Sentry.browserTracingIntegration({ router }),
    Sentry.replayIntegration(),
    Sentry.feedbackIntegration({
      colorScheme: "system",
      messagePlaceholder: "Please describe what you were doing when this error occurred. INCLUDE A SCREENSHOT of the error if possible. Unfortunately, I cannot respond to all feedback.",
    }),
  ],
  tracesSampleRate: 0.01,
  tracePropagationTargets: ["localhost", /^https:\/\/olc2weglide\.nl\/api/],
  replaysSessionSampleRate: 0.01,
  replaysOnErrorSampleRate: 1.0,
});

app.use(router).mount('#app');
app.use(PrimeVue);
