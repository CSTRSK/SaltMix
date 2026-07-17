"""
client/surb.py

Single-Use Reply Blocks (README §3.8).

A SURB lets a responder send a reply through the mix network without
ever learning the original sender's identity or address. The sender
precomputes a full layered-encryption path (using sphinx_packet.py)
addressed back to themselves, and hands the *reply block* — not their
address — to the responder.

Status: proof-of-concept / illustrative. Real SURB designs also need
to prevent replay of the same reply block beyond a single use (hence
"single-use") — the reuse guard below is an in-memory stand-in, not a
distributed replay-protection mechanism suitable for a real mix node.
"""

from __future__ import annotations

import os
import secrets
from dataclasses import dataclass, field

from client.path_selection import Node
from client.sphinx_packet import HopKey, build_packet


@dataclass(frozen=True)
class SURB:
    """A precomputed reply path plus the encryption keys needed to use it."""

    surb_id: bytes
    reply_path: list[str]          # node_ids, in forward-traversal order
    hop_keys: list[HopKey]         # same keys the client used when the
                                    # payload eventually completes the path
    first_hop_address: str


def create_surb(reply_path: list[Node], session_key_material: bytes) -> SURB:
    """
    Precompute a reply block addressed back to the SURB's creator.

    `session_key_material` should be fresh per SURB (e.g. drawn from a
    CSPRNG) so that reply-block keys are never reused across SURBs —
    reuse would let a responder or an observing node link two replies
    to the same underlying session.
    """
    hop_keys = [
        HopKey(node_id=node.node_id, key=_derive_hop_key(session_key_material, node.node_id))
        for node in reply_path
    ]
    return SURB(
        surb_id=secrets.token_bytes(16),
        reply_path=[n.node_id for n in reply_path],
        hop_keys=hop_keys,
        first_hop_address=reply_path[0].address,
    )


def _derive_hop_key(session_key_material: bytes, node_id: str) -> bytes:
    import hashlib
    return hashlib.blake2b(session_key_material + node_id.encode(), digest_size=32).digest()


class SURBAlreadyUsedError(Exception):
    pass


@dataclass
class SURBRegistry:
    """
    In-memory, single-process tracker of which SURB IDs have already
    been consumed. A real deployment needs this enforced at the mix
    nodes themselves (distributed, not client-local) — see
    docs/threat_model.md §5 (assumptions) for why client-side-only
    enforcement is not trustworthy against a malicious responder.
    """

    used_ids: set[bytes] = field(default_factory=set)

    def use(self, surb: SURB) -> bytes:
        if surb.surb_id in self.used_ids:
            raise SURBAlreadyUsedError(f"SURB {surb.surb_id.hex()} already consumed")
        self.used_ids.add(surb.surb_id)
        return build_packet(os.urandom(0), surb.hop_keys)
