"""
client/sphinx_packet.py

Layered, per-hop-salted packet construction (README §3.1, §3.2).

Status: proof-of-concept / illustrative. This is a SIMPLIFIED stand-in
for a real Sphinx packet format (Danezis & Goldberg). It demonstrates
the *shape* of per-hop salting and onion-layered encryption, not a
production cryptographic construction. In particular:

  - Real Sphinx uses a single fixed-size header with re-randomizable
    group elements so packet size never grows with hop count; this
    illustration instead nests layers directly, which leaks hop count
    via packet size. That's a real metadata leak this PoC does not fix.
  - Key derivation here uses BLAKE2b as a stand-in KDF, not a proper
    AEAD construction with authenticated encryption.
  - No replay-protection tag is derived/verified here — see
    node/mixer.py for where that would plug in.

Do not use this for anything beyond understanding the architecture.
"""

from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass


SALT_SIZE = 16
MAC_SIZE = 32


@dataclass(frozen=True)
class HopKey:
    """Symmetric key shared between the client and one mix node."""

    node_id: str
    key: bytes  # derived out-of-band via the node's published public key


def _derive_layer_key(hop_key: bytes, salt: bytes) -> bytes:
    return hashlib.blake2b(hop_key + salt, digest_size=32).digest()


def _xor(data: bytes, keystream: bytes) -> bytes:
    """Expand keystream via repeated hashing and XOR against data.

    NOT a real stream cipher — illustrative only. A real implementation
    uses an AEAD cipher (e.g. ChaCha20-Poly1305) per layer.
    """
    out = bytearray()
    counter = 0
    while len(out) < len(data):
        block = hashlib.blake2b(keystream + counter.to_bytes(4, "big"), digest_size=32).digest()
        out.extend(block)
        counter += 1
    return bytes(a ^ b for a, b in zip(data, out))


def salt_layer(payload: bytes, hop_key: bytes) -> bytes:
    """
    Apply one hop's salted encryption layer.

    Every call generates a fresh random salt, so encrypting the same
    payload under the same hop_key twice produces unrelated ciphertext
    — this is what prevents tagging attacks (README §3.1).
    """
    salt = os.urandom(SALT_SIZE)
    layer_key = _derive_layer_key(hop_key, salt)
    ciphertext = _xor(payload, layer_key)
    mac = hashlib.blake2b(layer_key + ciphertext, digest_size=MAC_SIZE).digest()
    return salt + mac + ciphertext


def peel_layer(packet: bytes, hop_key: bytes) -> bytes:
    """Reverse of salt_layer: verify the MAC and recover the inner payload."""
    salt, mac, ciphertext = (
        packet[:SALT_SIZE],
        packet[SALT_SIZE:SALT_SIZE + MAC_SIZE],
        packet[SALT_SIZE + MAC_SIZE:],
    )
    layer_key = _derive_layer_key(hop_key, salt)
    expected_mac = hashlib.blake2b(layer_key + ciphertext, digest_size=MAC_SIZE).digest()
    if not _constant_time_eq(mac, expected_mac):
        raise ValueError("layer authentication failed — packet tampered or wrong key")
    return _xor(ciphertext, layer_key)


def _constant_time_eq(a: bytes, b: bytes) -> bool:
    if len(a) != len(b):
        return False
    result = 0
    for x, y in zip(a, b):
        result |= x ^ y
    return result == 0


def build_packet(payload: bytes, hop_keys: list[HopKey]) -> bytes:
    """
    Wrap payload in one salted layer per hop, in REVERSE order, so the
    outermost layer is peeled first by hop 0 and the innermost layer
    (the original payload) is only recovered by the last hop.
    """
    packet = payload
    for hop in reversed(hop_keys):
        packet = salt_layer(packet, hop.key)
    return packet


def process_at_hop(packet: bytes, hop_key: bytes) -> bytes:
    """What a single mix node does: peel exactly one layer, forward the rest."""
    return peel_layer(packet, hop_key)
