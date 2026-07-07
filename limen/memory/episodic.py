"""limen.memory.episodic — the autobiographical record.

An append-only JSONL file (`episodic.jsonl`) holding one event per line:
every broadcast, tool call, sleep report, contradiction, alarm. This is the
mind's ground truth about its own past — the consolidation pass replays it,
the librarian searches it, and `limen inspect episodic` renders it.

Append-only is a feature: LIMEN never rewrites its history, it reinterprets
it (in the belief ledger). A recent-events ring buffer is kept in memory so
per-tick queries never touch disk.
"""
from __future__ import annotations

import json
from collections import deque
from pathlib import Path
from typing import Any, Iterator

from ..bus import to_jsonl
from ..util import similarity


class EpisodicMemory:
    KINDS = (
        "broadcast", "idle", "tool", "utterance", "sleep_report",
        "contradiction", "alarm", "stimulus", "belief_write", "ensemble",
    )

    def __init__(self, directory: Path, hot_window: int = 400) -> None:
        directory.mkdir(parents=True, exist_ok=True)
        self.path = directory / "episodic.jsonl"
        self._hot: deque[dict[str, Any]] = deque(maxlen=hot_window)
        self._count = 0
        if self.path.exists():  # warm the ring buffer on restart
            for event in self._read_all():
                self._hot.append(event)
                self._count += 1

    # ---------------------------------------------------------------- write

    def log(self, kind: str, tick: int, payload: dict[str, Any]) -> dict[str, Any]:
        assert kind in self.KINDS, f"unknown episodic kind: {kind}"
        event = {"n": self._count, "kind": kind, "tick": tick, **payload}
        with open(self.path, "a", encoding="utf-8") as f:
            f.write(to_jsonl(event) + "\n")
        self._hot.append(event)
        self._count += 1
        return event

    # ----------------------------------------------------------------- read

    def _read_all(self) -> Iterator[dict[str, Any]]:
        with open(self.path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    yield json.loads(line)

    def recent(self, n: int = 20, kind: str | None = None) -> list[dict[str, Any]]:
        events = [e for e in self._hot if kind is None or e["kind"] == kind]
        return events[-n:]

    def since_tick(self, tick: int, limit: int = 500) -> list[dict[str, Any]]:
        """Events with tick >= `tick`. Falls back to disk if beyond hot window."""
        if not self.path.exists():
            return []
        if self._hot and self._hot[0]["tick"] <= tick:
            return [e for e in self._hot if e["tick"] >= tick][:limit]
        return [e for e in self._read_all() if e["tick"] >= tick][:limit]

    def search(self, query: str, n: int = 5, floor: float = 0.25) -> list[dict[str, Any]]:
        """Similarity search over hot-window event text (librarian's tool)."""
        scored = []
        for e in self._hot:
            text = e.get("content") or e.get("text") or ""
            if not text:
                continue
            s = similarity(query, text)
            if s >= floor:
                scored.append((s, e))
        scored.sort(key=lambda p: p[0], reverse=True)
        return [e for _, e in scored[:n]]

    def __len__(self) -> int:
        return self._count
