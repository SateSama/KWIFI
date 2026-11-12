import queue
import threading
import time

from . import upnp
from .bbox import BboxClient, BboxError
from .freebox import FreeboxClient, FreeboxError
from .livebox import LiveboxClient, LiveboxError
from .sfr import SFRBoxClient, SFRBoxError

LIVEBOX_WS_URLS = [
    "http://livebox.home/ws",
    "http://192.168.1.1/ws",
    "http://livebox/ws",
]
SFR_BASE_URLS = [
    "http://192.168.1.1",
    "http://192.168.0.1",
    "http://sfrbox.lan",
]
BBOX_BASE_URLS = [
    "http://192.168.1.254",
    "http://gestionbbox.lan",
    "https://mabbox.bytel.fr",
]


class Monitor:
    def __init__(self, storage, poll_interval=2.0):
        self.storage = storage
        self.poll_interval = poll_interval
        self.events = queue.Queue()
        self.client = None
        self.mode = None
        self.upnp_client = None
        self._upnp_totals = None
        self._stop = threading.Event()
        self._thread = None
        self._last_totals = None
        self._password_requested = threading.Event()
        self._password_slot = []

    def _emit(self, kind, **data):
        self.events.put({"kind": kind, **data})

    def set_password(self, password):
        self._password_slot.append(password)
        self._password_requested.set()

    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()

    def _wait_for_password(self, box_name):
        self._emit(
            "credentials_required",
            box=box_name,
            message=(
                "%s : mot de passe admin requis pour les détails "
                "(appareils, compteurs)." % box_name
            ),
        )
        self._password_requested.wait(timeout=600)
        if self._password_slot:
            return self._password_slot.pop(0)
        return None

    def _run(self):
        self._emit("status", message="Détection de la box...")
        detected = self._detect()
        if detected is None:
            self._emit(
                "error",
                message=(
                    "Aucune box détectée. Êtes-vous connecté au réseau local "
                    "de la box ?"
                ),
            )
            return
        client, mode = detected
        if getattr(client, "requires_password", False):
            password = self._wait_for_password(client.box_label)
            if password is None:
                self._emit(
                    "error",
                    message="Mot de passe non fourni : mode limité (UPnP).",
                )
                fallback = self._try_upnp(report=False)
                if fallback is None:
                    return
                client, mode = fallback
            else:
                try:
                    client.login(password)
                except (LiveboxError, SFRBoxError, BboxError) as exc:
                    self._emit("error", message=str(exc))
                    return
        self.client = client
        self.mode = mode
        try:
            snapshot = client.get_snapshot()
        except (FreeboxError, LiveboxError, SFRBoxError, BboxError) as exc:
            self._emit("error", message=str(exc))
            return
        self._emit("connected", snapshot=snapshot)
        while not self._stop.is_set():
            started = time.time()
            try:
                snapshot = self._poll_once()
                if snapshot is not None:
                    self._emit("snapshot", snapshot=snapshot)
            except (FreeboxError, LiveboxError, SFRBoxError, BboxError) as exc:
                self._emit("status", message="Erreur de lecture : %s" % exc)
            except Exception as exc:
                self._emit("status", message="Erreur inattendue : %s" % exc)
            elapsed = time.time() - started
            self._stop.wait(max(0.5, self.poll_interval - elapsed))

    def _detect(self):
        attempts = (
            (self._try_freebox, "Freebox"),
            (self._try_livebox, "Livebox"),
            (self._try_sfr, "SFR"),
            (self._try_bbox, "Bbox"),
            (self._try_upnp, "UPnP"),
        )
        for attempt, label in attempts:
            self._emit("status", message="Détection : essai %s..." % label)
            result = attempt()
            if result is not None:
                return result
        return None

    def _try_freebox(self):
        client = FreeboxClient()
        if not client.discover():
            return None
        self._emit("status", message="Freebox détectée, ouverture de session...")
        try:
            client.open_session()
        except FreeboxError as exc:
            self._emit("pairing_required", message=str(exc))
            return None
        try:
            client.get_snapshot()
        except FreeboxError as exc:
            self._emit("error", message=str(exc))
            return None
        return client, "freebox"

    def pair_and_run(self):
        def run():
            self._emit("status", message="Appairage avec la Freebox...")
            try:
                client = FreeboxClient()
                if not client.discover():
                    self._emit("error", message="Freebox introuvable sur le réseau.")
                    return
                client.register()
                self._emit(
                    "status",
                    message=(
                        "Appuyez sur la flèche droite de la Freebox pour autoriser "
                        "l'application (2 minutes)."
                    ),
                )
                client.wait_for_authorization(
                    progress=lambda status: self._emit(
                        "status", message="Statut appairage : %s" % status
                    )
                )
                client.open_session()
                self.client = client
                self.mode = "freebox"
                self._emit("connected", snapshot=client.get_snapshot())
                while not self._stop.is_set():
                    time.sleep(self.poll_interval)
                    try:
                        self._emit("snapshot", snapshot=client.get_snapshot())
                    except FreeboxError as exc:
                        self._emit("status", message="Erreur : %s" % exc)
                        try:
                            client.open_session()
                        except FreeboxError:
                            break
            except FreeboxError as exc:
                self._emit("error", message=str(exc))

        self._stop.clear()
        self._thread = threading.Thread(target=run, daemon=True)
        self._thread.start()

    def _try_livebox(self):
        for ws_url in LIVEBOX_WS_URLS:
            client = LiveboxClient(ws_url)
            if not client.detect():
                continue
            self._emit("status", message="Livebox détectée (%s)." % ws_url)
            client.requires_password = True
            client.box_label = "Livebox"
            return client, "livebox"
        return None

    def _try_sfr(self):
        for base_url in SFR_BASE_URLS:
            client = SFRBoxClient(base_url)
            if not client.detect():
                continue
            self._emit("status", message="Box SFR détectée (%s)." % base_url)
            client.requires_password = True
            client.box_label = "Box SFR"
            return client, "sfr"
        return None

    def _try_bbox(self):
        for base_url in BBOX_BASE_URLS:
            client = BboxClient(base_url)
            if not client.detect():
                continue
            self._emit("status", message="Bbox détectée (%s)." % base_url)
            client.requires_password = False
            client.box_label = "Bbox"
            return client, "bbox"
        return None

    def _try_upnp(self, report=True):
        if report:
            self._emit("status", message="Recherche UPnP (box générique)...")
        try:
            locations = upnp.ssdp_discover(timeout=4)
        except OSError:
            return None
        for location in locations:
            try:
                client = upnp.UPnPClient(location)
                totals = client.get_totals()
            except (upnp.UPnPError, OSError):
                continue
            self.client = client
            self.mode = "upnp"
            now = time.time()
            self._last_totals = (now, totals["bytes_down"], totals["bytes_up"])
            return client, "upnp"
        return None

    def _ensure_upnp_fallback(self):
        if self.upnp_client is not None:
            return True
        try:
            locations = upnp.ssdp_discover(timeout=4)
        except OSError:
            return False
        for location in locations:
            try:
                client = upnp.UPnPClient(location)
                totals = client.get_totals()
            except (upnp.UPnPError, OSError):
                continue
            self.upnp_client = client
            now = time.time()
            self._upnp_totals = (now, totals["bytes_down"], totals["bytes_up"])
            return True
        return False

    def _augment_with_upnp(self, snapshot):
        if snapshot.get("bytes_down") is not None:
            return snapshot
        if not self._ensure_upnp_fallback():
            return snapshot
        try:
            totals = self.upnp_client.get_totals()
        except (upnp.UPnPError, OSError):
            return snapshot
        now = time.time()
        rate_down = rate_up = 0.0
        if self._upnp_totals:
            prev_ts, prev_down, prev_up = self._upnp_totals
            dt = now - prev_ts
            if dt > 0:
                rate_down = max(0.0, (totals["bytes_down"] - prev_down) / dt)
                rate_up = max(0.0, (totals["bytes_up"] - prev_up) / dt)
        self._upnp_totals = (now, totals["bytes_down"], totals["bytes_up"])
        snapshot["bytes_down"] = totals["bytes_down"]
        snapshot["bytes_up"] = totals["bytes_up"]
        if not snapshot.get("rate_down"):
            snapshot["rate_down"] = rate_down
        if not snapshot.get("rate_up"):
            snapshot["rate_up"] = rate_up
        if not snapshot.get("ipv4"):
            snapshot["ipv4"] = totals.get("ipv4", "")
        return snapshot

    def _poll_once(self):
        if self.mode == "freebox":
            return self.client.get_snapshot()
        if self.mode in ("livebox", "sfr", "bbox"):
            snapshot = self.client.get_snapshot()
            return self._augment_with_upnp(snapshot)
        if self.mode == "upnp":
            totals = self.client.get_totals()
            now = time.time()
            rate_down = rate_up = 0.0
            if self._last_totals:
                prev_ts, prev_down, prev_up = self._last_totals
                dt = now - prev_ts
                if dt > 0:
                    rate_down = max(0.0, (totals["bytes_down"] - prev_down) / dt)
                    rate_up = max(0.0, (totals["bytes_up"] - prev_up) / dt)
            self._last_totals = (now, totals["bytes_down"], totals["bytes_up"])
            return {
                "source": "UPnP",
                "box_name": self.client.friendly_name,
                "state": "UPnP",
                "rate_down": rate_down,
                "rate_up": rate_up,
                "bytes_down": totals["bytes_down"],
                "bytes_up": totals["bytes_up"],
                "bandwidth_down": 0.0,
                "bandwidth_up": 0.0,
                "ipv4": totals["ipv4"],
                "devices": [],
                "temps": {},
            }
        return None
