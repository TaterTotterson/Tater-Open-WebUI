import http.cookiejar
import ipaddress
import logging
import socket
import urllib.parse
from collections.abc import Sequence

import aiohttp
import requests
import urllib3.connection
import urllib3.connectionpool
import validators
from requests.adapters import HTTPAdapter

from open_webui.config import ENABLE_LOCAL_WEB_FETCH, WEB_FETCH_FILTER_LIST
from open_webui.constants import ERROR_MESSAGES
from open_webui.env import AIOHTTP_CLIENT_TIMEOUT
from open_webui.utils.misc import is_host_allowed, is_host_blocked

log = logging.getLogger(__name__)


def resolve_hostname(hostname):
    address_info = socket.getaddrinfo(hostname, None)
    ipv4_addresses = [info[4][0] for info in address_info if info[0] == socket.AF_INET]
    ipv6_addresses = [info[4][0] for info in address_info if info[0] == socket.AF_INET6]
    return ipv4_addresses, ipv6_addresses


def _embedded_ipv4(address: ipaddress.IPv4Address | ipaddress.IPv6Address) -> list[ipaddress.IPv4Address]:
    if not isinstance(address, ipaddress.IPv6Address):
        return []

    embedded = []
    if address.ipv4_mapped:
        embedded.append(address.ipv4_mapped)
    if address.sixtofour:
        embedded.append(address.sixtofour)
    if address.teredo:
        embedded.extend(address.teredo)

    packed = address.packed
    if packed[:12] in (b'\x00' * 12, b'\x00\x64\xff\x9b' + b'\x00' * 8):
        embedded.append(ipaddress.IPv4Address(packed[12:]))
    elif packed[:6] == b'\x00\x64\xff\x9b\x00\x01':
        embedded.append(ipaddress.IPv4Address(bytes((packed[6], packed[7], packed[9], packed[10]))))
    return embedded


def _assert_host_allowed(host: str | None) -> None:
    if WEB_FETCH_FILTER_LIST and not is_host_allowed(host, WEB_FETCH_FILTER_LIST):
        log.warning('Blocked by filter list: %s', host)
        raise ValueError(ERROR_MESSAGES.INVALID_URL)


def _assert_addresses_allowed(addresses: Sequence[str]) -> None:
    parsed = [ipaddress.ip_address(address) for address in addresses]
    candidates = [*parsed, *(ipv4 for address in parsed for ipv4 in _embedded_ipv4(address))]
    if is_host_blocked([str(address) for address in candidates], WEB_FETCH_FILTER_LIST):
        log.warning('Blocked addresses: %s', ', '.join(str(address) for address in candidates))
        raise ValueError(ERROR_MESSAGES.INVALID_URL)
    if not ENABLE_LOCAL_WEB_FETCH and any(not address.is_global for address in candidates):
        raise ValueError(ERROR_MESSAGES.INVALID_URL)


def validate_url(url: str | Sequence[str]):
    if isinstance(url, str):
        if isinstance(validators.url(url, simple_host=ENABLE_LOCAL_WEB_FETCH), validators.ValidationError):
            raise ValueError(ERROR_MESSAGES.INVALID_URL)
        if any(character in url for character in ('\\', '\t', '\n', '\r')):
            raise ValueError(ERROR_MESSAGES.INVALID_URL)

        parsed_url = urllib.parse.urlparse(url)
        if parsed_url.scheme not in ('http', 'https'):
            raise ValueError(ERROR_MESSAGES.INVALID_URL)
        _assert_host_allowed(parsed_url.hostname)
        try:
            ipv4_addresses, ipv6_addresses = resolve_hostname(parsed_url.hostname)
        except (socket.gaierror, UnicodeError):
            if not ENABLE_LOCAL_WEB_FETCH:
                raise ValueError(ERROR_MESSAGES.INVALID_URL) from None
            ipv4_addresses, ipv6_addresses = [], []
        _assert_addresses_allowed(ipv4_addresses + ipv6_addresses)
        return True
    if isinstance(url, Sequence):
        return all(validate_url(item) for item in url)
    return False


def _ssrf_safe_new_conn(self):
    host = getattr(self, '_dns_host', self.host)
    infos = socket.getaddrinfo(host, self.port, 0, socket.SOCK_STREAM)
    if not infos:
        raise OSError(f'getaddrinfo for {host!r} returned an empty list')
    _assert_addresses_allowed([address[0] for _, _, _, _, address in infos])
    error = None
    for family, socket_type, protocol, _, address in infos:
        connection = None
        try:
            connection = socket.socket(family, socket_type, protocol)
            if self.timeout is not socket._GLOBAL_DEFAULT_TIMEOUT:
                connection.settimeout(self.timeout)
            if getattr(self, 'source_address', None):
                connection.bind(self.source_address)
            for option in getattr(self, 'socket_options', None) or ():
                if len(option) == 4 and isinstance(option[3], str):
                    if option[3].lower() == 'tcp':
                        connection.setsockopt(*option[:3])
                    continue
                connection.setsockopt(*option)
            connection.connect(address)
            return connection
        except OSError as exc:
            error = exc
            if connection is not None:
                connection.close()
    raise error or OSError(f'connect to {host!r}:{self.port} failed')


class _SafeHTTPConnection(urllib3.connection.HTTPConnection):
    _new_conn = _ssrf_safe_new_conn


class _SafeHTTPSConnection(urllib3.connection.HTTPSConnection):
    _new_conn = _ssrf_safe_new_conn


class _SafeHTTPPool(urllib3.connectionpool.HTTPConnectionPool):
    ConnectionCls = _SafeHTTPConnection


class _SafeHTTPSPool(urllib3.connectionpool.HTTPSConnectionPool):
    ConnectionCls = _SafeHTTPSConnection


class _SSRFSafeAdapter(HTTPAdapter):
    def init_poolmanager(self, *args, **kwargs):
        super().init_poolmanager(*args, **kwargs)
        self.poolmanager.pool_classes_by_scheme = {'http': _SafeHTTPPool, 'https': _SafeHTTPSPool}

    def send(self, request, *args, **kwargs):
        _assert_host_allowed(urllib.parse.urlparse(request.url).hostname)
        return super().send(request, *args, **kwargs)


class _SSRFSafeConnector(aiohttp.TCPConnector):
    async def connect(self, req, traces, timeout):
        _assert_host_allowed(req.url.host)
        return await super().connect(req, traces, timeout)

    async def _resolve_host(self, host, port, traces=None):
        results = await super()._resolve_host(host, port, traces=traces)
        _assert_addresses_allowed([entry['host'] for entry in results])
        return results


def get_ssrf_safe_session(trust_env: bool = True, store_cookies: bool = True) -> aiohttp.ClientSession:
    return aiohttp.ClientSession(
        connector=_SSRFSafeConnector(),
        timeout=aiohttp.ClientTimeout(total=AIOHTTP_CLIENT_TIMEOUT),
        trust_env=trust_env,
        cookie_jar=None if store_cookies else aiohttp.DummyCookieJar(),
    )


def get_ssrf_safe_requests_session(trust_env: bool = True, store_cookies: bool = True) -> requests.Session:
    session = requests.Session()
    session.trust_env = trust_env
    if not store_cookies:
        session.cookies.set_policy(http.cookiejar.DefaultCookiePolicy(allowed_domains=[]))
    session.mount('http://', _SSRFSafeAdapter())
    session.mount('https://', _SSRFSafeAdapter())
    return session
