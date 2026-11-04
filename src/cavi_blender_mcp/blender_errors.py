"""Explicit no-edit validation failures; other native exceptions stay uncertain."""

from contextlib import contextmanager


class PreflightRejected(ValueError):
    """Validation ended before the operation began editing application data."""


@contextmanager
def preflight():
    """Use only around validation and computation that cannot edit application data."""
    try:
        yield
    except PreflightRejected:
        raise
    except ValueError as exc:
        raise PreflightRejected(str(exc)) from exc
