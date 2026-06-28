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
param(
    [int]$ShardCount = 8
)

$RepoRoot   = Split-Path -Parent $PSScriptRoot
$SourceDir  = Join-Path $RepoRoot "vendor\tectonic-content"
$ShardsRoot = Join-Path $RepoRoot "shards"

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
