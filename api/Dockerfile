FROM python:3.11-alpine

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

EXPOSE 9001

WORKDIR /usr/src/app

RUN apk add --no-cache gcc musl-dev python3-dev
RUN pip install --no-cache-dir --upgrade pip wheel setuptools
RUN pip install --no-cache-dir --upgrade --upgrade-strategy eager \
    requests tornado sentry-sdk requests_oauth2client aiohttp aiohttp_retry aiocache[redis] lz4 lxml fuzzywuzzy python-Levenshtein

COPY . /usr/src/app/

ENTRYPOINT ["python3", "app.py"]
