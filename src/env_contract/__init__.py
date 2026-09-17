"""Offline environment contract diff for code, templates and Compose."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("env-contract")
except PackageNotFoundError:  # running from a source checkout
    __version__ = "0.0.0"
