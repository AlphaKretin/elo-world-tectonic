# Pokemon Tectonic ELO World

Ranks every trainer in [Pokemon Tectonic](https://github.com/Pokemon-Tectonic-Team/Pokemon-Tectonic-Content) by running a full round-robin tournament of real, headless AI-vs-AI battles, then fitting Bradley-Terry ratings over the results — the same methodology as [elo_world_pokemon_crystal](https://github.com/jsettlem/elo_world_pokemon_crystal), built on top of Tectonic's [AI Benchmark](https://github.com/Pokemon-Tectonic-Team/Pokemon-Essentials-Chasm-Engine/tree/3.5-ai-rework) headless battle engine instead of emulator automation.

## Website

**[alphakretin.github.io/elo-world-tectonic](https://alphakretin.github.io/elo-world-tectonic/)** — browse the full round-robin results across all four formats (singles/doubles × cursed/uncursed, plus a "cursed-excluded" variant of each):

- **Leaderboard** — sortable, searchable rankings for any format, with tier and curse-roll filters. Click a trainer to open their full card (party, moves, held items, record, best win/worst loss), downloadable as a PNG.
- **Compare** — pick any two formats and see every trainer's rank and rating side-by-side, with the delta between them (rescaled so a trainer missing from one format doesn't inflate the others' rank deltas).
- **Stats** — scatter-plot any two metrics against each other (rating, rank, win rate, team level) across any format, with an optional least-squares trendline.

## Results

A preliminary published snapshot of the full round-robin ratings also lives in [`official_results/`](official_results/) as static Markdown — leaderboards, notable-match writeups, and top-16 bracket showcases, for the same four formats. This is a manually-curated snapshot, not auto-generated; `analysis/` produces the same reports plus supplementary output (comparison CSVs, raw JSON) but isn't committed since it's fully reproducible from `results/`.

---

The rest of this README covers the tournament infrastructure itself — running the headless battle engine, distributing it across a cloud fleet, and generating the ratings/reports/website data from the results.

## Layout

- `vendor/tectonic-content/` — submodule, pinned to a personal fork (`AlphaKretin/Pokemon-Tectonic-Mods` @ `elo-tournament`, not the team repo — this branch carries tournament-only hacks that don't belong upstream) of `Pokemon-Tectonic-Content`. The runnable mkxp-z game project. Also ships a native Linux build (`Game Linux.x86_64`, same mkxp-z engine) used by the cloud fleet tooling below.
- `vendor/tectonic-content/Plugins/ELO Tournament/` — the headless harness:
  - `headless_boot.rb` — boot hook (`ENV["ELO_TOURNAMENT"]`-gated): jumps straight into the tournament instead of the title screen, plus headless-environment compatibility patches.
  - `trainer_pool.rb` — builds the real trainer roster from `GameData::Trainer`, with any active quarantines for known-bad matchups.
  - `tournament.rb` — pairing, orchestration, resumable JSONL result logging, and `EloTournament.testSinglePairing!` (a one-pairing diagnostic harness — see below).
  - `replay.rb` — `EloTournament.saveReplay!` (`ELO_SAVE_REPLAY`): re-runs one exact stored `(trainer1, trainer2, format, seed)` with recording enabled, producing a `.dat` watchable in-game via the VS Recorder.
  - `bracket.rb` — `EloTournament.runBracket!` (`ELO_RUN_BRACKET`): seeded top-16 single-elimination bracket — see "Top 16 bracket" below.
- `scripts/` — PowerShell tooling for running the tournament outside the editor (Windows; see "Running a tournament"):
  - `setup_shards.ps1` — syncs N independent copies of the game directory under `shards/` (one per parallel process) via `robocopy /MIR`. `-Recompile` does a `debug` launch first to pick up Plugin code changes.
  - `run_parallel.ps1` — launches N `run_tournament.ps1` watchdogs, one per shard. Archives `errorlog.txt` first (every launch, fresh start or resume alike).
  - `run_tournament.ps1` — the actual watchdog: launches `Game.exe`, restarts it on a stalled turn or a stalled whole battle, until the shard reports `finished:true`.
  - `run_bracket.ps1` — the equivalent watchdog for the top-16 bracket (single, unsharded process — see "Top 16 bracket" below).
  - `pause_tournament.ps1` — stops every watchdog and `Game.exe`, in the right order (watchdogs first) so none auto-relaunch out from under you.
  - `archive_run.ps1` — moves `errorlog.txt` (always) and result/log files (`-IncludeResults`, for an intentional fresh start) into a timestamped `results/archive_.../` folder instead of deleting them.
  - `watch_tournament.ps1` / `watch_tournament_parallel.ps1` — read-only live status viewers.
  - Distributed (cloud droplet fleet) tooling — see "Running a tournament on a cloud fleet" below:
    - `remote_provision_shard.sh` — runs *on* a droplet: installs deps (Xvfb, Mesa, fluxbox), clones the game (from the personal fork noted above, not the team repo), debug-compiles, validates with a test battle. Idempotent.
    - `remote_run_tournament.sh` — runs *on* a droplet: Bash port of `run_tournament.ps1`'s watchdog, launching the headless Linux build (`Game Linux.x86_64` under Xvfb + fluxbox + software GL, since mkxp-z needs a real, if virtual, window). Takes `--formats singles,doubles` (comma-separated): works through the whole sequence on its own, recompiling between formats, with no dependency on any other shard or the control machine.
    - `setup_remote_shards.ps1` / `run_remote_parallel.ps1` / `watch_remote_tournament.ps1` / `pause_remote_tournament.ps1` / `pull_remote_results.ps1` — control-side (this machine): provision, launch, monitor, stop, and collect results from every droplet in `remote_hosts.txt`, in parallel over SSH.
    - `remote_hosts.txt` — one droplet IP per line (gitignored — live infra detail, not code; copy from `remote_hosts.txt.example`). Shard index/count are derived from this file's contents, not passed as separate parameters.
- `results/` — JSONL battle results, status/watchdog logs (gitignored; generated by running the tournament). `archive_*/` subfolders hold previous runs. `results/remote/` holds results pulled from the cloud fleet, kept separate from local shard data since both use the identical `elo_results_<format>_shard<N>.jsonl` naming convention and would otherwise silently overwrite each other.
- `official_results/` — committed, non-gitignored snapshot of the canonical published results (leaderboards, notable matches, bracket reports) across all four formats. Copied over by hand from `analysis/` output when publishing a new snapshot, not auto-regenerated.
- `analysis/` — Python rating computation and reporting over `results/`:
  - `ratings.py` — Bradley-Terry trainer ratings (one-hot ±1 logistic regression via scikit-learn), per format. Safe to run against a still-in-progress tournament.
  - `report.py` — turns `ratings.py`'s output into a Markdown leaderboard.
  - `bracket_report.py` — bracket-tree reporting, see "Top 16 bracket" below.
- `.venv/` — Python virtualenv for `analysis/` (gitignored; see "Analysis" below to recreate it).
- `web/` — the React/Vite site published at the URL above. Reads static JSON (`web/public/data/`) produced by `analysis/export_web_data.py`; see "Website" below. Deployed automatically to GitHub Pages by `.github/workflows/deploy-web.yml` on every push to `main` that touches `web/`.

## Running a tournament

One-time setup:
```powershell
git submodule update --init
.\scripts\setup_shards.ps1 -ShardCount 8 -Recompile
```

Start (or resume) the run:
```powershell
.\scripts\run_parallel.ps1 -ShardCount 8
```
Resuming is identity-based, not position-based: it's safe to stop and restart at any time, and already-completed pairings (by trainer identity + format) are skipped. After editing any Plugin code, re-run `setup_shards.ps1 -Recompile` before resuming so the change actually takes effect across all shards.

Check progress:
```powershell
.\scripts\watch_tournament_parallel.ps1
```

Stop everything cleanly:
```powershell
.\scripts\pause_tournament.ps1
```

Starting genuinely fresh (e.g. after a fix that invalidates prior results)? Archive the old data first, then redo the one-time setup + start:
```powershell
.\scripts\archive_run.ps1 -Label "some-description" -IncludeResults
```

### Diagnosing a specific bad battle

`EloTournament.testSinglePairing!` (gated by `ELO_TEST_SINGLE_PAIRING`) runs exactly one pairing, by explicit trainer identity and seed, outside the main pool/loop — much faster than reproducing an issue through the full tournament. Set the env vars and launch `Game.exe` directly from `vendor/tectonic-content` (non-debug, unless you've also edited Plugin code and need `debug` first):

```powershell
$env:ELO_TOURNAMENT = "1"
$env:ELO_TEST_SINGLE_PAIRING = "1"
$env:ELO_TEST_T1_TYPE = "YOUNGSTER"; $env:ELO_TEST_T1_NAME = "Joey"
$env:ELO_TEST_T2_TYPE = "HARLEQUIN"; $env:ELO_TEST_T2_NAME = "Vincenzi"
$env:ELO_TEST_SEED = "2786941428"
.\vendor\tectonic-content\Game.exe
```
Result lands in `vendor/tectonic-content/Analysis/single_pairing_test.txt`. Add `ELO_TEST_T1_VERSION`/`ELO_TEST_T2_VERSION` for non-zero trainer versions, or `ELO_TEST_PREBATTLE_ONLY=1` to dump each side's resolved party species without running a battle at all.

## Running a tournament on a cloud fleet

A local 8-shard run takes on the order of a week for a full singles round robin. Distributing across cheap cloud droplets (validated against DigitalOcean Basic, 1 vCPU/1GB, ~$6/mo each) cuts that dramatically: measured throughput is roughly 4x faster *per core* than this project's local Windows baseline, and droplet-hour pricing is flat regardless of fleet size, so more droplets buys speed without much added cost.

One-time setup, per droplet (root SSH key auth must already work, no password prompt):
```powershell
copy .\scripts\remote_hosts.txt.example .\scripts\remote_hosts.txt
# edit remote_hosts.txt: one droplet IP per line
.\scripts\setup_remote_shards.ps1
```
This clones the fork, installs the headless-Linux dependencies (Xvfb, Mesa software GL, fluxbox — `SDL_VIDEODRIVER=dummy` alone doesn't work, mkxp-z needs a real if virtual window with a window manager), debug-compiles, and validates each droplet with a test battle, in parallel.

Start the run:
```powershell
.\scripts\run_remote_parallel.ps1 -Formats "singles,doubles"
```
Each droplet works through the whole format sequence independently — finishes singles, recompiles, starts doubles — with no coordination between shards and no dependency on this machine staying on after launch.

Check progress:
```powershell
.\scripts\watch_remote_tournament.ps1
```

Pull results down (safe to run repeatedly mid-run):
```powershell
.\scripts\pull_remote_results.ps1
```
Lands in `results/remote/`, not `results/` — see the Layout note above for why.

Stop everything:
```powershell
.\scripts\pause_remote_tournament.ps1
```

Resuming and selective re-runs work the same identity-based way as the local case: `tournament.rb` skips any pairing already present in the results JSONL (by trainer identity + format), so fixing bad data later is just deleting those specific lines from the relevant shard's file and relaunching.

## Top 16 bracket

An exhibition top-16 single-elimination bracket can be run over a hand-curated list of 16 entrants, seeded NCAA-style (1v16, 8v9, ...) so the favorites stay apart for as long as possible. Every match is a fresh battle with a replay saved (`.dat`, same VS Recorder mechanism as `replay.rb`), even if that exact pairing already has a row in the sparse round-robin results — the bracket is a showcase, not more rating data.

Seeding is manual curation, not a straight top-16-by-rating pull: some formats' true top-16 is uninteresting (one trainer overwhelmingly favored, or duplicate trainers taking multiple slots), so `results/bracket_seeds_<format>.txt` is hand-written — plain tab-separated `seed<TAB>trainer label` (blank lines and `#`-comments skipped; use `analysis/ratings_<format>.json` to see who's actually rated highest and pick from there).

```powershell
.\scripts\run_bracket.ps1 -Format singles -UseDebugFlag   # -UseDebugFlag only needed the first time, to pick up bracket.rb
.\.venv\Scripts\python.exe analysis\bracket_report.py
```
`run_bracket.ps1` is a single unsharded watchdog (15 matches total, no need to shard) that resumes mid-bracket on a crash/restart the same way the round robin does — completed matches are keyed by `(round, match)` in `results/bracket_<format>_results.tsv`, not by position. `bracket_report.py` turns that into `analysis/bracket_report_<format>.md`. Replays land under `vendor/tectonic-content/VSRecorder/EloBracket/`.

A draw (or any non-decisive outcome) gets up to 5 reroll attempts with a different seed before falling back to the better seed advancing automatically; `decided_by` in the results file records which happened for each match.

## Analysis

```powershell
python -m venv .venv
.\.venv\Scripts\pip install scikit-learn numpy scipy
.\.venv\Scripts\python.exe analysis\ratings.py
.\.venv\Scripts\python.exe analysis\report.py
```
Outputs `analysis/ratings_<format>.{json,csv}` and `analysis/report_<format>.md` (all gitignored, regenerable).

## Developing the website

The site (`web/`) reads static JSON, not a live backend, so any new tournament results have to be re-exported before the site reflects them:

```powershell
.\.venv\Scripts\python.exe analysis\export_web_data.py
```
This regenerates everything under `web/public/data/` (leaderboards, trainer cards, team levels) from `analysis/`'s ratings/best-worst/trainer-card output — run `ratings.py` and `best_worst.py` first if those are stale. Skips any format whose `ratings_<fmt>.json` isn't present rather than failing the whole export.

Then, from `web/`:
```powershell
npm install
npm run dev      # local dev server
npm run build    # production build (tsc -b && vite build), what CI runs
```
Pushing to `main` with changes under `web/` triggers `.github/workflows/deploy-web.yml`, which builds and publishes to GitHub Pages automatically — no manual deploy step.

## Status

A full singles+doubles round robin has completed on the cloud fleet, with zero `had_error` battles remaining, and the top-16 bracket has been run for all four formats against that data — see [Website](#website) and [Results](#results) above. Every trainer's card (party, moves, held items, record, best win/worst loss) is viewable live on the site, rendered as HTML rather than committing ~555-per-format static PNGs to git.
