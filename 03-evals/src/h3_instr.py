"""H3-instr: Phase-A instrumentation — a scoring schema + emission seam that
logs eval scores for every serve call, with NO behavior change (read-only; the wrapped call's
output is returned byte-identical). Langfuse is the production online seam (CONTEXT_EVALS §"Langfuse").

Phase A = INSTRUMENT ONLY: we record scores, we do not gate on them (gating is Stage B / the
calibrated thresholds). The wrapper observes and emits; it never alters the served result.

Sinks (the seam is swappable):
  LangfuseSink — wraps the real `langfuse.Langfuse` client (trace + score). Production path.
  CaptureSink  — in-memory, for offline verification (no server needed).

NOTE (honest): no Langfuse server is running in this environment, so LangfuseSink emits into the
SDK but nothing is received remotely. The schema + read-only guarantee are verified via CaptureSink;
LangfuseSink is exercised to prove the real client binds and accepts the schema.
"""
import sys
import time

# Phase-A scoring schema — the eval dimensions logged per serve call (subset of the CONTEXT_EVALS
# 11-dim matrix that is computable online + cheap). data_type per Langfuse score conventions.
SCORE_SCHEMA = {
    "faithfulness":   {"data_type": "NUMERIC",      "range": [0, 1]},
    "sufficiency":    {"data_type": "NUMERIC",      "range": [0, 1]},
    "retrieval_score":{"data_type": "NUMERIC",      "range": [0, 1]},
    "isolation":      {"data_type": "NUMERIC",      "range": [0, 1]},   # namespace leakage; 0 = clean
    "gate_decision":  {"data_type": "CATEGORICAL",  "values": ["pass", "partial", "abstain", "escalate"]},
    "latency_ms":     {"data_type": "NUMERIC",      "range": [0, None]},
}


def validate_score(name, value):
    spec = SCORE_SCHEMA[name]
    if spec["data_type"] == "CATEGORICAL":
        return value in spec["values"]
    if value is None:
        return False
    lo, hi = spec.get("range", [None, None])
    return (lo is None or value >= lo) and (hi is None or value <= hi)


class CaptureSink:
    """In-memory sink: records emitted (trace, scores) for offline assertions."""
    def __init__(self):
        self.traces = []

    def emit(self, name, inputs, output, scores):
        self.traces.append({"name": name, "input": inputs, "output": output, "scores": dict(scores)})


class LangfuseSink:
    """Production seam: emits a trace + scores via the real Langfuse SDK."""
    def __init__(self):
        from langfuse import Langfuse
        # dummy creds + local host; no server running -> events are accepted by the SDK then dropped at flush
        self.client = Langfuse(public_key="pk-h3-phaseA", secret_key="sk-h3-phaseA",
                               host="http://localhost:3000")

    def emit(self, name, inputs, output, scores):
        tid = self.client.create_trace_id()
        self.client.create_event(trace_context={"trace_id": tid}, name=name,
                                 input=inputs, output=output)
        for k, v in scores.items():
            self.client.create_score(name=k, value=v, trace_id=tid,
                                     data_type=SCORE_SCHEMA[k]["data_type"])


def instrument(serve_fn, scorer, sink, name="serve"):
    """Wrap serve_fn: run it, score the result, emit to sink, return the ORIGINAL output unchanged."""
    def wrapped(*args, **kwargs):
        t0 = time.perf_counter()
        output = serve_fn(*args, **kwargs)              # <- the real work; result untouched
        scores = scorer(output)
        scores["latency_ms"] = round((time.perf_counter() - t0) * 1000, 3)
        for k, v in scores.items():
            assert validate_score(k, v), f"score {k}={v} violates schema"
        sink.emit(name, {"args": args, "kwargs": kwargs}, output, scores)
        return output                                   # <- read-only: identical to un-instrumented
    return wrapped


def demo():
    fail = []

    # a representative serve call: returns a node-card + a gate decision (the served result)
    def serve(query):
        return {"query": query, "card": {"node": "issue:ACME-1", "facts": ["ASSIGNED_TO -> agent:cto"]},
                "gate": "pass"}

    # scorer derives Phase-A scores from the served result (cheap/online signals)
    def scorer(out):
        return {"faithfulness": 0.92, "sufficiency": 0.80, "retrieval_score": 0.74,
                "isolation": 0.0, "gate_decision": out["gate"]}

    # 1) NO BEHAVIOR CHANGE: instrumented output must equal un-instrumented output, byte-for-byte
    cap = CaptureSink()
    plain = serve("who owns ACME-1")
    instr = instrument(serve, scorer, cap)("who owns ACME-1")
    print(f"[no-change] plain == instrumented: {plain == instr}")
    fail += [] if plain == instr else ["instrumentation altered output"]

    # 2) SCORING SCHEMA emitted + valid
    tr = cap.traces[-1]
    print(f"[schema]    emitted scores: { {k: tr['scores'][k] for k in tr['scores']} }")
    schema_ok = all(validate_score(k, v) for k, v in tr["scores"].items() if k in SCORE_SCHEMA)
    has_core = {"faithfulness", "sufficiency", "retrieval_score", "isolation", "gate_decision", "latency_ms"} <= set(tr["scores"])
    fail += [] if schema_ok and has_core else ["scoring schema incomplete/invalid"]
    print(f"[schema]    all scores valid against SCORE_SCHEMA={schema_ok} | core dims present={has_core}")

    # 3) PRODUCTION SEAM: the real Langfuse client binds + accepts the schema (server not running)
    try:
        lf = LangfuseSink()
        instrument(serve, scorer, lf, name="serve.phaseA")("who owns ACME-1")
        lf.client.flush()
        print("[langfuse]  real SDK emitted trace+scores (server not running -> dropped at flush; binding OK)")
        seam = "real-langfuse-sdk"
    except Exception as e:
        print(f"[langfuse]  SDK emission path error: {str(e)[:100]}")
        seam = "sdk-error"
        fail += ["langfuse SDK seam failed to bind"]

    if fail:
        print("H3_INSTR_FAIL:", fail); sys.exit(1)
    print(f"H3_INSTR_OK (seam={seam})")


if __name__ == "__main__":
    demo()
