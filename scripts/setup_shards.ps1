# Syncs N independent copies of the game directory for parallel tournament
# shards. Every debug launch recompiles Plugins into Data/PluginScripts.rxdata,
# so concurrent Game.exe instances sharing one directory would race on that
# write -- each shard gets its own copy instead.
#
# Uses robocopy /MIR rather than a full recursive copy: it only transfers
# files that actually changed (by timestamp/size) and removes files deleted
# from the source, so re-running this after a small code edit is fast --
# first run still does a full copy (nothing to diff against yet), but later
# runs only touch the handful of changed Plugin .rb files plus the
# recompiled PluginScripts.rxdata, not the ~0.67GB of Graphics/Audio/PBS
# data that never changes.
#
# A subset-pairs manifest for exact-pair reruns (tournament.rb's
# SUBSET_PAIRS_PATH) needs no special handling here: drop it anywhere under
# vendor\tectonic-content\Analysis\ before running this script and the /MIR
# below picks it up like any other source file, since it mirrors the whole
# game directory. (Remote droplets don't get this for free -- see
# setup_remote_shards.ps1's -SubsetPairsPath, since that provisions via a
# fresh git clone instead of copying this working tree.)
#
# -Recompile does a plain "debug" launch of the root game first (scripts
# only -- PluginScripts.rxdata -- not a PBS recompile; PBS data is a
# one-time "debug compile" pass done manually, not part of this routine
# flow) so edited Plugin code is actually picked up before syncing.
#
# Completion is detected via headless_boot.rb's ELO_COMPILE_ONLY path
# writing Analysis/compile_done.txt and exiting, not by comparing
# PluginScripts.rxdata's timestamp before/after: that comparison has to
# cross PowerShell (UTC) and whatever the file system reports, and got
# the UTC/local conversion wrong more than once -- a marker file written
# from inside the same process that's doing the compiling has no
# cross-tool timezone math to get wrong.
#
# Archives results/ (via archive_run.ps1 -IncludeResults) before syncing,
# same as setup_remote_shards.ps1 does before it provisions -- without
# this, a leftover elo_status_*/elo_results_* file from a days-old run
# silently sits in results/ and pollutes watch_parallel_tournament.ps1's
# aggregate for the next run, indistinguishable from live data (confirmed
# live 2026-07-08: a week-old elo_status_singles_shard0.json/
# elo_status_doubles_shard0.json pair was still being read into the
# aggregate). Use -SkipResultsArchive when resyncing mid-run (e.g. after a
# hotfix) and you want to keep in-progress results.
param(
    [int]$ShardCount = 8,
    [switch]$Recompile,
    [switch]$SkipResultsArchive
)

$RepoRoot   = Split-Path -Parent $PSScriptRoot
$SourceDir  = Join-Path $RepoRoot "vendor\tectonic-content"
$ShardsRoot = Join-Path $RepoRoot "shards"

if (-not $SkipResultsArchive) {
    & (Join-Path $PSScriptRoot "archive_run.ps1") -Label "pre_setup_shards" -IncludeResults
}

if ($Recompile) {
    $marker = Join-Path $SourceDir "Analysis\compile_done.txt"
    Remove-Item $marker -ErrorAction SilentlyContinue

    Write-Output "Recompiling scripts (debug launch)..."
    Push-Location $SourceDir
    $env:ELO_TOURNAMENT = "1"
    $env:ELO_COMPILE_ONLY = "1"
    $proc = Start-Process -FilePath ".\Game.exe" -ArgumentList "debug" -PassThru
    Remove-Item Env:\ELO_TOURNAMENT -ErrorAction SilentlyContinue
    Remove-Item Env:\ELO_COMPILE_ONLY -ErrorAction SilentlyContinue
    Pop-Location

    $deadline = (Get-Date).AddMinutes(2)
    while ((Get-Date) -lt $deadline) {
        Start-Sleep -Seconds 2
        if (Test-Path $marker) { break }
        if ($proc.HasExited) { break }
    }
    Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue

    if (Test-Path $marker) {
        Write-Output "Recompile done ($(Get-Content $marker))."
    } else {
        Write-Output "WARNING: compile_done.txt never appeared within 2 minutes -- check for a stuck dialog or compile error."
    }
}

New-Item -ItemType Directory -Force -Path $ShardsRoot | Out-Null

for ($i = 0; $i -lt $ShardCount; $i++) {
    $shardDir = Join-Path $ShardsRoot "shard$i"
    Write-Output "Syncing game directory -> $shardDir ..."
    # /MIR mirror (copies changed files, removes ones deleted from source)
    # /MT:8 multi-threaded  /R:1 /W:1 minimal retry on a locked file
    # /NFL /NDL /NJH /NP suppress the (huge, unhelpful) per-file listing
    #
    # Absolute path, not bare "robocopy": a detached process launched from
    # a git-bash-derived PATH (e.g. via the Bash tool) doesn't include
    # System32, so plain "robocopy" silently resolves to nothing and this
    # whole sync step no-ops -- happened for real on the 2026-06-28->29
    # singles-to-doubles handoff. $env:SystemRoot is set by the OS itself,
    # not derived from PATH, so it survives that.
    & "$env:SystemRoot\System32\robocopy.exe" $SourceDir $shardDir /MIR /MT:8 /NFL /NDL /NJH /NP /R:1 /W:1 | Out-Null
    # Robocopy exit codes 0-7 are all success (bit flags for what it did);
    # 8+ means a real error.
    if ($LASTEXITCODE -ge 8) {
        Write-Output "  WARNING: robocopy reported errors for shard$i (exit code $LASTEXITCODE)"
    }
}

Write-Output "Done. $ShardCount shard director(ies) synced under $ShardsRoot"
