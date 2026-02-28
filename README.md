# Gossipsub Refinement Verification

This repository contains the research artifacts accompanying the PhD thesis
**"Refinement-Based Reasoning of P2P Pubsub Protocols is Feasible and Useful"**
by [Ankit Kumar](https://ankitku.github.io/), Northeastern University.

The thesis develops a formal refinement hierarchy for peer-to-peer publish-subscribe
protocols, from abstract specifications down to realistic implementations, verified
using the [ACL2s](http://acl2s.ccs.neu.edu/acl2s/doc/) theorem prover. The
protocols studied — Floodsub, Gossipsub, and MeshSub — underpin blockchain
infrastructure used by Ethereum, IPFS, and Filecoin.

---

## Repository Structure

### [`gossipsub-formal/`](./gossipsub-formal)

Formal model of the GossipSub protocol in ACL2s, developed for the paper:

> **Formal Model-Driven Analysis of Resilience of GossipSub to Attacks from
> Misbehaving Peers**  
> Ankit Kumar, Max von Hippel, Pete Manolios, Cristina Nita-Rotaru  
> IEEE S&P 2024 · [arXiv](https://arxiv.org/abs/2212.05197)

This is the **first formal model of GossipSub**, officially endorsed by the
GossipSub developers. The model can simulate GossipSub networks of arbitrary
size and topology, and is used to:

- Prove and disprove security properties of the GossipSub score function.
- Show that the score function is always *fair*, but can be misconfigured to
  penalize good behavior or ignore bad behavior.
- Synthesize concrete attacks (AG1, eclipse, partition) against the Ethereum
  2.0 configuration, where misbehaving peers can permanently avoid pruning
  while never forwarding messages.
- Verify that all properties hold for the Filecoin configuration.

The models and proofs are also available in the
[ACL2 books](https://github.com/acl2/acl2/tree/master/books/workshops/2023/kumar-etal).

**Requirements:** [ACL2s](http://acl2s.ccs.neu.edu/acl2s/doc/) or Docker
(see subdirectory README for instructions).

---

### [`floodsub-refinement-mechanized-proof/`](./floodsub-refinement-mechanized-proof)

Mechanized refinement proof of the Floodsub protocol in ACL2s, developed for the paper:

> **A Formalization of the Correctness of the Floodsub Protocol**  
> Ankit Kumar, Pete Manolios  
> ACL2 Workshop 2025 · 🏆 Best Student Paper Award

This artifact proves that Floodsub (*fnet*) is a correct refinement of the
abstract Broadcastsub specification (*bnet*), establishing that safety and
liveness properties of the abstract model transfer to the concrete protocol.
Key contributions include:

- A formal LTS (labelled transition system) model of both Broadcastsub and
  Floodsub in ACL2s.
- A refinement map from *fnet* to *bnet*, with machine-checked proofs
  of all simulation obligations.
- Proof of Stuttering simulation refinement. 

**Requirements:** ACL2s.

---

### [`meshsub-parameter-optimization/`](./meshsub-parameter-optimization)

Simulation study and parameter sweep for the MeshSub protocol (the mesh
construction layer of GossipSub), providing empirical grounding for the
refinement hierarchy.

This artifact evaluates **495 parameter configurations** of MeshSub across five
levels of network churn, measuring message delivery reliability and propagation
latency. Key findings include:

- No single fixed parameter configuration achieves uniform reliability across
  all churn regimes.
- Delivery rate and latency exhibit a trade-off that depends on the ratio of
  mesh degree *D* to churn intensity.
- The simulation results are validated against Protocol Labs measurements of
  the Ethereum P2P network.
- Results inform the probabilistic argument for `TConnectedp` in the Floodsub
  refinement proof.

**Requirements:** Python 3, standard scientific stack (`numpy`, `matplotlib`,
`pandas`). See subdirectory README for instructions.

---

## Refinement Hierarchy

The overall structure of the thesis argument is a refinement chain:

```
Broadcastsub (bnet)   ←— abstract specification
       ↑                                              
   Floodsub (queue based), Fnet (set based)    ←— refinement proved in ACL2s for the set based version of Floodsub
       ↑
    MeshSub           ←— formal model + paper-pencil proof + parameter study (this repo)

   Gossipsub          ←— Property-based testing, Counter-example generation based disproof of refinement
```

Each level is related to the one above it by a formally verified or formally
analyzed refinement map. Correctness properties established at the top
propagate downward, contingent on the temporal connectedness condition.

---

## Publications


- **ACL2 Workshop 2025** *(Best Student Paper)* — A Formalization of the
  Correctness of the Floodsub Protocol
- **IEEE S&P 2024** — Formal Model-Driven Analysis of Resilience of GossipSub
  to Attacks from Misbehaving Peers
- **ACL2 Workshop 2023** *(Best Student Paper)* — Verification of Gossipsub
  in ACL2s
- **Meshsub parameter study paper** - Paper under review (anonymized)
---

## Citation

If you use these artifacts, please cite the relevant paper(s) listed above, or
the thesis:

```bibtex
@phdthesis{kumar2026,
  author = {Ankit Kumar},
  title  = {Refinement-Based Reasoning of P2P Pubsub Protocols is Feasible and Useful},
  school = {Northeastern University},
  year   = {2026}
}
```

---

## Contact

[Ankit Kumar](https://ankitku.github.io/) · Northeastern University  
For questions about the formal proofs, open an issue or reach out directly.
