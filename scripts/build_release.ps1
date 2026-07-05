# Builds and publishes a distributable release of the replay viewer for
# other Tectonic developers: PyInstaller-built viewer.exe + a trimmed
# vendor/tectonic-content (dev-only tooling stripped out, Windows binary
# only -- no Game Linux.x86_64/lib64) + the canonical full round-robin
# results data, zipped into one package and pushed to a GitHub Release.
#
# CI (GitHub Actions) was tried and abandoned for this: producing
# Data/PluginScripts.rxdata requires a real "debug" launch of Game.exe,
# which needs a working OpenGL context. A software-rendering swap
# (Mesa's Windows llvmpipe build) got further than an earlier attempt at
# a dummy/null video driver, but still crashed before Ruby-level error
# handling even initializes, and still requires popping a real window --
# not truly headless either way. Recompiling locally (where a real GPU
# and desktop already exist) sidesteps both problems, so this script is
# meant to be run by hand on a dev machine, not from CI.
param(
    [Parameter(Mandatory=$true)][string]$Version,   # e.g. "v0.1.0"
    [switch]$SkipRecompile,
    [switch]$SkipPublish
)

$ErrorActionPreference = "Stop"

$RepoRoot    = Split-Path -Parent $PSScriptRoot
$VendorDir   = Join-Path $RepoRoot "vendor\tectonic-content"
$ViewerDir   = Join-Path $RepoRoot "viewer"
$StagingRoot = Join-Path $RepoRoot "release-staging"
$PackageDir  = Join-Path $StagingRoot $Version
$GhExe       = "C:\Program Files\GitHub CLI\gh.exe"
$Robocopy    = "$env:WINDIR\System32\robocopy.exe"

if (-not (Test-Path (Join-Path $VendorDir "Game.exe"))) {
    throw "Game.exe not found under $VendorDir -- check the submodule is checked out."
}

# ---------------------------------------------------------------------------
# 1. Recompile Plugins -> Data/PluginScripts.rxdata (same pattern as
#    setup_shards.ps1 -Recompile: a marker file, not a timestamp diff,
#    since that crosses PowerShell/filesystem UTC-vs-local math that's
#    gotten this wrong before).
# ---------------------------------------------------------------------------
if (-not $SkipRecompile) {
    $marker = Join-Path $VendorDir "Analysis\compile_done.txt"
    Remove-Item $marker -ErrorAction SilentlyContinue

    Write-Output "Recompiling scripts (debug launch)..."
    Push-Location $VendorDir
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

    if (-not (Test-Path $marker)) {
        throw "compile_done.txt never appeared within 2 minutes -- check for a stuck dialog or compile error before releasing."
    }
    Write-Output "Recompile done ($(Get-Content $marker))."
}

# ---------------------------------------------------------------------------
# 2. Clean staging dir for this version.
# ---------------------------------------------------------------------------
Remove-Item $PackageDir -Recurse -Force -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Force -Path $PackageDir | Out-Null

# ---------------------------------------------------------------------------
# 3. PyInstaller build of the viewer app (onedir; see viewer.spec for why).
#    --hidden-import/--paths for results_lib.py are baked into the spec
#    file itself, not passed here.
# ---------------------------------------------------------------------------
Write-Output "Building viewer.exe (PyInstaller)..."
$PyiDist  = Join-Path $StagingRoot "pyinstaller-dist"
$PyiBuild = Join-Path $StagingRoot "pyinstaller-build"
Push-Location $ViewerDir
python -m PyInstaller viewer.spec --distpath $PyiDist --workpath $PyiBuild --noconfirm
Pop-Location
if (-not (Test-Path (Join-Path $PyiDist "viewer\viewer.exe"))) {
    throw "PyInstaller build didn't produce viewer.exe -- check the output above."
}
& $Robocopy (Join-Path $PyiDist "viewer") $PackageDir /MIR /MT:8 /NFL /NDL /NJH /NP | Out-Null

# ---------------------------------------------------------------------------
# 4. Stage a trimmed vendor/tectonic-content -- runtime files only, no dev
#    tooling (Build files/, Changelogs/, animmaker/extendtext, cable club
#    scripts, the .rxproj, etc.) and no Linux binary/lib64 (Windows-only
#    per the release scope).
# ---------------------------------------------------------------------------
Write-Output "Staging trimmed game files..."
$GameDest = Join-Path $PackageDir "vendor\tectonic-content"
New-Item -ItemType Directory -Force -Path $GameDest | Out-Null

$includeFiles = @(
    "Game.exe", "RGSS104E.dll", "x64-msvcrt-ruby310.dll", "zlib1.dll",
    "mkxp.json", "Project Chasm.ini", "soundfont.sf2", "LICENSE"
)
foreach ($f in $includeFiles) {
    Copy-Item (Join-Path $VendorDir $f) $GameDest -Force
}

$includeDirs = @("Data", "Graphics", "Audio", "Fonts", "PBS", "Plugins")
foreach ($d in $includeDirs) {
    & $Robocopy (Join-Path $VendorDir $d) (Join-Path $GameDest $d) /MIR /MT:8 /NFL /NDL /NJH /NP | Out-Null
}

# Empty runtime dirs the engine/viewer expect to exist but that shouldn't
# ship with the dev checkout's own contents (existing recordings/saves).
foreach ($d in @("Save Game", "VSRecorder", "Analysis")) {
    New-Item -ItemType Directory -Force -Path (Join-Path $GameDest $d) | Out-Null
}

# ---------------------------------------------------------------------------
# 5. Stage the canonical full round-robin results data (per-battle jsonl,
#    needed for the Browse tab -- see viewer/app/config.py's results_dir).
# ---------------------------------------------------------------------------
Write-Output "Staging results data..."
$ResultsDest = Join-Path $PackageDir "results\remote"
& $Robocopy (Join-Path $RepoRoot "results\remote") $ResultsDest /MIR /MT:8 /NFL /NDL /NJH /NP | Out-Null

# ---------------------------------------------------------------------------
# 6. Zip it up.
# ---------------------------------------------------------------------------
$ZipName = "elo-viewer-$Version-windows.zip"
$ZipPath = Join-Path $StagingRoot $ZipName
Remove-Item $ZipPath -ErrorAction SilentlyContinue
Write-Output "Zipping -> $ZipPath ..."
Compress-Archive -Path "$PackageDir\*" -DestinationPath $ZipPath

# ---------------------------------------------------------------------------
# 7. Publish to GitHub Releases.
# ---------------------------------------------------------------------------
if ($SkipPublish) {
    Write-Output "Skipping publish (-SkipPublish). Package ready at $ZipPath"
} else {
    Write-Output "Creating GitHub release $Version ..."
    & $GhExe release create $Version $ZipPath --repo AlphaKretin/elo-world-tectonic --title $Version --generate-notes
}
