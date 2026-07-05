"""Thin wrapper importing analysis/results_lib.py from the repo checkout.

Reimplementing the loader was considered and rejected: results_lib.py
encodes non-obvious, hand-maintained logic (sidecar-file exclusion,
raw-only-format exclusion, curse-pair bookkeeping) that a naive glob+parse
would silently regress. It's pure stdlib (glob/json/os only), so importing
it directly is cheap.

In a dev checkout, results_lib.py lives outside the viewer/ package tree, so
it's found via a plain sys.path insert. A PyInstaller build can't discover
that dynamic import through its static analysis, so scripts/build_release.ps1
instead passes --hidden-import=results_lib --paths=<repo>/analysis, which
bundles the module directly into the frozen app and puts it on the frozen
sys.path automatically -- no manual path insert needed (or possible, since
there's no analysis/ directory shipped alongside a frozen build to insert).
"""
import sys


def load_results_lib(analysis_dir):
    if not getattr(sys, "frozen", False) and analysis_dir not in sys.path:
        sys.path.insert(0, analysis_dir)
    import results_lib

    return results_lib
