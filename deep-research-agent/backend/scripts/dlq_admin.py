"""Dead-letter queue admin tool (Phase A).

Inspect, replay, or purge messages that could not be processed and were moved
to a queue's dead-letter list (``<queue>:dlq``).

Usage (from ``backend/`` with the app environment configured):

    uv run python -m scripts.dlq_admin list     [--queue research:queue] [--limit 50]
    uv run python -m scripts.dlq_admin requeue  [--queue research:queue]
    uv run python -m scripts.dlq_admin purge    [--queue research:queue] [--yes]

``requeue`` moves every dead-lettered message back onto its origin queue for
reprocessing (the worker re-dead-letters anything still unparseable). ``purge``
deletes them permanently — it asks for confirmation unless ``--yes`` is given.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys

from app.config.settings import get_settings
from app.infrastructure.queue.client import (
    dead_letter_queue_name,
    get_queue_client,
)


def _default_queue() -> str:
    return get_settings().research_queue_name


async def _list(queue_name: str, limit: int) -> int:
    client = get_queue_client()
    entries = await client.list_dead_letters(queue_name, limit=limit)
    dlq = dead_letter_queue_name(queue_name)
    depth = await client.depth(dlq)
    print(f"DLQ {dlq}: {depth} message(s)\n")
    for entry in entries:
        payload = entry.get("payload", "")
        # Show the parsed task for readability when it is JSON.
        try:
            payload = json.dumps(json.loads(payload), indent=2)
        except (ValueError, TypeError):
            pass
        print(f"[{entry.get('failed_at', '?')}] reason={entry.get('reason', '?')}")
        print(payload)
        print("-" * 60)
    await client.close()
    return 0


async def _requeue(queue_name: str) -> int:
    client = get_queue_client()
    moved = await client.requeue_dead_letter(queue_name)
    print(f"Requeued {moved} message(s) from {dead_letter_queue_name(queue_name)}.")
    await client.close()
    return 0


async def _purge(queue_name: str, *, assume_yes: bool) -> int:
    dlq = dead_letter_queue_name(queue_name)
    if not assume_yes:
        answer = input(f"Permanently delete all messages in {dlq}? [y/N] ")
        if answer.strip().lower() not in {"y", "yes"}:
            print("Aborted.")
            return 1
    client = get_queue_client()
    removed = await client.purge_dead_letter(queue_name)
    print(f"Purged {dlq} ({removed} key(s) removed).")
    await client.close()
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "command", choices=["list", "requeue", "purge"], help="Operation"
    )
    parser.add_argument("--queue", default=None, help="Origin queue name")
    parser.add_argument("--limit", type=int, default=50, help="List size cap")
    parser.add_argument("--yes", action="store_true", help="Skip purge confirmation")
    args = parser.parse_args(argv)

    queue_name = args.queue or _default_queue()
    if args.command == "list":
        return asyncio.run(_list(queue_name, args.limit))
    if args.command == "requeue":
        return asyncio.run(_requeue(queue_name))
    return asyncio.run(_purge(queue_name, assume_yes=args.yes))


if __name__ == "__main__":
    sys.exit(main())
