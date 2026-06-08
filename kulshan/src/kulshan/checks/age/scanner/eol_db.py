"""Embedded EOL/EOS date database for AWS runtimes and engines."""

import json
import os

LAST_UPDATED = "2026-02-27"
_OVERRIDES_PATH = os.path.join(os.path.expanduser("~"), ".Kulshan", "age", "eol_overrides.json")

# Lambda runtime EOL dates (Phase 2 = no updates, Phase 3 = no create)
LAMBDA_EOL = {
    "python3.8": {"eol": "2024-10-14", "status": "eol", "upgrade": "python3.12"},
    "python3.9": {"eol": "2025-11-01", "status": "approaching", "upgrade": "python3.12"},
    "python3.10": {"eol": "2026-07-01", "status": "approaching", "upgrade": "python3.13"},
    "python3.11": {"eol": "2027-03-01", "status": "current", "upgrade": "python3.13"},
    "python3.12": {"eol": "2028-03-01", "status": "current", "upgrade": None},
    "python3.13": {"eol": "2029-03-01", "status": "current", "upgrade": None},
    "nodejs14.x": {"eol": "2023-12-04", "status": "eol", "upgrade": "nodejs20.x"},
    "nodejs16.x": {"eol": "2024-06-12", "status": "eol", "upgrade": "nodejs20.x"},
    "nodejs18.x": {"eol": "2025-09-01", "status": "approaching", "upgrade": "nodejs22.x"},
    "nodejs20.x": {"eol": "2026-10-01", "status": "current", "upgrade": None},
    "nodejs22.x": {"eol": "2027-10-01", "status": "current", "upgrade": None},
    "java8": {"eol": "2024-01-08", "status": "eol", "upgrade": "java21"},
    "java8.al2": {"eol": "2025-02-01", "status": "approaching", "upgrade": "java21"},
    "java11": {"eol": "2025-09-01", "status": "approaching", "upgrade": "java21"},
    "java17": {"eol": "2026-09-01", "status": "current", "upgrade": "java21"},
    "java21": {"eol": "2028-09-01", "status": "current", "upgrade": None},
    "dotnet6": {"eol": "2024-07-12", "status": "eol", "upgrade": "dotnet8"},
    "dotnet8": {"eol": "2026-11-01", "status": "current", "upgrade": None},
    "ruby3.2": {"eol": "2026-03-01", "status": "current", "upgrade": "ruby3.3"},
    "ruby3.3": {"eol": "2027-03-01", "status": "current", "upgrade": None},
    "go1.x": {"eol": "2024-01-08", "status": "eol", "upgrade": "provided.al2023"},
    "provided": {"eol": "2024-01-08", "status": "eol", "upgrade": "provided.al2023"},
    "provided.al2": {"eol": "2025-09-01", "status": "approaching", "upgrade": "provided.al2023"},
    "provided.al2023": {"eol": "2028-03-01", "status": "current", "upgrade": None},
}

# RDS engine end-of-standard-support dates (after this, Extended Support = 3x cost)
RDS_EOL = {
    "mysql": {
        "5.7": {"eos": "2024-02-29", "status": "extended_support", "upgrade": "8.0", "surcharge": True},
        "8.0": {"eos": "2026-04-30", "status": "current", "upgrade": "8.4", "surcharge": False},
    },
    "postgres": {
        "11": {"eos": "2024-02-29", "status": "extended_support", "upgrade": "16", "surcharge": True},
        "12": {"eos": "2025-02-28", "status": "extended_support", "upgrade": "16", "surcharge": True},
        "13": {"eos": "2025-11-13", "status": "approaching", "upgrade": "16", "surcharge": False},
        "14": {"eos": "2026-11-12", "status": "current", "upgrade": "16", "surcharge": False},
        "15": {"eos": "2027-11-11", "status": "current", "upgrade": None, "surcharge": False},
        "16": {"eos": "2028-11-09", "status": "current", "upgrade": None, "surcharge": False},
    },
    "mariadb": {
        "10.4": {"eos": "2024-02-29", "status": "extended_support", "upgrade": "10.11", "surcharge": True},
        "10.5": {"eos": "2025-02-28", "status": "approaching", "upgrade": "10.11", "surcharge": False},
        "10.6": {"eos": "2026-02-28", "status": "current", "upgrade": "10.11", "surcharge": False},
        "10.11": {"eos": "2028-02-28", "status": "current", "upgrade": None, "surcharge": False},
    },
}

# EKS Kubernetes version EOL
EKS_EOL = {
    "1.24": {"eos": "2024-01-31", "status": "eol", "upgrade": "1.30"},
    "1.25": {"eos": "2024-05-01", "status": "eol", "upgrade": "1.30"},
    "1.26": {"eos": "2024-06-11", "status": "eol", "upgrade": "1.30"},
    "1.27": {"eos": "2024-07-24", "status": "eol", "upgrade": "1.31"},
    "1.28": {"eos": "2025-03-01", "status": "approaching", "upgrade": "1.31"},
    "1.29": {"eos": "2025-06-01", "status": "approaching", "upgrade": "1.31"},
    "1.30": {"eos": "2025-11-01", "status": "current", "upgrade": "1.31"},
    "1.31": {"eos": "2026-03-01", "status": "current", "upgrade": None},
}

# ElastiCache Redis version staleness
REDIS_EOL = {
    "5": {"status": "eol", "upgrade": "7"},
    "6": {"status": "approaching", "upgrade": "7"},
    "7": {"status": "current", "upgrade": None},
}


def load_eol_overrides():
    """Load user overrides from ~/.Kulshan/age/eol_overrides.json and merge over defaults."""
    if not os.path.exists(_OVERRIDES_PATH):
        return

    try:
        with open(_OVERRIDES_PATH, "r") as f:
            overrides = json.load(f)

        # Merge lambda overrides
        for runtime, info in overrides.get("lambda", {}).items():
            LAMBDA_EOL[runtime] = info

        # Merge RDS overrides
        for engine, versions in overrides.get("rds", {}).items():
            if engine not in RDS_EOL:
                RDS_EOL[engine] = {}
            for ver, info in versions.items():
                RDS_EOL[engine][ver] = info

        # Merge EKS overrides
        for ver, info in overrides.get("eks", {}).items():
            EKS_EOL[ver] = info

        # Merge Redis overrides
        for ver, info in overrides.get("redis", {}).items():
            REDIS_EOL[ver] = info
    except Exception:
        pass  # Silently ignore malformed overrides


def check_staleness():
    """Check if the embedded EOL database is potentially outdated."""
    from datetime import datetime
    try:
        updated = datetime.strptime(LAST_UPDATED, "%Y-%m-%d")
        age_days = (datetime.now() - updated).days
        if age_days > 180:
            return f"EOL database is {age_days} days old."
    except Exception:
        pass
    return None


# Auto-load overrides on import
load_eol_overrides()
