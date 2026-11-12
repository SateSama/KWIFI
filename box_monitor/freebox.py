import hashlib
import hmac
import json
import os
import time
import urllib.error
import urllib.request

DISCOVERY_URL = "http://mafreebox.freebox.fr/api_version"


class FreeboxError(Exception):
    pass


class FreeboxClient:
    APP_ID = "fr.surveillancebox.app"
    APP_NAME = "Surveillance Box"
    APP_VERSION = "1.0.0"
    DEVICE_NAME = "Surveillance Box"

    def __init__(self, token_path=None):
        if token_path is None:
            config_dir = os.path.join(
                os.path.expanduser("~"), ".config", "surveillance-box"
            )
            os.makedirs(config_dir, exist_ok=True)
            token_path = os.path.join(config_dir, "freebox_token.json")
        self.token_path = token_path
        self.api_base_url = None
        self.api_version = None
        self.device_name = "Freebox"
        self.app_token = None
        self.track_id = None
        self.session_token = None
        self.challenge = None

    def _load_token(self):
        try:
            with open(self.token_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            self.app_token = data.get("app_token")
            self.track_id = data.get("track_id")
        except (OSError, ValueError):
            self.app_token = None
            self.track_id = None

    def _save_token(self):
        data = {"app_token": self.app_token, "track_id": self.track_id}
        with open(self.token_path, "w", encoding="utf-8") as f:
            json.dump(data, f)

    def _request(self, url, method="GET", payload=None, headers=None, timeout=8):
        data = None
        if payload is not None:
            data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(url, data=data, method=method)
        req.add_header("Content-Type", "application/json")
        for key, value in (headers or {}).items():
            req.add_header(key, value)
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))

    def discover(self):
        try:
            resp = self._request(DISCOVERY_URL)
        except (urllib.error.URLError, OSError, ValueError):
            return False
        if not resp.get("api_base_url"):
            return False
        self.api_base_url = resp["api_base_url"]
        self.api_version = resp.get("api_version", "")
        self.device_name = resp.get("device_name", "Freebox")
        return True

    def _url(self, path):
        return "http://mafreebox.freebox.fr" + self.api_base_url + path

    def register(self):
        payload = {
            "app_id": self.APP_ID,
            "app_name": self.APP_NAME,
            "app_version": self.APP_VERSION,
            "device_name": self.DEVICE_NAME,
        }
        resp = self._request(self._url("login/authorize/"), method="POST", payload=payload)
        if not resp.get("success"):
            raise FreeboxError("Échec de la demande d'autorisation Freebox")
        result = resp["result"]
        self.track_id = result["track_id"]
        self.app_token = result["app_token"]
        self._save_token()

    def poll_authorization(self):
        resp = self._request(self._url("login/authorize/%d" % self.track_id))
        if not resp.get("success"):
            raise FreeboxError("Requête d'autorisation invalide")
        return resp["result"].get("status", "unknown")

    def wait_for_authorization(self, timeout=300, poll_delay=1.0, progress=None):
        deadline = time.time() + timeout
        while time.time() < deadline:
            status = self.poll_authorization()
            if progress:
                progress(status)
            if status == "granted":
                return True
            if status in ("denied", "timeout", "unknown"):
                raise FreeboxError(
                    "Autorisation refusée ou expirée (statut : %s)" % status
                )
            time.sleep(poll_delay)
        raise FreeboxError("Délai dépassé en attendant l'autorisation sur la Freebox")

    def open_session(self):
        self._load_token()
        if not self.app_token:
            raise FreeboxError(
                "Aucun jeton d'appairage. Lancez d'abord l'appairage avec la Freebox."
            )
        resp = self._request(self._url("login/"))
        challenge = resp["result"]["challenge"]
        if self.session_token:
            return
        password = hmac.new(
            self.app_token.encode("utf-8"), challenge.encode("utf-8"), hashlib.sha1
        ).hexdigest()
        payload = {
            "app_id": self.APP_ID,
            "app_version": self.APP_VERSION,
            "password": password,
        }
        resp = self._request(self._url("login/session/"), method="POST", payload=payload)
        if not resp.get("success"):
            raise FreeboxError("Ouverture de session refusée par la Freebox")
        result = resp["result"]
        self.session_token = result["session_token"]
        self.challenge = result.get("challenge", challenge)

    def _authed_get(self, path):
        if not self.session_token:
            raise FreeboxError("Non connecté à la Freebox")
        resp = self._request(
            self._url(path), headers={"X-Fbx-App-Auth": self.session_token}
        )
        if resp.get("error_code") in ("auth_required", "invalid_token"):
            self.session_token = None
            raise FreeboxError("Session Freebox expirée, reconnexion nécessaire")
        if not resp.get("success"):
            raise FreeboxError("Requête Freebox échouée : %s" % path)
        return resp["result"]

    def get_snapshot(self):
        connection = self._authed_get("connection/")
        snapshot = {
            "source": "Freebox",
            "box_name": self.device_name,
            "state": connection.get("state", ""),
            "rate_down": float(connection.get("rate_down", 0)),
            "rate_up": float(connection.get("rate_up", 0)),
            "bytes_down": int(connection.get("bytes_down", 0)),
            "bytes_up": int(connection.get("bytes_up", 0)),
            "bandwidth_down": float(connection.get("bandwidth_down", 0)),
            "bandwidth_up": float(connection.get("bandwidth_up", 0)),
            "ipv4": connection.get("ipv4", ""),
            "devices": [],
            "temps": {},
        }
        try:
            hosts = self._authed_get("lan/browser/pub/")
            for host in hosts:
                info = host.get("host", {}) or {}
                names = info.get("names") or []
                name = names[0].get("name") if names else info.get("primary_name", "")
                snapshot["devices"].append(
                    {
                        "name": name or "Inconnu",
                        "ip": info.get("l3connectivities", [{}])[0].get("addr", "")
                        if info.get("l3connectivities")
                        else "",
                        "mac": info.get("mac", ""),
                        "active": info.get("active", False),
                    }
                )
        except FreeboxError:
            pass
        try:
            system = self._authed_get("system/")
            temps = system.get("temperature", {}) or {}
            snapshot["temps"] = {
                "CPU (marron)": temps.get("temp_cpum"),
                "CPU (blanc)": temps.get("temp_cpub"),
                "Switch": temps.get("temp_sw"),
                "Interne": temps.get("temp_int"),
                "Ventilateur (rpm)": system.get("fan_rpm"),
                "Uptime (s)": system.get("uptime_val"),
            }
        except FreeboxError:
            pass
        return snapshot
