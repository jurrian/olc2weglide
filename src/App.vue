<template>
  <div id="app">
    <div class="container">
      <router-view></router-view>
      <div class="version">{{ version }}</div>
    </div>
  </div>
  <div class="social-links">
    <a href="https://github.com/jurrian/olc2weglide" target="_blank" rel="noopener"><img src="https://cdn.jsdelivr.net/gh/devicons/devicon/icons/github/github-original.svg" alt="GitHub"/></a>
    |
    <a href="https://www.weglide.org/user/12031" target="_blank" rel="noopener"><img src="https://www.weglide.org/favicon.ico" alt="Weglide"/></a>
  </div>
</template>

<script>
import packageJson from '../package.json';
export default {
  name: 'App',
  data() {
    return {
      version: packageJson.version
    };
  }
};
</script>
