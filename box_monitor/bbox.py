import http.cookiejar
import json
import ssl
import urllib.error
import urllib.parse
import urllib.request

BASE_URLS = [
    "http://192.168.1.254",
    "http://gestionbbox.lan",
    "https://mabbox.bytel.fr",
]


class BboxError(Exception):
    pass


def _walk_find(obj, predicate, results):
    if isinstance(obj, dict):
        for key, value in obj.items():
            if predicate(key, value):
                results.append((key, value))
            _walk_find(value, predicate, results)
    elif isinstance(obj, list):
        for index, item in enumerate(obj):
            if predicate(str(index), item):
                results.append((str(index), item))
            _walk_find(item, predicate, results)


class BboxClient:
    def __init__(self, base_url, password=None):
        self.base_url = base_url.rstrip("/")
        self.password = password
        context = ssl.create_default_context()
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE
        self.opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()),
            urllib.request.HTTPSHandler(context=context),
        )

    def _get_json(self, path, timeout=8):
        url = self.base_url + path
        req = urllib.request.Request(url)
        req.add_header("Accept", "application/json")
        try:
            resp = self.opener.open(req, timeout=timeout)
        except urllib.error.HTTPError as exc:
            if exc.code in (401, 403):
                raise BboxError("auth_required")
            raise BboxError("Erreur HTTP Bbox : %s" % exc.code)
        except (urllib.error.URLError, OSError) as exc:
            raise BboxError("Bbox injoignable : %s" % exc)
        body = resp.read().decode("utf-8", "replace")
        try:
            return json.loads(body)
        except ValueError:
            raise BboxError("Réponse Bbox illisible")

    def detect(self):
        try:
            data = self._get_json("/api/v1/device")
        except BboxError:
            return False
        return isinstance(data, dict) and bool(data.get("device"))

    def login(self, password=None):
        if password:
            self.password = password
        if not self.password:
            raise BboxError("Mot de passe admin Bbox requis")
        url = self.base_url + "/api/v1/login"
        data = urllib.parse.urlencode({"password": self.password}).encode("utf-8")
        req = urllib.request.Request(url, data=data, method="POST")
        req.add_header("Content-Type", "application/x-www-form-urlencoded")
        try:
            resp = self.opener.open(req, timeout=8)
            body = resp.read().decode("utf-8", "replace")
        except (urllib.error.URLError, OSError) as exc:
            raise BboxError("Connexion Bbox impossible : %s" % exc)
        if '"ok"' not in body and '"error"' in body:
            raise BboxError("Mot de passe Bbox refusé")

    def get_snapshot(self):
        snapshot = {
            "source": "Bbox",
            "box_name": "Bbox",
            "state": "",
            "rate_down": 0.0,
            "rate_up": 0.0,
            "bytes_down": None,
            "bytes_up": None,
            "bandwidth_down": 0.0,
            "bandwidth_up": 0.0,
            "ipv4": "",
            "devices": [],
            "temps": {},
        }
        try:
            stats = self._get_json("/api/v1/wan/ip/stats")
            rx, tx = self._extract_counters(stats)
            snapshot["bytes_down"] = rx
            snapshot["bytes_up"] = tx
        except BboxError as exc:
            if str(exc) == "auth_required" and self.password:
                self.login()
                stats = self._get_json("/api/v1/wan/ip/stats")
                rx, tx = self._extract_counters(stats)
                snapshot["bytes_down"] = rx
                snapshot["bytes_up"] = tx
        try:
            wan_ip = self._get_json("/api/v1/wan/ip")
            results = []
            _walk_find(
                wan_ip,
                lambda k, v: isinstance(v, str) and v.count(".") == 3,
                results,
            )
            if results:
                snapshot["ipv4"] = results[0][1]
        except BboxError:
            pass
        try:
            device = self._get_json("/api/v1/device")
            info = device.get("device", {}) if isinstance(device, dict) else {}
            if info.get("ModelName"):
                snapshot["box_name"] = "Bbox %s" % info["ModelName"]
            if info.get("Uptime"):
                snapshot["temps"]["Uptime (s)"] = int(info["Uptime"])
            if info.get("Temperature"):
                snapshot["temps"]["Température"] = info["Temperature"]
        except BboxError:
            pass
        try:
            hosts = self._get_json("/api/v1/hosts")
            devices = self._extract_hosts(hosts)
            snapshot["devices"] = devices
        except BboxError:
            pass
        return snapshot

    @staticmethod
    def _numeric(value):
        if isinstance(value, bool):
            return None
        if isinstance(value, (int, float)):
            return value
        if isinstance(value, str):
            try:
                return float(value)
            except ValueError:
                return None
        return None

    @classmethod
    def _extract_counters(cls, stats):
        rx = tx = None
        results = []
        _walk_find(
            stats,
            lambda k, v: ("rx" in k.lower() or "recv" in k.lower() or "received" in k.lower())
            and "byte" in k.lower()
            and cls._numeric(v) is not None,
            results,
        )
        if results:
            rx = int(max(cls._numeric(v) for _, v in results))
        results = []
        _walk_find(
            stats,
            lambda k, v: ("tx" in k.lower() or "sent" in k.lower() or "transmit" in k.lower())
            and "byte" in k.lower()
            and cls._numeric(v) is not None,
            results,
        )
        if results:
            tx = int(max(cls._numeric(v) for _, v in results))
        return rx, tx

    @staticmethod
    def _extract_hosts(data):
        hosts = []
        found = []

        def collect(key, value):
            if isinstance(value, dict) and any(
                k in value for k in ("macaddress", "mac_address", "mac")
            ):
                found.append(value)

        _walk_find(data, collect, found)
        for host in found:
            hosts.append(
                {
                    "name": host.get("hostname")
                    or host.get("name")
                    or "Inconnu",
                    "ip": host.get("ipaddress")
                    or host.get("ip_address")
                    or host.get("ip")
                    or "",
                    "mac": host.get("macaddress")
                    or host.get("mac_address")
                    or host.get("mac")
                    or "",
                    "active": bool(host.get("active", True)),
                }
            )
        return hosts
