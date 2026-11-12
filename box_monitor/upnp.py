import re
import socket
import time
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from urllib.parse import urlparse

SSDP_ADDR = ("239.255.255.250", 1900)
SSDP_QUERY = (
    "M-SEARCH * HTTP/1.1\r\n"
    "HOST: 239.255.255.250:1900\r\n"
    'MAN: "ssdp:discover"\r\n'
    "MX: 3\r\n"
    "ST: urn:schemas-upnp-org:device:InternetGatewayDevice:1\r\n"
    "\r\n"
)

SOAP_TMPL = """<?xml version="1.0"?>
<s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/"
    s:encodingStyle="http://schemas.xmlsoap.org/soap/encoding/">
  <s:Body>
    <u:{action} xmlns:u="{service_type}">
    </u:{action}>
  </s:Body>
</s:Envelope>
"""


class UPnPError(Exception):
    pass


def _http_get(url, timeout=8):
    req = urllib.request.Request(url)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8", "replace")


def _http_post(url, headers, body, timeout=8):
    req = urllib.request.Request(url, data=body.encode("utf-8"), method="POST")
    for key, value in headers.items():
        req.add_header(key, value)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8", "replace")


def _local_ip():
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.connect(("8.8.8.8", 80))
        return sock.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        sock.close()


def ssdp_discover(timeout=4):
    found = []
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
    sock.settimeout(timeout)
    try:
        sock.sendto(SSDP_QUERY.encode("utf-8"), SSDP_ADDR)
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                data, _ = sock.recvfrom(4096)
            except socket.timeout:
                break
            text = data.decode("utf-8", "replace")
            match = re.search(r"(?i)LOCATION:\s*(\S+)", text)
            if match and match.group(1) not in found:
                found.append(match.group(1))
    finally:
        sock.close()
    return found


def _resolve_url(base_url, control_url):
    if control_url.startswith("http://") or control_url.startswith("https://"):
        return control_url
    parsed = urlparse(base_url)
    origin = parsed.scheme + "://" + parsed.netloc
    if control_url.startswith("/"):
        return origin + control_url
    base = base_url.rsplit("/", 1)[0]
    return base + "/" + control_url


class UPnPClient:
    def __init__(self, location):
        self.location = location
        self.control_url = None
        self.service_type = None
        self.friendly_name = "Box"
        self._discover_service()

    def _discover_service(self):
        xml_text = _http_get(self.location)
        root = ET.fromstring(xml_text)
        parsed = urlparse(self.location)
        url_base = parsed.scheme + "://" + parsed.netloc
        name_node = next(
            (c for c in root.iter() if c.tag.endswith("URLBase")), None
        )
        if name_node is not None and (name_node.text or "").strip():
            url_base = name_node.text.strip()
        name_node = next(
            (c for c in root.iter() if c.tag.endswith("friendlyName")), None
        )
        if name_node is not None and (name_node.text or "").strip():
            self.friendly_name = name_node.text.strip()

        wanted = (
            "WANCommonIFC1",
            "WANCommonInterfaceConfig",
            "WANIPConnection",
            "WANPPPConnection",
        )
        candidates = []
        for service in root.iter():
            if not service.tag.endswith("service"):
                continue
            service_id = service_type = control_url = ""
            for child in service:
                if child.tag.endswith("serviceId"):
                    service_id = (child.text or "").strip()
                elif child.tag.endswith("serviceType"):
                    service_type = (child.text or "").strip()
                elif child.tag.endswith("controlURL"):
                    control_url = (child.text or "").strip()
            for index, want in enumerate(wanted):
                if want in service_id or want in service_type:
                    candidates.append((index, service_type, control_url))
                    break
        if not candidates:
            raise UPnPError("Aucun service UPnP WAN trouvé sur la box")
        candidates.sort(key=lambda item: item[0])
        _, self.service_type, control_url = candidates[0]
        self.control_url = _resolve_url(url_base, control_url)

    def _soap(self, action):
        body = SOAP_TMPL.format(action=action, service_type=self.service_type)
        headers = {
            "SOAPAction": '"%s#%s"' % (self.service_type, action),
            "Content-Type": "text/xml; charset=utf-8",
        }
        text = _http_post(self.control_url, headers, body)
        match = re.search(
            r"<%s(?:Response)?[^>]*>(.*?)</%s(?:Response)?>" % (action, action),
            text,
            re.S,
        )
        result = {}
        if match:
            for arg in re.finditer(
                r"<([A-Za-z0-9_]+)>(.*?)</\1>", match.group(1), re.S
            ):
                result[arg.group(1)] = arg.group(2).strip()
        return result

    def get_totals(self):
        sent = received = None
        external_ip = ""
        for action, key in (("GetTotalBytesSent", "bytes_up"), ("GetTotalBytesReceived", "bytes_down")):
            try:
                result = self._soap(action)
                value = int(result.get("NewTotalBytesSent" if key == "bytes_up" else "NewTotalBytesReceived", 0))
            except (urllib.error.URLError, ValueError, KeyError) as exc:
                raise UPnPError("Compteur %s indisponible : %s" % (action, exc))
            if key == "bytes_up":
                sent = value
            else:
                received = value
        try:
            external_ip = self._soap("GetExternalIPAddress").get(
                "NewExternalIPAddress", ""
            )
        except (urllib.error.URLError, KeyError):
            pass
        return {"bytes_up": sent, "bytes_down": received, "ipv4": external_ip}
