# Builds and publishes a distributable release of the replay viewer for
# other Tectonic developers: PyInstaller-built viewer.exe + a manifest
# pinning the vendor/tectonic-content commit + the canonical full
# round-robin results data, zipped into one package and pushed to a GitHub
# Release. The game itself is NOT bundled -- the viewer downloads the
# pinned commit as a GitHub archive on first run (viewer/app/vendor_fetch.py)
# and compiles the gitignored PluginScripts.rxdata/PBS data locally, which
# keeps the one-click download small and decouples the app version from the
# game version.
param(
    [Parameter(Mandatory=$true)][string]$Version,   # e.g. "v0.1.0"
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

# PowerShell's Compress-Archive is single-threaded with real per-entry
# overhead -- benchmarked at ~11x slower than NanaZip's 7-Zip-based engine
# on this package's ~20,000-small-files layout (17.9s vs 1.6s zipping just
# Graphics/, same output size), so it's worth resolving NanaZip dynamically
# rather than hardcoding its version-numbered install path (which changes
# on every NanaZip update).
$NanaZipPackage = Get-AppxPackage -Name "*NanaZip*" | Select-Object -First 1
if (-not $NanaZipPackage) {
    throw "NanaZip isn't installed -- it's what makes zipping this many small files fast. Install it (winget install NanaZip) or fall back to Compress-Archive by editing this script."
}
$NanaZipConsole = Join-Path $NanaZipPackage.InstallLocation "NanaZip.Universal.Console.exe"

if (-not (Test-Path (Join-Path $VendorDir "Game.exe"))) {
    throw "Game.exe not found under $VendorDir -- check the submodule is checked out."
}

# Robocopy's own summary table is noise on every successful run (and this
# script prints its own before/after messages around each copy already),
# but its retry/error output is exactly what you want to see when something
# genuinely goes wrong (e.g. a destination file still held open by a
# previous test run) -- so capture it and only surface it on failure.
# Exit codes 0-7 are success (bitmask of "files copied"/"extra files"/etc.);
# 8+ means real errors.
function Invoke-Robocopy {
    param([string[]]$RobocopyArgs)
    $output = & $Robocopy @RobocopyArgs
    if ($LASTEXITCODE -ge 8) {
        $output | Write-Output
        throw "Robocopy failed (exit code $LASTEXITCODE) copying to/from one of: $($RobocopyArgs -join ' ')"
    }
}

# ---------------------------------------------------------------------------
# 1. Clean staging dir for this version.
# ---------------------------------------------------------------------------
Remove-Item $PackageDir -Recurse -Force -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Force -Path $PackageDir | Out-Null

# ---------------------------------------------------------------------------
# 2. PyInstaller build of the viewer app (onedir; see viewer.spec for why).
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
Write-Output "Copying viewer.exe + dependencies into the package (PySide6/Qt bundles a lot of files, this can take a minute)..."
Invoke-Robocopy @((Join-Path $PyiDist "viewer"), $PackageDir, "/MIR", "/MT:8", "/R:3", "/W:2", "/NFL", "/NDL", "/NJH", "/NP")
Write-Output "Copy done."

# ---------------------------------------------------------------------------
# 3. Write the vendor manifest instead of bundling the game -- the viewer
#    downloads this exact commit as a GitHub archive on first run (see
#    viewer/app/vendor_fetch.py) rather than shipping it in the zip. This
#    trades a one-click install for a much smaller download; a version bump
#    that changes the pinned submodule commit just changes this file, and
#    the viewer re-fetches automatically the next time it launches.
# ---------------------------------------------------------------------------
Write-Output "Writing vendor manifest..."
$VendorCommit = (git -C $VendorDir rev-parse HEAD).Trim()
# Read from .gitmodules, not the submodule checkout's own "origin" remote --
# the local checkout's remote names/URLs are whatever the dev set up (can
# include an upstream "origin" alongside a "fork" remote), while .gitmodules
# is this project's authoritative declaration of where the pinned commit
# actually needs to be fetchable from.
$VendorRemote = (git config -f (Join-Path $RepoRoot ".gitmodules") --get submodule.vendor/tectonic-content.url).Trim()
$VendorRepoSlug = $VendorRemote -replace '^https://github.com/', '' -replace '\.git$', ''

# Hash the exact archive the viewer will download (codeload.github.com's
# zipball for this commit) so it can catch a corrupted/truncated download
# before extracting over a previous install -- GitHub doesn't publish a
# checksum for zipballs itself, so this is self-computed against the same
# bytes every end user's viewer will fetch.
#
# This doubles as a pre-publish gate: codeload.github.com can 404 on a
# commit for a short while right after it's pushed (archive generation lags
# the push itself), so a failure here means the archive isn't reliably
# fetchable yet -- wait a bit and rerun rather than working around it,
# since that's exactly what an end user's first launch would also hit.
$VendorArchiveUrl = "https://codeload.github.com/$VendorRepoSlug/zip/$VendorCommit"
$VendorArchiveTemp = Join-Path $StagingRoot "vendor_archive_checksum.zip"
Write-Output "Downloading vendor archive to compute checksum..."
try {
    Invoke-WebRequest -Uri $VendorArchiveUrl -OutFile $VendorArchiveTemp
} catch {
    throw "Failed to download $VendorArchiveUrl -- if $VendorCommit was just pushed, codeload may still be catching up (wait a minute or two and rerun); otherwise check the commit was actually pushed. $_"
}
$VendorSha256 = (Get-FileHash -Path $VendorArchiveTemp -Algorithm SHA256).Hash.ToLower()
# codeload responses often omit Content-Length (chunked transfer), so the
# viewer can't derive a progress-bar total from the download itself --
# stash the size here, from the same archive that was just hashed, instead.
$VendorSizeBytes = (Get-Item $VendorArchiveTemp).Length
Remove-Item $VendorArchiveTemp -ErrorAction SilentlyContinue

@{ repo = $VendorRepoSlug; commit = $VendorCommit; sha256 = $VendorSha256; size_bytes = $VendorSizeBytes } | ConvertTo-Json | Set-Content -Path (Join-Path $PackageDir "vendor_manifest.json") -Encoding utf8
Write-Output "  -> $VendorRepoSlug @ $VendorCommit (sha256 $VendorSha256)"

# ---------------------------------------------------------------------------
# 4. Stage the canonical full round-robin results data (per-battle jsonl,
#    needed for the Browse tab -- see viewer/app/config.py's results_dir).
# ---------------------------------------------------------------------------
Write-Output "Staging results data..."
$ResultsDest = Join-Path $PackageDir "results\current"
Invoke-Robocopy @((Join-Path $RepoRoot "results\current"), $ResultsDest, "/MIR", "/MT:8", "/R:3", "/W:2", "/NFL", "/NDL", "/NJH", "/NP")
Write-Output "Results staged."

# ---------------------------------------------------------------------------
# 5. Zip it up.
# ---------------------------------------------------------------------------
$ZipName = "elo-viewer-$Version-windows.zip"
$ZipPath = Join-Path $StagingRoot $ZipName
Remove-Item $ZipPath -ErrorAction SilentlyContinue
Write-Output "Zipping -> $ZipPath ..."
& $NanaZipConsole a -tzip -mx=5 -mmt=on $ZipPath "$PackageDir\*" | Out-Null
if (-not (Test-Path $ZipPath)) {
    throw "NanaZip didn't produce $ZipPath -- check the output above."
}

# ---------------------------------------------------------------------------
# 6. Publish to GitHub Releases.
# ---------------------------------------------------------------------------
if ($SkipPublish) {
    Write-Output "Skipping publish (-SkipPublish). Package ready at $ZipPath"
} else {
    Write-Output "Creating GitHub release $Version ..."
    & $GhExe release create $Version $ZipPath --repo AlphaKretin/elo-world-tectonic --title $Version --generate-notes
}
