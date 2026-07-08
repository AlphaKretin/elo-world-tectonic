# Shared archive-path helper, dot-sourced by archive_run.ps1 and
# setup_remote_shards.ps1 so both build the one consolidated
# results/archive/<timestamp>_<label>/ convention identically instead of
# each growing its own naming scheme (formerly results/archive_<ts>_<label>/
# and results/remote/archive_<ts>_pre_provision/ independently).
function New-ArchiveDir {
    param([Parameter(Mandatory)][string]$Label)
    $repoRoot   = Split-Path -Parent $PSScriptRoot
    $timestamp  = Get-Date -Format "yyyy-MM-dd_HHmmss"
    $archiveDir = Join-Path $repoRoot "results\archive\${timestamp}_$Label"
    New-Item -ItemType Directory -Force -Path $archiveDir | Out-Null
    return $archiveDir
}
