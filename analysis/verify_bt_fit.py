#!/usr/bin/env python3
"""
Pinned regression check for ratings.py's hand-rolled Newton solver
(fit_bt) against a tightly-converged sklearn LogisticRegression fit --
the one configuration (zero-mean prior, no offset) where an established
package can serve as ground truth. See fit_bt's docstring for why sklearn
isn't used directly in production (its default tolerance under-converges
this problem's scale) and why this is checked against a *tightened*
sklearn fit rather than sklearn's own defaults.

Guards against a future change to fit_bt silently breaking convergence or
the math itself -- run this after touching fit_bt/_design_matrix.

Exits nonzero (and prints which trainers/format failed) if any check's
max rating-scale discrepancy exceeds its tolerance.
"""
import sys

import numpy as np
from sklearn.linear_model import LogisticRegression

import ratings
import results_lib


def check(fmt, tol=0.01):
    rows = results_lib.load_results(fmt, results_dir=ratings.RESULTS_DIR, report_skipped=True)
    stats, fit_rows = ratings._collect_stats_and_fit_rows(rows, (), None, ())
    trainers = sorted(stats.keys())
    index = {t: i for i, t in enumerate(trainers)}

    X, y = ratings._design_matrix(fit_rows, index)
    sklearn_model = LogisticRegression(fit_intercept=False, C=ratings.REG_C, max_iter=20000, tol=1e-12)
    sklearn_model.fit(X, y)
    sklearn_ratings = sklearn_model.coef_[0] * ratings.ELO_SCALE + ratings.ELO_BASE

    newton_w, _ = ratings.fit_bt(fit_rows, index)
    newton_ratings = newton_w * ratings.ELO_SCALE + ratings.ELO_BASE

    diff = np.abs(sklearn_ratings - newton_ratings)
    max_diff = diff.max()
    worst = trainers[int(np.argmax(diff))]
    ok = max_diff <= tol
    status = "OK" if ok else "FAIL"
    print(f"[{status}] {fmt}: {len(trainers)} trainers, {len(fit_rows)} battles, "
          f"max diff {max_diff:.5f} rating points (tol {tol}), worst: {worst}")
    return ok


def main():
    formats = sys.argv[1:] or ["singles"]
    results = [check(fmt) for fmt in formats]
    if not all(results):
        sys.exit(1)
    print("All checks passed.")


if __name__ == "__main__":
    main()
