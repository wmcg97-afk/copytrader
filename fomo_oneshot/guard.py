"""Turn provider and Telegram failures into strings that cannot carry requests."""

from __future__ import annotations

from typing import NoReturn

import urllib.request

from .redact import redact


def guarded_opener(redirect_handler):
    """Opener with redirects replaced and environment proxies left unused.

    An empty ProxyHandler replaces the default one, so https_proxy cannot
    receive the bearer token or add a hop outside the request cap.
    """
    return urllib.request.build_opener(urllib.request.ProxyHandler({}), redirect_handler)


def raise_clean(error: BaseException) -> NoReturn:
    """Raise `error` without the active exception, its body, or its request."""
    try:
        raise error from None
    except BaseException as raised:
        _clear(raised)
        raise


def safe_text(exc: BaseException) -> str:
    message = redact(str(exc))
    _clear(exc)
    return message


def _clear(exc: BaseException) -> None:
    exc.__traceback__ = None
    exc.__context__ = None
    exc.__cause__ = None
    exc.__suppress_context__ = True
