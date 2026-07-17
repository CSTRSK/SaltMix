"""
node/mixer.py

Mix node core: peel one encryption layer, apply a Poisson-distributed
forwarding delay, and hand the packet to the next hop (README §3.3).

Status: proof-of-concept / illustrative. Single-process, in-memory
simulation — no real networking, no persistence, no protection against
a node operator who simply reads memory. See docs/threat_model.md §2.2
for what a single malicious node is and is not assumed capable of.
"""

from __future__ import annotations

import asyncio
import random
import time
from dataclasses import dataclass, field

from client.sphinx_packet import peel_layer


@dataclass
class ReplayGuard:
    """
    Rejects packets whose (salt, mac) pair has been seen before, within
    a bounded window. A real implementation needs a space-efficient
    probabilistic structure (Bloom filter) with periodic rotation, not
    an unbounded Python set — see README §1 (replay protection).
    """

    window_size: int = 100_000
    _seen: set[bytes] = field(default_factory=set)
    _order: list[bytes] = field(default_factory=list)

    def check_and_record(self, packet_tag: bytes) -> bool:
        """Return True if this is a fresh packet, False if it's a replay."""
        if packet_tag in self._seen:
            return False
        self._seen.add(packet_tag)
        self._order.append(packet_tag)
        if len(self._order) > self.window_size:
            oldest = self._order.pop(0)
            self._seen.discard(oldest)
        return True


def mixing_delay(mean_delay_seconds: float = 2.0, rng: random.Random | None = None) -> float:
    """
    Draw a forwarding delay from an exponential distribution
    (continuous-time / Poisson mixing, README §3.3), rather than
    batching packets into fixed windows.
    """
    rng = rng or random
    return rng.expovariate(1 / mean_delay_seconds)


@dataclass
class MixNode:
    node_id: str
    hop_key: bytes
    mean_delay_seconds: float = 2.0
    replay_guard: ReplayGuard = field(default_factory=ReplayGuard)

    async def process(self, packet: bytes, forward_fn) -> None:
        """
        Peel this node's encryption layer, check for replay, wait a
        Poisson-distributed delay, then invoke `forward_fn` with the
        inner packet.

        `forward_fn` is a callable — in a real deployment this would
        be a network send to the next hop's address (or, at the last
        hop, delivery to the destination). Kept abstract here so this
        module has no networking dependency.
        """
        tag = packet[: 48]  # salt + mac, see sphinx_packet.SALT_SIZE/MAC_SIZE
        if not self.replay_guard.check_and_record(tag):
            return  # silently drop — do not signal replay detection externally

        inner = peel_layer(packet, self.hop_key)

        delay = mixing_delay(self.mean_delay_seconds)
        await asyncio.sleep(delay)

        forward_fn(inner)
