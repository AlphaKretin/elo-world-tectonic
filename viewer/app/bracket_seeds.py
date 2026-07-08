"""Hand-curated top-16 bracket seedings. Brackets are an arbitrary list, not
one-per-format: each entry has a display "name", a "format" (one of the raw
match pools format_selector.format_key() produces -- "singles",
"singles_uncursed", "doubles", "doubles_uncursed" -- which drives results
lookup/replay naming exactly like Browse/Generate/Watch's format pickers),
and a "seeds" list of exactly 16 trainer labels ("TYPE:Name" or
"TYPE:Name#version") in seed order -- index 0 is seed 1, index 15 is seed 16.

Deliberately not derived from ratings_<fmt>.json: a straight top-16-by-rating
pull is often an uninteresting bracket (one dominant trainer, or duplicate
trainers filling multiple slots), so who's actually seeded is a manual
editorial call, not a computation. Multiple brackets can share the same
format (e.g. a "developer_only" bracket alongside the main one) -- format
here is just which raw match pool to resolve results against, not a unique
key. "name" is what's shown in bracket_tab.py's bracket picker and must be
unique across entries (it's also the QSettings persistence key, via
ui_settings.bind_combo's findText lookup).
"""

BRACKETS = [
    {
        "name": "Singles",
        "format": "singles",
        "seeds": [
            "SPIRITGUARDIAN4:Brigitte#1",
            "POKEMONTRAINER_Yezera:Yezera#9",
            "TOURISTM:Chus",
            "POKEMONCHAMPION_Vanya:Vanya",
            "LEADER_Bence:Bence#3",
            "COOLTRAINER_M7:X#1",
            "MASKEDVILLAIN2:Teal#23",
            "FORMERCHAMP_Elise:Elise#2",
            "HEXMANIAC:Errata",
            "LEADER_Eko:Eko#3",
            "FORMERCHAMP_Ansel:Ansel",
            "LEADER_Samorn:Samorn#3",
            "SPIRITGUARDIAN3:Preeti#1",
            "MASKEDVILLAIN2:Teal#21",
            "MASKEDVILLAIN2:Teal#15",
            "TRAINER_Zain:Zain#3",
        ],
    },
    {
        "name": "Singles (Uncursed)",
        "format": "singles_uncursed",
        "seeds": [
            "POKEMONCHAMPION_Vanya:Vanya",
            "TOURISTM:Chus",
            "HEXMANIAC:Errata",
            "FORMERCHAMP_Ansel:Ansel",
            "SPIRITGUARDIAN3:Preeti#1",
            "MASKEDVILLAIN:Crimson#23",
            "SHADOWMAVIS:Mavis#1",
            "TRAINER_Alessa:Alessa#6",
            "FORMERCHAMP_Scilla:Scilla",
            "LADY2:Eseria",
            "FORMERCHAMP_Elise:Elise",
            "ODDISH:Oddium",
            "LEADER_Samorn:Samorn#2",
            "TRAINER_Zain:Zain#2",
            "COOLTRAINER_M7:X",
            "LEADER_Eko:Eko#2",
        ],
    },
    {
        "name": "Developers",
        "format": "singles",
        "seeds": [
            "HEXMANIAC:Errata",
            "TOURISTM:Chus",
            "LADY2:Eseria",
            "WAITRESS3:Destiny",
            "FAIRYTALEGIRL:Emmi",
            "DELINQUENT:Lilypad",
            "ODDISH:Oddium",
            "TOURISTM:Azeler",
            "KATY:Manycrows",
            "SCIENTIST_F:LunaFlare",
            "GUITARIST3:Envy",
            "VETERANM_2:Kirbae",
            "WAITRESS2:Fanfan",
            "KILLU:Killu",
            "POKEMONRANGER_M:Zufaix",
            "DRAGONTAMER_F:Zinnia",
        ],
    },
    {
        "name": "Doubles",
        "format": "doubles",
        "seeds": [
            "POKEMONTRAINER_Yezera:Yezera#9",
            "LEADER_Bence:Bence#3",
            "MASKEDVILLAIN2:Teal#23",
            "POKEMONTRAINER_Vanya:Vanya#2",
            "FORMERCHAMP_Elise:Elise#2",
            "TOURISTM:Azeler",
            "SPIRITGUARDIAN4:Brigitte#1",
            "TRAINER_Sang:Sang#5",
            "MASKEDVILLAIN2_DOUBLE:Teal#13",
            "COOLTRAINER_M7:X#1",
            "MASKEDVILLAIN2:Teal#17",
            "SPIRITGUARDIAN3:Preeti#1",
            "ODDISH:Oddium",
            "LEADER_Eko:Eko#3",
            "TOURISTM:Chus",
            "VETERANM_2:Kirbae",
        ],
    },
    {
        "name": "Doubles (Uncursed)",
        "format": "doubles_uncursed",
        "seeds": [
            "POKEMONTRAINER_Vanya:Vanya#2",
            "TOURISTM:Azeler",
            "ODDISH:Oddium",
            "POKEMONTRAINER_Yezera:Yezera#11",
            "MASKEDVILLAIN:Crimson#23",
            "TOURISTM:Chus",
            "SHADOWMAVIS:Mavis#1",
            "VETERANM_2:Kirbae",
            "SPIRITGUARDIAN3:Preeti",
            "WAITRESS3:Destiny",
            "HEXMANIAC:Errata",
            "ULTRALAINIE:Lainie",
            "SCIENTIST_F:LunaFlare",
            "TRAINER_Alessa:Alessa#6",
            "NIGHTMAREQUEEN_Elise:Elise",
            "PUNKM:ValourDyke",
        ],
    },
    {
        "name": "Developers (Doubles)",
        "format": "doubles",
        "seeds": [
            "TOURISTM:Azeler",
            "HEXMANIAC:Errata",
            "ODDISH:Oddium",
            "VETERANM_2:Kirbae",
            "TOURISTM:Chus",
            "SCIENTIST_F:LunaFlare",
            "KATY:Manycrows",
            "WAITRESS3:Destiny",
            "FAIRYTALEGIRL:Emmi",
            "KILLU:Killu",
            "PUNKM:ValourDyke",
            "POKEMONRANGER_M:Zufaix",
            "WAITRESS2:Fanfan",
            "LADY2:Eseria",
            "DRAGONTAMER_F:Bella",
            "HIKER:Valrex",
        ],
    },
]
