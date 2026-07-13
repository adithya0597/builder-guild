# Licensing

Builder Guild is released under the **GNU Affero General Public License v3.0**
(AGPL-3.0) — see [LICENSE](LICENSE).

## What AGPL-3.0 means for you

- **Use, modify, and self-host freely.** AGPL grants all the usual open-source
  freedoms.
- **Network-use copyleft (§13).** If you run a *modified* Builder Guild as a
  network service (i.e. users interact with it over a network), you must offer
  those users the **complete corresponding source** of your modified version
  under AGPL-3.0.
- This is intentional. It keeps improvements open and stops a closed, hosted
  fork from competing against the project without contributing back.

## Commercial license

If AGPL-3.0's network-copyleft does not fit your use — for example you want to:

- embed Builder Guild in a **proprietary / closed-source** product, or
- offer a **hosted service** built on Builder Guild **without** releasing your
  modifications under AGPL,

then a **commercial license** is available that removes the AGPL obligations.

**Contact:** adithya.m0511@gmail.com — subject line `Builder Guild commercial license`.

## Scope note (read this)

A commercial Builder Guild license covers **only the code in this repository**.
It does **not** relicense third-party dependencies. In particular, the *optional*
Leiden backend (`requirements-leiden.txt`) pulls **GPL** packages
(`leidenalg`, `python-igraph`). The **default** community-detection backend is
networkx (BSD-3) and carries no such obligation — run the default to keep your
deployment free of third-party copyleft.

Likewise, the Neo4j **database** (run as a separate process via Docker) is GPLv3
and is **not** covered by — or redistributable under — a commercial Builder Guild
license; you obtain Neo4j under its own terms. The Python `neo4j` driver that
Builder Guild links is Apache-2.0 and is unaffected.

## The name vs. the code

Both grants above — AGPL-3.0 and commercial — cover the **code**, not the
"Builder Guild" **name**. Anyone may run, modify, fork, or host the code under
its license. If you offer a hosted service or a fork built on it, we ask that you
present it under your own name — "[Your Name] for Builder Guild," or similar —
rather than as bare "Builder Guild," so nobody mistakes it for the official
project. No trademark registration is claimed or promised here; this is a
naming-clarity note, not a legal filing.

---

*This document explains the project's licensing intent; it is **not** legal
advice. Have counsel review the commercial-license terms and the contributor
agreement before you sell licenses or merge outside contributions.*
