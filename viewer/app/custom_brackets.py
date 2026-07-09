"""User-authored brackets, persisted alongside the curated ones in
bracket_seeds.py but kept in a separate, gitignored JSON file instead of
being written into that source module -- bracket_seeds.py stays exclusively
hand-curated/source-controlled, custom brackets are local user data. Each
entry has the same shape as a bracket_seeds.BRACKETS entry:
{"name": str, "format": str, "seeds": [16 "TYPE:Name" labels]}, so
bracket_tab.py can merge the two lists and treat every entry identically
once loaded.
"""
import json
import os

FILENAME = "custom_brackets.json"


def custom_brackets_path(config):
    return os.path.join(config.repo_root, "viewer", FILENAME)


def load_custom_brackets(config):
    path = custom_brackets_path(config)
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return []
    if not isinstance(data, list):
        return []
    return data


def save_custom_brackets(config, brackets):
    path = custom_brackets_path(config)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp_path = path + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(brackets, f, indent=2)
    os.replace(tmp_path, path)
