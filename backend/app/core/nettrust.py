"""Outbound-request safety (SSRF guard) shared by every feature that reaches a
user-supplied URL — data-source sync and alert webhooks.

The policy, applied to the initial URL and re-applied to every redirect hop:
  * only http / https schemes;
  * the host must resolve *exclusively* to public IPs — private, loopback,
    link-local (incl. the 169.254.169.254 cloud-metadata endpoint), reserved,
    multicast, unspecified, and IPv4-mapped variants are refused;
  * the response body is size-capped while streaming.

Escape hatch: IH_ALLOW_PRIVATE_FETCH=1 to allow internal URLs on a trusted
network. (Residual: validate-then-connect leaves a narrow DNS-rebinding TOCTOU
window — acceptable at this trust level and documented here.)
"""

import ipaddress
import json
import socket
import urllib.request
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse

from . import config

_UA = "InsightHub/0.1 (+outbound)"


class BlockedURLError(ValueError):
    """URL rejected by the SSRF policy (bad scheme or internal address)."""


class FetchError(ValueError):
    """The request itself failed (HTTP error, timeout, or oversize response)."""


def _reject_ip(ip_str: str) -> None:
    ip = ipaddress.ip_address(ip_str)
    if ip.version == 6 and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped  # unwrap ::ffff:127.0.0.1 etc.
    if (
        ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved
        or ip.is_multicast or ip.is_unspecified or not ip.is_global
    ):
        raise BlockedURLError(
            "refusing to reach a private or internal address — use a publicly "
            "reachable URL (set IH_ALLOW_PRIVATE_FETCH=1 to override)"
        )


def validate_url(url: str, allow_private: bool | None = None) -> None:
    """Enforce the SSRF policy for a single URL (scheme + every resolved IP)."""
    if allow_private is None:
        allow_private = config.ALLOW_PRIVATE_FETCH
    parts = urlparse(url)
    if parts.scheme not in ("http", "https"):
        raise BlockedURLError("only http/https URLs are supported")
    host = parts.hostname
    if not host:
        raise BlockedURLError("URL has no host")
    if allow_private:
        return
    port = parts.port or (443 if parts.scheme == "https" else 80)
    try:
        infos = socket.getaddrinfo(host, port, proto=socket.IPPROTO_TCP)
    except socket.gaierror:
        raise BlockedURLError(f"could not resolve host {host!r}")
    if not infos:
        raise BlockedURLError(f"could not resolve host {host!r}")
    for info in infos:
        _reject_ip(info[4][0])


class _ValidatingRedirect(urllib.request.HTTPRedirectHandler):
    """Follow redirects, re-validating each target against the SSRF policy."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        validate_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _opener():
    return urllib.request.build_opener(_ValidatingRedirect())


def http_get(url: str, max_bytes: int, timeout: int | None = None) -> bytes:
    """GET with SSRF guarding, a timeout, and a hard size cap."""
    validate_url(url)
    req = urllib.request.Request(url, headers={"User-Agent": _UA, "Accept": "text/csv, */*"})
    try:
        with _opener().open(req, timeout=timeout or config.SOURCE_FETCH_TIMEOUT) as resp:
            data = resp.read(max_bytes + 1)
    except HTTPError as exc:
        raise FetchError(f"remote returned HTTP {exc.code}")
    except (URLError, TimeoutError, socket.timeout) as exc:
        raise FetchError(f"request failed: {getattr(exc, 'reason', exc)}")
    if len(data) > max_bytes:
        raise FetchError("response is larger than the allowed size limit")
    if not data.strip():
        raise FetchError("response was empty")
    return data


def http_post_json(url: str, payload: dict, timeout: int | None = None, max_bytes: int = 65536) -> int:
    """POST a JSON body with SSRF guarding. Returns the HTTP status code."""
    validate_url(url)
    body = json.dumps(payload).encode()
    req = urllib.request.Request(
        url, data=body, method="POST",
        headers={"User-Agent": _UA, "Content-Type": "application/json"},
    )
    try:
        with _opener().open(req, timeout=timeout or config.SOURCE_FETCH_TIMEOUT) as resp:
            resp.read(max_bytes + 1)  # drain (and cap) the response, ignore contents
            return getattr(resp, "status", 200)
    except HTTPError as exc:
        raise FetchError(f"webhook returned HTTP {exc.code}")
    except (URLError, TimeoutError, socket.timeout) as exc:
        raise FetchError(f"webhook request failed: {getattr(exc, 'reason', exc)}")
