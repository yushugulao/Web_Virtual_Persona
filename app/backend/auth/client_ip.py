from __future__ import annotations

from fastapi import Request


def _strip_port(host: str) -> str:
    value = host.strip()
    if not value:
        return ""
    if value.startswith("[") and "]" in value:
        return value[1 : value.index("]")]
    if value.count(":") == 1:
        name, port = value.rsplit(":", 1)
        if port.isdigit():
            return name
    return value


def client_ip_from_request(request: Request, *, trust_proxy_headers: bool) -> str:
    if trust_proxy_headers:
        forwarded_for = request.headers.get("x-forwarded-for", "")
        if forwarded_for:
            first = forwarded_for.split(",", 1)[0].strip()
            if first:
                return _strip_port(first)
        real_ip = request.headers.get("x-real-ip", "")
        if real_ip:
            return _strip_port(real_ip)
    if request.client is None:
        return "unknown"
    return _strip_port(request.client.host) or "unknown"
