<template>
  <h1>Found OLC flights</h1>
  <p>Flights will show here below soon, loading might take a few minutes.<br/>
    If you have a lot of flights and it does not load, try selecting a smaller range.<br />
    Usually some flights do not upload with the first try, usually because the request to OLC times out, select them and <strong>try them again</strong>.
  </p>
  <p>Currently there is a limit of about <strong>~50 flights per time</strong>, capped per year. Try again with the years you are not seeing now.</p>
  <div v-if="loading" class="loader"></div>
  <p v-if="errorMessage" class="error">{{ errorMessage }}</p>
  <div v-if="flights.length > 0">
    <form v-if="!loading" @submit.prevent="submitForm" :disabled="processing">
      <input type="hidden" :value="userId">
      <input type="hidden" :value="startYear">
      <table class="flights">
        <tbody>
          <tr>
            <th><input type="checkbox" @change="toggleAll" v-model="allSelected" /></th>
            <th>OLC ID</th>
            <th class="date">Date</th>
            <th>Glider type</th>
            <th>Registration</th>
            <th>Competition ID</th>
            <th>Distance</th>
            <th>Km/h</th>
            <th>Pilot</th>
            <th>Co-pilot</th>
            <th>Club</th>
            <th>Takeoff</th>
            <th class="result">Status</th>
          </tr>
          <tr v-for="flight in flights" :key="flight.id">
            <td><input type="checkbox" :value="flight.id" v-model="flight.checked" /></td>
            <td><a :href="'https://www.onlinecontest.org/olc-3.0/gliding/flightinfo.html?dsId=' + flight.id" target="_blank">{{ flight.id }}</a></td>
            <td class="date">{{ flight.date }}</td>
            <td>
              <AutoComplete inputClass="plane_type" v-model="flight.airplane_weglide" variant="filled" :suggestions="suggestions" optionLabel="name" @complete="searchGliders" completeOnFocus forceSelection  />
              <br /><span title="From OLC" style="cursor: help">{{ flight.airplane }}</span>
            </td>
            <td><input class="registration" type="text" v-model="flight.registration" /></td>
            <td><input class="registration"  type="text" v-model="flight.competition_id" pattern=".{0,3}" title="Format: 3 chars" /></td>
            <td>{{ flight.distanceInKm }}</td>
            <td>{{ flight.speedInKmH }}</td>
            <td>{{ flight.pilot.firstName }} {{ flight.pilot.surName }}</td>
            <td><input v-if="flight.copilot" type="text" class="copilot" v-model="flight.co_pilot_name" placeholder="Full name" /></td>
            <td>{{ flight.club.name }}</td>
            <td>{{ flight.takeoff.name }}</td>
            <td class="result"><span v-html="flight.result"></span><span v-if="flight.processing" class="indicator"></span></td>
          </tr>
        </tbody>
      </table>

      <table border="0">
        <tbody>
          <tr>
            <td>
              <h2>Weglide</h2>
              <p>Find your Weglide ID here:<br/>
                <a target="_blank" href="https://www.weglide.org/">Weglide</a> > My profile > WeGlide ID (left-bottom next to date joined)
              </p>
              <div class="form-group">
                <label><span>Weglide ID: </span><input v-model="weglideUserId" type="number" placeholder="Weglide ID" required /></label>
              </div>
              <div class="form-group">
                <label><span>Date of birth: </span><input v-model="weglideDateOfBirth" type="date" required /></label>
              </div>
              <input type="submit" value="Upload to WeGlide" :disabled="processing" />
            </td>
            <td>
              <h2>OLC</h2>
              <p>Fill here your OLC <u>username</u> (<strong>not OLC ID as previous page</strong>) and password.<br />These are the same credentials that you use <a target="_blank" href="https://www.onlinecontest.org/olc-3.0/secure/login.html">to login at OLC</a>. Without, OLC will modify the IGC to <u>not</u> be valid.
                <br />Your password will be passed through the server, change your OLC password beforehand if that worries you.</p>
              <div class="form-group">
                <label><span>OLC <u>username</u>: </span><input v-model="olcUser" type="text" placeholder="User name is NOT your OLC ID" pattern=".*[^\d].*" title="Please fill your alphanumeric OLC username not your OLC ID" required /></label>
              </div>
              <div class="form-group">
                <label><span>Password: </span><input v-model="olcPassword" type="text" required /></label>
              </div>
            </td>
          </tr>
        </tbody>
      </table>
    </form>

    <p>A few things to consider:</p>
    <ul class="blue">
      <li>This tool depends heavily on server availability of both WeGlide and OLC, especially OLC has a tendency to time-out requests. Too much requests and time-outs can cause some flights to fail, <strong>try them again later</strong>.</li>
      <li>When the service is overloaded, it will usually return a 504 error. There is nothing else to do than wait.</li>
      <li>Check if the glider type is actually correct, in some cases there could be a mismatch in naming between OLC and WeGlide.</li>
      <li>Valid uploaded flights will <i>not</i> retrospectively count in the rankings, but do count towards total flying distance and hours.</li>
      <li>Flights after 11th of April 2023 will count for WeGlide <a href="https://docs.weglide.org/badges/badges_motivation.html">badges</a>.</li>
      <li>Flights that are already uploaded on WeGlide will be ignored.</li>
      <li>You cannot upload a flight where you are co-pilot, only the PIC can upload to WeGlide.</li>
      <li>This is a free service, I do not offer support. If problems persist: wait a few hours or till next day, still not working? "Report a Bug" right below with a screenshot, due to the amount of reports I will probably not respond.</li>
    </ul>
  </div>
  <div v-else>
    <p v-if="!loading"><strong>No flights found for this user in the selected period, check if the user is correct, go <a href="/">back</a> and try again.</strong></p>
  </div>
