"""
client/path_selection.py

Diversity-constrained path selection for SaltMix.

Status: proof-of-concept / illustrative. Not audited, not constant-time,
not hardened against adversarial node-list poisoning beyond the basic
diversity constraint shown here. See docs/threat_model.md §2.4 (Sybil
operator) and §4 (non-goals) before using any part of this in a real
deployment.
"""

from __future__ import annotations

import random
from dataclasses import dataclass


@dataclass(frozen=True)
class Node:
    """A single mix node as published by the directory authority."""

    node_id: str
    address: str
    public_key: bytes
    asn: int
    country: str
    reputation: float = 1.0  # 0.0 (untrusted) .. 1.0 (fully trusted)


class InsufficientDiverseNodesError(Exception):
    """Raised when the candidate pool cannot satisfy diversity constraints."""


def select_path(
    nodes: list[Node],
    hop_count: int = 3,
    min_reputation: float = 0.5,
    rng: random.Random | None = None,
) -> list[Node]:
    """
    Select `hop_count` nodes such that no two hops share an AS or a
    country, and every selected node meets a minimum reputation
    threshold.

    This is a greedy algorithm, not an optimal one: it shuffles the
    candidate pool and takes the first nodes that satisfy the
    constraints. A production implementation would want weighted
    sampling (e.g. by stake and uptime) rather than uniform shuffling,
    and should treat reputation source integrity itself as untrusted
    input — see docs/threat_model.md.
    """
    rng = rng or random.Random()

    candidates = [n for n in nodes if n.reputation >= min_reputation]
    rng.shuffle(candidates)

    path: list[Node] = []
    used_as: set[int] = set()
    used_country: set[str] = set()

    for node in candidates:
        if len(path) >= hop_count:
            break
        if node.asn in used_as or node.country in used_country:
            continue
        path.append(node)
        used_as.add(node.asn)
        used_country.add(node.country)

    if len(path) < hop_count:
        raise InsufficientDiverseNodesError(
            f"requested {hop_count} diverse hops, found {len(path)} "
            f"from a pool of {len(candidates)} eligible nodes"
        )

    return path


def select_surb_path(
    nodes: list[Node],
    hop_count: int = 3,
    exclude_node_ids: set[str] | None = None,
    rng: random.Random | None = None,
) -> list[Node]:
    """
    Select a return path for a SURB (see client/surb.py), optionally
    excluding nodes already used on the forward path to reduce the
    chance that a single node observes both directions of a
    conversation.
    """
    exclude_node_ids = exclude_node_ids or set()
    pool = [n for n in nodes if n.node_id not in exclude_node_ids]
    return select_path(pool, hop_count=hop_count, rng=rng)
