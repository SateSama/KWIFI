import hashlib
import hmac
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

BASE_URLS = [
    "http://192.168.1.1",
    "http://192.168.0.1",
    "http://sfrbox.lan",
]

TOKEN_LIFETIME = 300


class SFRBoxError(Exception):
    pass


class SFRBoxClient:
    def __init__(self, base_url, password=None):
        self.base_url = base_url.rstrip("/")
        self.password = password
        self.token = None
        self.token_time = 0.0

    def _get_xml(self, params):
        query = urllib.parse.urlencode(params)
        url = self.base_url + "/api/1.0/?" + query
        req = urllib.request.Request(url)
        try:
            with urllib.request.urlopen(req, timeout=8) as resp:
                text = resp.read().decode("utf-8", "replace")
        except (urllib.error.URLError, OSError) as exc:
            raise SFRBoxError("Box SFR injoignable : %s" % exc)
        try:
            root = ET.fromstring(text)
        except ET.ParseError:
            raise SFRBoxError("Réponse SFR illisible")
        if root.get("stat") != "ok":
            err = root.find("err")
            code = err.get("code") if err is not None else "?"
            message = err.get("msg") if err is not None else "erreur inconnue"
            if code in ("115", "204", "901"):
                self.token = None
                raise SFRBoxError("Authentification SFR requise ou invalide")
            raise SFRBoxError("Erreur API SFR [%s] : %s" % (code, message))
        return root

    def detect(self):
        try:
            root = self._get_xml({"method": "system.getInfo"})
        except SFRBoxError:
            return False
        return root.find("system") is not None

    @staticmethod
    def _hmac_value(token, value):
        value_hash = hashlib.sha256(value.encode()).hexdigest()
        return hmac.new(
            token.encode(), value_hash.encode(), hashlib.sha256
        ).hexdigest()

    def _ensure_token(self):
        if self.token and (time.time() - self.token_time) < TOKEN_LIFETIME:
            return self.token
        if not self.password:
            raise SFRBoxError("Mot de passe admin SFR requis")
        root = self._get_xml({"method": "auth.getToken"})
        auth = root.find("auth")
        if auth is None:
            raise SFRBoxError("Token SFR indisponible")
        method = auth.get("method", "")
        if method not in ("all", "passwd"):
            raise SFRBoxError(
                "L'authentification par mot de passe est désactivée sur la box SFR"
            )
        token = auth.get("token", "")
        token_hash = self._hmac_value(token, "admin") + self._hmac_value(
            token, self.password
        )
        root = self._get_xml(
            {"method": "auth.checkToken", "token": token, "hash": token_hash}
        )
        auth = root.find("auth")
        if auth is None or not auth.get("token"):
            raise SFRBoxError("Authentification SFR refusée (mot de passe ?)")
        self.token = auth.get("token")
        self.token_time = time.time()
        return self.token

    def get_snapshot(self):
        snapshot = {
            "source": "SFR",
            "box_name": "Box SFR",
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
            root = self._get_xml({"method": "wan.getInfo"})
            wan = root.find("wan")
            if wan is not None:
                snapshot["ipv4"] = wan.get("ip_addr", "") or ""
                snapshot["state"] = wan.get("status", "") or ""
        except SFRBoxError:
            pass
        try:
            root = self._get_xml({"method": "system.getInfo"})
            system = root.find("system")
            if system is not None:
                if system.get("uptime"):
                    snapshot["temps"]["Uptime (s)"] = int(system.get("uptime"))
                temperature = system.get("temperature")
                if temperature:
                    value = float(temperature)
                    if value > 200:
                        value /= 1000
                    snapshot["temps"]["Température"] = value
                if system.get("product_id"):
                    snapshot["box_name"] = "Box SFR (%s)" % system.get("product_id")
        except SFRBoxError:
            pass
        try:
            token = self._ensure_token()
            root = self._get_xml({"method": "lan.getHostsInfo", "token": token})
            hosts = root.find("lan")
            clients = hosts.findall("client") if hosts is not None else []
            if not clients:
                root = self._get_xml({"method": "wlan.getClientList", "token": token})
                clients = root.findall("client")
            for client in clients:
                snapshot["devices"].append(
                    {
                        "name": client.get("hostname")
                        or client.get("interface")
                        or "Inconnu",
                        "ip": client.get("ip_addr", ""),
                        "mac": client.get("mac_addr", ""),
                        "active": client.get("status", "up") != "down",
                    }
                )
        except SFRBoxError:
            pass
        return snapshot
