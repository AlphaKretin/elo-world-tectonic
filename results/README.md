# results/ layout

Four subfolders, each with one job. `results/` root itself holds no loose
files — only these four, plus this README.

- **`local/`** — local shard-run scratch space: everything
  `run_tournament.ps1`/`run_parallel.ps1` (and the bracket/custom-trainer
  diversions) write while running — JSONL results, status/watchdog/game
  logs, chunk-queue state, hand-written bracket seed files, etc.
- **`remote/`** — pull-landing zone only, exactly what
  `pull_remote_results.ps1`/`setup_remote_shards.ps1` scp down from the
  droplet fleet, plus the remote chunk-supervisor's own queue state/log.
  Not read directly by any analysis script.
- **`current/`** — the actual ground truth. Every analysis script reads
  from here by default (`results_lib.RESULTS_DIR`). Promoting data from
  `remote/` or `local/` into here after a pull/run is a manual `cp` —
  intentionally not automated, so there's no separate "did you remember to
  promote?" step to forget (see `project_uncursed_data_staleness.md` for
  what happened when a similar merge step *was* implicit and got missed).
  Example, after a pull:
  ```
  cp results/remote/elo_results_singles_shard*.jsonl results/current/
  ```
- **`archive/`** — single consolidated root for every historical backup
  (`archive_run.ps1`, `apply_subset_rerun.py`, `setup_remote_shards.ps1`'s
  pre-provision archive), each in its own `<timestamp>_<label>/` folder.
  Always moved, never deleted — old data stays available for later
  diagnosis even once it's no longer valid for ratings.

`elo_results_<fmt>_uncursed_shard*.jsonl` is a special case wherever it
appears (`local/`, `remote/`, or `current/`): it's always the raw
curse-stripped *partial* re-battle subset, never a full round robin on its
own. `results_lib.load_results()` merges it with the base format's
`curse:false` population in memory on every load — there is no separate
merged file to promote or go stale.
