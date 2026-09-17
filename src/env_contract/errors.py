class ParseError(Exception):
    """A project file could not be parsed; reported as ``path:line: message``."""

    def __init__(self, path: str, line: int | None, message: str) -> None:
        self.path = path
        self.line = line
        self.message = message
        location = path if line is None else f"{path}:{line}"
        super().__init__(f"{location}: {message}")
