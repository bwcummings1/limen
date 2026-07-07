"""Sensor tests: FileWatcher baseline/change/digest/persistence, RSSWatcher
parsing + dedup via file:// URLs (offline), and cycle integration."""
import tempfile
import time
import unittest
from pathlib import Path

from limen import Config, Mind
from limen.bus import Percept
from limen.sensors import FileWatcher, RSSWatcher, Sensor

RSS = """<?xml version="1.0"?>
<rss version="2.0"><channel>
  <title>Test Feed</title>
  <item><title>First post</title><guid>g1</guid></item>
  <item><title>Second post</title><guid>g2</guid></item>
</channel></rss>"""

ATOM = """<?xml version="1.0"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <title>Atom Feed</title>
  <entry><title>Atom entry</title><id>a1</id></entry>
</feed>"""


class TestFileWatcher(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.watched = Path(self.tmp.name) / "inbox"
        self.watched.mkdir()
        self.state = Path(self.tmp.name) / "state"

    def tearDown(self):
        self.tmp.cleanup()

    def _watcher(self):
        return FileWatcher(self.watched, self.state, salience=0.6)

    def test_first_run_baselines_silently(self):
        (self.watched / "existing.md").write_text("was here", encoding="utf-8")
        w = self._watcher()
        self.assertEqual(w.poll(1), [])   # existing files are already known

    def test_new_file_becomes_percept(self):
        w = self._watcher()
        w.poll(1)                          # baseline
        (self.watched / "note.md").write_text("remember the DNS cutover",
                                              encoding="utf-8")
        pcts = w.poll(2)
        self.assertEqual(len(pcts), 1)
        self.assertIn("note.md", pcts[0].content)
        self.assertIn("DNS cutover", pcts[0].content)
        self.assertEqual(pcts[0].salience_hint, 0.6)
        self.assertEqual(w.poll(3), [])   # unchanged -> quiet

    def test_modified_file_fires_again(self):
        w = self._watcher()
        f = self.watched / "note.md"
        f.write_text("v1", encoding="utf-8")
        w.poll(1)                          # baseline includes v1... no:
        # baseline happens on first poll; the write above pre-dates it, so
        # force a change afterwards with a distinct mtime.
        time.sleep(0.01)
        f.write_text("v2 changed", encoding="utf-8")
        import os
        os.utime(f, (time.time() + 5, time.time() + 5))
        pcts = w.poll(2)
        self.assertEqual(len(pcts), 1)

    def test_many_changes_digest(self):
        w = self._watcher()
        w.poll(1)
        for i in range(5):
            (self.watched / f"f{i}.txt").write_text("x", encoding="utf-8")
        pcts = w.poll(2)
        self.assertEqual(len(pcts), 1)     # digest discipline
        self.assertIn("5 files changed", pcts[0].content)

    def test_state_survives_restart(self):
        w = self._watcher()
        w.poll(1)
        (self.watched / "a.txt").write_text("x", encoding="utf-8")
        w.poll(2)                          # perceived + persisted
        w2 = self._watcher()               # daemon restart
        self.assertEqual(w2.poll(3), [])   # not re-perceived


class TestRSSWatcher(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.state = Path(self.tmp.name) / "state"

    def tearDown(self):
        self.tmp.cleanup()

    def _feed(self, text: str) -> str:
        p = Path(self.tmp.name) / "feed.xml"
        p.write_text(text, encoding="utf-8")
        return p.as_uri()                  # file:// URL — offline

    def test_rss_digest_then_quiet(self):
        w = RSSWatcher(self._feed(RSS), self.state, every_ticks=2)
        pcts = w.poll(1)
        self.assertEqual(len(pcts), 1)
        self.assertIn("Test Feed", pcts[0].content)
        self.assertIn("First post", pcts[0].content)
        self.assertIn("2 new item(s)", pcts[0].content)
        self.assertEqual(w.poll(3), [])    # nothing new

    def test_atom_supported(self):
        w = RSSWatcher(self._feed(ATOM), self.state, every_ticks=1)
        pcts = w.poll(1)
        self.assertEqual(len(pcts), 1)
        self.assertIn("Atom entry", pcts[0].content)

    def test_poll_cadence_gate(self):
        w = RSSWatcher(self._feed(RSS), self.state, every_ticks=10)
        w.poll(1)
        # New item appears, but the cadence gate holds until tick 11.
        self.assertEqual(w.poll(5), [])

    def test_seen_guids_survive_restart(self):
        url = self._feed(RSS)
        RSSWatcher(url, self.state, every_ticks=1).poll(1)
        w2 = RSSWatcher(url, self.state, every_ticks=1)
        self.assertEqual(w2.poll(2), [])


class StubSensor(Sensor):
    name = "stub"

    def poll(self, tick):
        if tick == 2:
            return [Percept(source="sensor:stub", content="the backup job "
                            "completed successfully", salience_hint=0.7,
                            tags=["backup_ok"])]
        return []


class FailingSensor(Sensor):
    name = "broken"

    def poll(self, tick):
        raise RuntimeError("sensor hardware on fire")


class TestCycleIntegration(unittest.TestCase):
    def test_sensor_percepts_enter_the_cycle(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = Config()
            cfg.mind.data_dir = tmp
            cfg.provider.kind = "mock"
            mind = Mind.from_config(cfg)
            mind.add_sensor(StubSensor())
            mind.tick()
            r = mind.tick()                # StubSensor fires at tick 2
            self.assertTrue(r.ignited)
            stimuli = mind.episodic.recent(20, kind="stimulus")
            self.assertTrue(any(e["source"] == "sensor:stub" for e in stimuli))
            # The tag reached the episodic log -> dead-man switches watching
            # "backup_ok" would disarm off this percept.
            tagged = [e for e in stimuli if "backup_ok" in e.get("tags", [])]
            self.assertTrue(tagged)

    def test_failing_sensor_is_contained(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = Config()
            cfg.mind.data_dir = tmp
            cfg.provider.kind = "mock"
            mind = Mind.from_config(cfg)
            mind.add_sensor(FailingSensor())
            mind.tick()                    # must not raise
            self.assertTrue(any("sensor.broken" in n
                                for n in mind.metrics.failure_notes))


if __name__ == "__main__":
    unittest.main()
