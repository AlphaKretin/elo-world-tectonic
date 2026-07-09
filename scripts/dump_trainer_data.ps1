$RepoRoot = Split-Path -Parent $PSScriptRoot
$ResultsDir = Join-Path $RepoRoot "results\current"
$GameDir = Join-Path $RepoRoot "vendor\tectonic-content"
New-Item -ItemType Directory -Force -Path $ResultsDir | Out-Null

$env:ELO_TOURNAMENT = "1"
$env:ELO_DUMP_TRAINER_CARD_DATA = "1"

Push-Location $GameDir
Start-Process -FilePath ".\Game.exe" -PassThru -Wait 
Pop-Location

Remove-Item Env:\ELO_TOURNAMENT, Env:\ELO_DUMP_TRAINER_CARD_DATA -ErrorAction SilentlyContinue

Write-Output "Trainer data dumped."
