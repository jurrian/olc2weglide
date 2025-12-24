import logging
from datetime import date
from typing import TextIO

import os
import requests
import sentry_sdk
from requests import JSONDecodeError
from requests.cookies import RequestsCookieJar
from requests_oauth2client import OAuth2Client, OAuth2ResourceOwnerPasswordAuth
from sentry_sdk import capture_exception, new_scope

from gliders import gliders
from misc import make_link_if_url


class WeglideResponseError(Exception):
    def __init__(self, *args, error=None, error_description=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.error = error
        self.error_description = error_description


class WeglideInterface:
    """Interface to interact with WeGlide.

    Ensure to set USER_AGENT_EMAIL to identify yourself to WeGlide, in case of problems.
    Obtain a WEGLIDE_CLIENT_ID from WeGlide: https://api.weglide.org/redoc#tag/auth
    """
    def __init__(self, username: str = None, password: str = None):
        self.username = username
        self.password = password
        self.client_id = os.environ['WEGLIDE_CLIENT_ID']

        try:
            user_agent_email = os.environ["USER_AGENT_EMAIL"]
        except KeyError:
            raise ValueError("Fill your USER_AGENT_EMAIL in the .env file")

        self.base = 'https://api.weglide.org/v1/'
        self.session = requests.Session()
        self.session.headers = {
            'user-agent': f'OLCtoWeglide ({user_agent_email})',
        }
        self.cookie_jar = RequestsCookieJar()
        # Allow requests without auth
        if self.username and self.password:
            oauth2client = OAuth2Client(token_endpoint=self.base + 'auth/token', client_id=self.client_id)
            auth = OAuth2ResourceOwnerPasswordAuth(
                oauth2client, username=self.username, password=self.password, scope='declare upload', resource=self.base)
            self.session.auth = auth

    def _update_cookies(self, response):
        self.cookie_jar.update(response.cookies)
        self.session.cookies.clear()

    def set_flight_cookie(self, flight_id: int):
        cookie_name = f'edit_flight_{flight_id}'
        if cookie_name in self.cookie_jar:
            self.session.cookies.update({cookie_name: self.cookie_jar[cookie_name]})

    def upload_igc(self, filename: str, file: TextIO, user_id: int, date_of_birth: str):
        # TODO: verify IGC data against OLC to detect differences

        with sentry_sdk.start_span(op='request', name='upload_igc') as span:
            span.set_data('upload_igc_user', user_id)
            span.set_data('upload_igc_date_of_birth', date_of_birth)
            span.set_data('upload_igc_filename', filename)
            response = self.session.post(self.base + 'igcfile', files={'file': (filename, file)}, data={
                'user_id': user_id,
                'date_of_birth': date_of_birth,
            })
            self._update_cookies(response)
            with new_scope() as scope:
                scope.set_extra("request_headers", dict(response.request.headers))
                scope.set_extra('response', response.text)
                try:
                    response.raise_for_status()
                    if not response.text:
                        raise WeglideResponseError('Empty response from WeGlide')
                    json_response = response.json()
                except JSONDecodeError as e:
                    logging.error(f'JSONDecodeError: {response.text}')

                    capture_exception(e)
                    span.set_data("request_headers", dict(response.request.headers))
                    span.set_data('error', "JSONDecodeError")
                    span.set_data('upload_igc_fail', 1)
                    raise WeglideResponseError(f'Could not parse JSON response: {e}') from e
                except requests.HTTPError as e:
                    try:
                        json_response = response.json()
                        error = make_link_if_url(json_response.get('error', ''))
                        error_description = make_link_if_url(json_response.get('error_description', ''))
                        span.set_data('error', error)
                        span.set_data('upload_igc_already_uploaded', 1)
                        raise WeglideResponseError(
                            f'{error or error_description or response.text}',
                            error=error, error_description=error_description
                        ) from e
                    except JSONDecodeError:
                        pass

                    span.set_data('error', 'HTTPError')
                    span.set_data('upload_igc_fail', 1)
                    capture_exception(e)
                    raise WeglideResponseError(
                        'WeGlide could not process the request, problem has been reported. Try again later',
                        error_description=response.text
                    ) from e
            # WeGlide splits into multiple flights when detecting multiple takeoffs
            # Just reference the first flight for now
            span.set_data('upload_igc_success', len(json_response))
            return json_response[0]

    def post_comment(self, flight_id: int, comment: str):
        with sentry_sdk.start_span(op='request', name='post_comment') as span:
            if not comment:
                return
            self.set_flight_cookie(flight_id)
            response = self.session.post(f'{self.base}comment/flight/{flight_id}', json={
                'comment': comment,
                'pinned': True
            })
            response.raise_for_status()

    def search(self, documents, search_items, limit=1):
        with sentry_sdk.start_span(op='request', name='seach') as span:
            response = self.session.post(f'{self.base}search', json={
                "search_items": search_items,
                "limit": limit,
                "documents": documents,
            })
            json_response = response.json()
            response.raise_for_status()
            return json_response

    def search_user(self, fullname: str):
        with sentry_sdk.start_span(op='request', name='search_user') as span:
            results = self.search('user', [{
                "key": "name",
                "value": fullname,
            }])
            assert len(results) == 1, 'Multiple search results returned'
            try:
                return results[0]
            except IndexError:
                return None

    def search_flight(self, user_id: int, scoring_date: date, registration: str, distance: float):
        with sentry_sdk.start_span(op='request', name='search_flight') as span:
            distance = int(distance)
            response = self.session.get(f'{self.base}flight', params={
                'user_id_in': user_id,
                'scoring_date_in': scoring_date,
                'registration_in': registration,
                'distance_gt': distance - 3,
                'distance_lt': distance + 3,
            })
            json_response = response.json()
            response.raise_for_status()
            assert len(json_response) == 1, 'More than one flight returned'
            return json_response[0]

    def patch_flightdata(self, flight_id, data):
        with sentry_sdk.start_span(op='request', name='patch_flightdata') as span:
            self.set_flight_cookie(flight_id)
            response = self.session.patch(f'{self.base}flightdetail/{flight_id}', json={k: v for k, v in data.items() if v})
            if response.status_code != 200:
                if response.text:
                    try:
                        json_response = response.json()
                    except JSONDecodeError:
                        json_response = {}
                    error = json_response.get('error')
                    error_description = json_response.get('error_description')
                    raise WeglideResponseError(
                        f'Status {response.status_code}: {error or response.text}',
                        error=error, error_description=error_description
                    )
                raise WeglideResponseError(f'Status {response.status_code}: could not set flightdata')

    def get_user(self, user_id):
        with sentry_sdk.start_span(op='request', name='get_user') as span:
            response = self.session.get(f'{self.base}user/{user_id}')
            json_response = response.json()
            response.raise_for_status()
            return json_response

    def set_gliders(self):
        with sentry_sdk.start_span(op='request', name='set_gliders') as span:
            try:
                response = self.session.get(f'{self.base}aircraft')
                json_response = response.json()
                response.raise_for_status()
                gliders.clear()
                gliders.update({x['name']: x['id'] for x in json_response})
            except (requests.HTTPError, JSONDecodeError) as e:
                logging.warning(f'Could not fetch gliders from Weglide: {e}')


interface = WeglideInterface()
interface.set_gliders()  # Only fetch once
