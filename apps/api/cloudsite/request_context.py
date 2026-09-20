import ipaddress

from fastapi import Request

from .config import settings


def normalize_ip(value: str) -> str:
    address = ipaddress.ip_address(value.strip())
    if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped:
        address = address.ipv4_mapped
    return address.compressed


def _trusted_networks():
    networks = []
    for value in settings.trusted_proxy_cidr_list:
        try:
            networks.append(ipaddress.ip_network(value, strict=False))
        except ValueError:
            continue
    return tuple(networks)


def is_trusted_proxy(address: str) -> bool:
    try:
        parsed = ipaddress.ip_address(address)
    except ValueError:
        return False
    return any(parsed.version == network.version and parsed in network for network in _trusted_networks())


def is_trusted_proxy_request(request: Request) -> bool:
    if not request.client:
        return False
    try:
        return is_trusted_proxy(normalize_ip(request.client.host))
    except ValueError:
        return False


def request_scheme(request: Request) -> str:
    if is_trusted_proxy_request(request):
        forwarded = request.headers.get("x-forwarded-proto", "").split(",")[0].strip().lower()
        if forwarded in {"http", "https"}:
            return forwarded
    return request.url.scheme.lower()


def request_host(request: Request) -> str:
    if is_trusted_proxy_request(request):
        forwarded = request.headers.get("x-forwarded-host", "").split(",")[0].strip()
        if forwarded:
            return forwarded
    return request.headers.get("host", "").split(",")[0].strip()


def request_is_https(request: Request) -> bool:
    return request_scheme(request) == "https"
