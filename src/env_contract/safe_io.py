"""The only place env-contract opens files.

Real dotenv files (``.env``, ``.env.local``, ...) hold secret values, so they
are refused by name before anything is opened -- including when an allowed
name is a symlink that resolves to one of them.
"""

import os

TEMPLATE_NAME = ".env.example"


class ForbiddenFileError(Exception):
    pass


def is_forbidden_name(name: str) -> bool:
    if name == TEMPLATE_NAME:
        return False
    return name == ".env" or name.startswith(".env.")


def is_forbidden(path: str) -> bool:
    if is_forbidden_name(os.path.basename(path)):
        return True
    return is_forbidden_name(os.path.basename(os.path.realpath(path)))


def read_bytes(path: str) -> bytes:
    if is_forbidden(path):
        raise ForbiddenFileError(f"refusing to open {path}: may contain secret values")
    with open(path, "rb") as fh:
        return fh.read()
