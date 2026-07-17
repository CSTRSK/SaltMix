"""
node/cover_traffic.py

Cover traffic / decoy loop generation (README §3.4).

Idle nodes periodically emit dummy packets that are indistinguishable
from real traffic to an external observer. Decoy packets traverse a
random subset of the network and are discarded at a designated hop,
so overall traffic volume does not correlate with real message volume.

Status: proof-of-concept / illustrative. Volume-only simulation — does
not implement the actual padding/sizing needed to make decoys visually
indistinguishable from real packets on the wire (README §3.5 handles
that separately and both need to be applied together in practice).
"""

from __future__ import annotations

import asyncio
import os
import random
from dataclasses import dataclass

from client.path_selection import Node, select_path
from client.sphinx_packet import HopKey, build_packet


DECOY_MARKER = b"\x00" * 8  # discarded at the terminal hop, never delivered


@dataclass
class CoverTrafficGenerator:
    """
    Emits decoy packets at a rate independent of real traffic, so an
    observer watching a single node's egress cannot distinguish "this
    node is relaying real messages" from "this node is idle and padding".
    """

    node_pool: list[Node]
    own_node_id: str
    mean_interval_seconds: float = 5.0
    hop_count: int = 3
    packet_size_bytes: int = 1024  # must match README §3.5 constant size
    rng: random.Random = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        self.rng = self.rng or random.Random()

    async def run(self, send_fn, stop_event: asyncio.Event) -> None:
        """
        Continuously emit decoy loop packets until `stop_event` is set.
        `send_fn(first_hop_address, packet_bytes)` hands off to the
        network layer — kept abstract to avoid a networking dependency
        in this module.
        """
        while not stop_event.is_set():
            interval = self.rng.expovariate(1 / self.mean_interval_seconds)
            try:
                await asyncio.wait_for(stop_event.wait(), timeout=interval)
                break  # stop_event was set during the wait
            except asyncio.TimeoutError:
                pass  # normal case: interval elapsed, emit a decoy

            packet, first_hop = self._build_decoy()
            send_fn(first_hop.address, packet)

    def _build_decoy(self) -> tuple[bytes, Node]:
        candidates = [n for n in self.node_pool if n.node_id != self.own_node_id]
        path = select_path(candidates, hop_count=self.hop_count, rng=self.rng)

        payload = DECOY_MARKER + os.urandom(self.packet_size_bytes - len(DECOY_MARKER))
        hop_keys = [HopKey(node_id=n.node_id, key=_session_key_for(n)) for n in path]
        packet = build_packet(payload, hop_keys)
        return packet, path[0]


def is_decoy(payload: bytes) -> bool:
    """
    Called at the terminal hop to decide whether to deliver a payload
    upward to an application, or silently discard it as a decoy.
    """
    return payload[: len(DECOY_MARKER)] == DECOY_MARKER


def _session_key_for(node: Node) -> bytes:
    # Placeholder for real key agreement (e.g. X25519 with node.public_key).
    # Illustrative only — see client/sphinx_packet.py module docstring.
    import hashlib
    return hashlib.blake2b(node.public_key, digest_size=32).digest()
