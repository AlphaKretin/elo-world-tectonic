# Pokemon Tectonic ELO World

Ranks every trainer in [Pokemon Tectonic](https://github.com/Pokemon-Tectonic-Team/Pokemon-Tectonic-Content) by running a full round-robin tournament of real, headless AI-vs-AI battles, then fitting Bradley-Terry ratings over the results — the same methodology as [elo_world_pokemon_crystal](https://github.com/jsettlem/elo_world_pokemon_crystal), built on top of Tectonic's [AI Benchmark](https://github.com/Pokemon-Tectonic-Team/Pokemon-Essentials-Chasm-Engine/tree/3.5-ai-rework) headless battle engine instead of emulator automation.

## Website

**[alphakretin.github.io/elo-world-tectonic](https://alphakretin.github.io/elo-world-tectonic/)** — browse the full round-robin results. Every leaderboard/compare/stats view is addressed by three orthogonal axes: **battle type** (singles/doubles), **curse variant** (cursed/uncursed — see "Curse-stripped battles" below), and **filter** (none / cursed-excluded / level70-only), e.g. `/singles/uncursed/level70_only`.

- **Leaderboard** — sortable, searchable rankings for the current battle type/curse variant/filter, with a tier badge. Click a trainer to open their full card (party, moves, held items, record, best win/worst loss with the opponent's own rank shown alongside), downloadable as a PNG.
- **Compare** — pick any two of the above combinations and see every trainer's rank side-by-side, with the rank delta between them (rescaled so a trainer missing from one format doesn't inflate the others' rank deltas). Deliberately rank-only, not rating-delta: each format's Bradley-Terry fit has no shared anchor, so a raw rating difference across two independent fits isn't a meaningful quantity.
- **Stats** — scatter-plot any two metrics against each other (rating, rank, win rate, team level) for the current battle type/curse variant/filter, with an optional least-squares trendline.

## Replay viewer

**[Latest release](https://github.com/AlphaKretin/elo-world-tectonic/releases/latest)** — a companion desktop app (`viewer/`) for browsing and watching individual battles, complementing the website's overall ratings with a look at specific matches: search the full results set for a pairing, generate that exact battle as a watchable replay, and step through it turn-by-turn — all headless, no need for the in-game VS Recorder. See "Developing the replay viewer" below for how to run or build it.

---

The rest of this README covers the tournament infrastructure itself — running the headless battle engine, distributing it across a cloud fleet, and generating ratings/reports/website data from the results.

## Layout

- `vendor/tectonic-content/` — submodule, pinned to a personal fork (`AlphaKretin/Pokemon-Tectonic-Mods` @ `elo-tournament`, not the team repo — this branch carries tournament-only hacks that don't belong upstream) of `Pokemon-Tectonic-Content`. The runnable mkxp-z game project. Also ships a native Linux build (`Game Linux.x86_64`, same mkxp-z engine) used by the cloud fleet tooling below.
- `vendor/tectonic-content/Plugins/ELO Tournament/` — the headless harness:
  - `headless_boot.rb` — boot hook (`ENV["ELO_TOURNAMENT"]`-gated): jumps straight into the tournament instead of the title screen, plus headless-environment compatibility patches.
  - `trainer_pool.rb` — builds the real trainer roster from `GameData::Trainer`, with any active quarantines for known-bad matchups.
  - `tournament.rb` — pairing, orchestration, resumable JSONL result logging, `EloTournament.testSinglePairing!` (a one-pairing diagnostic harness — see below), and the curse-stripping/uncursed-rebattle plumbing consumed by `analysis/build_uncursed_results.py`.
  - `custom_trainer_battles.rb` — `ELO_CUSTOM_TRAINER_BATTLES`-gated: battles one custom, not-in-the-pool trainer against the existing rated pool without touching the real round-robin — see "Testing a custom trainer against the pool" below.
  - `replay.rb` — `EloTournament.saveReplay!` (`ELO_SAVE_REPLAY`): re-runs one exact stored `(trainer1, trainer2, format, seed)` with recording enabled, producing a `.dat` watchable via the desktop viewer app (or in-game via the VS Recorder).
  - `bracket.rb` — `EloTournament.runBracket!` (`ELO_RUN_BRACKET`): seeded top-16 single-elimination bracket, curse-strips entrants when the format is an `_uncursed`/`double`-style variant — see "Top 16 bracket" below.
- `scripts/` — PowerShell tooling for running the tournament outside the editor (Windows; see "Running a tournament"):
  - `setup_shards.ps1` — syncs N independent copies of the game directory under `shards/` (one per parallel process) via `robocopy /MIR`. `-Recompile` does a `debug` launch first to pick up Plugin code changes.
  - `run_parallel.ps1` — launches N `run_tournament.ps1` watchdogs, one per shard directory. Archives `errorlog.txt` first (every launch, fresh start or resume alike). Takes `-Formats singles,doubles` (comma-separated; each shard works through the whole sequence on its own) and `-ChunksPerShard`/`-ChunksPerFormat` to split the pairing pool more finely than one chunk per shard directory, reassigning a freed-up directory to whichever (format, chunk) is next via a background supervisor (`supervise_local_chunks.ps1`) — mirrors `run_remote_parallel.ps1`'s design exactly, sharing the actual queue-building math with it via `_chunk_queue.ps1` so the two backends can't silently diverge.
  - `run_tournament.ps1` — the actual watchdog: launches `Game.exe`, restarts it on a stalled turn or a stalled whole battle, until the shard reports `finished:true`. Runs its own `-Formats` sequence to completion, one format at a time, in one shard directory.
  - `run_bracket.ps1` — the equivalent watchdog for the top-16 bracket (single, unsharded process — see "Top 16 bracket" below).
  - `run_custom_trainer.ps1` / `watch_custom_trainer.ps1` — the custom-trainer-vs-pool diversion workflow — see "Testing a custom trainer against the pool" below.
  - `pause_tournament.ps1` — stops every watchdog and `Game.exe`, in the right order (watchdogs first) so none auto-relaunch out from under you.
  - `archive_run.ps1` — moves `errorlog.txt` (always) and result/log files (`-IncludeResults`, for an intentional fresh start) into a timestamped `results/archive_.../` folder instead of deleting them.
  - `watch_parallel_tournament.ps1` — read-only live status viewer, aggregated across every shard directory and format.
  - `build_release.ps1` — packages the desktop viewer app into a distributable release — see "Developing the replay viewer" below.
  - Distributed (cloud droplet fleet) tooling — see "Running a tournament on a cloud fleet" below:
    - `remote_provision_shard.sh` — runs *on* a droplet: installs deps (Xvfb, Mesa, fluxbox), clones the game (from the personal fork noted above, not the team repo), debug-compiles, validates with a test battle. Idempotent.
    - `remote_run_tournament.sh` — runs *on* a droplet: Bash port of `run_tournament.ps1`'s watchdog, launching the headless Linux build (`Game Linux.x86_64` under Xvfb + fluxbox + software GL, since mkxp-z needs a real, if virtual, window). Takes `--formats singles,doubles` (comma-separated) plus subset-rerun flags: works through the whole sequence on its own (no recompile needed between formats — curse-stripping is a runtime check, not compile-time), with no dependency on any other shard or the control machine.
    - `setup_remote_shards.ps1` / `run_remote_parallel.ps1` / `watch_remote_tournament.ps1` / `pause_remote_tournament.ps1` / `pull_remote_results.ps1` — control-side (this machine): provision, launch, monitor, stop, and collect results from every droplet in `remote_hosts.txt`, in parallel over SSH.
    - `_remote_chunk_launch.ps1` / `supervise_remote_chunks.ps1` — chunk-oversubscription and subset-rerun support for the above — see "Running a tournament on a cloud fleet" below.
    - `remote_hosts.txt` — one droplet IP per line (gitignored — live infra detail, not code; copy from `remote_hosts.txt.example`). Shard index/count are derived from this file's contents, not passed as separate parameters.
- `results/` — JSONL battle results, status/watchdog logs (gitignored; generated by running the tournament). `archive_*/` subfolders hold previous runs. `results/remote/` holds results pulled from the cloud fleet, kept separate from local shard data since both use the identical `elo_results_<format>_shard<N>.jsonl` naming convention and would otherwise silently overwrite each other. Also holds custom-trainer diversion results (`custom_trainer_results_<format>_shard<N>.jsonl`) and subset-rerun backups (`backup_<timestamp>_<label>/`).
- `analysis/` — Python rating computation and reporting over `results/`:
  - `results_lib.py` — shared boilerplate (paths, format discovery, results/ratings/card-data loading) plus the `FILTERS` registry (`cursed_excluded`, `level70_only`; see "Analysis" below) used by every other script here via a common `--filter` flag.
  - `ratings.py` — Bradley-Terry trainer ratings (one-hot ±1 logistic regression via scikit-learn), per format/filter combination. Safe to run against a still-in-progress tournament.
  - `best_worst.py` — each trainer's best win / worst loss (with the opponent's own rank/rating) per format/filter combination.
  - `build_uncursed_results.py` — builds the `_uncursed` battle datasets (see "Curse-stripped battles" below).
  - `report.py` — turns `ratings.py`'s output into a Markdown leaderboard.
  - `bracket_report.py` — bracket-tree reporting, see "Top 16 bracket" below.
  - `compare_formats.py` — cross-format rank comparison (see "Website" above for why it's rank-only, not rating-delta).
  - `custom_trainer_report.py` — reports on a custom-trainer-vs-pool diversion run — see "Testing a custom trainer against the pool" below.
  - `apply_subset_rerun.py` — splices a targeted subset rerun's results back into the main `elo_results_<fmt>_shard*.jsonl` files in place, backing up the originals first.
  - `notable_matches.py`, `trainer_cards.py`, `level_plot.py` — supplementary reports (upsets/grinds/self-mirrors, per-trainer card data, level-vs-rating scatter).
  - `export_web_data.py` — regenerates `web/public/data/` for the website; self-regenerates `ratings_*`/`best_worst_*` first, so it's safe to run on its own — see "Developing the website" below.
- `.venv/` — Python virtualenv for `analysis/` (gitignored; see "Analysis" below to recreate it).
- `viewer/` — a PySide6 desktop app for browsing tournament results and generating/watching individual battle replays, without needing the game's own VS Recorder UI. See "Replay viewer / generator app" below.
- `web/` — the React/Vite site published at the URL above. Reads static JSON (`web/public/data/`) produced by `analysis/export_web_data.py`; see "Developing the website" below. Deployed automatically to GitHub Pages by `.github/workflows/deploy-web.yml` on every push to `main` that touches `web/`.

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
.\scripts\watch_parallel_tournament.ps1
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

### Testing a custom trainer against the pool

To see how a not-yet-in-the-pool trainer (e.g. a PBS file you're iterating on) would perform against the existing rated pool, without adding them to the real round-robin or re-rating anyone:

```powershell
.\scripts\run_custom_trainer.ps1 -PbsFile "C:\path\to\my_trainer.txt" -Format singles -ShardCount 8
.\scripts\watch_custom_trainer.ps1 -Format singles
.\.venv\Scripts\python.exe analysis\custom_trainer_report.py --format singles
```
`custom_trainer_report.py` ranks the custom trainer's results against the *existing* `ratings_<format>.json` (so it doesn't need to re-rate the pool) and prints ready-to-run `save_replay.ps1`-equivalent commands for the best win / worst loss. Results are identity-resumable the same way the main tournament is, and are written to the repo's own `results/` (not a shard's internal folder) since `setup_shards.ps1 -Recompile`'s `robocopy /MIR` would otherwise wipe anything shard-local not present in the source.

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
Each droplet works through the whole format sequence independently — finishes singles, starts doubles — with no coordination between shards and no dependency on this machine staying on after launch. With a single format and the default one-chunk-per-host layout, each host runs exactly one chunk for that format, same as before. Passing `-ChunksPerHost` above 1 (or multiple formats) instead builds a flat, format-major/chunk-minor priority queue and launches a detached `supervise_remote_chunks.ps1`, which oversubscribes: as soon as a host finishes its current chunk, the supervisor hands it the next one off the queue, so fast hosts pick up more work instead of idling behind a slow one. The queue state lives in a JSON file, not script parameters, so the supervisor is resumable if it dies mid-run.

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

Resuming works the same identity-based way as the local case: `tournament.rb` skips any pairing already present in the results JSONL (by trainer identity + format). For correcting existing data after a bug fix (rather than starting over), `-SubsetTrainerLabels`/`-SubsetTag` on `run_remote_parallel.ps1` reruns only the specified trainers' pairings into a separate `elo_results_<fmt>_<subset_tag>_shard*.jsonl` set, which `analysis/apply_subset_rerun.py` then splices back into the main results files in place (backing up the originals first).

## Curse-stripped battles

Alongside the real cursed round robin, `analysis/build_uncursed_results.py` builds a third battle dataset per base format (`singles_uncursed`, `doubles_uncursed`) by re-running curse-flagged pairings with curses stripped and merging the results back in: non-cursed rows carry over unchanged, `curse:true` rows are replaced by their curse-stripped re-battle where one exists, and any leftover cursed row for a trainer that turned out `identical_to_base` (curse-stripping made no difference) is dropped as a redundant opponent. These `_uncursed` formats are first-class from that point on — `discover_formats()` treats them the same as `singles`/`doubles`, so `ratings.py`/`best_worst.py`/the website's filters all apply on top of them the same way.

## Top 16 bracket

An exhibition top-16 single-elimination bracket can be run over a hand-curated list of 16 entrants, seeded NCAA-style (1v16, 8v9, ...) so the favorites stay apart for as long as possible, for any format including the `_uncursed` variants. Every match is a fresh battle with a replay saved (`.dat`, same VS Recorder mechanism as `replay.rb`), even if that exact pairing already has a row in the sparse round-robin results — the bracket is a showcase, not more rating data.

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
Outputs `analysis/ratings_<format>.{json,csv}` and `analysis/report_<format>.md` (all gitignored, regenerable). Most scripts here (`ratings.py`, `best_worst.py`, `custom_trainer_report.py`, ...) accept a repeatable `--filter NAME` flag (`cursed_excluded`, `level70_only`; see `analysis/results_lib.py`'s `FILTERS` registry) which both restricts the input rows and picks the `_<name1>_<name2>...` suffix on the output file, so battle type, curse variant, and filter compose as three independent axes.

## Developing the website

The site (`web/`) reads static JSON, not a live backend, so any new tournament results have to be re-exported before the site reflects them:

```powershell
.\.venv\Scripts\python.exe analysis\export_web_data.py
```
This regenerates everything under `web/public/data/` (leaderboards, trainer cards, team levels) from `analysis/`'s ratings/best-worst/trainer-card output. It's safe to run on its own — it recomputes `ratings_*`/`best_worst_*` for every published format/filter combination itself before exporting, rather than requiring `ratings.py`/`best_worst.py` to be run first. Skips any format/filter combination with no usable results yet rather than failing the whole export.

Then, from `web/`:
```powershell
npm install
npm run dev      # local dev server
npm run build    # production build (tsc -b && vite build), what CI runs
```
Pushing to `main` with changes under `web/` triggers `.github/workflows/deploy-web.yml`, which builds and publishes to GitHub Pages automatically — no manual deploy step.

## Developing the replay viewer

`viewer/` is a PySide6 desktop app for browsing tournament results and generating/watching individual battle replays, without needing to hand-run `Game.exe` with env vars or use the in-game VS Recorder directly:

- **Browse** — search/filter the actual tournament results data (`elo_results_*.jsonl`) and send a battle straight to Generate.
- **Generate** — given trainers/seed/format, runs that exact battle headlessly and produces a `.dat` replay.
- **Watch** — plays back a generated (or Browse-selected) `.dat` replay, with battle-scene/text-speed/transition options.

The app manages its own copy of the game: on first run it downloads and compiles `vendor/tectonic-content` (pinned to the same commit as the rest of this repo) rather than bundling it.

Run from source:
```powershell
cd viewer
pip install -r requirements.txt
python main.py
```

Build a distributable release (PyInstaller, via `viewer/viewer.spec`):
```powershell
.\scripts\build_release.ps1 -Version v0.1.0
```
This runs PyInstaller, stages the output under `release-staging/<version>/` alongside a `vendor_manifest.json` (pins the exact `vendor/tectonic-content` commit the build expects) and a copy of `results/remote/` (for Browse), zips it, and publishes to GitHub Releases via `gh release create`. Pass `-SkipPublish` to build/stage without publishing.

## Status

A full singles+doubles round robin has completed on the cloud fleet, with zero `had_error` battles remaining, curse-stripped `_uncursed` re-battles have been generated for both, and the top-16 bracket has been run for all four resulting formats — see [Website](#website) above. Every trainer's card (party, moves, held items, record, best win/worst loss) is viewable live on the site, rendered as HTML rather than committing per-format static PNGs to git.
