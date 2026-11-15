"""Connection check CLI:  python -m app.connectors.check

Prints status only (never credentials). Exit code 0 = connected, 1 = failed/not configured.
The authenticated HTTP equivalent (per workspace) is POST /workspaces/{id}/credentials/{cid}/test.
"""
import sys
from typing import Optional

from app.config import Settings, get_settings
from app.connectors.aceden.factory import build_aceden_connector


def run_check(settings: Optional[Settings] = None, **connector_kw) -> dict:
    settings = settings or get_settings()
    connector = build_aceden_connector(settings, **connector_kw)
    if connector is None:
        return {"connector": "aceden", "configured": False, "ok": False, "message": "not_configured"}
    try:
        status = connector.validate_connection()
    finally:
        connector.close()
    return {"connector": "aceden", "configured": True, "ok": status.ok, "message": status.message}


def main(argv=None, **connector_kw) -> int:
    result = run_check(**connector_kw)
    print(f"{result['connector']}: configured={result['configured']} ok={result['ok']} ({result['message']})")
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
