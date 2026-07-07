"""Hand-curated top-16 bracket seedings, one list per format key (battle_type
[+ "_uncursed"][+ "_<filter>"], matching results_lib.filter_suffix()'s
ordering), each exactly 16 trainer labels ("TYPE:Name" or "TYPE:Name#version")
in seed order -- index 0 is seed 1, index 15 is seed 16.

Deliberately not derived from ratings_<fmt>.json: a straight top-16-by-rating
pull is often an uninteresting bracket (one dominant trainer, or duplicate
trainers filling multiple slots), so who's actually seeded is a manual
editorial call, not a computation. A format with no entry here just has no
curated bracket yet -- see bracket_tab.py's handling of a missing key.
"""

BRACKET_SEEDS = {}
