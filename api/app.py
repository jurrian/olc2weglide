import logging
import os

import aiocache
import redis
import sentry_sdk
import tornado
from tornado import autoreload
from tornado.log import enable_pretty_logging

from drr_scheduler import drr_scheduler

enable_pretty_logging()
logging.basicConfig(level=logging.INFO)
local = os.environ.get('LOCAL', False)

redis_host = os.environ.get('REDIS_HOST', 'localhost')
redis_port = os.environ.get('REDIS_PORT', '6379')
redis_client = redis.Redis(redis_host, redis_port, decode_responses=True)

# Local, see production settings below
aiocache.caches.set_config({
    'default': {
        'cache': "aiocache.SimpleMemoryCache",
        'plugins': [
            {'class': "misc.SentryAiocachePlugin"},
        ],
    }
})

if not local:
    sentry_sdk.init(
        dsn=os.environ.get('VITE_SENTRY_DSN'),
        max_value_length=2048,  # Allow bigger messages
        send_default_pii=True,
        traces_sample_rate=1.0,
        profile_session_sample_rate=1.0,
        profiles_sample_rate=1.0,
        profile_lifecycle="trace",
        enable_logs=True,
    )

    # Production settings
    aiocache.caches.set_config({
        'default': {
            'cache': "aiocache.backends.redis.RedisCache",
            'serializer': {
                'class': "misc.Lz4PickleSerializer"
            },
            'plugins': [
                {'class': "misc.SentryAiocachePlugin"},
            ],
        }
    })


def make_app():
    # Aiocache will not work if imported before setting the config
    from api import FetchFlightsHandler, UploadFlightsHandler, UploadStatusHandler, FindGliders, AppStatus

    settings = {
        'debug': local,
    }
    return tornado.web.Application([
        (r"/upload_flights", UploadFlightsHandler),
        (r"/upload_status", UploadStatusHandler),
        (r"/fetch_flights", FetchFlightsHandler),
        (r"/find_gliders", FindGliders),
        (r"/status", AppStatus),
    ], **settings)


if __name__ == "__main__":
    app = make_app()
    app.listen(9001)

    autoreload.start()
    io_loop = tornado.ioloop.IOLoop.current()
    io_loop.spawn_callback(drr_scheduler.run)
    io_loop.start()
