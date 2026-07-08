"""Trainer label -> human-readable display name, reusing the exact logic
trainer_cards.py and export_web_data.py use (analysis/trainer_naming.py) so
the viewer never grows its own copy of the fight-numbering/masked-villain
rules. Loads results/current/trainer_data.json once and caches the
label->row index, same shape results_lib.load_trainer_data() returns.
"""
import sys

from app.results_source import load_results_lib


def load_trainer_naming(analysis_dir):
    if not getattr(sys, "frozen", False) and analysis_dir not in sys.path:
        sys.path.insert(0, analysis_dir)
    import trainer_naming

    return trainer_naming


class TrainerNameResolver:
    """label ("TYPE:Name#version") -> display name ("Leader Name #2"),
    falling back to the raw label if trainer_data.json hasn't been dumped
    yet or doesn't contain this label (e.g. a hand-typed label in Generate
    that doesn't match any known trainer).

    Every label's display name is computed once, up front, and cached --
    resolve_display_name's per-label cost is O(all trainer rows) (it
    re-walks every sibling version to work out fight numbering), so calling
    it fresh per Browse-tab row made loading a large results table visibly
    slow (O(rows x trainer rows)). There are only a few hundred
    trainer_data.json rows regardless of how many battle results reference
    them, so computing the whole label -> name mapping once is cheap and
    every later lookup is a plain dict get."""

    def __init__(self, config):
        self.config = config
        self._display_names = None
        self._load_error = None

    def _ensure_loaded(self):
        if self._display_names is not None or self._load_error is not None:
            return
        try:
            results_lib = load_results_lib(self.config.analysis_dir)
            naming = load_trainer_naming(self.config.analysis_dir)
            trainer_data_by_label = results_lib.load_trainer_data(results_dir=self.config.results_dir)
            self._display_names = {
                label: naming.resolve_display_name(label, trainer_data_by_label)
                for label in trainer_data_by_label
            }
        except (OSError, ValueError) as exc:
            self._load_error = exc
            self._display_names = {}

    def display_name(self, label):
        self._ensure_loaded()
        if not label:
            return label
        return self._display_names.get(label, label)
