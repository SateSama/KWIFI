import csv
import os
import sqlite3
import time

SCHEMA = """
CREATE TABLE IF NOT EXISTS traffic (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts REAL NOT NULL,
    source TEXT NOT NULL,
    bytes_down INTEGER NOT NULL,
    bytes_up INTEGER NOT NULL,
    rate_down REAL NOT NULL,
    rate_up REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_traffic_ts ON traffic(ts);
"""


class Storage:
    def __init__(self, db_path=None):
        if db_path is None:
            data_dir = os.path.join(
                os.path.expanduser("~"), ".local", "share", "surveillance-box"
            )
            os.makedirs(data_dir, exist_ok=True)
            db_path = os.path.join(data_dir, "traffic.db")
        self.db_path = db_path
        self.conn = sqlite3.connect(db_path)
        self.conn.executescript(SCHEMA)
        self.conn.commit()

    def insert(self, source, bytes_down, bytes_up, rate_down, rate_up):
        self.conn.execute(
            "INSERT INTO traffic (ts, source, bytes_down, bytes_up, rate_down, rate_up)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (time.time(), source, bytes_down, bytes_up, rate_down, rate_up),
        )
        self.conn.commit()

    def last(self, limit=500):
        cur = self.conn.execute(
            "SELECT ts, source, bytes_down, bytes_up, rate_down, rate_up"
            " FROM traffic ORDER BY ts DESC LIMIT ?",
            (limit,),
        )
        return cur.fetchall()

    def export_csv(self, path):
        cur = self.conn.execute(
            "SELECT ts, source, bytes_down, bytes_up, rate_down, rate_up"
            " FROM traffic ORDER BY ts ASC"
        )
        with open(path, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(
                [
                    "horodatage_iso",
                    "source",
                    "octets_descendant",
                    "octets_montant",
                    "debit_descendant_o_s",
                    "debit_montant_o_s",
                ]
            )
            for ts, source, bdown, bup, rdown, rup in cur:
                writer.writerow(
                    [
                        time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(ts)),
                        source,
                        bdown,
                        bup,
                        rdown,
                        rup,
                    ]
                )
        return path

    def close(self):
        self.conn.close()
