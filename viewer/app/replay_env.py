"""Trainer label parsing + ELO_REPLAY_*/ELO_WATCH_* env-var building.

Mirrors scripts/save_replay.ps1's Set-ReplayTrainerEnv exactly, so a
TYPE:Name / TYPE:Name#version label pulled straight out of
results/*.jsonl works here unchanged. Pure functions, no Qt/process
dependency, so this is unit-testable on its own.
"""
import re

TRAINER_LABEL_RE = re.compile(r"^(?P<type>[^:#]+):(?P<name>[^#]+)(#(?P<version>\d+))?$")


class InvalidTrainerLabel(ValueError):
    pass


def parse_trainer_label(label):
    match = TRAINER_LABEL_RE.match(label)
    if not match:
        raise InvalidTrainerLabel(
            f"Trainer label {label!r} isn't in TYPE:Name or TYPE:Name#version form."
        )
    return {
        "type": match.group("type"),
        "name": match.group("name"),
        "version": match.group("version") or "0",
    }


def build_env(
    trainer1_label,
    trainer2_label,
    seed,
    battle_format="singles",
    output_name=None,
    backdrop=None,
):
    """Build the ELO_REPLAY_* env-var dict for one save_replay-equivalent
    (always headless) run.

    battle_format takes the same "singles"/"doubles" values as the results
    jsonl's "format" field; ELO_REPLAY_FORMAT itself uses the engine's
    "single"/"double" values, same translation save_replay.ps1 does.

    backdrop names a Graphics/Battlebacks/<name>_bg file to force instead of
    the "indoor1" default. Side-swapping is a UI-level concern (the caller
    just swaps which label it passes as trainer1_label/trainer2_label --
    confirmed empirically that this only mirrors the result/rounds, not the
    simulated battle), so there's no separate env var for it.
    """
    t1 = parse_trainer_label(trainer1_label)
    t2 = parse_trainer_label(trainer2_label)

    env = {
        "ELO_TOURNAMENT": "1",
        "ELO_SAVE_REPLAY": "1",
        "ELO_REPLAY_FORMAT": "double" if battle_format == "doubles" else "single",
        "ELO_REPLAY_SEED": str(seed),
        "ELO_REPLAY_T1_TYPE": t1["type"],
        "ELO_REPLAY_T1_NAME": t1["name"],
        "ELO_REPLAY_T1_VERSION": t1["version"],
        "ELO_REPLAY_T2_TYPE": t2["type"],
        "ELO_REPLAY_T2_NAME": t2["name"],
        "ELO_REPLAY_T2_VERSION": t2["version"],
    }
    if output_name:
        env["ELO_REPLAY_NAME"] = output_name
    if backdrop:
        env["ELO_REPLAY_BACKDROP"] = backdrop
    return env


def build_watch_env(
    replay_name,
    battlescene=None,
    textspeed=None,
    transitions=None,
    bgmvolume=None,
    mevolume=None,
    sevolume=None,
    bgm=None,
):
    """Build the ELO_WATCH_* env-var dict for watching a .dat already
    staged into vendor_dir/VSRecorder/ELOReplay/<replay_name>.dat via
    playRecordedBattle.

    battlescene/textspeed/transitions map straight onto $Options'
    battlescene/textspeed/battle_transitions int values; bgmvolume/mevolume/
    sevolume map onto $Options' bgmvolume/mevolume/sevolume (0-100, same
    scale as the in-game volume sliders -- 0 is an effective mute). All of
    these are applied in-memory only by the engine (never persisted to
    Options.dat); leave unset to use whatever the game's own settings
    already are.

    bgm names an Audio/BGM/<name> track (extension-less, e.g. "Battle wild")
    to force via pbSetNextBattleBGM instead of whatever the engine would
    normally derive from the recorded opponent -- the replay itself never
    stores BGM data, so this is watch-time-only, unlike backdrop/side-swap
    which are baked in at record time.
    """
    env = {
        "ELO_TOURNAMENT": "1",
        "ELO_WATCH_REPLAY_NAME": replay_name,
    }
    if battlescene is not None:
        env["ELO_WATCH_BATTLESCENE"] = str(battlescene)
    if textspeed is not None:
        env["ELO_WATCH_TEXTSPEED"] = str(textspeed)
    if transitions is not None:
        env["ELO_WATCH_TRANSITIONS"] = str(transitions)
    if bgmvolume is not None:
        env["ELO_WATCH_BGMVOLUME"] = str(bgmvolume)
    if mevolume is not None:
        env["ELO_WATCH_MEVOLUME"] = str(mevolume)
    if sevolume is not None:
        env["ELO_WATCH_SEVOLUME"] = str(sevolume)
    if bgm:
        env["ELO_WATCH_BGM"] = bgm
    return env
