"""
directory/bft_consensus.py

BFT-based directory authority (README §5).

Instead of a single trusted directory server, the published node list
is agreed upon by a small cluster of independent authorities, tolerant
of up to f faulty/malicious authorities out of 3f+1 total — the
standard BFT quorum requirement.

Status: proof-of-concept / illustrative. This implements a simplified
one-round voting scheme, NOT a full PBFT/Tendermint-style protocol
(no view changes, no leader election, no Byzantine-safe message
authentication beyond what's shown). It exists to document the
*shape* of the trust assumption — see docs/threat_model.md §2.6 and §5
for what this does and does not guarantee.
"""

from __future__ import annotations

import hashlib
from collections import Counter
from dataclasses import dataclass, field


@dataclass(frozen=True)
class NodeListProposal:
    """A candidate version of the published mix-node directory."""

    version: int
    node_entries: tuple[str, ...]  # serialized node records, sorted/canonical

    def digest(self) -> bytes:
        payload = f"{self.version}:{','.join(self.node_entries)}".encode()
        return hashlib.sha256(payload).digest()


class ConsensusFailure(Exception):
    """Raised when no proposal reaches the required quorum."""


@dataclass
class BFTDirectoryCluster:
    """
    A cluster of `total_authorities` directory authorities, tolerant of
    up to `max_faulty` acting maliciously or being offline, where
    total_authorities >= 3 * max_faulty + 1 (standard BFT bound).
    """

    total_authorities: int
    max_faulty: int

    def __post_init__(self) -> None:
        required_min = 3 * self.max_faulty + 1
        if self.total_authorities < required_min:
            raise ValueError(
                f"{self.total_authorities} authorities cannot tolerate "
                f"{self.max_faulty} faulty ones; need >= {required_min}"
            )

    @property
    def quorum_size(self) -> int:
        # 2f + 1 votes required to commit, out of 3f + 1 total.
        return 2 * self.max_faulty + 1

    def resolve(self, votes: list[NodeListProposal]) -> NodeListProposal:
        """
        Given one proposal per responding authority (a missing/faulty
        authority simply doesn't appear in `votes`), determine whether
        any single proposal digest reached quorum.
        """
        if len(votes) < self.quorum_size:
            raise ConsensusFailure(
                f"only {len(votes)} authorities responded, "
                f"need {self.quorum_size} for quorum"
            )

        tally: Counter[bytes] = Counter(v.digest() for v in votes)
        winning_digest, count = tally.most_common(1)[0]

        if count < self.quorum_size:
            raise ConsensusFailure(
                f"no proposal reached quorum: best had {count} votes, "
                f"need {self.quorum_size}"
            )

        for v in votes:
            if v.digest() == winning_digest:
                return v

        raise ConsensusFailure("unreachable: winning digest matched no vote")


def verify_client_view(
    proposal: NodeListProposal, authority_signatures: dict[str, bytes], cluster: BFTDirectoryCluster
) -> bool:
    """
    A client fetching the node list should verify it against at least
    `cluster.quorum_size` independent authority signatures before
    trusting it for path selection — never trust a single authority's
    unsigned response. Signature verification itself is out of scope
    here (depends on the chosen signature scheme); this function only
    checks that enough distinct authorities are represented.
    """
    return len(authority_signatures) >= cluster.quorum_size
