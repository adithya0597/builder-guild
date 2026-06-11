# Coordination Patterns — for a fleet on governed context

Five patterns, ordered by complexity. Start at the simplest that fits; escalate only on observed
failure. Every pattern assumes agents read through `serve(query, role)` — coordination never
bypasses the context layer.

## 1. Generator–Verifier
Produce-then-check loop. Verifier criteria are defined BEFORE the loop; the verifier never shares
the generator's context ("intended approach" leaks rubber-stamp it). Max ~3 iterations, then
escalate to a human. Used here: code → adversarial review (this repo's isolation bugs were caught
by an independent cross-family reviewer, three times).

## 2. Orchestrator–Subagent
One planner decomposes; bounded subtasks execute in isolated contexts; the orchestrator sees
summaries only. Decompose by CONTEXT NEEDED, not by function. If subtask B needs subtask A's
output, make them sequential — don't simulate it with shared scratch state.

## 3. Agent Teams
Persistent workers with specializations claim tasks from a queue (atomically — no two workers on
one task). Requires task independence; if tasks share state, you wanted pattern 5. Lead checks for
conflicts after each completion.

## 4. Message Bus
Event-driven: publishers emit, subscribers react, a router delivers. Events must be self-contained;
log everything (multi-agent debugging without logs is archaeology); guard against circular chains.
Choose only when decoupling matters more than traceability.

## 5. Shared State
Agents collaborate through a shared store with partitioned writes (each agent owns a namespace —
which is exactly what the context layer's role slices provide). Define convergence upfront
("no new findings for N cycles") and a hard budget; without both, agents burn tokens forever.

## Fleet-specific rules

- **Role slices are the partition.** Two agents in different namespaces cannot conflict on facts
  by construction; cross-namespace coordination goes through `shared` or a human.
- **Suggest-only agents coordinate freely; acting agents serialize.** While autonomy is leased
  (per namespace), at most one acting agent per namespace per action category — the action-audit
  loop (`fix_decision.py`) needs attributable outcomes.
- **The overseer is not a coordinator.** Oversight reads everything to detect drift/conflict; it
  must not become the message bus, or its read-all power becomes a write-all power in practice.
