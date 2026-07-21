"""Safety guard for one-off maintenance scripts that mutate PRODUCTION BigQuery.

Several scripts in this folder (cleanup/reset/seed) issue DELETE/UPDATE/INSERT DML
against the live `sfa_web` dataset the instant they run. Call `confirm_destructive()`
at the top of any such script so an accidental `python <script>.py` (wrong terminal,
double-click, shell history) cannot silently rewrite production data.

Opt-in is explicit and non-interactive-friendly (works in CI/automation):
    PowerShell : $env:STEP_ALLOW_DESTRUCTIVE=1; python cleanup_demo_data.py
    bash       : STEP_ALLOW_DESTRUCTIVE=1 python cleanup_demo_data.py
    any shell  : python cleanup_demo_data.py --yes
"""
from __future__ import annotations

import os
import sys

_TRUTHY = {"1", "true", "yes", "y", "on"}


def confirm_destructive(action: str, target: str) -> None:
    """Refuse to proceed unless the operator has explicitly opted in.

    Prints exactly what will be mutated and where, then either returns (opted in)
    or exits with a non-zero status (not opted in).
    """
    opted_in = (
        os.getenv("STEP_ALLOW_DESTRUCTIVE", "").strip().lower() in _TRUTHY
        or "--yes" in sys.argv
    )

    rule = "=" * 68
    banner = (
        f"\n{rule}\n"
        f"  DESTRUCTIVE OPERATION\n"
        f"  Target : {target}\n"
        f"  Action : {action}\n"
        f"{rule}\n"
    )

    if opted_in:
        print(banner + "  Confirmation received (STEP_ALLOW_DESTRUCTIVE / --yes). Proceeding.\n")
        return

    print(
        banner
        + "  Refusing to run without explicit confirmation.\n"
        "  This mutates PRODUCTION data and cannot be undone.\n\n"
        "  Re-run with one of:\n"
        "    PowerShell : $env:STEP_ALLOW_DESTRUCTIVE=1; python <script>.py\n"
        "    bash       : STEP_ALLOW_DESTRUCTIVE=1 python <script>.py\n"
        "    any shell  : python <script>.py --yes\n"
    )
    sys.exit(1)
