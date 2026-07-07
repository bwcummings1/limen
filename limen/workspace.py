"""limen.workspace — the stage.

The GlobalWorkspace is the only shared mutable cognitive state in LIMEN:
a small, strictly bounded buffer of Broadcasts — the mind's conscious
contents. Bounded three ways, because scarcity is what makes attention
mean anything:

  capacity_tokens   total estimated tokens of resident content
  max_items         count of simultaneous contents (Miller's 7±2, roughly)
  item_ttl          ticks an item survives without being refreshed

Eviction: expired TTLs first, then lowest (priority × freshness) until both
bounds hold. `render()` serializes the stage into the exact text every
specialist receives as its view of consciousness — if it isn't in render(),
no specialist can see it, period. That strictness is the architecture.
"""
from __future__ import annotations

from .bus import Broadcast, Proposal
from .config import WorkspaceConfig


class GlobalWorkspace:
    def __init__(self, config: WorkspaceConfig) -> None:
        self.cfg = config
        self.contents: list[Broadcast] = []
        self.history_count = 0

    # ---------------------------------------------------------------- admit

    def admit(self, winners: list[tuple[Proposal, float]], tick: int) -> list[Broadcast]:
        """Add auction winners, then enforce bounds. Returns new broadcasts."""
        new: list[Broadcast] = []
        for proposal, priority in winners:
            # A re-won topic refreshes in place instead of duplicating —
            # adopting the newer wording, which may carry updated detail.
            existing = self._find_similar(proposal)
            if existing:
                existing.proposal = proposal
                existing.ttl = self.cfg.item_ttl
                existing.priority = max(existing.priority, priority)
                continue
            b = Broadcast(
                proposal=proposal, priority=priority,
                tick=tick, ttl=self.cfg.item_ttl,
            )
            self.contents.append(b)
            new.append(b)
            self.history_count += 1
        self._enforce_bounds()
        return new

    def _find_similar(self, p: Proposal) -> Broadcast | None:
        from .util import similarity
        for b in self.contents:
            if b.author == p.author and similarity(b.content, p.content) > 0.9:
                return b
        return None

    def _enforce_bounds(self) -> None:
        def keep_score(b: Broadcast) -> float:
            freshness = b.ttl / max(self.cfg.item_ttl, 1)
            return b.priority * (0.5 + 0.5 * freshness)

        self.contents.sort(key=keep_score, reverse=True)
        while len(self.contents) > self.cfg.max_items:
            self.contents.pop()
        while self.total_tokens() > self.cfg.capacity_tokens and len(self.contents) > 1:
            self.contents.pop()

    # ----------------------------------------------------------------- decay

    def age(self) -> list[Broadcast]:
        """Tick-end decay: decrement TTLs, evict the expired."""
        expired = [b for b in self.contents if b.ttl <= 1]
        self.contents = [b for b in self.contents if b.ttl > 1]
        for b in self.contents:
            b.ttl -= 1
        return expired

    # ------------------------------------------------------------------ view

    def total_tokens(self) -> int:
        return sum(b.tokens for b in self.contents)

    def render(self) -> str:
        """The conscious contents as text — every specialist's entire view."""
        if not self.contents:
            return "(the workspace is empty — nothing is currently conscious)"
        lines = []
        for b in sorted(self.contents, key=lambda x: -x.priority):
            lines.append(f"• [{b.author}/{b.kind} t={b.tick} p={b.priority:.2f}] {b.content}")
        return "\n".join(lines)

    def kinds_present(self) -> set[str]:
        return {b.kind for b in self.contents}

    def by_kind(self, kind: str) -> list[Broadcast]:
        return [b for b in self.contents if b.kind == kind]

    def __len__(self) -> int:
        return len(self.contents)
