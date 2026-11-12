import queue
import threading
import time

from . import upnp
from .freebox import FreeboxClient, FreeboxError


class Monitor:
    def __init__(self, storage, poll_interval=2.0):
        self.storage = storage
        self.poll_interval = poll_interval
        self.events = queue.Queue()
        self.client = None
        self.mode = None
        self._stop = threading.Event()
        self._thread = None
        self._last_totals = None

    def _emit(self, kind, **data):
        self.events.put({"kind": kind, **data})

    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()

    def _run(self):
        self._emit("status", message="Détection de la box...")
        snapshot = self._try_freebox()
        if snapshot is None:
            snapshot = self._try_upnp()
        if snapshot is None:
            self._emit(
                "error",
                message=(
                    "Aucune box détectée. Êtes-vous connecté au réseau local de la box ?"
                ),
            )
            return
        self._emit("connected", snapshot=snapshot)
        while not self._stop.is_set():
            started = time.time()
            try:
                snapshot = self._poll_once()
                if snapshot is not None:
                    self._emit("snapshot", snapshot=snapshot)
            except Exception as exc:
                self._emit("status", message="Erreur de lecture : %s" % exc)
            elapsed = time.time() - started
            self._stop.wait(max(0.5, self.poll_interval - elapsed))

    def _try_freebox(self):
        client = FreeboxClient()
        if not client.discover():
            self._emit("status", message="Freebox non détectée, essai UPnP...")
            return None
        self._emit("status", message="Freebox détectée, ouverture de session...")
        try:
            client.open_session()
        except FreeboxError as exc:
            self._emit("pairing_required", message=str(exc))
            return None
        self.client = client
        self.mode = "freebox"
        try:
            return client.get_snapshot()
        except FreeboxError as exc:
            self._emit("error", message=str(exc))
            return None

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

    def _try_upnp(self):
        self._emit("status", message="Recherche UPnP (Livebox, SFR...)...")
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
            return {
                "source": "UPnP",
                "box_name": client.friendly_name,
                "state": "UPnP",
                "rate_down": 0.0,
                "rate_up": 0.0,
                "bytes_down": totals["bytes_down"],
                "bytes_up": totals["bytes_up"],
                "bandwidth_down": 0.0,
                "bandwidth_up": 0.0,
                "ipv4": totals["ipv4"],
                "devices": [],
                "temps": {},
            }
        return None

    def _poll_once(self):
        if self.mode == "freebox":
            return self.client.get_snapshot()
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
