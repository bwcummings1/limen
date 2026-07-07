"""limen.sensors — sensory channels: the world, arriving as percepts.

A Sensor is anything that produces Percepts on a cadence. Sensors are
polled in the SENSE phase of every tick (cycle.py step 3), each wrapped in
the same guard as specialists: a failing sensor contributes nothing and a
`metrics.note_failure` entry. Channels assign salience *hints* and tags,
but they never decide what matters — the auction does. That is the whole
point: one attention system triaging heterogeneous streams, with
habituation as built-in anti-spam.

Two disciplines every sensor must follow:

  1. DIGEST, don't flood. A busy channel emits one percept summarizing N
     items, not N percepts — the bid phase is metered attention, not a
     message queue. Both built-ins batch.
  2. Sensors are the interface layer, not cognition. They may touch wall
     time and the network (the ordinary tick/wall rule binds *core*
     algorithms); their OUTPUT is tick-stamped percepts like any other.

Built-ins (both pure stdlib, both persist seen-state under
data_dir/sensors/ so a daemon restart doesn't re-perceive the world):

  FileWatcher   polls a directory for new/changed files. On first ever run
                it baselines silently (existing files are "already known").
  RSSWatcher    polls an RSS/Atom feed every N ticks, emits one digest
                percept of new item titles.

Writing your own: subclass Sensor, implement `poll(tick) -> list[Percept]`,
then `mind.add_sensor(YourSensor(...))`. Keep poll fast — it runs on a
thread inside the tick, under the specialist watchdog timeout.
"""
from __future__ import annotations

import json
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

from .bus import Percept
from .util import truncate

_MAX_TEXT_HEAD = 60      # tokens of file content quoted into a percept
_MAX_TITLES = 5          # feed titles per digest percept
_MAX_SEEN = 500          # feed guids remembered


class Sensor:
    """The contract: a name, and poll(tick) -> list[Percept]."""

    name = "sensor"

    def poll(self, tick: int) -> list[Percept]:
        return []


class _SeenState:
    """Tiny JSON persistence for a sensor's seen-state."""

    def __init__(self, directory: Path, name: str) -> None:
        directory.mkdir(parents=True, exist_ok=True)
        self.path = directory / f"{name}.json"

    def load(self) -> dict | None:
        if self.path.exists():
            return json.loads(self.path.read_text(encoding="utf-8"))
        return None

    def save(self, data: dict) -> None:
        self.path.write_text(
            json.dumps(data, ensure_ascii=False), encoding="utf-8"
        )


class FileWatcher(Sensor):
    """Watches one directory (non-recursive) for new and changed files.

    First run with no saved state BASELINES silently: everything already
    present is treated as known, so a fresh mind pointed at a full folder
    doesn't drown in percepts. After that, each poll emits:

      * <= 3 changes: one percept per file, quoting a head of the content;
      * > 3 changes: a single digest percept naming the files.
    """

    def __init__(self, path: str | Path, state_dir: Path,
                 salience: float = 0.55, name: str | None = None) -> None:
        self.dir = Path(path).expanduser()
        self.name = name or f"watch:{self.dir.name}"
        self.salience = salience
        self._state = _SeenState(state_dir, self.name.replace(":", "_"))
        saved = self._state.load()
        if saved is not None:
            self._seen: dict[str, float] | None = saved.get("mtimes", {})
        else:
            self._seen = None  # baseline on first poll

    def _scan(self) -> dict[str, float]:
        out: dict[str, float] = {}
        if not self.dir.is_dir():
            return out
        for p in sorted(self.dir.iterdir()):
            if p.is_file() and not p.name.startswith("."):
                out[p.name] = p.stat().st_mtime
        return out

    def poll(self, tick: int) -> list[Percept]:
        current = self._scan()
        if self._seen is None:                      # first ever run: baseline
            self._seen = current
            self._state.save({"mtimes": current})
            return []
        changed = [
            fname for fname, mtime in current.items()
            if self._seen.get(fname) != mtime
        ]
        self._seen = current
        if not changed:
            return []
        self._state.save({"mtimes": current})

        if len(changed) > 3:                        # digest discipline
            listing = ", ".join(changed[:8])
            return [Percept(
                source=self.name,
                content=f"{len(changed)} files changed in {self.dir.name}/: "
                        f"{listing}",
                salience_hint=self.salience,
                tags=["file", self.dir.name],
            )]
        out = []
        for fname in changed:
            head = ""
            try:
                head = truncate(
                    (self.dir / fname).read_text(encoding="utf-8",
                                                 errors="replace").strip(),
                    _MAX_TEXT_HEAD,
                )
            except OSError:
                pass
            body = f"File changed: {fname}"
            if head:
                body += f" — begins: {head}"
            out.append(Percept(
                source=self.name,
                content=body,
                salience_hint=self.salience,
                tags=["file", Path(fname).stem],
            ))
        return out


