"""Rotate the seeded UAT account passwords off the known public default.

Several UAT accounts ship with a shared, publicly-known password
(`STEP@2026` / `Step@2026!`). This rotates each to a strong random secret (or an
operator-supplied one) and writes the new plaintext to a **gitignored** file so it
can be moved into Secret Manager. Nothing is printed to stdout.

Run from backend/ (destructive — guarded):
    STEP_ALLOW_DESTRUCTIVE=1 python -m scripts.ops.rotate_test_passwords

Pin a specific password per account with STEP_PW_<username>, e.g.
    STEP_PW_admin=... STEP_PW_demo=...
otherwise a 20-char random password is generated for each.

AFTER rotating: move backend/rotated-credentials.local.txt into Secret Manager,
delete it, and point the test suite at the new secrets via STEP_TEST_PASSWORD /
STEP_ADMIN_PASSWORD (see backend/tests/conftest.py).
"""
from __future__ import annotations

import os
import secrets
import string
from datetime import datetime, timezone

from ops_guard import confirm_destructive
from config import settings
from services.auth import hash_password
from services.bq import BQClient

# Seeded UAT accounts to rotate. Keep in sync with docs/current/06-operations-runbook.
ACCOUNTS = ["admin", "demo", "test_se", "test_spv", "test_dist", "se1"]

OUT_FILE = "rotated-credentials.local.txt"  # gitignored — see .gitignore


def _generate() -> str:
    alphabet = string.ascii_letters + string.digits + "!@#$%^&*"
    return "".join(secrets.choice(alphabet) for _ in range(20))


def main() -> None:
    project = settings.bq_project
    dataset = settings.bq_dataset
    confirm_destructive(
        f"UPDATE users.password_hash for {len(ACCOUNTS)} seeded UAT accounts",
        f"{project}.{dataset}",
    )

    bq = BQClient.get()
    stamp = datetime.now(timezone.utc).isoformat()
    lines = [
        f"# STEP rotated UAT credentials — {stamp}",
        "# Move into Secret Manager, then DELETE this file. Never commit it.",
        "# username\tpassword",
    ]

    for username in ACCOUNTS:
        new_pw = os.environ.get(f"STEP_PW_{username}") or _generate()
        bq.execute(
            f"UPDATE `{project}.{dataset}.users` "
            "SET password_hash=@h, updated_at=CURRENT_TIMESTAMP() WHERE username=@u",
            [bq.p("h", "STRING", hash_password(new_pw)), bq.p("u", "STRING", username)],
        )
        lines.append(f"{username}\t{new_pw}")

    with open(OUT_FILE, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")

    print(f"Rotated {len(ACCOUNTS)} accounts.")
    print(f"New passwords written to backend/{OUT_FILE} (gitignored).")
    print("Next: move into Secret Manager, delete the file, set STEP_TEST_PASSWORD/STEP_ADMIN_PASSWORD for tests.")


if __name__ == "__main__":
    main()
