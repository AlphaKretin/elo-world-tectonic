"""Raw game-asset filename -> human-readable display name, for the
Backdrop/BGM dropdowns in game_assets.py. A raw name's presence as a dict key
IS the whitelist (game_assets filters dynamically-listed disk files down to
whatever's in these dicts) -- so trimming the selection is just deleting an
entry, and adding a display name for a not-yet-reviewed asset is editing its
value in place.
"""

BGM_NAMES = {
    "DPPTTrainer": "Battle! Trainer",
    "Battle wild": "Battle! Wild Pokemon",
    "Battle avatar": "Battle! Avatar",
    "Battle vanya": "Battle! Pokemon Trainer Vanya",
    "Battle Gym Leader 1": "Battle! Gym Leader",
    "Battle Gym Leader 2": "Battle! Cursed Gym Leader",
    "Battle pro": "Battle! Pro Trainer",
    "Battle avatar legendary": "Battle! Legendary Avatar",
    "Battle alessa": "Battle! Alessa",
    "Battle keoni": "Battle! Keoni",
    "Battle imogene": "Battle! Imogene",
    "Battle eifion": "Battle! Eifion",
    "Battle candy": "Battle! Candy",
    "Battle zain": "Battle! Your Brother Zain",
    "Tectonic_Yezera_Battle_Theme": "Battle! Yezera",
    "Battle villain": "Battle! Masked Villain",
    "Battle sang": "Battle! Sang",
    "Battle tournament": "Battle! Makyan Championships",
    "Battle tournament final": "Battle! Makyan Championships Finals",
    "Tectonic_Floral_Rest": "Floral Rest (Carnation Graves)",
    "Battle skyler": "Battle! Skyler",
    "Battle tamarind": "Battle! Professor Tamarind",
    "Tectonic_Epitaph_of_the_Demiurge": "Epitaph of the Demiurge (Battle! Regi)",
    "Battle another": "Battle! Another Possible Trainer",
    "Battle champion iris": "Battle! Former Champion",
    "Battle nightmare queen": "Battle! Nightmare Queen Elise",
    "Battle Nora": "Battle! Seeker Nora",
    "TrainerBattleKanto": "Battle! Wild Pokemon (Tri Island)",
    "Battle lainie": "Battle! Archfriend Lainie",
    "Battle lainie ultra": "Battle! Ultra Lainie",
    "BWELITE4": "Battle! Monument Trainer",
    "Battle vanya final": "Battle! Pokemon Master Vanya",
}

# Base environments only -- time-of-day (_eve/_night) suffixes are handled
# as a separate Day/Evening/Night selector (see game_assets.resolve_backdrop),
# not as their own dict entries, since every environment that has them
# (city/field/forest/rocky/sand/snow/water) would otherwise need three
# near-duplicate rows here.
BACKDROP_NAMES = {
    "cave1": "Cave (1)",
    "cave2": "Cave (2)",
    "cave3": "Cave (3)",
    "city": "City",
    "field": "Field",
    "forest": "Forest",
    "indoor1": "Indoor (1)",
    "indoor2": "Indoor (2)",
    "indoor3": "Indoor (3)",
    "rocky": "Rocky",
    "sand": "Sand",
    "snow": "Snow",
    "water": "Surfing",
    "distortion": "Catacombs",
    "wcave": "White Cave",
    "elite3": "Gym (Casaba Villa)",
    "elite8": "Gym (Novo Town)",
    "elite2": "Gym (Luxtech Campus)",
    "elite6": "Gym (Velenz)",
    "elite7": "Gym (Prizca West)",
    "elite5": "Gym (Prizca East)",
    "champion2": "Gym (Sweetrock Harbour)",
    "champion1": "Gym (Team Chasm HQ)",
    "elite1": "Battle Monument",
}
