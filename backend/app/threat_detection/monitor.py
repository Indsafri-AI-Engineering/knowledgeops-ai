import os
import threading
import time
from collections import defaultdict, deque

from backend.app.storage.audit import AuditEvent
from backend.app.threat_detection.alerts import create_security_alert
from backend.app.threat_detection.rules import DETECTOR_VERSION, ThreatIndicator

_EVENT_LOCK = threading.Lock()
_EVENT_WINDOWS: dict[str, deque[float]] = defaultdict(deque)
_LAST_ALERT_AT: dict[str, float] = {}
_LAST_SEEN: dict[str, float] = {}
_MAX_MONITORED_SUBJECTS = 2_048


def process_audit_event(event: AuditEvent) -> None:
    if event.outcome != "denied" or not (
        event.action.startswith("auth.")
        or event.action.startswith("authorization.")
    ):
        return

    threshold = int(os.getenv("SECURITY_DENIAL_THRESHOLD", "5"))
    window_seconds = int(os.getenv("SECURITY_DENIAL_WINDOW_SECONDS", "300"))
    cooldown_seconds = int(os.getenv("SECURITY_DENIAL_ALERT_COOLDOWN_SECONDS", "600"))
    if (
        not 2 <= threshold <= 10_000
        or not 60 <= window_seconds <= 86_400
        or not 60 <= cooldown_seconds <= 86_400
    ):
        raise ValueError("Security event monitoring thresholds are out of range.")

    source_fingerprint = event.metadata.get("source_fingerprint")
    key_part = (
        source_fingerprint
        if isinstance(source_fingerprint, str)
        else event.actor_id
    )
    monitor_key = f"{event.action.split('.', 1)[0]}:{key_part}"
    now = time.monotonic()
    with _EVENT_LOCK:
        events = _EVENT_WINDOWS[monitor_key]
        events.append(now)
        _LAST_SEEN[monitor_key] = now
        while events and now - events[0] > window_seconds:
            events.popleft()
        if len(_EVENT_WINDOWS) > _MAX_MONITORED_SUBJECTS:
            stale_keys = [
                key
                for key, last_seen in _LAST_SEEN.items()
                if now - last_seen > window_seconds
            ]
            for key in stale_keys:
                _EVENT_WINDOWS.pop(key, None)
                _LAST_ALERT_AT.pop(key, None)
                _LAST_SEEN.pop(key, None)
            while len(_EVENT_WINDOWS) > _MAX_MONITORED_SUBJECTS:
                oldest_key = min(_LAST_SEEN, key=_LAST_SEEN.__getitem__)
                _EVENT_WINDOWS.pop(oldest_key, None)
                _LAST_ALERT_AT.pop(oldest_key, None)
                _LAST_SEEN.pop(oldest_key, None)
        previous_alert = _LAST_ALERT_AT.get(monitor_key, 0)
        if len(events) < threshold or now - previous_alert < cooldown_seconds:
            return
        _LAST_ALERT_AT[monitor_key] = now
        event_count = len(events)

    indicator = ThreatIndicator(
        rule_id="repeated-security-denials",
        severity="medium",
        description=(
            "Repeated authentication or authorization denials exceeded the "
            "configured monitoring threshold."
        ),
        evidence="event count and source identifier withheld",
    )
    create_security_alert(
        alert_type=(
            "authentication_anomaly"
            if event.action.startswith("auth.")
            else "authorization_anomaly"
        ),
        severity="medium",
        title="Repeated security access denials",
        summary=(
            f"{event_count} denied security events occurred within "
            f"{window_seconds // 60} minutes."
        ),
        actor_id=event.actor_id if event.actor_id != "anonymous" else None,
        detector_version=f"{DETECTOR_VERSION}+audit-monitor-v1",
        indicators=[indicator],
    )


def reset_monitor_state() -> None:
    with _EVENT_LOCK:
        _EVENT_WINDOWS.clear()
        _LAST_ALERT_AT.clear()
        _LAST_SEEN.clear()
