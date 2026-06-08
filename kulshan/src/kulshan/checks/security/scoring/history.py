"""Security History, SQLite-based scan history with trend tracking."""

import sqlite3
import json
import os
from datetime import datetime
from typing import Dict, List, Optional

DB_PATH = os.path.join(os.path.expanduser("~"), ".Kulshan", "security", "history.db")


def _get_db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""CREATE TABLE IF NOT EXISTS scans (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        account_id TEXT NOT NULL,
        scan_date TEXT NOT NULL,
        overall_score REAL,
        overall_grade TEXT,
        total_findings INTEGER,
        critical INTEGER,
        high INTEGER,
        medium INTEGER,
        low INTEGER,
        category_scores TEXT,
        exposure_score REAL,
        scan_duration REAL,
        regions INTEGER,
        summary TEXT
    )""")
    conn.commit()
    return conn


def save_scan(account_id: str, scores: Dict, exposure: Dict, scan_duration: float,
              regions: int, findings_count: Dict):
    conn = _get_db()
    conn.execute(
        """INSERT INTO scans (account_id, scan_date, overall_score, overall_grade,
           total_findings, critical, high, medium, low, category_scores,
           exposure_score, scan_duration, regions)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (account_id, datetime.now().isoformat(),
         scores["overall_score"], scores["overall_grade"],
         scores["total_findings"],
         scores["severity_counts"]["critical"],
         scores["severity_counts"]["high"],
         scores["severity_counts"]["medium"],
         scores["severity_counts"]["low"],
         json.dumps(scores["category_scores"]),
         exposure.get("score", 0) if exposure else 0,
         scan_duration, regions))
    conn.commit()
    conn.close()


def get_history(account_id: str, limit: int = 20) -> List[Dict]:
    conn = _get_db()
    cursor = conn.execute(
        """SELECT scan_date, overall_score, overall_grade, total_findings,
                  critical, high, medium, low, exposure_score, scan_duration
           FROM scans WHERE account_id = ? ORDER BY scan_date DESC LIMIT ?""",
        (account_id, limit))
    rows = cursor.fetchall()
    conn.close()
    return [
        {"date": r[0][:16], "score": r[1], "grade": r[2], "findings": r[3],
         "critical": r[4], "high": r[5], "medium": r[6], "low": r[7],
         "exposure": r[8], "duration": r[9]}
        for r in rows
    ]


def get_trend_data(account_id: str, limit: int = 30) -> List[Dict]:
    """Get score trend for sparkline/chart."""
    return get_history(account_id, limit)
