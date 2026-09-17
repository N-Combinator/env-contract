import os

DATABASE_URL = os.getenv("DATABASE_URL")
TIMEOUT = int(os.getenv("TIMEOUT", "30"))
DEBUG = os.environ.get("DEBUG") == "1"
SECRET_KEY = os.environ["SECRET_KEY"]
FEATURE_FLAG = "FEATURE_FLAG" in os.environ
LEGACY_MODE = "LEGACY_MODE" not in os.environ

# Not configuration the operator has to provide: set for child processes.
os.environ["CHILD_PROCESS_ONLY"] = "1"
del os.environ["CHILD_PROCESS_ONLY"]

# Look-alikes that are not environment reads.
config = {"NOT_AN_ENV_VAR": 1}
config.get("NOT_AN_ENV_VAR")
config["NOT_AN_ENV_VAR"]


def lookup(name):
    return os.getenv(name)


def lookup_many(prefix):
    return os.environ.get(f"{prefix}_URL"), os.environ[prefix], prefix in os.environ
