"""Trainer label parsing + ELO_REPLAY_* env-var building.

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


def build_env(trainer1_label, trainer2_label, seed, battle_format="singles", output_name=None):
    """Build the ELO_REPLAY_* env-var dict for one save_replay-equivalent
    (always headless) run.

    battle_format takes the same "singles"/"doubles" values as the results
    jsonl's "format" field; ELO_REPLAY_FORMAT itself uses the engine's
    "single"/"double" values, same translation save_replay.ps1 does.
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
    return env
