#!/bin/bash

git pull
pnpm install && pnpm build
docker-compose up -d --build api redis
