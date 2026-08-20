"""
One-shot trigger for the external distributor transaction sync.

Calls services.ext_transactions.run_sync() directly — no HTTP, no JWT. This is
the entrypoint for the scheduled Cloud Run Job (see docs/current/17 and the
2026-08-19 sync-scheduling note), which deliberately bypasses the
POST /ext-transaction/sync HTTP route: that route requires a full ho_admin user
JWT (require_role("ho_admin")), and there is no service/machine-credential path
in the app's auth model. Rather than mint or store a long-lived privileged token
for automation, the scheduled job calls the same underlying function in-process,
authenticating to BigQuery via the job's own IAM identity (sfa-web-api@...,
already granted bigquery.dataViewer + jobUser + sfa_web WRITER — no new grant).

    python -m scripts.ops.run_ext_sync

Exit code 0 on SUCCESS/PARTIAL, 1 on FAILED (so Cloud Scheduler / Cloud Run Job
retry policy reacts to a genuine failure).
"""
import sys

sys.path.insert(0, ".")

from services.ext_transactions import run_sync  # noqa: E402


def main() -> int:
    result = run_sync(triggered_by="cloud-scheduler")
    d = result.as_dict()
    for k, v in d.items():
        print(f"{k}: {v}")
    return 1 if result.status == "FAILED" else 0


if __name__ == "__main__":
    raise SystemExit(main())
