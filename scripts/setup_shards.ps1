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
param(
    [int]$ShardCount = 8,
    [switch]$Recompile
)

$RepoRoot   = Split-Path -Parent $PSScriptRoot
$SourceDir  = Join-Path $RepoRoot "vendor\tectonic-content"
$ShardsRoot = Join-Path $RepoRoot "shards"

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
    robocopy $SourceDir $shardDir /MIR /MT:8 /NFL /NDL /NJH /NP /R:1 /W:1 | Out-Null
    # Robocopy exit codes 0-7 are all success (bit flags for what it did);
    # 8+ means a real error.
    if ($LASTEXITCODE -ge 8) {
        Write-Output "  WARNING: robocopy reported errors for shard$i (exit code $LASTEXITCODE)"
    }
}

Write-Output "Done. $ShardCount shard director(ies) synced under $ShardsRoot"
