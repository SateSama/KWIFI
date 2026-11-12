import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from .formatting import format_bytes, format_rate
from .monitor import Monitor
from .storage import Storage


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Surveillance Box")
        self.geometry("860x640")
        self.minsize(720, 560)

        self.storage = Storage()
        self.monitor = Monitor(self.storage)
        self.samples = []
        self.max_samples = 150

        self._build_ui()
        self.after(150, self._drain_events)
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.monitor.start()

    def _build_ui(self):
        header = ttk.Frame(self, padding=(12, 10))
        header.pack(fill="x")
        self.box_label = ttk.Label(header, text="Box : détection...", font=("", 12, "bold"))
        self.box_label.pack(side="left")
        self.ip_label = ttk.Label(header, text="IP publique : —")
        self.ip_label.pack(side="right")

        main = ttk.Frame(self, padding=(12, 0))
        main.pack(fill="both", expand=True)

        rates = ttk.LabelFrame(main, text="Trafic en temps réel", padding=12)
        rates.pack(fill="x")
        self.down_label = ttk.Label(
            rates, text="↓ Descendant : —", font=("", 16, "bold"), foreground="#1a7f37"
        )
        self.down_label.grid(row=0, column=0, sticky="w", padx=(0, 30))
        self.up_label = ttk.Label(
            rates, text="↑ Montant : —", font=("", 16, "bold"), foreground="#b35900"
        )
        self.up_label.grid(row=0, column=1, sticky="w")
        self.total_label = ttk.Label(rates, text="Depuis le démarrage du compteur : —", foreground="#555")
        self.total_label.grid(row=1, column=0, columnspan=2, sticky="w", pady=(6, 0))

        graph_frame = ttk.LabelFrame(main, text="Historique des débits", padding=8)
        graph_frame.pack(fill="both", expand=True, pady=(10, 0))
        self.canvas = tk.Canvas(graph_frame, height=220, background="#fafafa", highlightthickness=0)
        self.canvas.pack(fill="both", expand=True)
        self.canvas.bind("<Configure>", lambda event: self._draw_graph())

        bottom = ttk.Frame(main)
        bottom.pack(fill="both", expand=True, pady=(10, 0))
        devices_frame = ttk.LabelFrame(bottom, text="Appareils connectés (Freebox)", padding=6)
        devices_frame.pack(side="left", fill="both", expand=True, padx=(0, 10))
        columns = ("name", "ip", "mac", "status")
        self.devices = ttk.Treeview(devices_frame, columns=columns, show="headings", height=7)
        self.devices.heading("name", text="Nom")
        self.devices.heading("ip", text="IP")
        self.devices.heading("mac", text="MAC")
        self.devices.heading("status", text="État")
        self.devices.column("name", width=180)
        self.devices.column("ip", width=120)
        self.devices.column("mac", width=140)
        self.devices.column("status", width=70, anchor="center")
        self.devices.pack(fill="both", expand=True)

        info_frame = ttk.LabelFrame(bottom, text="Informations box", padding=6)
        info_frame.pack(side="left", fill="both", expand=True)
        self.info_text = tk.Text(info_frame, height=7, width=32, state="disabled", relief="flat", background="#fafafa")
        self.info_text.pack(fill="both", expand=True)

        actions = ttk.Frame(self, padding=(12, 8))
        actions.pack(fill="x")
        ttk.Button(actions, text="Exporter l'historique (CSV)", command=self._export_csv).pack(side="left")
        ttk.Button(actions, text="Appairer la Freebox", command=self._pair_freebox).pack(side="left", padx=8)
        self.status_label = ttk.Label(actions, text="Prêt.", foreground="#555")
        self.status_label.pack(side="right", padx=8)

    def _drain_events(self):
        try:
            while True:
                event = self.monitor.events.get_nowait()
                self._handle_event(event)
        except Exception:
            pass
        self.after(150, self._drain_events)

    def _handle_event(self, event):
        kind = event["kind"]
        message = event.get("message")
        if message:
            self.status_label.config(text=message)
        if kind == "connected":
            self.status_label.config(text="Connecté à la box.")
            self._apply_snapshot(event["snapshot"])
        elif kind == "snapshot":
            self._apply_snapshot(event["snapshot"])
        elif kind == "pairing_required":
            self.status_label.config(
                text="Appairage Freebox requis : cliquez sur « Appairer la Freebox »."
            )
        elif kind == "error":
            messagebox.showwarning("Surveillance Box", message)

    def _apply_snapshot(self, snapshot):
        self.box_label.config(
            text="Box : %s (%s)" % (snapshot["box_name"], snapshot["source"])
        )
        self.ip_label.config(text="IP publique : %s" % (snapshot["ipv4"] or "—"))
        self.down_label.config(text="↓ Descendant : %s" % format_rate(snapshot["rate_down"]))
        self.up_label.config(text="↑ Montant : %s" % format_rate(snapshot["rate_up"]))
        self.total_label.config(
            text="Depuis le démarrage du compteur : ↓ %s  •  ↑ %s"
            % (
                format_bytes(snapshot["bytes_down"]),
                format_bytes(snapshot["bytes_up"]),
            )
        )
        self.storage.insert(
            snapshot["source"],
            snapshot["bytes_down"],
            snapshot["bytes_up"],
            snapshot["rate_down"],
            snapshot["rate_up"],
        )
        self.samples.append((snapshot["rate_down"], snapshot["rate_up"]))
        if len(self.samples) > self.max_samples:
            self.samples = self.samples[-self.max_samples:]
        self._draw_graph()

        self.devices.delete(*self.devices.get_children())
        for device in snapshot["devices"]:
            self.devices.insert(
                "",
                "end",
                values=(
                    device["name"],
                    device["ip"],
                    device["mac"],
                    "Actif" if device["active"] else "Inactif",
                ),
            )

        temps = snapshot["temps"]
        if temps:
            self.info_text.config(state="normal")
            self.info_text.delete("1.0", "end")
            for key, value in temps.items():
                if value is None:
                    continue
                if "Uptime" in key:
                    days, rest = divmod(int(value), 86400)
                    hours, rest = divmod(rest, 3600)
                    minutes = rest // 60
                    text = "%dj %dh %dm" % (days, hours, minutes)
                elif "Ventilateur" in key:
                    text = "%d rpm" % value
                else:
                    text = "%.0f °C" % value
                self.info_text.insert("end", "%s : %s\n" % (key, text))
            self.info_text.config(state="disabled")
        else:
            self.info_text.config(state="normal")
            self.info_text.delete("1.0", "end")
            self.info_text.insert(
                "end",
                "Mode UPnP générique :\ndétails limités à la box.\nVolume total et débits\nsont enregistrés.",
            )
            self.info_text.config(state="disabled")

    def _draw_graph(self):
        canvas = self.canvas
        canvas.delete("all")
        width = canvas.winfo_width()
        height = canvas.winfo_height()
        if width < 50 or height < 50:
            return
        padding = 28
        plot_w = width - padding * 2
        plot_h = height - padding * 2
        peak = max([max(d, u) for d, u in self.samples] or [1]) or 1
        peak *= 1.15
        for i in range(1, 5):
            y = padding + plot_h * i / 5
            canvas.create_line(padding, y, width - padding, y, fill="#e0e0e0")
            canvas.create_text(
                4,
                y,
                text=format_rate(peak * (5 - i) / 5),
                anchor="w",
                font=("", 7),
                fill="#888",
            )
        if len(self.samples) < 2:
            return
        step = plot_w / (self.max_samples - 1)
        offset = plot_w - step * (len(self.samples) - 1)

        def points(index):
            coords = []
            for i, sample in enumerate(self.samples):
                x = padding + offset + i * step
                y = padding + plot_h * (1 - sample[index] / peak)
                coords.extend((x, y))
            return coords

        canvas.create_line(points(0), fill="#1a7f37", width=2, tags="down")
        canvas.create_line(points(1), fill="#b35900", width=2, tags="up")
        canvas.create_text(
            width - padding,
            12,
            text="↓ descendant (vert)   ↑ montant (orange)",
            anchor="e",
            font=("", 8),
            fill="#666",
        )

    def _export_csv(self):
        path = filedialog.asksaveasfilename(
            defaultextension=".csv",
            filetypes=[("Fichier CSV", "*.csv")],
            initialfile="historique_trafic_box.csv",
        )
        if not path:
            return
        self.storage.export_csv(path)
        messagebox.showinfo("Surveillance Box", "Historique exporté :\n%s" % path)

    def _pair_freebox(self):
        self.monitor.stop()
        self.monitor.pair_and_run()

    def _on_close(self):
        self.monitor.stop()
        self.storage.close()
        self.destroy()


def run():
    app = App()
    app.mainloop()
