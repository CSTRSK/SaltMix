"""
node/reputation.py

Reputation scoring and stake slashing (README §3.6, docs/threat_model.md §2.4).

Node operators lock an economic stake to participate in path selection.
Misbehavior detected here (missed forwards, invalid MACs, excessive
latency) reduces reputation and, past a threshold, triggers slashing.

Status: proof-of-concept / illustrative. Scoring here is a simple
exponential moving average over self-reported/locally-observed events.
A real deployment needs this fed by cross-node attestations reaching
consensus (see directory/bft_consensus.py) — a single observer's
opinion of another node's misbehavior is not by itself trustworthy
evidence; see docs/threat_model.md §5 (assumptions).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum, auto


class EventType(Enum):
    SUCCESSFUL_FORWARD = auto()
    MISSED_FORWARD = auto()
    INVALID_MAC = auto()          # possible tampering or misconfiguration
    EXCESSIVE_LATENCY = auto()
    REPLAY_DETECTED = auto()      # forwarded a packet outside its window


# How much each event moves the reputation score, and in which direction.
_EVENT_WEIGHT: dict[EventType, float] = {
    EventType.SUCCESSFUL_FORWARD: +0.01,
    EventType.MISSED_FORWARD: -0.05,
    EventType.INVALID_MAC: -0.20,
    EventType.EXCESSIVE_LATENCY: -0.02,
    EventType.REPLAY_DETECTED: -0.30,
}

SLASH_THRESHOLD = 0.30       # reputation below this triggers slashing
DECAY_FACTOR = 0.98          # per-update pull toward neutral, so old
                              # misbehavior doesn't haunt a node forever


@dataclass
class ReputationRecord:
    node_id: str
    score: float = 1.0
    stake_locked: float = 0.0
    slashed: bool = False
    event_count: int = 0


class SlashingEvent(Exception):
    """Raised when a node's score drops below the slashing threshold."""

    def __init__(self, node_id: str, score: float):
        self.node_id = node_id
        self.score = score
        super().__init__(f"node {node_id} slashed at reputation {score:.3f}")


@dataclass
class ReputationTracker:
    records: dict[str, ReputationRecord] = field(default_factory=dict)

    def register_node(self, node_id: str, stake: float) -> None:
        self.records[node_id] = ReputationRecord(node_id=node_id, stake_locked=stake)

    def record_event(self, node_id: str, event: EventType) -> ReputationRecord:
        record = self.records.setdefault(node_id, ReputationRecord(node_id=node_id))
        if record.slashed:
            return record  # already excluded from path selection

        # Decay toward 1.0 slightly before applying the new event, so
        # sustained good behavior gradually recovers reputation.
        record.score = record.score * DECAY_FACTOR + (1 - DECAY_FACTOR) * 1.0
        record.score = max(0.0, min(1.0, record.score + _EVENT_WEIGHT[event]))
        record.event_count += 1

        if record.score < SLASH_THRESHOLD:
            record.slashed = True
            raise SlashingEvent(node_id, record.score)

        return record

    def eligible_nodes(self, min_reputation: float = 0.5) -> list[str]:
        """Node IDs suitable for inclusion in client path selection."""
        return [
            r.node_id
            for r in self.records.values()
            if not r.slashed and r.score >= min_reputation
        ]
