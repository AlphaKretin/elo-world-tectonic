# Pokémon Tectonic Elo World

Ranks every trainer in the fangame [Pokémon Tectonic](https://github.com/Pokemon-Tectonic-Team/Pokemon-Tectonic-Content) by running a full round-robin tournament of real, headless AI-vs-AI battles, then fitting Bradley-Terry ratings over the results — the same methodology as [elo_world_pokemon_crystal](https://github.com/jsettlem/elo_world_pokemon_crystal), built on top of Tectonic's [AI Benchmark](https://github.com/Pokemon-Tectonic-Team/Pokemon-Essentials-Chasm-Engine/tree/3.5-ai-rework) headless battle engine instead of emulator automation.

## Website

**[alphakretin.github.io/elo-world-tectonic](https://alphakretin.github.io/elo-world-tectonic/)** — browse the full round-robin results. Every leaderboard/compare/stats view is addressed by three orthogonal axes: **battle type** (singles/doubles), **curse variant** (cursed/uncursed — see "Curse-stripped battles" below), and **filter** (none / cursed-excluded / level70-only), e.g. `/singles/uncursed/level70_only`.

- **Leaderboard** — sortable, searchable rankings for the current battle type/curse variant/filter, with a tier badge. Click a trainer to open their full card (party, moves, held items, record, best win/worst loss with the opponent's own rank shown alongside), downloadable as a PNG.
- **Compare** — pick any two of the above combinations and see every trainer's rank side-by-side, with the rank delta between them (rescaled so a trainer missing from one format doesn't inflate the others' rank deltas). Deliberately rank-only, not rating-delta: each format's Bradley-Terry fit has no shared anchor, so a raw rating difference across two independent fits isn't a meaningful quantity.
- **Stats** — scatter-plot any two metrics against each other (rating, rank, win rate, team level) for the current battle type/curse variant/filter, with an optional least-squares trendline.

## Replay viewer

**[Latest release](https://github.com/AlphaKretin/elo-world-tectonic/releases/latest)** — **Battle Station**, a companion desktop app (`viewer/`) for browsing and watching individual battles, complementing the website's overall ratings with a look at specific matches: search the full results set for a pairing, generate that exact battle as a watchable replay, and step through it turn-by-turn — all headless, no need for the in-game VS Recorder. See "Developing the replay viewer" below for how to run or build it.

---

The rest of this README covers the tournament infrastructure itself — running the headless battle engine, distributing it across a cloud fleet, and generating ratings/reports/website data from the results.

## Layout

- `vendor/tectonic-content/` — submodule, pinned to a personal fork (`AlphaKretin/Pokemon-Tectonic-Mods` @ `elo-tournament`, not the team repo — this branch carries tournament-only hacks that don't belong upstream) of `Pokemon-Tectonic-Content`. The runnable mkxp-z game project. Also ships a native Linux build (`Game Linux.x86_64`, same mkxp-z engine) used by the cloud fleet tooling below.
- `vendor/tectonic-content/Plugins/ELO Tournament/` — the headless harness:
  - `headless_boot.rb` — boot hook (`ENV["ELO_TOURNAMENT"]`-gated): jumps straight into the tournament instead of the title screen, plus headless-environment compatibility patches.
  - `trainer_pool.rb` — builds the real trainer roster from `GameData::Trainer`, with any active quarantines for known-bad matchups.
  - `tournament.rb` — pairing, orchestration, resumable JSONL result logging, `EloTournament.testSinglePairing!`/`testBatchPairings!` (one-pairing/many-pairing diagnostic harnesses — see below), and the curse-stripping/uncursed-rebattle plumbing consumed in memory by `analysis/results_lib.py` (see "Curse-stripped battles" below).
  - `custom_trainer_battles.rb` — `ELO_CUSTOM_TRAINER_BATTLES`-gated: battles one custom, not-in-the-pool trainer against the existing rated pool without touching the real round-robin — see "Testing a custom trainer against the pool" below.
  - `replay.rb` — `EloTournament.saveReplay!` (`ELO_SAVE_REPLAY`): re-runs one exact stored `(trainer1, trainer2, format, seed)` with recording enabled, producing a `.dat` watchable via the desktop viewer app (or in-game via the VS Recorder).
- `scripts/` — PowerShell tooling for running the tournament outside the editor (Windows; see "Running a tournament"):
  - `setup_shards.ps1` — syncs N independent copies of the game directory under `shards/` (one per parallel process) via `robocopy /MIR`. `-Recompile` does a `debug` launch first to pick up Plugin code changes.
  - `run_parallel.ps1` — launches N `run_tournament.ps1` watchdogs, one per shard directory. Archives `errorlog.txt` first (every launch, fresh start or resume alike). Takes `-Formats singles,doubles` (comma-separated; each shard works through the whole sequence on its own) and `-ChunksPerShard`/`-ChunksPerFormat` to split the pairing pool more finely than one chunk per shard directory, reassigning a freed-up directory to whichever (format, chunk) is next via a background supervisor (`supervise_local_chunks.ps1`) — mirrors `run_remote_parallel.ps1`'s design exactly, sharing the actual queue-building math with it via `_chunk_queue.ps1` so the two backends can't silently diverge.
  - `run_tournament.ps1` — the actual watchdog: launches `Game.exe`, restarts it on a stalled turn or a stalled whole battle, until the shard reports `finished:true`. Runs its own `-Formats` sequence to completion, one format at a time, in one shard directory.
  - `run_custom_trainer.ps1` / `watch_custom_trainer.ps1` — the custom-trainer-vs-pool diversion workflow — see "Testing a custom trainer against the pool" below.
  - `run_single_pairing.ps1` / `run_batch_pairings.ps1` — one-off pairing diagnostics, outside the main pool/loop — see "Diagnosing a specific bad battle" below.
  - `pause_tournament.ps1` — stops every watchdog and `Game.exe`, in the right order (watchdogs first) so none auto-relaunch out from under you.
  - `archive_run.ps1` — moves `errorlog.txt` (always) and result/log files (`-IncludeResults`, for an intentional fresh start) into a timestamped `results/archive/.../` folder instead of deleting them (see `archive_lib.ps1`).
  - `watch_parallel_tournament.ps1` — read-only live status viewer, aggregated across every shard directory and format.
  - `build_release.ps1` — packages the desktop viewer app into a distributable release — see "Developing the replay viewer" below.
  - Distributed (cloud droplet fleet) tooling — see "Running a tournament on a cloud fleet" below:
    - `remote_provision_shard.sh` — runs *on* a droplet: installs deps (Xvfb, Mesa, fluxbox), clones the game (from the personal fork noted above, not the team repo), debug-compiles, validates with a test battle. Idempotent.
    - `remote_run_tournament.sh` — runs *on* a droplet: Bash port of `run_tournament.ps1`'s watchdog, launching the headless Linux build (`Game Linux.x86_64` under Xvfb + fluxbox + software GL, since mkxp-z needs a real, if virtual, window). Takes `--formats singles,doubles` (comma-separated) plus subset-rerun flags: works through the whole sequence on its own (no recompile needed between formats — curse-stripping is a runtime check, not compile-time), with no dependency on any other shard or the control machine.
    - `setup_remote_shards.ps1` / `run_remote_parallel.ps1` / `watch_remote_tournament.ps1` / `pause_remote_tournament.ps1` / `pull_remote_results.ps1` — control-side (this machine): provision, launch, monitor, stop, and collect results from every droplet in `remote_hosts.txt`, in parallel over SSH.
    - `_remote_chunk_launch.ps1` / `supervise_remote_chunks.ps1` — chunk-oversubscription and subset-rerun support for the above — see "Running a tournament on a cloud fleet" below.
    - `remote_hosts.txt` — one droplet IP per line (gitignored — live infra detail, not code; copy from `remote_hosts.txt.example`). Shard index/count are derived from this file's contents, not passed as separate parameters.
- `results/` — JSONL battle results, status/watchdog logs (gitignored except each subfolder's `.gitkeep`; results/ root itself holds no loose files, only these four subfolders):
  - `results/local/` — local shard-run scratch space: everything `run_tournament.ps1`/`run_parallel.ps1` (and the custom-trainer/single-pairing/batch-pairing diversions) write while running, one shard's worth of JSONL results, status/watchdog/game logs, chunk-queue state, etc.
  - `results/remote/` — pull-landing zone only: exactly what `pull_remote_results.ps1`/`setup_remote_shards.ps1` scp down from the droplet fleet, plus the remote chunk-supervisor's own queue state/log. Not read directly by any analysis script.
  - `results/current/` — the actual ground truth every analysis script reads by default (`results_lib.RESULTS_DIR`). Promoting data from `results/remote/` or `results/local/` into here after a pull/run is a manual `cp`, by design — there's no tooling step to forget.
  - `results/archive/` — single consolidated root for every historical backup (`archive_run.ps1`, `apply_subset_rerun.py`, `setup_remote_shards.ps1`'s pre-provision archive), each in its own `<timestamp>_<label>/` folder. Moved (never deleted), so old data stays available for later diagnosis even once it's no longer valid for ratings.
- `analysis/` — Python rating computation and reporting over `results/`. Only scripts (+ `card_constants.py`, shared card-rendering constants) live at this level; every script's generated output goes into its own gitignored, regenerable subfolder instead (`ratings/`, `best_worst/`, `reports/`, `compare/`, `notable_matches/`, `custom_trainer/`, `cards/`), named after the kind of file it holds:
  - `results_lib.py` — shared boilerplate (paths, format discovery, results/ratings/card-data loading) plus the `FILTERS` registry (`cursed_excluded`, `level70_only`; see "Analysis" below) used by every other script here via a common `--filter` flag. Also owns the output-subfolder path constants (`RATINGS_DIR`, `BEST_WORST_DIR`, etc.) every other script writes into.
  - `ratings.py` — Bradley-Terry trainer ratings (one-hot ±1 logistic regression via scikit-learn), per format/filter combination, written to `ratings/`. Safe to run against a still-in-progress tournament.
  - `best_worst.py` — each trainer's best win / worst loss (with the opponent's own rank/rating) per format/filter combination, written to `best_worst/`.
  - `report.py` — turns `ratings.py`'s output into a Markdown leaderboard under `reports/`.
  - `compare_formats.py` — cross-format rank comparison under `compare/` (see "Website" above for why it's rank-only, not rating-delta).
  - `custom_trainer_report.py` — reports (under `custom_trainer/`) on a custom-trainer-vs-pool diversion run — see "Testing a custom trainer against the pool" below.
  - `apply_subset_rerun.py` — splices a targeted subset rerun's results back into the main `elo_results_<fmt>_shard*.jsonl` files in place, backing up the originals first.
  - `notable_matches.py`, `trainer_cards.py`, `level_plot.py` — supplementary reports (upsets/grinds/self-mirrors under `notable_matches/`, per-trainer card data under `cards/`, level-vs-rating scatter).
  - `export_web_data.py` — regenerates `web/public/data/` for the website; self-regenerates `ratings/`/`best_worst/` first, so it's safe to run on its own — see "Developing the website" below.
- `.venv/` — Python virtualenv for `analysis/` (gitignored; see "Analysis" below to recreate it).
- `viewer/` — **Battle Station**, a PySide6 desktop app for browsing tournament results and generating/watching individual battle replays, without needing the game's own VS Recorder UI. See "Replay viewer / generator app" below.
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

`EloTournament.testSinglePairing!` (gated by `ELO_TEST_SINGLE_PAIRING`) runs exactly one pairing, by explicit trainer identity and seed, outside the main pool/loop — much faster than reproducing an issue through the full tournament:

```powershell
.\scripts\run_single_pairing.ps1 -T1Type YOUNGSTER -T1Name Joey -T2Type HARLEQUIN -T2Name Vincenzi -Seed 2786941428
```
Runs directly in `vendor/tectonic-content` (no shard dir needed for one battle) and copies the result out to `results/local/single_pairing_test_<timestamp>.txt`, printing it too. Add `-T1Version`/`-T2Version` for non-zero trainer versions, `-T1PartyIndices`/`-T2PartyIndices` (comma-separated, 0-based) to bisect which party member is responsible for a crash/hang, or `-PrebattleOnly` to dump each side's resolved party species without running a battle at all.

For more than a handful of pairings (e.g. rerunning every battle affected by a behavior fix), `EloTournament.testBatchPairings!` (gated by `ELO_TEST_BATCH_PAIRINGS`) takes a tab-separated manifest instead of paying a fresh `Game.exe` boot per pairing:

```powershell
.\scripts\run_batch_pairings.ps1 -ManifestPath "C:\path\to\pairings.tsv" -ShardCount 8
```
Manifest format: `t1Type<TAB>t1Name<TAB>t1Version<TAB>t2Type<TAB>t2Name<TAB>t2Version<TAB>seed<TAB>battleMode` (one pairing per line, `#`-comments/blank lines OK; `battleMode` is the engine's own `single`/`double`/`triple`, not this repo's `singles`/`doubles` `ELO_FORMAT` convention). `-ShardCount` (default 1) splits the manifest round-robin across that many shard directories. Combined results land in `results/local/batch_pairing_results_<timestamp>.jsonl`.

### Testing a custom trainer against the pool

To see how a not-yet-in-the-pool trainer (e.g. a PBS file you're iterating on) would perform against the existing rated pool, without adding them to the real round-robin or re-rating anyone:

```powershell
.\scripts\run_custom_trainer.ps1 -PbsFile "C:\path\to\my_trainer.txt" -Format singles -ShardCount 8
.\scripts\watch_custom_trainer.ps1 -Format singles
.\.venv\Scripts\python.exe analysis\custom_trainer_report.py --format singles
```
`custom_trainer_report.py` ranks the custom trainer's results against the *existing* `ratings_<format>.json` (so it doesn't need to re-rate the pool) and prints ready-to-run `save_replay.ps1`-equivalent commands for the best win / worst loss. Results are identity-resumable the same way the main tournament is, and are written to the repo's own `results/local/` (not a shard's internal folder) since `setup_shards.ps1 -Recompile`'s `robocopy /MIR` would otherwise wipe anything shard-local not present in the source.

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
Lands in `results/remote/`, the pull-landing zone — see the Layout note above. Promote into `results/current/` (a manual `cp`) once you're ready to rate against it.

Stop everything:
```powershell
.\scripts\pause_remote_tournament.ps1
```

Resuming works the same identity-based way as the local case: `tournament.rb` skips any pairing already present in the results JSONL (by trainer identity + format). For correcting existing data after a bug fix (rather than starting over), `-SubsetTrainerLabels`/`-SubsetTag` on `run_remote_parallel.ps1` reruns only the specified trainers' pairings into a separate `elo_results_<fmt>_<subset_tag>_shard*.jsonl` set, which `analysis/apply_subset_rerun.py` then splices back into the main results files in place (backing up the originals first).

## Curse-stripped battles

Alongside the real cursed round robin, the curse-stripped tournament run re-battles every curse-flagged pairing with curses stripped and writes its results to `elo_results_<fmt>_uncursed_shard*.jsonl` — always a *partial* re-battle subset (only pairings where stripping curses actually changed a party get re-run), never a full round robin on its own. `results_lib.load_results()` merges that on-disk subset with the base format's `curse:false` population in memory on every call (see `results_lib.is_uncursed_format`/`_merge_uncursed`): non-cursed rows carry over unchanged, `curse:true` rows are replaced by their curse-stripped re-battle where one exists, and any leftover cursed row for a trainer that turned out `identical_to_base` (curse-stripping made no difference) is dropped as a redundant opponent. There is no separate merged file to keep in sync — `singles_uncursed`/`doubles_uncursed` are first-class formats computed fresh on every load, so `ratings.py`/`best_worst.py`/the website's filters all apply on top of them the same way as `singles`/`doubles`.

## Top 16 bracket

An exhibition top-16 single-elimination bracket, seeded NCAA-style (1v16, 8v9, ...) so the favorites stay apart for as long as possible, for any format including the `_uncursed` variants. This lives entirely in the replay viewer's Bracket tab (`viewer/app/bracket_tab.py`/`bracket_lib.py`) — it resolves each match client-side in Python, either instantly (an existing decisive round-robin result for that pairing) or by handing off to the Generate tab for a fresh headless battle, without ever shelling out to a separate bracket runner. See "Replay viewer / generator app" below for running the viewer.

Seeding is manual curation, not a straight top-16-by-rating pull: some formats' true top-16 is uninteresting (one trainer overwhelmingly favored, or duplicate trainers taking multiple slots), so `viewer/app/bracket_seeds.py`'s `BRACKETS` list is hand-written -- each entry a `name` (shown in the Bracket tab's picker), a `format` (which raw match pool to resolve results against), and a curated list of 16 trainer labels in seed order (use `analysis/ratings/ratings_<format>.json` to see who's actually rated highest and pick from there). Brackets aren't one-per-format: several can share the same `format` (e.g. a developer-only bracket alongside the main one) when a format's default top-16 and some other curated subset are both worth watching.

## Analysis

```powershell
python -m venv .venv
.\.venv\Scripts\pip install scikit-learn numpy scipy
.\.venv\Scripts\python.exe analysis\ratings.py
.\.venv\Scripts\python.exe analysis\report.py
```
Outputs `analysis/ratings/ratings_<format>.{json,csv}` and `analysis/reports/report_<format>.md` (all gitignored, regenerable — each script's output lives in its own subfolder under `analysis/`, named after the kind of file it produces). Most scripts here (`ratings.py`, `best_worst.py`, `custom_trainer_report.py`, ...) accept a repeatable `--filter NAME` flag (`cursed_excluded`, `level70_only`; see `analysis/results_lib.py`'s `FILTERS` registry) which both restricts the input rows and picks the `_<name1>_<name2>...` suffix on the output file, so battle type, curse variant, and filter compose as three independent axes.

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

`viewer/` (**Battle Station**) is a PySide6 desktop app for browsing tournament results and generating/watching individual battle replays, without needing to hand-run `Game.exe` with env vars or use the in-game VS Recorder directly:

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
This runs PyInstaller, stages the output under `release-staging/<version>/` alongside a `vendor_manifest.json` (pins the exact `vendor/tectonic-content` commit the build expects) and a copy of `results/current/` (for Browse), zips it, and publishes to GitHub Releases via `gh release create`. Pass `-SkipPublish` to build/stage without publishing.

## Status

A full singles+doubles round robin has completed on the cloud fleet, with zero `had_error` battles remaining, curse-stripped `_uncursed` re-battles have been generated for both, and the top-16 bracket has been run for all four resulting formats — see [Website](#website) above. Every trainer's card (party, moves, held items, record, best win/worst loss) is viewable live on the site, rendered as HTML rather than committing per-format static PNGs to git.
