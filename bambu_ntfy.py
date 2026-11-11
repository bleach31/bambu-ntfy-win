"""Bambu P1S LAN MQTT -> ntfy. Python 3.10+, no Bambu cloud required."""
from __future__ import annotations

import argparse
import json
import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
import ssl
import sys
import time
import urllib.error
import urllib.request
from urllib.parse import urlsplit
from uuid import uuid4

LOG = logging.getLogger("bambu_ntfy")
STATES = {"IDLE", "PREPARE", "RUNNING", "PAUSE", "FINISH", "FAILED"}
EVENTS = {
    "started": ("印刷開始", "printer,rocket", 3),
    "resumed": ("印刷再開", "printer,arrow_forward", 3),
    "paused": ("印刷一時停止", "warning,printer", 4),
    "finished": ("印刷完了", "white_check_mark,printer", 3),
    "failed": ("印刷失敗", "rotating_light,printer", 5),
}


def read_config(path: Path) -> dict:
    try:
        cfg = json.loads(path.read_text(encoding="utf-8-sig"))
        printer, ntfy = cfg["printer"], cfg["ntfy"]
        for entry in ("host", "serial", "access_code"):
            if not isinstance(printer[entry], str) or not printer[entry].strip():
                raise ValueError(f"printer.{entry} must be a nonempty string")
        for entry in ("server", "topic"):
            if not isinstance(ntfy[entry], str) or not ntfy[entry].strip():
                raise ValueError(f"ntfy.{entry} must be a nonempty string")
        url = urlsplit(ntfy["server"])
        if url.scheme != "https" and not (
            url.scheme == "http" and url.hostname in ("127.0.0.1", "localhost", "::1")
        ):
            raise ValueError("ntfy.server must use HTTPS (HTTP allowed only for localhost)")
        if not url.netloc or url.username or url.password or url.query or url.fragment:
            raise ValueError("invalid ntfy.server URL")
        if any(ch in ntfy["topic"] for ch in "/?# \t\r\n"):
            raise ValueError("ntfy.topic cannot contain whitespace or URL separators")
        options = cfg.setdefault("options", {})
        if not isinstance(options, dict):
            raise ValueError("options must be an object")
        refresh = options.get("refresh_seconds", 180)
        if not isinstance(refresh, int) or isinstance(refresh, bool) or not 30 <= refresh <= 3600:
            raise ValueError("options.refresh_seconds must be 30..3600")
        return cfg
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
        raise ValueError(f"Invalid config {path}: {exc}") from exc


class StateTracker:
    """Observe partial printer reports and return a notification only on transitions."""

    def __init__(self, state: str | None = None, job: str | None = None):
        self.state = state
        self.job = job
        self.job_name = ""

    def apply(self, payload: dict, notify_initial: bool = False) -> str | None:
        report = payload.get("print")
        if not isinstance(report, dict):
            return None
        incoming = report.get("gcode_state")
        if not isinstance(incoming, str):
            return None
        new_state = incoming.upper()
        if new_state not in STATES:
            LOG.debug("Ignoring unknown printer state %r", incoming)
            return None

        name = report.get("subtask_name") or report.get("gcode_file")
        if isinstance(name, str) and name:
            self.job_name = name

        # Job IDs can be absent from incremental reports. Keep the last known ID.
        job = report.get("task_id") or report.get("subtask_id")
        new_job = str(job) if job is not None and str(job) != "0" else self.job
        different_job = bool(new_job and self.job and new_job != self.job)
        previous = self.state
        self.state = new_state
        self.job = new_job

        if previous is None and not notify_initial:
            return None
        if previous == new_state and not (new_state == "RUNNING" and different_job):
            return None
        if new_state == "RUNNING":
            return "resumed" if previous == "PAUSE" and not different_job else "started"
        if new_state == "PAUSE":
            return "paused"
        if new_state == "FINISH":
            return "finished"
        if new_state == "FAILED":
            return "failed"
        return None

    def as_dict(self) -> dict:
        return {"state": self.state, "job": self.job}

    @classmethod
    def from_file(cls, path: Path) -> StateTracker:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            state = data.get("state") if data.get("state") in STATES else None
            job = data.get("job")
            return cls(state, str(job) if job is not None else None)
        except (OSError, ValueError, TypeError, AttributeError):
            return cls()

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps(self.as_dict()), encoding="utf-8")
        os.replace(temporary, path)


def make_notification(event: str, printer: str, job_name: str = "") -> dict:
    title, tags, priority = EVENTS[event]
    message = f"{printer}: {title}"
    if job_name:
        message += f"\nファイル: {job_name}"
    return {"title": f"{printer} | {title}", "message": message,
            "tags": tags.split(","), "priority": priority}


def publish_ntfy(config: dict, notice: dict) -> None:
    target = config["ntfy"]
    body = json.dumps({"topic": target["topic"], **notice}, ensure_ascii=False).encode("utf-8")
    headers = {"Content-Type": "application/json; charset=utf-8"}
    if target.get("token"):
        headers["Authorization"] = f"Bearer {target['token']}"
    req = urllib.request.Request(target["server"].rstrip("/") + "/",
                                 data=body, headers=headers, method="POST")
    # One retry for transient errors. This call runs in the MQTT callback, so bound its duration.
    for attempt in range(2):
        try:
            with urllib.request.urlopen(req, timeout=8) as response:
                if not 200 <= response.status < 300:
                    raise RuntimeError(f"ntfy returned HTTP {response.status}")
            return
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            if attempt == 1:
                raise RuntimeError(f"ntfy delivery failed: {exc}") from exc
            time.sleep(1)


