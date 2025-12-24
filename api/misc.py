import asyncio
import logging
import random
import re
import sys
import time

import lz4.frame
import sentry_sdk
from aiocache.plugins import BasePlugin
from aiocache.serializers import PickleSerializer

from app import redis_client


def make_link_if_url(text):
    url_pattern = re.compile(r'(https?://[^\s]+)')
    if not text:
        return text
    # Replace URLs in the text with HTML links
    return url_pattern.sub(r'<a href="\1" target="_blank">\1</a>', text)


def make_hashable(obj):
    if isinstance(obj, (tuple, list)):
        return tuple(make_hashable(e) for e in obj)
    if isinstance(obj, dict):
        return tuple(sorted((k, make_hashable(v)) for k, v in obj.items()))
    if isinstance(obj, set):
        return tuple(sorted(make_hashable(e) for e in obj))
    return obj


def extract_arguments(prefix, arguments):
    data = {}
    for key, value in arguments.items():
        if key.startswith(f'{prefix}['):
            flight_id = int(key[len(f'{prefix}['):-1])
            data[flight_id] = value[0].decode('utf-8').strip()
    return data


def format_registration(input_string):
    if input_string is None:
        return None

    # Skip formatting for US
    if input_string[0:1] == 'N':
        return input_string

    # Remove all spaces
    no_spaces = re.sub(r'\s+', '', input_string)

    if '-' in no_spaces:
        return no_spaces

    # Match the pattern [A-Z]{1,2}-[0-9A-Z]{1,4}
    match = re.match(r'([A-Z]{1,2})([0-9A-Z]{1,4})', no_spaces)
    if match:
        return f'{match.group(1)}-{match.group(2)}'
    else:
        # If we cannot fix it, return the original and let the user fix it
        return input_string


class MetricSemaphore(asyncio.Semaphore):
    def __init__(self, *args, **kwargs):
        self.t0 = None
        self.t1 = None
        super().__init__(*args, **kwargs)

    async def acquire(self):
        with sentry_sdk.start_span(op="queue.wait", name="semaphore.acquire") as span:
            self.t0 = time.perf_counter()
            result = await super().acquire()
            self.t1 = time.perf_counter()
            wait_time = (self.t1 - self.t0) * 1000.0
            span.set_data("queue.wait_ms", wait_time)
            span.set_data("queue.available", self._value)
            if self._waiters:
                span.set_data("queue.waiters", len(self._waiters))
            logging.debug(f"Semaphore acquired after waiting {wait_time:.1f}ms")
            return result

    def release(self):
        with sentry_sdk.start_span(op="queue.release", name="semaphore.release") as span:
            use_time = (time.perf_counter() - self.t1) * 1000.0
            span.set_data("queue.use_ms", use_time)
            span.set_data("queue.available", self._value)
            if self._waiters:
                span.set_data("queue.waiters", len(self._waiters))
            logging.debug(f"Semaphore released after {use_time:.1f}ms")
            return super().release()


def cache_key_builder(func, *args, **kwargs):
    """Create a cache key, ignoring 'self' and any argument starting with '_'.
    """
    if args and hasattr(args[0], "__class__"):
        args = args[1:]
    args = tuple(a for a in args if not (isinstance(a, str) and a.startswith('_')))
    kwargs = {k: v for k, v in kwargs.items() if not k.startswith('_')}
    if args and args[0] == 81464:
        return f"{func.__name__}:no_cache_{random.randint(1, 1000000)}"  # Disable caching for this user
    assert len(args) + len(kwargs) > 0, "At least one argument is required to build the cache key"
    key = f"{func.__name__}:{args}:{kwargs}"
    return key


class SentryAiocachePlugin(BasePlugin):
    async def post_get(self, client, key, took=0, ret=None, **kwargs):
        with sentry_sdk.start_span(op="cache.get") as span:
            span.set_data("cache.key", [key])
            hit = ret is not None
            span.set_data("cache.hit", hit)
            logging.debug(f"Cache {'hit' if hit else 'miss'} for key: {key}")

    async def post_set(self, client, key, value, *args, **kwargs):
        with sentry_sdk.start_span(op="cache.put") as span:
            span.set_data("cache.key", [key])
            if value is not None:
                byte_size = sys.getsizeof(value)
                span.set_data("cache.item_size", byte_size)
                logging.debug(f"Cached {byte_size} bytes for key: {key}")
            else:
                logging.debug(f"Cached None value for key: {key}")
            if client.ttl is not None:
                span.set_data("cache.ttl", client.ttl)


class Lz4PickleSerializer(PickleSerializer):
    def dumps(self, value):
        if value is not None:
            value = super().dumps(value)
            value = lz4.frame.compress(value)
        return value

    def loads(self, value):
        if value is not None:
            value = lz4.frame.decompress(value)
            value = super().loads(value)
        return value


status_expiry_seconds = 60*5  # Expire in 5 minutes

def set_upload_status(flight_id, result, status=None):
    if result is not None:
        redis_client.set(f"upload_result:{flight_id}", result, ex=status_expiry_seconds)
    if status is not None:
        redis_client.set(f"upload_status:{flight_id}", status, ex=status_expiry_seconds)

def get_upload_status(flight_id):
    result = redis_client.get(f"upload_result:{flight_id}")
    status = redis_client.get(f"upload_status:{flight_id}")
    if result is None:
        return {'status': None, 'result': ''}
    return {'status': status, 'result': result}
