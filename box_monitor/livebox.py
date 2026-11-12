import http.cookiejar
import json
import urllib.error
import urllib.request

WS_URLS = [
    "http://livebox.home/ws",
    "http://192.168.1.1/ws",
    "http://livebox/ws",
]

COUNTER_KEYS_RX = ("rxbytes", "bytesreceived", "rx_byte")
COUNTER_KEYS_TX = ("txbytes", "bytessent", "tx_byte")


class LiveboxError(Exception):
    pass


class LiveboxClient:
    def __init__(self, ws_url, password=None):
        self.ws_url = ws_url
        self.password = password
        self.context_id = None
        self.sessid = None
        self.opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar())
        )

    def _post(self, service, method, parameters=None, authed=False):
        payload = {
            "service": service,
            "method": method,
            "parameters": parameters or {},
        }
        req = urllib.request.Request(
            self.ws_url,
            data=json.dumps(payload).encode("utf-8"),
            method="POST",
        )
        req.add_header("Content-Type", "application/x-sah-ws-4-call+json")
        if authed and self.context_id:
            req.add_header("Authorization", "X-Sah " + self.context_id)
            req.add_header("X-Context", self.context_id)
            if self.sessid:
                req.add_header("Cookie", "sessid=" + self.sessid)
        try:
            resp = self.opener.open(req, timeout=8)
        except (urllib.error.URLError, OSError) as exc:
            raise LiveboxError("Livebox injoignable : %s" % exc)
        body = resp.read().decode("utf-8", "replace")
        set_cookie = resp.headers.get("Set-Cookie", "") or ""
        for part in set_cookie.split(","):
            part = part.strip()
            if part.startswith("sessid="):
                self.sessid = part.split(";", 1)[0].split("=", 1)[1]
        try:
            return json.loads(body)
        except ValueError:
            raise LiveboxError("Réponse Livebox illisible")

    def detect(self):
        try:
            resp = self._post("NMC", "getWANStatus")
        except LiveboxError:
            return False
        data = (resp.get("data") or {}) if isinstance(resp, dict) else {}
        return bool(data.get("IPAddress") or data.get("ConnectionState"))

    def login(self, password=None):
        if password:
            self.password = password
        parameters = {
            "applicationName": "webui",
            "username": "admin",
            "password": self.password or "",
        }
        req = urllib.request.Request(
            self.ws_url,
            data=json.dumps(
                {
                    "service": "sah.Device.Information",
                    "method": "createContext",
                    "parameters": parameters,
                }
            ).encode("utf-8"),
            method="POST",
        )
        req.add_header("Content-Type", "application/x-sah-ws-4-call+json")
        req.add_header("Authorization", "X-Sah-Login")
        resp = self.opener.open(req, timeout=8)
        body = resp.read().decode("utf-8", "replace")
        set_cookie = resp.headers.get("Set-Cookie", "") or ""
        for part in set_cookie.split(","):
            part = part.strip()
            if part.startswith("sessid="):
                self.sessid = part.split(";", 1)[0].split("=", 1)[1]
        data = json.loads(body)
        if data.get("status") != 0 or not (data.get("data") or {}).get("contextID"):
            raise LiveboxError(
                "Connexion Livebox refusée. Vérifiez le mot de passe admin "
                "(par défaut : les 8 premiers caractères de la clé Wi-Fi)."
            )
        self.context_id = data["data"]["contextID"]

    def _find_counters(self, obj, found):
        if isinstance(obj, dict):
            for key, value in obj.items():
                kl = key.lower()
                if isinstance(value, (int, float)) and not isinstance(value, bool):
                    if any(k in kl for k in COUNTER_KEYS_RX):
                        found[0] = max(found[0], int(value))
                    elif any(k in kl for k in COUNTER_KEYS_TX):
                        found[1] = max(found[1], int(value))
                self._find_counters(value, found)
        elif isinstance(obj, list):
            for item in obj:
                self._find_counters(item, found)

    def _try_counters(self):
        for service, method, params in (
            ("NeMo.Intf.data", "getCounters", {}),
            ("NeMo.Intf.data", "getMIBs", {"mibs": "ptm_wan"}),
            ("NeMo.Intf.net", "getCounters", {}),
        ):
            try:
                resp = self._post(service, method, params, authed=True)
            except LiveboxError:
                continue
            found = [0, 0]
            self._find_counters(resp, found)
            if found[0] or found[1]:
                return found[0], found[1]
        return None, None

    def get_snapshot(self):
        status = self._post("NMC", "getWANStatus")
        wan = status.get("data") or {}

        bytes_down, bytes_up = self._try_counters()
        devices = []
        try:
            resp = self._post("Devices", "get", {}, authed=True)
            status_list = (resp.get("result", {}) or {}).get("status", []) or []
            if isinstance(status_list, list):
                for device in status_list:
                    if not isinstance(device, dict):
                        continue
                    names = device.get("Names") or []
                    name = (
                        device.get("Name")
                        or (names[0].get("Name") if names and isinstance(names[0], dict) else "")
                        or "Inconnu"
                    )
                    devices.append(
                        {
                            "name": name,
                            "ip": device.get("IPAddress")
                            or device.get("ConnectionIPv4Address")
                            or "",
                            "mac": device.get("MACAddress")
                            or device.get("PhysAddress")
                            or "",
                            "active": bool(device.get("Active")),
                        }
                    )
        except LiveboxError:
            pass

        temps = {}
        try:
            resp = self._post("System", "getInfo", {}, authed=True)
            info = (resp.get("result", {}) or {}).get("status", {}) or {}
            if isinstance(info, dict):
                if info.get("Temperature"):
                    temps["Température"] = info["Temperature"]
                if info.get("Uptime"):
                    temps["Uptime (s)"] = int(info["Uptime"])
        except LiveboxError:
            pass

        return {
            "source": "Livebox",
            "box_name": "Livebox",
            "state": wan.get("ConnectionState", ""),
            "rate_down": 0.0,
            "rate_up": 0.0,
            "bytes_down": bytes_down,
            "bytes_up": bytes_up,
            "bandwidth_down": 0.0,
            "bandwidth_up": 0.0,
            "ipv4": wan.get("IPAddress", ""),
            "devices": devices,
            "temps": temps,
        }
