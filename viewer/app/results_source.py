"""Thin wrapper importing analysis/results_lib.py from the repo checkout.

Reimplementing the loader was considered and rejected: results_lib.py
encodes non-obvious, hand-maintained logic (sidecar-file exclusion,
raw-only-format exclusion, curse-pair bookkeeping) that a naive glob+parse
would silently regress. It's pure stdlib (glob/json/os only), so importing
it directly is cheap.
"""
import sys


def load_results_lib(analysis_dir):
    if analysis_dir not in sys.path:
        sys.path.insert(0, analysis_dir)
    import results_lib

    return results_lib
