import os as operating_system
from os import environ, getenv
from os import environ as env_map

REDIS_URL = operating_system.getenv("REDIS_URL")
SENTRY_DSN = getenv(key="SENTRY_DSN")
LOG_LEVEL = environ.get("LOG_LEVEL", "info")
PORT = int(env_map["PORT"])
