<template>
  <h1>Migrate your OLC flights to WeGlide</h1>
  <p>
    This tool is stable but depends on the availability and load of OLC and WeGlide to function properly.<br />
    High traffic on those servers can occasionally cause timeouts or errors.
  </p>
  <p>
    The project is open-source and written in Python + Vue.js, it is in maintenance mode;<br />
    small bugs can be reported <a href="https://github.com/jurrian/olc2weglide/issues" target="_blank">here</a>, but no new features will be added by the maintainer.
  </p>
  <p>
    You are invited to view the source code on <a href="https://github.com/jurrian/olc2weglide" target="_blank">GitHub</a>.<br />
    Contributions and new features from the community are very welcome and encouraged!
  </p>

  <h2>How to use</h2>
  <ol>
    <li>Find and fill your OLC ID (log-in and go to <a target="_blank" href="https://www.onlinecontest.org/olc-3.0/secure/memberadmin.html">your settings</a> in OLC, fill the "Id" value below)</li>
    <li>Fill the scoring season years you want to search</li>
    <li>Select which flights you want to migrate</li>
    <li>View your created flights on WeGlide!</li>
  </ol>

  <form @submit.prevent="submitForm">
    <div class="form-group">
      <label for="user_id">OLC ID:</label>
      <input id="user_id" v-model="userId" type="number" required />
    </div>
    <div class="form-group">
      <label for="start_year">Scoring season* (how far back to search OLC):</label>
      <input id="start_year" v-model.number="startYear" type="number" min="2007" max="2030" step="1" required />
      <input id="end_year" v-model.number="endYear" type="number" min="2007" max="2030" step="1" />
      <p><strong>Currently there is a limit of ~200 flights per time, please do not select too many years or you will get an error!</strong></p>
      <p><small>* OLC scoring period ends 12 days before the first Saturday in October. Older flights than 2007 cannot be retrieved using this tool.</small></p>
    </div>
    <div><input type="submit" value="Ok"/></div>
  </form>

  <div v-if="statusMessage !== '' && statusMessage !== 'None'" class="warning-box">
    <i class="fas fa-exclamation-triangle"></i>
    <span>{{ statusMessage }}. <a href="https://stats.uptimerobot.com/8iuRfXYQgP">Status page</a></span>
  </div>
  <div v-else-if="statusMessage === 'None'" class="success-box" title="OLC was not blocking in the last 10 minutes">
    <i class="fas fa-check-circle"></i>
    <span><a href="https://stats.uptimerobot.com/8iuRfXYQgP">System operational</a></span>
  </div>
</template>

<script>
import * as Sentry from "@sentry/vue";

export default {
  data() {
    return {
      userId: import.meta.env.PROD ? '' : '81464',
      startYear: 2024,
      endYear: 2024,
      statusMessage: '',
    };
  },
  methods: {
    submitForm() {
      Sentry.setUser({ id: this.userId });
      this.$router.push({
        name: 'Confirm',
        query: {
          user_id: this.userId,
          start_year: this.startYear,
          end_year: this.endYear
        }
      });
    },
    async checkStatus() {
      this.statusMessage = '⏳ Checking for status..';
      try {
        const response = await fetch('/api/status');
        if (!response.ok) {
          const data = await response.json();
          if (!data.fetch_flights || !data.fetch_igc) {
            this.statusMessage = 'OLC is overloaded or blocking the service, try again later';
          }
        } else {
          this.statusMessage = 'None';
        }
      } catch (error) {
        Sentry.captureException(error)
        this.statusMessage = `Error occurred, try again later`;
      }
    },
  },
  mounted() {
    // this.checkStatus();
  },
};
</script>

<style scoped>
.form-group {
  margin-bottom: 1em;
}
</style>
