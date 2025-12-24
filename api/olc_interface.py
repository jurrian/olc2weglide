import asyncio
import logging
import random
import time
from datetime import datetime

import os
import aiohttp
import sentry_sdk
from aiocache import cached
from aiohttp import ClientTimeout
from aiohttp_retry import ExponentialRetry, RetryClient
from aiohttp_retry.client import _RequestContext
from lxml import etree
from requests import JSONDecodeError
from sentry_sdk import new_scope

from gliders import weglide_find_closest_gliders
from misc import cache_key_builder, format_registration

# TODO make this dynamic
flights_max = 200  # Max number of flights to fetch from OLC per user
olc_timeout = 30  # 30 seconds timeout for OLC requests

# OLC will fail fast when it's stalling the response, proxy is allowed more time
olc_client_timeout = ClientTimeout(total=olc_timeout, connect=10)
proxy_client_timeout = ClientTimeout(total=60)

headers_list = [
    {
        'accept-language': 'en-US,en;q=0.9',
        'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
        'accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
    },
    {
        'accept-language': 'en-US,en;q=0.9',
        'user-agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/14.1.1 Safari/605.1.15',
        'accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
    },
    {
        'accept-language': 'en-US,en;q=0.9',
        'user-agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
        'accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
    },
    {
        'accept-language': 'en-US,en;q=0.9',
        'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:89.0) Gecko/20100101 Firefox/89.0',
        'accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
    },
    {
        'accept-language': 'en-US,en;q=0.9',
        'user-agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7; rv:89.0) Gecko/20100101 Firefox/89.0',
        'accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
    },
    {
        'accept-language': 'en-US,en;q=0.9',
        'user-agent': 'Mozilla/5.0 (iPhone; CPU iPhone OS 14_6 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/14.0 Mobile/15E148 Safari/604.1',
        'accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
    },
    {
        'accept-language': 'en-US,en;q=0.9',
        'user-agent': 'Mozilla/5.0 (iPad; CPU OS 14_6 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/14.0 Mobile/15E148 Safari/604.1',
        'accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
    },
    {
        'accept-language': 'en-US,en;q=0.9',
        'user-agent': 'Mozilla/5.0 (Linux; Android 11; SM-G991B) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Mobile Safari/537.36',
        'accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
    },
    {
        'accept-language': 'en-US,en;q=0.9',
        'user-agent': 'Mozilla/5.0 (Linux; Android 11; Pixel 5) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Mobile Safari/537.36',
        'accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
    },
    {
        'accept-language': 'en-US,en;q=0.9',
        'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Edge/91.0.864.59',
        'accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
    }
]

class OlcRequestError(Exception):
    pass


class ProxyRetryClient(RetryClient):
    """RetryClient that adds a proxy on retries, but not on the first attempt.
    """
    def __init__(self, proxy, *args, **kwargs):
        self.proxy = proxy
        super().__init__(*args, **kwargs)

    def _make_requests(self, params_list, retry_options=None, raise_for_status=None):
        with sentry_sdk.start_span(op='request', name='retry') as span:
            if retry_options is None:
                retry_options = self._retry_options
            if raise_for_status is None:
                raise_for_status = self._raise_for_status

            def request_wrapper(*args, **kwargs):
                """Wrap the request to add proxy on retries (not on first attempt)."""
                try:
                    current_attempt = kwargs["trace_request_ctx"]["current_attempt"]
                except (KeyError, TypeError):
                    current_attempt = 1
                span.set_data('attempt', current_attempt)

                if current_attempt > 1:
                    kwargs['proxy'] = self.proxy
                    span.set_data('proxy', True)
                else:
                    span.set_data('proxy', False)

                self._client._timeout = olc_client_timeout
                if kwargs.get('proxy'):
                    # Allow the proxy more time
                    self._client._timeout = proxy_client_timeout
                span.set_data('client_timeout', self._client.timeout.total)
                return self._client.request(*args, **kwargs)

            return _RequestContext(
                request_func=request_wrapper,
                params_list=params_list,
                logger=self._logger,
                retry_options=retry_options,
                raise_for_status=raise_for_status,
            )


