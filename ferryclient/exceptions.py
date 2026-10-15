# Copyright the Ferry authors.
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may not
# use this file except in compliance with the License. You may obtain a copy of
# the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
"""Exceptions raised by the Ferry client.

The API reports errors as ``application/problem+json`` (RFC 7807,
https://datatracker.ietf.org/doc/html/rfc7807) with two additions worth
keeping: a stable machine-readable ``code``, and the ``request_id`` the server
logged the failure under. The code is what a script should branch on; the
request id is what ties a user's report to a line in the service log.
"""


class FerryError(Exception):
    """Base for every error this client raises."""


class EndpointNotFound(FerryError):
    """No endpoint for the service in the catalog.

    Usually means the service is not deployed in this region, or the requested
    interface is not registered.
    """


class HTTPError(FerryError):
    """An error response from the API.

    ``code`` is the field to branch on. ``title`` and ``detail`` are for humans
    and may change between releases.
    """

    status_code = None

    def __init__(self, status_code, code=None, title=None, detail=None,
                 request_id=None, response=None, fields=None,
                 retry_after=None):
        self.status_code = status_code
        self.code = code
        self.title = title
        self.detail = detail
        self.fields = fields or {}
        self.request_id = request_id
        self.response = response
        self.retry_after = retry_after
        super().__init__(str(self))

    def __str__(self):
        parts = [f"HTTP {self.status_code}"]
        if self.code:
            parts.append(f"({self.code})")
        headline = self.title or ""
        if self.detail and self.detail != self.title:
            headline = f"{headline}: {self.detail}" if headline else self.detail
        if headline:
            parts.append(headline)
        if self.retry_after is not None:
            parts.append(f"(retry after {self.retry_after}s)")
        text = " ".join(parts)
        # Carried into the user's terminal on purpose: it is what turns "it
        # failed" into a grep against the service log.
        if self.request_id:
            text = f"{text} [request-id: {self.request_id}]"
        lines = [text]
        for name in sorted(self.fields):
            lines.append(f"  {name}: {self.fields[name]}")
        return "\n".join(lines)


class BadRequest(HTTPError):
    status_code = 400


class Unauthorized(HTTPError):
    status_code = 401


class Forbidden(HTTPError):
    status_code = 403


class NotFound(HTTPError):
    status_code = 404


class Conflict(HTTPError):
    status_code = 409


class ServiceUnavailable(HTTPError):
    status_code = 503


_BY_STATUS = {
    cls.status_code: cls
    for cls in (BadRequest, Unauthorized, Forbidden, NotFound, Conflict,
                ServiceUnavailable)
}


def from_response(response):
    """Build the most specific exception for an error response.

    A body that is not a problem document is not itself an error, since a
    proxy between the client and the API may answer with HTML, so the raw text
    is kept as the detail rather than discarded.
    """
    status = response.status_code
    code = title = detail = request_id = fields = None

    try:
        body = response.json()
    except ValueError:
        body = None

    if isinstance(body, dict):
        code = body.get("code")
        title = body.get("title")
        detail = body.get("detail")
        request_id = body.get("request_id")
        if isinstance(body.get("fields"), dict):
            fields = body["fields"]
    if detail is None and not isinstance(body, dict):
        text = (response.text or "").strip()
        detail = text[:400] or None

    # The header wins when both are present: a problem document is produced by
    # a handler, the header by the middleware that actually logged the request.
    request_id = response.headers.get("X-Request-Id", request_id)

    cls = _BY_STATUS.get(status, HTTPError)
    return cls(status_code=status, code=code, title=title, detail=detail,
               request_id=request_id, response=response, fields=fields,
               retry_after=_retry_after(response.headers))


def _retry_after(headers):
    value = (headers.get("Retry-After") or "").strip()
    if not value.isdigit():
        return None
    return int(value)
