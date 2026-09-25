"""Shared error taxonomy for the sync pipeline. No gi imports."""
from __future__ import annotations

import errno
import http.client
import logging
import socket
import ssl
import subprocess
import time
import urllib.error
from enum import Enum

log = logging.getLogger("calpi.sync")


class ErrorCode(str, Enum):
    AUTH_FAILED = "AUTH_FAILED"
    NETWORK_DOWN = "NETWORK_DOWN"
    DNS_FAILED = "DNS_FAILED"
    TIMEOUT = "TIMEOUT"
    TLS_ERROR = "TLS_ERROR"
    CLOCK_WRONG = "CLOCK_WRONG"
    SERVER_ERROR = "SERVER_ERROR"
    RATE_LIMITED = "RATE_LIMITED"
    NOT_FOUND = "NOT_FOUND"
    PARSE_ERROR = "PARSE_ERROR"
    CREDENTIALS_UNREADABLE = "CREDENTIALS_UNREADABLE"
    DISK_FULL = "DISK_FULL"
    UNKNOWN = "UNKNOWN"


_TRANSIENT = {ErrorCode.NETWORK_DOWN, ErrorCode.DNS_FAILED, ErrorCode.TIMEOUT,
              ErrorCode.SERVER_ERROR, ErrorCode.RATE_LIMITED}


class SyncError(Exception):
    def __init__(self, code: ErrorCode, detail: str = "", retry_after: int | None = None):
        super().__init__(f"{code.value}: {detail}" if detail else code.value)
        self.code = code
        self.detail = detail
        self.retry_after = retry_after

    @property
    def transient(self) -> bool:
        return self.code in _TRANSIENT


def clock_looks_wrong(now: float | None = None) -> bool:
    """Year < 2025 or NTP not synchronised. Runs a subprocess: never call on the UI thread."""
    if time.gmtime(now if now is not None else time.time()).tm_year < 2025:
        return True
    try:
        r = subprocess.run(["timedatectl", "show", "-p", "NTPSynchronized", "--value"],
                           capture_output=True, text=True, timeout=3)
        return r.returncode == 0 and r.stdout.strip() == "no"
    except (OSError, subprocess.SubprocessError):
        return False


def _tls_error(exc: BaseException) -> SyncError:
    msg = str(getattr(exc, "verify_message", "") or exc)
    low = msg.lower()
    if ("not yet valid" in low or "expired" in low
            or (isinstance(exc, ssl.SSLCertVerificationError) and clock_looks_wrong())):
        return SyncError(ErrorCode.CLOCK_WRONG, "certificate check failed and the system clock looks wrong")
    return SyncError(ErrorCode.TLS_ERROR, msg[:200])


def classify_exception(exc: BaseException) -> SyncError:
    if isinstance(exc, SyncError):
        return exc
    if isinstance(exc, urllib.error.URLError) and not isinstance(exc, urllib.error.HTTPError):
        reason = exc.reason
        if isinstance(reason, BaseException):
            return classify_exception(reason)
        return SyncError(ErrorCode.NETWORK_DOWN, str(reason)[:200])
    if isinstance(exc, ssl.SSLCertVerificationError):
        return _tls_error(exc)
    if isinstance(exc, ssl.SSLError):
        return SyncError(ErrorCode.TLS_ERROR, str(exc)[:200])
    if isinstance(exc, socket.gaierror):
        return SyncError(ErrorCode.DNS_FAILED, str(exc)[:200])
    if isinstance(exc, (TimeoutError, socket.timeout)):
        return SyncError(ErrorCode.TIMEOUT, "timed out")
    if isinstance(exc, (http.client.RemoteDisconnected, ConnectionError)):
        return SyncError(ErrorCode.NETWORK_DOWN, type(exc).__name__)
    if isinstance(exc, http.client.HTTPException):
        return SyncError(ErrorCode.SERVER_ERROR, type(exc).__name__)
    if isinstance(exc, OSError):
        if exc.errno in (errno.ENETUNREACH, errno.EHOSTUNREACH, errno.ENETDOWN, errno.ECONNREFUSED):
            return SyncError(ErrorCode.NETWORK_DOWN, errno.errorcode.get(exc.errno, "os error"))
        if exc.errno == errno.ENOSPC:
            return SyncError(ErrorCode.DISK_FULL, "no space left on device")
    return SyncError(ErrorCode.UNKNOWN, type(exc).__name__)