class RSSWatcher(Sensor):
    """Polls one RSS 2.0 / Atom feed every `every_ticks` ticks and emits a
    single digest percept of new item titles. Supports file:// URLs, which
    is also how the tests stay offline."""

    def __init__(self, url: str, state_dir: Path, every_ticks: int = 12,
                 salience: float = 0.45, timeout: float = 15.0,
                 name: str | None = None) -> None:
        self.url = url
        self.every_ticks = max(1, every_ticks)
        self.salience = salience
        self.timeout = timeout
        tail = url.rstrip("/").rsplit("/", 1)[-1][:40] or "feed"
        self.name = name or f"rss:{tail}"
        self._state = _SeenState(state_dir, self.name.replace(":", "_").replace("/", "_"))
        saved = self._state.load() or {}
        self._seen: list[str] = saved.get("guids", [])
        self._last_poll_tick = -(10 ** 9)

    # ------------------------------------------------------------- parsing

    @staticmethod
    def _items(root: ET.Element) -> list[tuple[str, str]]:
        """(guid, title) pairs from RSS 2.0 or Atom, namespace-tolerant."""
        found: list[tuple[str, str]] = []

        def local(tag: str) -> str:
            return tag.rsplit("}", 1)[-1]

        for el in root.iter():
            if local(el.tag) not in ("item", "entry"):
                continue
            title, guid, link = "", "", ""
            for child in el:
                name = local(child.tag)
                text = (child.text or "").strip()
                if name == "title":
                    title = text
                elif name in ("guid", "id"):
                    guid = text
                elif name == "link":
                    link = text or child.get("href", "")
            key = guid or link or title
            if key and title:
                found.append((key, title))
        return found

    # ---------------------------------------------------------------- poll

    def poll(self, tick: int) -> list[Percept]:
        if tick - self._last_poll_tick < self.every_ticks:
            return []
        self._last_poll_tick = tick

        with urllib.request.urlopen(self.url, timeout=self.timeout) as resp:
            root = ET.fromstring(resp.read())

        feed_title = ""
        for el in root.iter():
            if el.tag.rsplit("}", 1)[-1] == "title":
                feed_title = (el.text or "").strip()
                break

        items = self._items(root)
        seen = set(self._seen)
        new = [(g, t) for g, t in items if g not in seen]
        if not new:
            return []
        self._seen = (self._seen + [g for g, _ in new])[-_MAX_SEEN:]
        self._state.save({"guids": self._seen})

        titles = "; ".join(t for _, t in new[:_MAX_TITLES])
        more = f" (+{len(new) - _MAX_TITLES} more)" if len(new) > _MAX_TITLES else ""
        label = feed_title or self.name
        return [Percept(
            source=self.name,
            content=f"{label}: {len(new)} new item(s): {titles}{more}",
            salience_hint=self.salience,
            tags=["rss", label[:24]],
        )]


def build_sensors(config, data_dir: Path) -> list[Sensor]:
    """From [sensors] config. Mirrors providers.build_provider."""
    state_dir = data_dir / "sensors"
    out: list[Sensor] = []
    for d in config.sensors.watch_dirs:
        out.append(FileWatcher(
            d, state_dir, salience=config.sensors.watch_salience,
        ))
    for url in config.sensors.rss_feeds:
        out.append(RSSWatcher(
            url, state_dir,
            every_ticks=config.sensors.rss_every_ticks,
            salience=config.sensors.rss_salience,
        ))
    return out
