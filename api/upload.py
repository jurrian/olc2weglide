import asyncio
import concurrent.futures
import logging
from io import StringIO

import sentry_sdk
import tornado.ioloop
import tornado.web
from aiohttp import ClientError
from requests import RequestException
from sentry_sdk import new_scope

from misc import format_registration, MetricSemaphore, set_upload_status
from olc_interface import OlcInterface, OlcRequestError
from weglide_interface import interface, WeglideResponseError

loop = tornado.ioloop.IOLoop.current()
executor = concurrent.futures.ThreadPoolExecutor()
weglide_semaphore = MetricSemaphore(2)


async def upload_flight(flight, weglide_user_id, weglide_dateofbirth, olc_user, olc_password):
    olc_flight_id = int(flight['id'])
    set_upload_status(olc_flight_id, 'Processing', 'processing')
    try:
        with sentry_sdk.start_span(op='subprocess', name='fetch_olc_igc') as inner_span:
            try:
                async with OlcInterface(user=olc_user, password=olc_password) as olc:
                    flight_ref = await olc.fetch_flight_ref(olc_flight_id)
                    set_upload_status(olc_flight_id, 'Downloading IGC')
                    filename, igc_data = await olc.fetch_igc(flight_ref)
                    file = StringIO(igc_data)
            except (RequestException, asyncio.TimeoutError) as e:
                set_upload_status(olc_flight_id, 'Request to OLC failed, try again later')
                logging.info(f'Error fetching OLC flight {olc_flight_id}: {e} ({type(e).__name__})')
                return
            except (ClientError, OlcRequestError, ValueError) as e:
                set_upload_status(olc_flight_id, 'OLC: ' + str(e) or repr(e))
                logging.info(f'Error fetching {olc_flight_id} from OLC: {e} ({type(e).__name__})')
                return

        with sentry_sdk.start_span(op='subprocess', name='upload_weglide') as inner_span:
            try:
                async with weglide_semaphore:
                    logging.info(f'Uploading IGC for OLC flight {olc_flight_id} to WeGlide')
                    set_upload_status(olc_flight_id, 'Uploading to WeGlide')
                    response_json = await loop.run_in_executor(executor, interface.upload_igc, filename, file, weglide_user_id, weglide_dateofbirth)
                weglide_flight_id = response_json['id']
                logging.info(f'Done uploading IGC for OLC flight {olc_flight_id} to WeGlide: {weglide_flight_id}')
                set_upload_status(olc_flight_id, f'<a target="_blank" href="https://www.weglide.org/flight/{weglide_flight_id}">View</a>', 'done')
                airplane_id = flight['airplane_weglide']['id']
                interface.patch_flightdata(response_json['id'], {
                    'registration': format_registration(flight.get('registration')),
                    'competition_id': flight.get('competition_id'),
                    'aircraft_id': airplane_id,
                })
                if flight.get('co_pilot'):
                    interface.patch_flightdata(response_json['id'], {'co_user_name': flight.get('co_pilot')})
                interface.post_comment(weglide_flight_id, flight.get('pilot_comment'))
            except RequestException as e:
                set_upload_status(olc_flight_id, 'Request to WeGlide failed, try again later', 'error')
                logging.info(f'Error uploading OLC flight {olc_flight_id} to WeGlide')
                return
            except TypeError as e:
                # Temporary debug
                with new_scope() as scope:
                    scope.set_extra('flight', flight)
                    sentry_sdk.capture_exception(e)
                return
            except WeglideResponseError as e:
                result = str(e)
                if hasattr(e, 'error') and e.error == 'already_uploaded':
                    try:
                        flight = interface.search_flight(weglide_user_id, flight['date'], format_registration(flight['registration']), flight['distance'])
                        result = f'<a target="_blank" href="https://www.weglide.org/flight/{flight["id"]}">{result}</a>'
                    except Exception:
                        pass
                set_upload_status(olc_flight_id, 'WeGlide: ' + result, 'error')
                logging.info(f'Error uploading IGC for OLC flight {olc_flight_id} to WeGlide: {e} ({e.error})')
                return
            set_upload_status(olc_flight_id, None, status='done')

    # Handle all other general exceptions
    except AssertionError as e:
        set_upload_status(olc_flight_id, str(e), 'error')
        logging.info(f'Generic problem for {olc_flight_id}: {e}')
    except Exception as e:
        # Alert every other problems
        sentry_sdk.capture_exception(e)
        set_upload_status(olc_flight_id, str(e), 'error')
        logging.info(f'Unknown error while uploading IGC for OLC flight {olc_flight_id} to WeGlide: {e}')
