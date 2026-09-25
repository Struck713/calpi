"""Generic WebDAV/CalDAV helpers: PROPFIND building and 207 Multi-Status parsing. No gi."""
from __future__ import annotations

import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from urllib.parse import urljoin

from calpi.sync.errors import ErrorCode, SyncError
from calpi.sync.http import HttpClient

NS = {"d": "DAV:", "c": "urn:ietf:params:xml:ns:caldav",
      "cs": "http://calendarserver.org/ns/", "a": "http://apple.com/ns/ical/"}

for _p, _u in NS.items():
    ET.register_namespace(_p, _u)


def qname(prop: str) -> str:
    """'d:displayname' -> '{DAV:}displayname'."""
    p, local = prop.split(":", 1)
    return f"{{{NS[p]}}}{local}"


def build_propfind(props: list[str]) -> bytes:
    root = ET.Element(qname("d:propfind"))
    prop = ET.SubElement(root, qname("d:prop"))
    for p in props:
        ET.SubElement(prop, qname(p))
    return ET.tostring(root, encoding="utf-8", xml_declaration=True)


@dataclass
class DavResponse:
    href: str
    props: dict = field(default_factory=dict)     # "d:displayname" -> Element (200 propstats only)


def _short(tag: str) -> str:
    if tag.startswith("{"):
        uri, local = tag[1:].split("}", 1)
        for p, u in NS.items():
            if u == uri:
                return f"{p}:{local}"
        return tag
    return tag


def check_xml(body: bytes) -> None:
    if b"<!DOCTYPE" in body.upper():
        raise SyncError(ErrorCode.PARSE_ERROR, "DOCTYPE not allowed")


def parse_multistatus(body: bytes, base_url: str) -> list[DavResponse]:
    check_xml(body)
    try:
        root = ET.fromstring(body)
    except ET.ParseError as e:
        raise SyncError(ErrorCode.PARSE_ERROR, f"invalid XML: {e}") from None
    if root.tag != qname("d:multistatus"):
        raise SyncError(ErrorCode.PARSE_ERROR, "not a multistatus response")
    out = []
    for r in root.findall("d:response", NS):
        href = r.findtext("d:href", default="", namespaces=NS).strip()
        if not href:
            continue
        resp = DavResponse(urljoin(base_url, href))
        for ps in r.findall("d:propstat", NS):
            if " 200 " not in " " + (ps.findtext("d:status", default="", namespaces=NS) or "") + " ":
                continue
            prop = ps.find("d:prop", NS)
            if prop is None:
                continue
            for el in prop:
                resp.props[_short(el.tag)] = el
        out.append(resp)
    return out


def propfind(client: HttpClient, url: str, props: list[str], depth: int, auth) -> list[DavResponse]:
    r = client.request("PROPFIND", url, body=build_propfind(props),
                       headers={"Depth": str(depth)}, auth=auth)
    return parse_multistatus(r.body, base_url=r.url)


def text(resp: DavResponse, prop: str) -> str | None:
    el = resp.props.get(prop)
    if el is None or el.text is None:
        return None
    t = el.text.strip()
    return t or None


def href_in(resp: DavResponse, prop: str) -> str | None:
    el = resp.props.get(prop)
    if el is None:
        return None
    h = el.findtext("d:href", default="", namespaces=NS).strip()
    return urljoin(resp.href, h) if h else None