</template>

<script>
import axios from 'axios';
import AutoComplete from 'primevue/autocomplete';
import * as Sentry from "@sentry/vue";

export default {
  components: {
    AutoComplete
  },
  data() {
    return {
      userId: this.$route.query.user_id,
      startYear: this.$route.query.start_year,
      endYear: this.$route.query.end_year,
      flights: [],
      weglideUserId: '',
      weglideDateOfBirth: '',
      olcUser: import.meta.env.PROD ? '' : import.meta.env.VITE_OLC_DEFAULT_USER,
      olcPassword: import.meta.env.PROD ? '' : import.meta.env.VITE_OLC_DEFAULT_PASSWORD,
      allSelected: true,
      loading: true,
      errorMessage: '',
      suggestions: [],
      processing: false,
    };
  },
  methods: {
    submitForm() {
      const formData = {
        user_id: this.userId,
        start_year: this.startYear,
        weglide_user_id: this.weglideUserId,
        weglide_dateofbirth: this.weglideDateOfBirth,
        olc_user: this.olcUser,
        olc_password: this.olcPassword,
        flights: this.flights.filter(flight => flight.checked).map(flight => ({
          id: flight.id,
          date: flight.date,
          pilot: flight.pilot.firstName + ' ' + flight.pilot.surName,
          co_pilot: flight.co_pilot_name,
          airplane_weglide: flight.airplane_weglide,
          registration: flight.registration,
          competition_id: flight.competition_id,
          distance: flight.distanceInKm,
          pilot_comment: flight.pilot_comment,
        })),
      };

      if (this.flights.filter(flight => flight.checked).length === 0) {
        this.errorMessage = 'Please select at least one flight to upload.';
        return;
      }

      this.processing = true;
      this.flights.forEach(flight => {
        if (flight.checked) {
          flight.result = 'Pending';
        }
      });

      this.errorMessage = '';
      axios.post('api/upload_flights', formData)
        .then(() => {
          this.pollUploadStatus(this.flights.filter(flight => flight.checked).map(flight => flight.id));
        })
        .catch(error => {
          console.error('Form submission failed:', error);
          Sentry.captureException(error, {
            extra: {
              url: error.config?.url,
              method: error.config?.method,
              status: error.response?.status,
              data: error.response?.data,
            }
          });
          this.errorMessage = 'A problem occurred: ' + error;
          this.flights.forEach(flight => {
            if (flight.checked) {
              flight.result = '';
            }
          });
        });
    },
    pollUploadStatus(flightIds) {
      axios.get('api/upload_status', { params: { flight_ids: flightIds.join(',') } })
        .then(response => {
          let stillProcessing = false;
          flightIds.forEach(flightId => {
            const flight = this.flights.find(f => f.id === flightId);
            if (flight) {
              const flightData = response?.data?.[flightId] || {};
              flight.response = flightData['response'] || null;
              flight.result = flightData['result'] || 'Something went wrong';
              if (response.data[flightId] && response.data[flightId]['status'] && response.data[flightId]['status'] === 'processing') {
                stillProcessing = true;
                flight.processing = true;
              } else {
                flight.processing = false;
              }
            }
          });
          if (stillProcessing) {
            setTimeout(() => {
              this.pollUploadStatus(flightIds);
            }, 5000); // Poll every 5 seconds
          } else {
            this.processing = false;
          }
        })
        .catch(error => {
          console.error('Error polling upload status:', error);
          this.flights.forEach(flight => {
            if (flight.checked) {
              flight.result = 'Server error';
              flight.processing = false;
            }
          });
          Sentry.captureException(error, {
            extra: {
              url: error.config?.url,
              method: error.config?.method,
              status: error.response?.status,
              data: error.response?.data,
            }
          });
          this.errorMessage = 'A problem occurred: ' + (error?.response?.data?.message || error?.message || error);
        });
    },
    searchGliders(event) {
      axios.get('/api/find_gliders', { params: { name: event.query } })
        .then(response => {
          this.suggestions = response?.data || [];
        })
        .catch(error => {
          console.error('Error fetching gliders:', error);
          Sentry.captureException(error, {
            extra: {
              url: error.config?.url,
              method: error.config?.method,
              status: error.response?.status,
              data: error.response?.data,
            }
          });
          return [];
        });
    },
    toggleAll() {
      this.flights.forEach(flight => {
        flight.checked = this.allSelected;
      });
    }
  },
  created() {
    // Fetch flights data from the server
    axios.get('api/fetch_flights', { params: { user_id: this.userId, start_year: this.startYear, end_year: this.endYear } })
      .then(response => {
        this.flights = response?.data || [];
        this.loading = false;
      })
      .catch(error => {
        this.loading = false;
        Sentry.captureException(error, {
          extra: {
            url: error.config?.url,
            method: error.config?.method,
            status: error.response?.status,
            data: error.response?.data,
          }
        });
        console.error('Error fetching flights:', error);
        this.errorMessage = 'A problem occurred: ' + (error?.response?.data?.message || error?.message || error);
      });
  }
};
</script>