class OlcInterface:
    """Interface to interact with OLC.
    
    OLC throttles or eventually blocks requests from the same IP,
    so we use ScraperAPI proxy to avoid that.
    """
    user_cookies = {}
    user_locks = {}

    def __init__(self, user=os.environ['VITE_OLC_DEFAULT_USER'], password=os.environ['VITE_OLC_DEFAULT_PASSWORD']):
        self.base = 'https://www.onlinecontest.org/olc-3.0/'
        self.proxy = os.environ.get('SCRAPERAPI_PROXY_URL')
        if not any(c.isalpha() for c in user):
            raise ValueError('username cannot be all numbers, fill your OLC username, not your ID')

        self.user = user
        self.password = password
        self.retry_client = None
        if self.user not in OlcInterface.user_locks:
            self.user_locks[self.user] = asyncio.Lock()

    def __repr__(self):
        return f'<OlcInterface user="{self.user}" at {id(self)}>'

    async def ensure_session(self):
        if (
            self.retry_client is None
            or not hasattr(self.retry_client, "_client")
            or self.retry_client._client.closed
        ):
            headers = random.choice(headers_list)
            retry_options = ExponentialRetry(
                attempts=3,
                start_timeout=0.1,
                exceptions={
                    aiohttp.ClientConnectionError,
                    aiohttp.ServerDisconnectedError,
                },
                statuses={429},
                retry_all_server_errors=False,
            )
            session = aiohttp.ClientSession(
                connector=aiohttp.TCPConnector(keepalive_timeout=olc_timeout),
                timeout=olc_client_timeout,  # Switched in ProxyRetryClient
            )
            if self.proxy:
                self.retry_client = ProxyRetryClient(self.proxy, session, headers=headers, raise_for_status=False, retry_options=retry_options)
            else:
                self.retry_client = RetryClient(session, headers=headers, raise_for_status=False, retry_options=retry_options)
            self.reuse_cookies()

    async def __aenter__(self):
        await self.ensure_session()
        return self

    async def __aexit__(self, exc_type, exc, tb):
        if self.retry_client is not None:
            await self.retry_client.close()

    def reuse_cookies(self):
        if self.user in self.user_cookies:
            logging.debug(f"Reusing cookies for user: {self.user}")
            self.retry_client._client.cookie_jar.update_cookies(self.user_cookies[self.user])

    async def login(self, force=False):
        async with OlcInterface.user_locks[self.user]:
            if not force:
                self.reuse_cookies()
                if 'OLCAUTH' in self.retry_client._client.cookie_jar.filter_cookies(self.base):
                    return
            await self.ensure_session()
            with sentry_sdk.start_span(op='request', name='olc_login') as span:
                logging.debug(f"Logging into OLC for: {self.user}")
                t0 = time.perf_counter()
                async with self.retry_client.post(
                    self.base + 'secure/login.html',
                    ssl=False,
                    data={
                        '_ident_': self.user,
                        '_name__': self.password,
                        'ok_par.x': '1',
                    }
                ) as response:
                    if response.status == 429:
                        logging.error('429 returned!')
                        sentry_sdk.capture_exception(Exception('OLC returned 429 on login'))
                        span.set_data("error", "429")
                        span.set_data("olc_login_error_429", 1)
                    response_text = await response.text()
                    if 'Faulty entry' in response_text:
                        span.set_data("error", "faulty entry")
                        span.set_data("olc_login_faulty_entry", 1)
                        raise OlcRequestError(f'login credentials not correct for user {self.user}: faulty entry. Ensure you used the correct OLC username and not the OLC ID')
                    cookies = self.retry_client._client.cookie_jar.filter_cookies(self.base)
                    if 'OLCAUTH' not in cookies:
                        tree = etree.HTML(response_text)
                        try:
                            mobile_login = etree.tostring(tree.xpath('//*[@id="OLCmobileLogin"]')[0], encoding='unicode')
                        except IndexError:
                            span.set_data("error", "no #OLCmobileLogin")
                            span.set_data('olc_login_no_olcmobilelogin', 1)
                            mobile_login = '#OLCmobileLogin not found'
                        else:
                            span.set_data('olc_login_unknown_error', 1)
                            span.set_data('olc_login_mobile_login', mobile_login)
                        final_url = response.headers.get('sa-final-url', None)
                        set_cookie = bool(response.headers.get('Set-Cookie'))
                        sentry_sdk.capture_exception(Exception(f"OLC cookies status:{response.status} Set-Cookie:{set_cookie}\nsa-final-url:{final_url}\n\n{mobile_login}"))
                        raise OlcRequestError(f"login cookies not found for user {self.user}")
                    self.user_cookies[self.user] = cookies
                    span.set_data('olc_login_success', 1)
                    t1 = time.perf_counter()
                    wait_time = (t1 - t0) * 1000
                    logging.info(f"Login OLC for user {self.user} succeeded in {wait_time:.0f}ms")

    @cached(alias='default', key_builder=cache_key_builder, ttl=60 * 60 * 72)
    async def _do_request(self, method, url, *args, **kwargs):
        with sentry_sdk.start_span(op='request', name='_do_request') as span:
            span.set_data('request', method)
            span.set_data('url', url)
            span.set_data('args', args)
            span.set_data('kwargs', kwargs)
            span.set_data('client_timeout', self.retry_client._client.timeout.total)

            t0 = time.perf_counter()
            try:
                logging.info(f'Request: {method} {self.base}{url}')
                async with self.retry_client.request(method, self.base + url, ssl=False, *args, **kwargs) as response:
                    if response.status == 401:
                        logging.warning(f'Got 401 Unauthorized for {self.user}, re-logging in')
                        await self.login(force=True)
                        return await self._do_request(method, url, *args, **kwargs)
                    if response.status == 404:
                        # Not found, no need to log it
                        raise OlcRequestError(f'OLC returned 404 Not Found for {url}')
                    try:
                        response.raise_for_status()
                        if response.headers['Content-Type'][0:9] == 'text/html':
                            raise OlcRequestError(f'HTML returned in OLC response')
                        json_response = await response.json()
                    except (aiohttp.ClientResponseError, JSONDecodeError) as e:
                        message = getattr(e, 'message', str(e))
                        with new_scope() as scope:
                            scope.set_extra("url", str(response.url))
                            sentry_sdk.capture_exception(e)
                        raise OlcRequestError(f'OLC response: {message}') from e  # Re-raise

                    t1 = time.perf_counter()
                    wait_time = (t1 - t0) * 1000
                    span.set_data("request.wait_ms", wait_time)
                    using_proxy = 'using proxy' if kwargs.get('proxy') else 'direct'
                    logging.info(f'Fetched OLC {method} {url} {using_proxy} in {wait_time:.0f}ms')
                    return json_response
            except asyncio.TimeoutError as e:
                logging.error(f'Timeout fetching OLC {url}')
                span.set_data('error', 'timeout')
                span.set_data('olc_request_timeout', 1)
                if not kwargs.get('proxy'):
                    # Try again with proxy
                    return await self._do_request(method, url, *args, proxy=self.proxy, **kwargs)
                raise OlcRequestError('Took too long to fetch flights from OLC, try less flights at once') from e

    @cached(alias='default', key_builder=cache_key_builder, ttl=60 * 60 * 72)
    async def fetch_flights(self, user_id: int, start_year: int, end_year: int = None, _scrape=True):
        with sentry_sdk.start_span(op='request', name='fetch_flights') as span:
            # assert 2007 <= start_year <= 2030, 'Invalid start year: <2007 or >2030'
            year = end_year or datetime.now().year

            tasks = []
            while year >= start_year:
                competition_type = 'olcp'
                if year <= 2010:
                    # OLC Plus exists from October 2010
                    competition_type = 'olc'

                with sentry_sdk.start_span(op='request', name='prepare_task') as inner_span:
                    inner_span.set_data('year', year)
                    inner_span.set_data('user_id', user_id)
                    inner_span.set_data('competition_type', competition_type)
                    tasks.append(self._do_request('POST', f'gliding/flightbook.html?sp={year}&pi={user_id}', json={
                        "q": "ds",
                        "st": competition_type,
                        "offset": 0,
                        "limit": 2147483647
                    }, headers={'Accept': 'application/json'}))
                year -= 1
            span.set_data('olc_tasks', len(tasks))

            flights = []
            scrape_tasks = []
            with sentry_sdk.start_span(op='request', name='prepare_task'):
                for task in asyncio.as_completed(tasks):
                    with sentry_sdk.start_span(op='request', name='await_task'):
                        if len(flights) > flights_max:
                            logging.info(f'Stopping fetching flights after {flights_max} flights for user {user_id}')
                            break

                        try:
                            response = await task
                        except OlcRequestError:
                            continue

                        for flight in response['result']:
                            flight['airplane_weglide'] = weglide_find_closest_gliders(flight['airplane'])[0]
                            flight['date'] = datetime.utcfromtimestamp(flight['dateOfFlight'] / 1000).date().isoformat()
                            flight['distanceInKm'] = round(flight['distanceInKm'], 1)
                            flight['speedInKmH'] = round(flight['speedInKmH'], 1)
                            flight['checked'] = True
                            copilot = flight.get('copilot')
                            if copilot:
                                copilot = copilot['firstName'] + ' ' + copilot['surName']
                                flight['co_pilot_name'] = copilot
                            if _scrape:
                                scrape_tasks.append(self.scrape_flight(flight))
                            flights.append(flight)
            span.set_data('olc_fetched_flights', len(flights))

            if _scrape:
                span.set_data('scrape_tasks' , len(scrape_tasks))
                with sentry_sdk.start_span(op='request', name='scrape_tasks'):
                    await asyncio.gather(*scrape_tasks, return_exceptions=True)
            return sorted(flights, key=lambda flight: int(flight['id']))

    @cached(alias='default', key_builder=cache_key_builder, ttl=60 * 60 * 72)
    async def fetch_flight_ref(self, flight_id: int):
        with sentry_sdk.start_span(op='request', name='fetch_flight_ref') as span:
            json_response = await self._do_request('GET', f'gliding/rest/flightstatistics.json?dsIds={flight_id}')
            assert len(json_response) == 1, 'More than one flight_ref'
            map_href = json_response[0]['mapHref']
            _, _, ref = map_href.partition('ref=')
            span.set_data('olc_fetch_flight_ref_success', 1)
            return int(ref)

    @cached(alias='default', key_builder=cache_key_builder, ttl=60 * 60 * 72)
    async def fetch_igc(self, flight_ref: int, _retry=True, _head=False, **kwargs):
        with sentry_sdk.start_span(op='request', name='fetch_igc') as span:
            logging.info(f'Fetching OLC IGC for user "{self.user}" with ref "{flight_ref}"')
            method = 'HEAD' if _head else 'GET'
            await self.login()
            t0 = time.perf_counter()
            try:
                async with self.retry_client.request(
                    method,
                    f'{self.base}gliding/download.html?flightId={flight_ref}',
                    timeout=aiohttp.ClientTimeout(total=30, connect=10),
                    allow_redirects=False,
                    ssl=False,
                    **kwargs,
                ) as response:
                    if response.status == 429:
                        span.set_data('olc_fetch_igc_fail', 1)
                        raise OlcRequestError('OLC or proxy limit exceeded, try again')
                    response.raise_for_status()
                    if _retry and response.status == 302:
                        await self.login(force=True)
                        return await self.fetch_igc(flight_ref, _retry=False)
                    elif not _retry and response.status == 302:
                        span.set_data('olc_fetch_igc_fail', 1)
                        raise OlcRequestError('Could not log-in to OLC')
                    assert 'application/igc' in response.headers['Content-Type'], 'Not an IGC file'
                    # _, _, filename = response.headers['Content-Disposition'].partition('filename=')
                    # logging.info(f'Fetched OLC IGC {filename}')
                    try:
                        data = await response.text()
                    except UnicodeDecodeError:
                        raw_data = await response.read()
                        try:
                            data = raw_data.decode('latin-1')
                        except UnicodeDecodeError as e:
                            scope = sentry_sdk.get_current_scope()
                            scope.add_attachment(bytes=raw_data, filename=str(flight_ref))
                            span.set_data('olc_fetch_igc_fail', 1)
                            raise OlcRequestError(f'Could not decode IGC: {flight_ref}') from e
                    filename = f'{abs(int(flight_ref))}.igc'  # Filename in IGC file might be malformed, containing slashes, makes WeGlide reject
                    span.set_data('olc_fetch_igc_success', 1)
                    t1 = time.perf_counter()
                    wait_time = (t1 - t0) * 1000
                    span.set_data("request.wait_ms", wait_time)
                    using_proxy = 'using proxy' if kwargs.get('proxy') else 'direct'
                    logging.info(f'Fetched IGC flight_ref {flight_ref} {using_proxy} in {wait_time:.0f}ms')
                    return filename, data
            except asyncio.TimeoutError as e:
                span.set_data('error', 'timeout')
                span.set_data('igc_request_timeout', 1)
                if not kwargs.get('proxy'):
                    # Try again with proxy
                    return await self.fetch_igc(flight_ref, _retry, _head, proxy=self.proxy, **kwargs)
                raise OlcRequestError('Took too long to fetch IGC from OLC') from e

    # Cannot be cached as it does not return anything
    async def scrape_flight(self, flight):
        with sentry_sdk.start_span(op='request', name='scrape_flight') as span:
            flight_id = flight['id']
            logging.debug(f'Scraping flight {flight_id}')
            await self.login()
            async with self.retry_client.get(f'{self.base}gliding/flightinfo.html?dsId={flight_id}', ssl=False) as html_response:
                html_response.raise_for_status()
                tree = etree.HTML(await html_response.text())
            info_box = tree.xpath('//div[@class="OlcButtonBar"]/div/div/div[@class="dropdown-menu"]/dl')[0]
            comment_chunks = tree.xpath('//div[@class="OlcFlightInfoBox olcfiComment"]')[0].xpath('blockquote[1]/p[1]/text()')
            comment_list = []
            for comment_chunk in comment_chunks:
                comment_list.append(comment_chunk.strip())
            comment = '\n\n'.join(comment_list)
            if comment[0] == '-' and comment[-1] == '-':  # Remove comment if "- no Comment -"
                comment = None
            flight['aircraft'] = info_box.xpath('string(dd[1]/text())').strip()
            flight['registration'] = format_registration(info_box.xpath('string(dd[2]/text())'))
            flight['competition_id'] = info_box.xpath('string(dd[3]/text())').strip()
            flight['pilot_comment'] = comment
            span.set_data('olc_scraped_flights', 1)
