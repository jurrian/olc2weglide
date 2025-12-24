import asyncio
import json
import os
from asyncio import wait_for

import sentry_sdk
import tornado
import tornado.ioloop
import tornado.web
from aiocache import Cache, cached
from aiohttp import ClientError
from tornado.log import enable_pretty_logging

from gliders import weglide_find_closest_gliders
from misc import set_upload_status
from olc_interface import OlcInterface, OlcRequestError
from drr_scheduler import drr_scheduler
from upload import upload_flight

enable_pretty_logging()
root = os.path.dirname(__file__)

# Shared data structure to store upload results
sentry_upload_users = {}


class BaseHandler(tornado.web.RequestHandler):
    def write_error(self, status_code, **kwargs):
        self.set_header('Content-Type', 'application/json')
        if 'exc_info' in kwargs:
            exc = kwargs['exc_info'][1]
            self.finish(json.dumps({
                'error': exc.__class__.__name__,
                'message': str(exc),
            }))
        else:
            self.finish(json.dumps({
                'status_code': status_code,
                'error': self._reason
            }))


class UploadFlightsHandler(BaseHandler):
    async def post(self, *args, **kwargs):
        global sentry_upload_users
        try:
            body = json.loads(self.request.body)
        except json.JSONDecodeError:
            raise tornado.web.HTTPError(400, 'Invalid JSON')

        if not body:
            raise tornado.web.HTTPError(400, 'No flights selected')

        weglide_user_id = body.get('weglide_user_id')
        weglide_dateofbirth = body.get('weglide_dateofbirth')
        olc_user = body.get('olc_user')
        olc_password = body.get('olc_password')

        sentry_sdk.set_user({'id': weglide_user_id})

        with sentry_sdk.start_span(op='request', name='upload_flight') as span:
            for flight in body['flights']:
                set_upload_status(int(flight['id']), 'Pending', 'processing')  # Reset status
                # loop.spawn_callback(upload_flight, flight)
                drr_scheduler.enqueue_one(
                    weglide_user_id,
                    upload_flight(flight, weglide_user_id, weglide_dateofbirth, olc_user, olc_password)
                )
            # TODO fix this to count only successful uploads
            # flight_count = len(body['flights'])
            #
            # try:
            #     pilot_name = interface.get_user(weglide_user_id)['name']
            # except:
            #     pilot_name = weglide_user_id
            #
            # user_id = f'{pilot_name}_{flight_count}'
            # if not sentry_upload_users.get(user_id, False):
            #     span.set_data('pilot_name', pilot_name)
            #     span.set_data('weglide_user_id', weglide_user_id)
            #     span.set_data('flight_count', flight_count)
            #     span.set_data(pilot_name, flight_count)
            #     sentry_sdk.capture_message(f'{pilot_name}: uploaded {flight_count}')
            #     sentry_upload_users[user_id] = True


class UploadStatusHandler(BaseHandler):
    def get(self):
        from misc import get_upload_status
        flight_ids_str = self.get_argument('flight_ids')
        flight_ids_list = [int(flight_id) for flight_id in flight_ids_str.split(',')]
        statuses = {flight_id: get_upload_status(flight_id) for flight_id in flight_ids_list}
        if statuses:
            self.write(statuses)


class FetchFlightsHandler(BaseHandler):
    async def get(self):
        user_id = self.get_argument('user_id')
        start_year = self.get_argument('start_year')
        end_year = self.get_argument('end_year', None)

        if not user_id or not start_year:
            raise tornado.web.HTTPError(400, 'Invalid input, fill the User ID and Start year')

        user_id = int(user_id)
        start_year = int(start_year)
        end_year = end_year and int(end_year)

        sentry_sdk.set_user({'id': user_id})

        async with OlcInterface() as olc:
            try:
                # TODO enforce timeout?
                future = drr_scheduler.enqueue_one(
                    user_id,
                    olc.fetch_flights(user_id, start_year, end_year),
                )
                flights = await future
            except asyncio.TimeoutError:
                raise tornado.web.HTTPError(408, 'Took too long to fetch flights from OLC, try less flights at once')
            except OlcRequestError as e:
                raise tornado.web.HTTPError(400, str(e))
            else:
                self.write(json.dumps(flights))


class FindGliders(BaseHandler):
    def get(self):
        glider_name = self.get_argument('name')
        closest_ids = weglide_find_closest_gliders(glider_name)
        self.write(json.dumps(closest_ids))


class AppStatus(BaseHandler):
    async def get(self):
        result = await self.app_status()
        if not result['fetch_flights'] or not result['fetch_igc']:
            sentry_sdk.capture_exception(Exception(f'OLC failed: {result}'))
            self.set_status(500)

        inflight, cap = drr_scheduler.global_load()
        s_mean, s50, s90 = drr_scheduler.service_times()
        active_users = drr_scheduler.active_user_count()

        with sentry_sdk.start_span(op='queue', name='app_status') as span:
            span.set_data('inflight', inflight)
            span.set_data('cap', cap)
            span.set_data('s_mean', s_mean)
            span.set_data('s50', s50)
            span.set_data('s90', s90)
            span.set_data('active_users', active_users)

        # r_user, share = drr_scheduler.user_effective_rate(user_id)
        result["upstream_load"] = {"inflight": inflight, "cap": cap}
        result["service_time_sec"] = {"mean": s_mean, "p50": s50, "p90": s90}
        # "your_rate_items_per_sec": r_user,
        # "your_share": share,
        result["active_users"] = active_users

        self.write(json.dumps(result))

    async def head(self):
        result = await self.app_status()
        if result:
            self.set_status(500)

    @cached(ttl=60 * 10, cache=Cache.MEMORY, key="app_status")
    async def app_status(self):
        try:
            async with OlcInterface() as olc:
                fetch_flights = bool(await wait_for(olc.fetch_flights(83040, 2023, 2023, _scrape=False), timeout=20))
                try:
                    # https://www.onlinecontest.org/olc-3.0/gliding/flightinfo.html?dsId=9365672&f_map=
                    await olc.fetch_igc('-348283551', _head=True)  # Or 732598177
                    fetch_igc = True
                except (ClientError, OlcRequestError):
                    fetch_igc = False
                return {'fetch_flights': fetch_flights, 'fetch_igc': fetch_igc}
        except TimeoutError:
            raise tornado.web.HTTPError(408, 'Request Timeout')
