import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from bambu_ntfy import StateTracker, make_notification, publish_ntfy, read_config


class TrackerTests(unittest.TestCase):
    def message(self, state, **extras):
        return {"print": {"gcode_state": state, **extras}}

    def test_idle_start_finish_new_job(self):
        tracker = StateTracker()
        self.assertIsNone(tracker.apply(self.message("IDLE")))
        self.assertEqual(tracker.apply(self.message("RUNNING", task_id="10")), "started")
        self.assertIsNone(tracker.apply(self.message("RUNNING", task_id="10")))
        self.assertEqual(tracker.apply(self.message("FINISH", task_id="10")), "finished")
        self.assertIsNone(tracker.apply(self.message("IDLE")))
        self.assertEqual(tracker.apply(self.message("RUNNING", task_id="11")), "started")

    def test_pause_resume_failure(self):
        tracker = StateTracker(state="RUNNING", job="10")
        self.assertEqual(tracker.apply(self.message("PAUSE")), "paused")
        self.assertEqual(tracker.apply(self.message("RUNNING")), "resumed")
        self.assertEqual(tracker.apply(self.message("FAILED")), "failed")

    def test_startup_does_not_claim_new_job(self):
        tracker = StateTracker()
        self.assertIsNone(tracker.apply(self.message("RUNNING")))
        self.assertIsNone(tracker.apply(self.message("RUNNING")))
        self.assertEqual(tracker.apply(self.message("FINISH")), "finished")

    def test_optional_notify_initial_state(self):
        tracker = StateTracker()
        self.assertEqual(tracker.apply(self.message("RUNNING"), True), "started")

    def test_partial_reports_ignored(self):
        tracker = StateTracker(state="RUNNING", job="10")
        self.assertIsNone(tracker.apply({"print": {"mc_percent": 50}}))
        self.assertIsNone(tracker.apply({"system": {"state": "IDLE"}}))
        self.assertIsNone(tracker.apply(self.message("UNKNOWN")))
        self.assertEqual(tracker.state, "RUNNING")

    def test_new_job_while_running(self):
        tracker = StateTracker(state="RUNNING", job="10")
        self.assertEqual(tracker.apply(self.message("RUNNING", task_id="11")), "started")

    def test_persistence(self):
        with tempfile.TemporaryDirectory() as tmp:
            file = Path(tmp) / "state.json"
            StateTracker(state="PAUSE", job="23").save(file)
            loaded = StateTracker.from_file(file)
            self.assertEqual(loaded.state, "PAUSE")
            self.assertEqual(loaded.job, "23")
            self.assertEqual(loaded.apply(self.message("RUNNING")), "resumed")

    def test_missing_state_file(self):
        self.assertIsNone(StateTracker.from_file(Path("missing-state.json")).state)


class NotificationTests(unittest.TestCase):
    def test_notice(self):
        notice = make_notification("finished", "P1S", "demo.3mf")
        self.assertIn("demo.3mf", notice["message"])
        self.assertEqual(notice["priority"], 3)

    @patch("bambu_ntfy.urllib.request.urlopen")
    def test_json_ntfy_handles_japanese(self, urlopen):
        urlopen.return_value.__enter__.return_value.status = 200
        cfg = {"ntfy": {"server": "https://ntfy.sh", "topic": "random-topic-123"}}
        publish_ntfy(cfg, make_notification("finished", "P1S"))
        request = urlopen.call_args.args[0]
        self.assertEqual(request.full_url, "https://ntfy.sh/")
        data = json.loads(request.data.decode("utf-8"))
        self.assertEqual(data["topic"], "random-topic-123")
        self.assertIn("完了", data["title"])

    def test_config_validation(self):
        cfg = {"printer": {"host": "192.168.1.2", "serial": "TEST123",
                           "access_code": "example"},
               "ntfy": {"server": "https://ntfy.sh", "topic": "random-topic"}}
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.json"
            path.write_text(json.dumps(cfg), encoding="utf-8")
            self.assertEqual(read_config(path)["options"], {})
            cfg["ntfy"]["server"] = "http://ntfy.sh"
            path.write_text(json.dumps(cfg), encoding="utf-8")
            with self.assertRaises(ValueError):
                read_config(path)


if __name__ == "__main__":
    unittest.main()
