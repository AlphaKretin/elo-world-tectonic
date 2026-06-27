# Sets up N independent copies of the game directory for parallel
# tournament shards. Every `debug` launch recompiles Plugins into
# Data/PluginScripts.rxdata, so concurrent Game.exe instances sharing one
# directory would race on that write -- each shard gets its own full copy
# instead. Re-run this after pulling engine/content changes to refresh the
# shard copies (existing shards are left alone unless -Force is passed).
param(
    [int]$ShardCount = 8,
    [switch]$Force
)

$RepoRoot   = Split-Path -Parent $PSScriptRoot
$SourceDir  = Join-Path $RepoRoot "vendor\tectonic-content"
$ShardsRoot = Join-Path $RepoRoot "shards"

New-Item -ItemType Directory -Force -Path $ShardsRoot | Out-Null

for ($i = 0; $i -lt $ShardCount; $i++) {
    $shardDir = Join-Path $ShardsRoot "shard$i"
    if ((Test-Path $shardDir) -and -not $Force) {
        Write-Output "shard$i already exists, skipping (use -Force to refresh)"
        continue
    }
    if (Test-Path $shardDir) {
        Remove-Item -Recurse -Force $shardDir
    }
    Write-Output "Copying game directory -> $shardDir ..."
    Copy-Item -Recurse -Path $SourceDir -Destination $shardDir
}

Write-Output "Done. $ShardCount shard director(ies) ready under $ShardsRoot"
