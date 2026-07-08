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

# sample bracket - not based on genuine results, just for testing
BRACKET_SEEDS = { "singles": ["SPIRITGUARDIAN4:Brigitte#1",
                 "LEADER_Bence:Bence#3",
                 "MASKEDVILLAIN2:Teal#23",
                 "COOLTRAINER_M7:X#1",
                 "TOURISTM:Chus",
                 "LEADER_Eko:Eko#3",
                 "FORMERCHAMP_Ansel:Ansel",
                 "LEADER_Samorn:Samorn#3",
                 "MASKEDVILLAIN2:Teal#15",
                 "SPIRITGUARDIAN3:Preeti#1",
                 "TRAINER_Zain:Zain#3",
                 "MASKEDVILLAIN2:Teal#21",
                 "NIGHTMAREQUEEN_Elise:Elise",
                 "MASKEDVILLAIN2_DOUBLE:Teal#13",
                 "TAPU_KOKO:Tapu Koko#1",
                 "POKEMONTRAINER_Vanya:Vanya#2"]}
