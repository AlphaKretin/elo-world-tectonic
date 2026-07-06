# PyInstaller spec for the replay viewer, invoked by scripts/build_release.ps1
# (`pyinstaller viewer.spec`). Onedir build: startup time matters more than a
# single-file download for an app a dev launches repeatedly while working on
# replays, and onedir avoids onefile's temp-extraction-on-every-launch cost.
#
# results_lib.py (analysis/results_lib.py) is imported dynamically via
# sys.path manipulation at runtime (app/results_source.py), which
# PyInstaller's static analysis can't trace on its own -- hiddenimports +
# pathex here is what actually bundles it into the frozen app; without both,
# the Browse tab would ImportError as soon as it's opened.
import os

SPEC_DIR = os.path.dirname(os.path.abspath(SPEC))
ANALYSIS_DIR = os.path.join(os.path.dirname(SPEC_DIR), "analysis")

a = Analysis(
    ["main.py"],
    pathex=[ANALYSIS_DIR],
    hiddenimports=["results_lib", "trainer_naming"],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="viewer",
    console=False,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    name="viewer",
)
