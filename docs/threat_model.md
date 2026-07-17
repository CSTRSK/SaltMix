# SaltMix Threat Model

> Companion document to the [SaltMix README](../README.md). This expands on §4 of the README with adversary definitions, per-layer analysis, and explicit non-goals.

---

## 1. Purpose & Scope

This document defines the adversaries SaltMix is designed to resist, the assumptions each mitigation relies on, and — just as importantly — what is explicitly **out of scope** for this proof of concept. A threat model that doesn't state its limits is not a threat model, it's marketing.

SaltMix protects **metadata unlinkability**: the inability of an adversary to determine who is communicating with whom, when, and how much. It does **not** by itself guarantee message confidentiality beyond standard transport encryption, nor does it protect the endpoints themselves.

---

## 2. Adversary Model

We define adversaries by capability, from weakest to strongest.

### 2.1 Passive Network Observer
Can observe traffic on links they have access to (e.g. an ISP, an IXP, a Wi-Fi network) but cannot modify, drop, or inject packets, and does not control any mix node.

**Capabilities:** packet timing, packet size, volume, source/destination IP pairs on observed links.
**Mitigations:** constant packet size + padding (§3.5 in README), cover traffic (§3.4), encrypted transport between hops.

### 2.2 Malicious Node Operator (Single Node)
Controls one mix node, honestly participates in the protocol but logs and analyzes everything it sees.

**Capabilities:** sees the previous hop, the next hop, and can attempt to correlate packet content/timing it processes.
**Mitigations:** per-hop salted Sphinx packets (§3.1), layered encryption (§3.2) — a single node never sees the full path or plaintext.

### 2.3 Malicious Entry + Exit Node (Collusion)
Controls both the first and last hop of a specific path, either by owning both nodes or colluding with another operator.

**Capabilities:** can attempt to correlate the packet it injected with the packet it receives at exit, via timing or tagging.
**Mitigations:** per-hop salting prevents tagging; Poisson mixing (§3.3) and cover traffic reduce timing correlation. Diversity-constrained path selection (§3.7) reduces the *probability* that a single adversary controls both ends of a path.
**Residual risk:** if the adversary controls a large fraction of nodes, the probability of controlling both entry and exit on some paths rises. This is a probabilistic mitigation, not a guarantee — see §4.

### 2.4 Sybil Operator
Runs many nodes under different identities to increase the probability of appearing multiple times on a single path.

**Capabilities:** same as 2.3, but at higher probability by sheer node count.
**Mitigations:** economic staking raises the cost per identity (§3.6); reputation scoring can detect and exclude anomalous nodes over time; diversity constraints (AS/country/operator) limit how many Sybil nodes from one cluster can appear on the same path.
**Residual risk:** an adversary with sufficient capital can still out-stake honest operators. Staking raises cost, it does not make Sybil attacks impossible.

### 2.5 Global Passive Adversary (Partial)
Can observe traffic on a large fraction of network links simultaneously (e.g. a large-scale internet backbone observer), but does not control mix nodes and cannot inject/drop packets.

**Capabilities:** large-scale timing correlation across many links at once.
**Mitigations:** Poisson mixing and cover traffic raise the cost of correlation, but do not eliminate it — see §4 for why a *full* global passive adversary is out of scope.

### 2.6 Directory Compromise
Attempts to manipulate the published node list (e.g. to bias path selection toward adversary-controlled nodes, or to censor honest nodes).

**Capabilities:** if it controls the directory, it controls what clients believe the network looks like.
**Mitigations:** BFT consensus across multiple independent directory operators (README §5) means no single compromised operator can unilaterally alter the list.
**Residual risk:** if the adversary compromises more than the BFT fault threshold (typically ⅓ of consensus participants), directory integrity is lost.

---

## 3. Mitigation-to-Adversary Mapping

| # | Mitigation | Primary adversary addressed | Layer |
|---|---|---|---|
| 1 | Per-hop salted Sphinx packets | Single malicious node, tagging | Cryptographic |
| 2 | Layered (onion) encryption | Single malicious node | Cryptographic |
| 3 | Poisson mixing | Entry/exit collusion, partial global passive | Traffic analysis |
| 4 | Cover traffic / decoy loops | Passive observer, partial global passive | Traffic analysis |
| 5 | Constant packet size + padding | Passive observer | Traffic analysis |
| 6 | Staking | Sybil operator | Network/economic |
| 7 | Diversity-constrained path selection | Entry/exit collusion, Sybil | Network |
| 8 | Reputation scoring | Sybil, misbehaving nodes | Network |
| 9 | BFT directory authority | Directory compromise | Governance |
| 10 | SURBs | Sender de-anonymization via reply traffic | Metadata |

Each mitigation targets specific adversary capabilities from §2 — none of them, individually or combined, is a complete defense against every adversary in every scenario. See §4.

---

## 4. Explicit Non-Goals / Out of Scope

Stating what a system does **not** protect against is as important as stating what it does. For this proof of concept:

- **Full global active adversary.** An adversary who can observe *and* actively manipulate (delay, drop, inject, replay) traffic across a majority of the network is not defended against. Real-world mixnets generally treat this as a research-grade open problem, not a solved one.
- **Endpoint compromise.** SaltMix protects the network path. It does nothing if the client or destination device itself is compromised (malware, keyloggers, coerced disclosure).
- **Long-term intersection attacks.** An adversary who observes a user's traffic patterns over weeks/months and correlates them against a fixed set of likely destinations may still succeed, even with perfect per-message unlinkability. This requires application-level mitigations (e.g. varying communication patterns) beyond what a mixnet alone provides.
- **Application-layer fingerprinting.** If the payload or client behavior (e.g. distinctive request sizes, timing patterns specific to an app) leaks information, no amount of network-layer mixing fixes that.
- **Legal/coercive compromise of node operators.** Staking and reputation raise the cost of running malicious nodes, but do not prevent a legitimate operator from being legally compelled to log traffic. Jurisdictional diversity (README §... governance ideas) is a partial mitigation, not a solution.
- **Denial of service.** This document does not address availability guarantees; a resourced adversary could still degrade network performance through flooding or targeted node takedown.

---

## 5. Assumptions

The mitigations above rely on the following assumptions holding:

1. A sufficient number of independently-operated, geographically/AS-diverse nodes exist and remain online.
2. The BFT directory consensus threshold (honest majority) is not exceeded by a colluding minority.
3. Cryptographic primitives (Sphinx construction, underlying ciphers) remain unbroken over the relevant time horizon.
4. Clients correctly implement path diversity constraints and do not opt out of cover traffic for performance reasons (a common real-world failure mode in deployed mixnets).

If any of these assumptions fail, the corresponding guarantees degrade — this should be treated as a live risk register, not a one-time checklist.

---

## 6. Status

This threat model describes a **design-stage proof of concept** (see main [README](../README.md), §7). It has not been through external cryptographic review or formal verification. Treat every mitigation above as "intended to raise attacker cost," not as a proven guarantee, until independently audited.

Feedback, attack proposals, and critiques are welcome via issues/PRs.
