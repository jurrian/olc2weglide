import { createRouter, createWebHistory } from 'vue-router';
import Start from '@/components/Start.vue';
import OlcFlights from '@/components/OlcFlights.vue';

const routes = [
  {
    path: '/',
    name: 'Start',
    component: Start
  },
  {
    path: '/confirm',
    name: 'Confirm',
    component: OlcFlights
  }
];

const router = createRouter({
  history: createWebHistory(),
  routes
});

export default router;
