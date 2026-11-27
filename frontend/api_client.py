"""Requests wrapper for server-side Streamlit to FastAPI calls."""
import os

import requests as _requests


def _headers(headers=None):
    result = dict(headers or {})
    api_key = os.getenv("AIOPS_API_KEY", "")
    if api_key:
        result["Authorization"] = f"Bearer {api_key}"
    return result


def get(url, **kwargs):
    kwargs["headers"] = _headers(kwargs.get("headers"))
    return _requests.get(url, **kwargs)


def post(url, **kwargs):
    kwargs["headers"] = _headers(kwargs.get("headers"))
    return _requests.post(url, **kwargs)


def put(url, **kwargs):
    kwargs["headers"] = _headers(kwargs.get("headers"))
    return _requests.put(url, **kwargs)


def delete(url, **kwargs):
    kwargs["headers"] = _headers(kwargs.get("headers"))
    return _requests.delete(url, **kwargs)


class RequestsFacade:
    get = staticmethod(get)
    post = staticmethod(post)
    put = staticmethod(put)
    delete = staticmethod(delete)
    RequestException = _requests.RequestException
    exceptions = _requests.exceptions


requests = RequestsFacade()
