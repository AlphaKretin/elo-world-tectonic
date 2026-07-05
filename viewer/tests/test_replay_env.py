import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import replay_env


class ParseTrainerLabelTests(unittest.TestCase):
    def test_label_without_version(self):
        # from results/archive_.../elo_results_singles.jsonl
        result = replay_env.parse_trainer_label("BATTLEGIRL:Tester")
        self.assertEqual(result, {"type": "BATTLEGIRL", "name": "Tester", "version": "0"})

    def test_label_with_version(self):
        # from official_results/compare_doubles_doubles_cursed_excluded.csv
        result = replay_env.parse_trainer_label("MASKEDVILLAIN2:Teal#16")
        self.assertEqual(result, {"type": "MASKEDVILLAIN2", "name": "Teal", "version": "16"})

    def test_label_with_space_in_name(self):
        result = replay_env.parse_trainer_label("ROLLERSKATER_M:Lane Tester")
        self.assertEqual(result, {"type": "ROLLERSKATER_M", "name": "Lane Tester", "version": "0"})

    def test_invalid_label_raises(self):
        with self.assertRaises(replay_env.InvalidTrainerLabel):
            replay_env.parse_trainer_label("not-a-valid-label")


class BuildEnvTests(unittest.TestCase):
    def test_minimal_singles_headless(self):
        env = replay_env.build_env("BATTLEGIRL:Tester", "YOUNGSTER:Joey", 343599764, battle_format="singles")
        self.assertEqual(env["ELO_TOURNAMENT"], "1")
        self.assertEqual(env["ELO_SAVE_REPLAY"], "1")
        self.assertEqual(env["ELO_REPLAY_FORMAT"], "single")
        self.assertEqual(env["ELO_REPLAY_SEED"], "343599764")
        self.assertEqual(env["ELO_REPLAY_T1_TYPE"], "BATTLEGIRL")
        self.assertEqual(env["ELO_REPLAY_T1_NAME"], "Tester")
        self.assertEqual(env["ELO_REPLAY_T1_VERSION"], "0")
        self.assertEqual(env["ELO_REPLAY_T2_TYPE"], "YOUNGSTER")
        self.assertEqual(env["ELO_REPLAY_T2_NAME"], "Joey")
        self.assertEqual(env["ELO_REPLAY_T2_VERSION"], "0")
        self.assertNotIn("ELO_REPLAY_NAME", env)

    def test_doubles_maps_to_double(self):
        env = replay_env.build_env("MASKEDVILLAIN2:Teal#16", "MASKEDVILLAIN2_DOUBLE:Teal#12", 1, battle_format="doubles")
        self.assertEqual(env["ELO_REPLAY_FORMAT"], "double")
        self.assertEqual(env["ELO_REPLAY_T1_VERSION"], "16")
        self.assertEqual(env["ELO_REPLAY_T2_VERSION"], "12")

    def test_output_name(self):
        env = replay_env.build_env("BATTLEGIRL:Tester", "YOUNGSTER:Joey", 1, output_name="my_replay")
        self.assertEqual(env["ELO_REPLAY_NAME"], "my_replay")

    def test_no_backdrop_by_default(self):
        env = replay_env.build_env("BATTLEGIRL:Tester", "YOUNGSTER:Joey", 1)
        self.assertNotIn("ELO_REPLAY_BACKDROP", env)

    def test_backdrop_override(self):
        env = replay_env.build_env("BATTLEGIRL:Tester", "YOUNGSTER:Joey", 1, backdrop="cave1")
        self.assertEqual(env["ELO_REPLAY_BACKDROP"], "cave1")


class BuildWatchEnvTests(unittest.TestCase):
    def test_minimal(self):
        env = replay_env.build_watch_env("_WatchStaging")
        self.assertEqual(env["ELO_TOURNAMENT"], "1")
        self.assertEqual(env["ELO_WATCH_REPLAY_NAME"], "_WatchStaging")
        self.assertNotIn("ELO_WATCH_BATTLESCENE", env)
        self.assertNotIn("ELO_WATCH_TEXTSPEED", env)
        self.assertNotIn("ELO_WATCH_TRANSITIONS", env)

    def test_display_overrides(self):
        env = replay_env.build_watch_env("_WatchStaging", battlescene=0, textspeed=4, transitions=1)
        self.assertEqual(env["ELO_WATCH_BATTLESCENE"], "0")
        self.assertEqual(env["ELO_WATCH_TEXTSPEED"], "4")
        self.assertEqual(env["ELO_WATCH_TRANSITIONS"], "1")

    def test_volume_overrides(self):
        env = replay_env.build_watch_env("_WatchStaging", bgmvolume=0, mevolume=0, sevolume=50)
        self.assertEqual(env["ELO_WATCH_BGMVOLUME"], "0")
        self.assertEqual(env["ELO_WATCH_MEVOLUME"], "0")
        self.assertEqual(env["ELO_WATCH_SEVOLUME"], "50")

    def test_no_volume_overrides_by_default(self):
        env = replay_env.build_watch_env("_WatchStaging")
        self.assertNotIn("ELO_WATCH_BGMVOLUME", env)
        self.assertNotIn("ELO_WATCH_MEVOLUME", env)
        self.assertNotIn("ELO_WATCH_SEVOLUME", env)

    def test_bgm_override(self):
        env = replay_env.build_watch_env("_WatchStaging", bgm="Battle wild")
        self.assertEqual(env["ELO_WATCH_BGM"], "Battle wild")

    def test_no_bgm_by_default(self):
        env = replay_env.build_watch_env("_WatchStaging")
        self.assertNotIn("ELO_WATCH_BGM", env)


if __name__ == "__main__":
    unittest.main()
