import tempfile
import unittest
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from veille.config import DEFAULTS
from veille.pipeline import due_edition, edition_to_send, window_start
from veille.state import AlreadyRunning, State, single_instance

TZ = timezone(timedelta(hours=2))
MONDAY = date(2026, 10, 19)


def at(day: date, hour: int, minute: int = 0) -> datetime:
    return datetime(day.year, day.month, day.day, hour, minute, tzinfo=TZ)


class EditionTest(unittest.TestCase):
    def test_due_edition(self):
        self.assertEqual(due_edition(at(MONDAY, 20, 0), "20:00"), MONDAY)
        self.assertEqual(due_edition(at(MONDAY, 19, 59), "20:00"), MONDAY - timedelta(days=1))

    def test_normal_evening(self):
        due, _ = edition_to_send(at(MONDAY, 20, 2), "20:00", MONDAY - timedelta(days=1), True)
        self.assertEqual(due, MONDAY)

    def test_already_sent(self):
        due, reason = edition_to_send(at(MONDAY, 22), "20:00", MONDAY, True)
        self.assertIsNone(due)
        self.assertIn("déjà", reason)

    def test_pc_off_at_eight_catch_up_next_morning(self):
        tuesday = MONDAY + timedelta(days=1)
        due, reason = edition_to_send(at(tuesday, 8, 30), "20:00", MONDAY - timedelta(days=1), True)
        self.assertEqual(due, MONDAY)
        self.assertIn("Rattrapage", reason)
        # Le soir même, l'édition du mardi part normalement.
        due, _ = edition_to_send(at(tuesday, 20, 0), "20:00", MONDAY, True)
        self.assertEqual(due, tuesday)

    def test_catch_up_disabled(self):
        due, _ = edition_to_send(at(MONDAY + timedelta(days=1), 8), "20:00", MONDAY - timedelta(days=1), False)
        self.assertIsNone(due)

    def test_fresh_install_waits_for_first_send_time(self):
        due, reason = edition_to_send(at(MONDAY, 10), "20:00", None, True)
        self.assertIsNone(due)
        self.assertIn("Première", reason)
        due, _ = edition_to_send(at(MONDAY, 20, 5), "20:00", None, True)
        self.assertEqual(due, MONDAY)

    def test_logon_before_send_time_does_nothing_if_yesterday_sent(self):
        due, _ = edition_to_send(at(MONDAY, 9), "20:00", MONDAY - timedelta(days=1), True)
        self.assertIsNone(due)


class WindowTest(unittest.TestCase):
    def test_window_is_since_last_send_within_bounds(self):
        now = at(MONDAY, 20)
        self.assertEqual(window_start(None, now, DEFAULTS), now - timedelta(hours=24))
        self.assertEqual(window_start(now - timedelta(hours=3), now, DEFAULTS), now - timedelta(hours=24))
        self.assertEqual(window_start(now - timedelta(days=3), now, DEFAULTS), now - timedelta(days=3))
        self.assertEqual(window_start(now - timedelta(days=30), now, DEFAULTS), now - timedelta(hours=168))


class StateTest(unittest.TestCase):
    def test_round_trip_and_pruning(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "etat.json"
            state = State(path)
            old = at(MONDAY - timedelta(days=20), 20)
            state.record_edition(old.date(), old, ["ancien"], [frozenset({"vieux", "sujet"})])
            now = at(MONDAY, 20)
            state.record_edition(MONDAY, now, ["k1", "k2"], [frozenset({"openai", "gpt"})])
            state.save()
            loaded = State(path)
            self.assertEqual(loaded.last_edition, MONDAY)
            self.assertEqual(loaded.last_sent_at, now)
            self.assertEqual(loaded.seen_keys(), {"k1", "k2"})  # « ancien » a plus de 14 jours
            self.assertEqual(loaded.recent_tokens(), [frozenset({"openai", "gpt"})])

    def test_corrupted_state_starts_fresh(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "etat.json"
            path.write_text("{pas du json", encoding="utf-8")
            with self.assertLogs("veille.state", "WARNING"):
                self.assertIsNone(State(path).last_edition)

    def test_single_instance(self):
        with tempfile.TemporaryDirectory() as tmp:
            lock = Path(tmp) / "x.lock"
            with single_instance(lock):
                with self.assertRaises(AlreadyRunning):
                    with single_instance(lock):
                        pass
            self.assertFalse(lock.exists())


if __name__ == "__main__":
    unittest.main()