def configure_logging(base: Path) -> None:
    runtime = base / ".runtime"
    runtime.mkdir(parents=True, exist_ok=True)
    formatter = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    file_log = RotatingFileHandler(runtime / "bambu-ntfy.log", maxBytes=1_000_000,
                                   backupCount=3, encoding="utf-8")
    file_log.setFormatter(formatter)
    handlers: list[logging.Handler] = [file_log]
    if sys.stdout is not None:
        console = logging.StreamHandler(sys.stdout)
        console.setFormatter(formatter)
        handlers.append(console)
    logging.basicConfig(level=logging.INFO, handlers=handlers)


def monitor(cfg: dict, runtime: Path) -> None:
    # Import lazily so unit tests and --test-notification only need the stdlib.
    import paho.mqtt.client as mqtt

    printer = cfg["printer"]
    options = cfg["options"]
    name = str(options.get("printer_name", "P1S"))
    tracker_path = runtime / "state.json"
    tracker = StateTracker.from_file(tracker_path)
    report_topic = f"device/{printer['serial']}/report"
    request_topic = f"device/{printer['serial']}/request"

    mqtt_client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2,
                              client_id=f"bambu-ntfy-win-{uuid4().hex[:8]}",
                              protocol=mqtt.MQTTv311)
    mqtt_client.username_pw_set("bblp", printer["access_code"])
    # P1S uses a device/self-signed certificate. TLS still encrypts the traffic,
    # but certificate identity cannot be verified with this default setup.
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE
    mqtt_client.tls_set_context(context)
    mqtt_client.reconnect_delay_set(min_delay=2, max_delay=60)

    def request_snapshot() -> None:
        packet = {"pushing": {"sequence_id": str(int(time.time())),
                              "command": "pushall"}}
        status = mqtt_client.publish(request_topic, json.dumps(packet), qos=0)
        if status.rc != mqtt.MQTT_ERR_SUCCESS:
            LOG.warning("pushall request failed: MQTT rc=%s", status.rc)

    def on_connect(client, userdata, flags, reason_code, properties):
        if reason_code.is_failure:
            LOG.error("MQTT connection rejected: %s", reason_code)
            return
        LOG.info("Connected to P1S at %s:8883", printer["host"])
        rc, _mid = client.subscribe(report_topic, qos=1)
        if rc != mqtt.MQTT_ERR_SUCCESS:
            LOG.error("Could not subscribe to %s: %s", report_topic, rc)

    def on_subscribe(client, userdata, mid, reason_codes, properties):
        if any(code.is_failure for code in reason_codes):
            LOG.error("MQTT subscribe rejected: %s", reason_codes)
        else:
            request_snapshot()

    def on_disconnect(client, userdata, disconnect_flags, reason_code, properties):
        if reason_code != 0:
            LOG.warning("MQTT disconnected (%s). Waiting for auto-reconnect.", reason_code)

    def on_message(client, userdata, msg):
        try:
            payload = json.loads(msg.payload)
            if not isinstance(payload, dict):
                return
            old_state = tracker.state
            old_job = tracker.job
            event = tracker.apply(payload, bool(options.get("notify_initial_state", False)))
            if tracker.state != old_state or tracker.job != old_job:
                tracker.save(tracker_path)
                LOG.info("Printer state: %s", tracker.state)
            if event is None:
                return
            job_name = tracker.job_name if options.get("include_job_name", True) else ""
            notice = make_notification(event, name, job_name)
            publish_ntfy(cfg, notice)
            LOG.info("ntfy delivered: %s", event)
        except Exception:
            LOG.exception("Failed processing MQTT report or sending notification")

    mqtt_client.on_connect = on_connect
    mqtt_client.on_subscribe = on_subscribe
    mqtt_client.on_disconnect = on_disconnect
    mqtt_client.on_message = on_message

    LOG.info("Connecting to MQTT %s:8883, report topic %s", printer["host"], report_topic)
    mqtt_client.connect_async(printer["host"], 8883, keepalive=60)
    mqtt_client.loop_start()
    last_refresh = time.monotonic()
    try:
        while True:
            time.sleep(1)
            now = time.monotonic()
            if now - last_refresh >= options.get("refresh_seconds", 180):
                if mqtt_client.is_connected():
                    request_snapshot()
                last_refresh = now
    except KeyboardInterrupt:
        LOG.info("Stopping")
    finally:
        mqtt_client.disconnect()
        mqtt_client.loop_stop()


def main() -> int:
    parser = argparse.ArgumentParser(description="P1S LAN MQTT -> ntfy (Windows)")
    parser.add_argument("--config", default="config.json", help="Path to local JSON config")
    parser.add_argument("--test-notification", action="store_true",
                        help="Send an ntfy test without connecting to the printer")
    args = parser.parse_args()
    base = Path(__file__).resolve().parent
    configure_logging(base)
    config_path = Path(args.config).expanduser().resolve()
    try:
        cfg = read_config(config_path)
        if args.test_notification:
            publish_ntfy(cfg, {"title": "P1S | テスト通知",
                               "message": "Windowsからntfyへの通知に成功しました。",
                               "priority": 3, "tags": ["test_tube"]})
            LOG.info("ntfy test notification sent successfully")
        else:
            monitor(cfg, base / ".runtime")
        return 0
    except Exception as exc:
        LOG.error("%s", exc)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
