"""Container healthcheck probe.

Used by the Docker Compose API healthcheck so the container only reports healthy
once the readiness endpoint answers. Runs in the backend's venv with stdlib only
(no extra network client needed).

Usage::

    uv run python -m app.healthcheck --url http://localhost:8000/api/ready

Exits 0 when the URL returns HTTP 200, otherwise 1.
"""

from __future__ import annotations

import argparse
import sys
import urllib.request


def _probe(url: str) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=5) as response:
            return response.status == 200
    except Exception:  # noqa: BLE001 - any failure means unhealthy
        return False


def main() -> int:
    parser = argparse.ArgumentParser(description="Probe a URL and exit 0 on HTTP 200.")
    parser.add_argument("--url", required=True)
    args = parser.parse_args()
    return 0 if _probe(args.url) else 1


if __name__ == "__main__":
    sys.exit(main())