# run log — explore
<!-- Append one JSON entry per run. No silent runs.
     {"run_id":"<UTC ISO8601>","pattern":"explore","outcome":"report-only|no-op",
      "approx_tokens":0,"reason":"<only for no-op>",
      "sample_read":"<one line: which finding was sampled, what changed, why. Empty = not done;
                      an empty sample_read blocks promotion review. See LOOP.md 'Sample read'.>"}
     The block above is the FORMAT TEMPLATE, not a run. Anything with a <placeholder> must never
     be counted as run history. -->
