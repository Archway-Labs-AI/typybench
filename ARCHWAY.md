# Archway TypyBench Fork

This fork keeps Archway's operational patches to TypyBench separate from
Archway-specific benchmark adapters.

Policy:

- Do not change TypyBench scoring semantics without an explicit compatibility
  note.
- Keep Archway prediction emitters, adapters, and internal storage in
  `archway-benchmarks` / `archway-bench-internal`.
- Use this fork for runner observability, reproducibility, resume behavior, and
  workflow stability.
- Pin Archway benchmark runs to a TypyBench fork commit when using fork-specific
  runner behavior.

Current Archway additions:

- `run.py --progress-jsonl PATH` writes machine-readable run/repo events.
- `run.py --log-dir PATH` stores per-repo stdout, stderr, and metadata.
- `run.py --skip-completed` skips scored repos whose
  `*_results_w_exact.csv` already exists.
