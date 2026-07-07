"""limen.memory.procedural — skills the mind writes for itself.

Procedural memory = "how to do things," stored as human-readable markdown
files under data_dir/skills/. During sleep, lessons tagged PROCEDURE are
promoted into skill files; the librarian surfaces relevant skills back into
consciousness when their trigger keywords match the current workspace.

This is the self-growing-harness idea in miniature: the mind's competence
is partly *files it wrote*, inspectable and editable by its human.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from ..util import keywords, similarity

_SLUG = re.compile(r"[^a-z0-9]+")


class SkillStore:
    def __init__(self, directory: Path) -> None:
        self.dir = directory / "skills"
        self.dir.mkdir(parents=True, exist_ok=True)
        self.index_path = self.dir / "_index.json"
        self.index: dict[str, dict] = {}
        if self.index_path.exists():
            self.index = json.loads(self.index_path.read_text(encoding="utf-8"))

    def _slug(self, title: str) -> str:
        return _SLUG.sub("-", title.lower()).strip("-")[:60] or "skill"

    def write(self, title: str, body: str, tick: int, source: str) -> Path:
        slug = self._slug(title)
        path = self.dir / f"{slug}.md"
        header = f"# {title}\n\n*Written by {source} at tick {tick}.*\n\n"
        path.write_text(header + body.strip() + "\n", encoding="utf-8")
        self.index[slug] = {
            "title": title,
            "triggers": keywords(title + " " + body, 10),
            "tick": tick,
        }
        self.index_path.write_text(
            json.dumps(self.index, indent=1, ensure_ascii=False), encoding="utf-8"
        )
        return path

    def relevant(self, context: str, n: int = 2, floor: float = 0.28) -> list[dict]:
        scored = []
        for slug, meta in self.index.items():
            s = similarity(context, meta["title"] + " " + " ".join(meta["triggers"]))
            if s >= floor:
                scored.append((s, slug, meta))
        scored.sort(reverse=True, key=lambda t: t[0])
        out = []
        for s, slug, meta in scored[:n]:
            body = (self.dir / f"{slug}.md").read_text(encoding="utf-8")
            out.append({"slug": slug, "title": meta["title"], "body": body, "score": s})
        return out

    def __len__(self) -> int:
        return len(self.index)
