"""Opt-in Prometheus service watcher with durable incidents and no remediation."""

import asyncio
import json
import logging
import math
import os
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from src.database.models import AiopsRun, OpsWatchIncident, OpsWatchServiceState
from src.database.sql_session import SessionLocal
from src.settings import settings

logger = logging.getLogger(__name__)

FAILURE_THRESHOLD = 3
RECOVERY_THRESHOLD = 2
_MAX_EVIDENCE_SAMPLES = 20


def classify_up_samples(payload: dict[str, Any], now: datetime, stale_after_seconds: int):
    """Classify fresh binary health samples; the original signal stays attached."""
    source = payload.get("data_source") if isinstance(payload, dict) else None
    samples = payload.get("samples") if isinstance(payload, dict) else None
    if source not in {"prometheus", "windows_probe"}:
        return "unknown", [], f"data source is {source or 'missing'}"
    if not isinstance(samples, list) or not samples:
        return "unknown", [], "no matching Prometheus samples"

    now = now.astimezone(timezone.utc)
    normalized = []
    seen = {}
    for sample in samples:
        if not isinstance(sample, dict):
            return "unknown", [], "invalid Prometheus sample"
        try:
            timestamp = float(sample["sample_time_unix"])
            value = float(sample["value"])
        except (KeyError, TypeError, ValueError):
            return "unknown", [], "sample is missing a timestamp or value"
        if not math.isfinite(timestamp) or value not in (0.0, 1.0):
            return "unknown", [], "sample value or timestamp is invalid"
        series_key = str(sample.get("series_key") or sample.get("instance") or "").strip()
        if not series_key:
            return "unknown", [], "sample is missing a stable series identity"
        age = now.timestamp() - timestamp
        if age < -5:
            return "unknown", [], "sample timestamp is ahead of the monitor clock"
        if age > stale_after_seconds:
            return "unknown", [], "Prometheus sample is stale"
        if series_key in seen:
            if seen[series_key] != (timestamp, value):
                return "unknown", [], "conflicting samples for the same series"
            continue
        seen[series_key] = (timestamp, value)
        normalized.append({
            "instance": str(sample.get("instance", "")),
            "series_key": series_key,
            "value": value,
            "sample_time": datetime.fromtimestamp(timestamp, timezone.utc).isoformat(),
        })

    status = "unhealthy" if any(sample["value"] == 0.0 for sample in normalized) else "healthy"
    return status, normalized, None


def record_observation(db, service_name: str, payload: dict[str, Any], now: datetime,
                       stale_after_seconds: int = 120) -> dict[str, Any]:
    observation, samples, error = classify_up_samples(payload, now, stale_after_seconds)
    state = db.query(OpsWatchServiceState).filter_by(service_name=service_name).one_or_none()
    if state is None:
        state = OpsWatchServiceState(service_name=service_name)
        db.add(state)
        db.flush()

    if observation != "unknown":
        watermarks = {}
        for signature in state.latest_sample_signature or []:
            key, separator, timestamp = signature.rpartition("|")
            if separator:
                watermarks[key] = timestamp
        if any(sample["series_key"] in watermarks and sample["sample_time"] <= watermarks[sample["series_key"]]
               for sample in samples):
            state.last_observed_at = now
            db.commit()
            return {"observation": state.latest_observation, "status": state.status, "transition": None,
                    "new_sample": False, "incident_id": state.active_incident_id, "diagnosis_status": None}
        watermarks.update({sample["series_key"]: sample["sample_time"] for sample in samples})
        cutoff = now.timestamp() - stale_after_seconds
        state.latest_sample_signature = sorted(f"{key}|{timestamp}" for key, timestamp in watermarks.items()
                                               if datetime.fromisoformat(timestamp).timestamp() >= cutoff)

    previous = state.latest_observation
    state.latest_observation = observation
    state.data_source = payload.get("data_source") if isinstance(payload, dict) else None
    state.last_observed_at = now
    state.latest_sample_at = (min(datetime.fromisoformat(sample["sample_time"]) for sample in samples)
                              if samples else None)
    state.latest_value = min((sample["value"] for sample in samples), default=None)
    state.last_error = error
    transition = None
    recent = list(state.recent_observations or [])

    if observation == "unknown":
        state.breach_count = 0
        state.recovery_count = 0
        state.recent_observations = []
        state.status = "alerting" if state.active_incident_id else "unknown"
        if state.active_incident_id:
            incident = db.query(OpsWatchIncident).filter_by(
                incident_uid=state.active_incident_id).one_or_none()
            if incident:
                evidence = dict(incident.evidence or {})
                evidence["latest_observation"] = {
                    "status": "unknown", "observed_at": now.astimezone(timezone.utc).isoformat(),
                    "error": error, "data_source": state.data_source,
                }
                incident.evidence = evidence
    else:
        signal = {"data_source": state.data_source, "signal_kind": payload.get("signal_kind", "prometheus_up")}
        if payload.get("evidence"):
            signal.update(evidence=payload["evidence"], rule=payload.get("rule"), measurement=payload.get("measurement"))
        recent = recent + [{
            "status": observation,
            "observed_at": now.astimezone(timezone.utc).isoformat(),
            **signal,
            "samples": samples,
        }] if previous == observation else [{
            "status": observation,
            "observed_at": now.astimezone(timezone.utc).isoformat(),
            **signal,
            "samples": samples,
        }]
        state.recent_observations = recent[-max(FAILURE_THRESHOLD, RECOVERY_THRESHOLD):]

        if observation == "unhealthy":
            state.breach_count = min(state.breach_count + 1, FAILURE_THRESHOLD)
            state.recovery_count = 0
            if state.active_incident_id:
                state.status = "alerting"
                incident = db.query(OpsWatchIncident).filter_by(
                    incident_uid=state.active_incident_id).one_or_none()
                if incident:
                    evidence = dict(incident.evidence or {})
                    latest_bad = list(evidence.get("latest_bad_samples", []))
                    latest_bad.extend(recent[-1:])
                    evidence["latest_bad_samples"] = latest_bad[-_MAX_EVIDENCE_SAMPLES:]
                    incident.evidence = evidence
            elif state.breach_count >= FAILURE_THRESHOLD:
                incident_uid = uuid4().hex
                incident = OpsWatchIncident(
                    incident_uid=incident_uid,
                    service_name=service_name,
                    status="open",
                    opened_at=now,
                    evidence={"trigger_samples": recent[-FAILURE_THRESHOLD:], "recovery_samples": []},
                    diagnosis_status="pending" if settings.OPS_WATCH_AUTO_DIAGNOSE else "disabled",
                )
                db.add(incident)
                state.active_incident_id = incident_uid
                state.status = "alerting"
                transition = "opened"
            else:
                state.status = "suspect"
        else:
            state.breach_count = 0
            if state.active_incident_id:
                state.recovery_count = state.recovery_count + 1 if previous == "healthy" else 1
                state.status = "alerting"
                incident = db.query(OpsWatchIncident).filter_by(
                    incident_uid=state.active_incident_id).one_or_none()
                if incident:
                    evidence = dict(incident.evidence or {})
                    evidence["recovery_samples"] = recent[-RECOVERY_THRESHOLD:]
                    incident.evidence = evidence
                if state.recovery_count >= RECOVERY_THRESHOLD:
                    if incident:
                        incident.status = "resolved"
                        incident.resolved_at = now
                    state.active_incident_id = None
                    state.recovery_count = 0
                    state.status = "healthy"
                    transition = "resolved"
            else:
                state.recovery_count = 0
                state.status = "healthy"

    db.commit()
    return {
        "observation": observation,
        "status": state.status,
        "transition": transition,
        "new_sample": observation != "unknown",
        "incident_id": state.active_incident_id or (incident.incident_uid if transition == "resolved" else None),
        "diagnosis_status": (incident.diagnosis_status if transition == "opened" else None),
    }


def _reset_after_restart() -> None:
    with SessionLocal() as db:
        states = db.query(OpsWatchServiceState).all()
        for state in states:
            state.latest_observation = "unknown"
            state.breach_count = 0
            state.recovery_count = 0
            state.recent_observations = []
            state.status = "alerting" if state.active_incident_id else "unknown"
            state.last_error = "monitor worker restarted; waiting for fresh samples"
        for incident in db.query(OpsWatchIncident).filter(
                OpsWatchIncident.diagnosis_status.in_(["pending", "running"])).all():
            incident.diagnosis_status = "interrupted"
            _interrupt_linked_run(db, incident.diagnosis_thread_id)
        db.commit()


def _interrupt_linked_run(db, thread_id):
    if thread_id:
        db.query(AiopsRun).filter_by(thread_id=thread_id, user_id=None, status="running").update(
            {"status": "failed", "report": "自动诊断已中断，请核对监察事件后重新发起诊断", "terminal_approval": None})


def _diagnosis_trigger_samples(evidence: Any) -> list[dict[str, Any]]:
    """Project persisted trigger observations to a small, label-free model context."""
    if not isinstance(evidence, dict):
        return []
    observations = evidence.get("trigger_samples")
    if not isinstance(observations, list):
        return []

    projected = []
    for observation in observations[-FAILURE_THRESHOLD:]:
        if not isinstance(observation, dict):
            continue
        observed_at = _normalized_timestamp(observation.get("observed_at"))
        source_samples = observation.get("samples")
        if not observed_at or not isinstance(source_samples, list):
            continue
        samples = []
        for sample in source_samples[:_MAX_EVIDENCE_SAMPLES]:
            if not isinstance(sample, dict):
                continue
            try:
                value = float(sample["value"])
            except (KeyError, TypeError, ValueError):
                continue
            sample_time = _normalized_timestamp(sample.get("sample_time"))
            if value not in (0.0, 1.0) or not sample_time:
                continue
            samples.append({
                "sample": len(samples) + 1,
                "sample_time": sample_time,
                **({"up": int(value)} if observation.get("data_source", "prometheus") == "prometheus" else {"healthy": bool(value)}),
            })
        if samples:
            item = {"observed_at": observed_at, "samples": samples,
                    "signal_kind": observation.get("signal_kind", "prometheus_up")}
            if observation.get("data_source") == "windows_probe":
                measurement = observation.get("measurement") or {}
                rule = observation.get("rule") or {}
                if isinstance(measurement, dict) and isinstance(rule, dict):
                    item["measurement"] = {key: value for key, value in measurement.items()
                        if key in {"http_status", "elapsed_ms", "http_error", "error_count", "window_complete", "event_loop_lag_ms"}
                        and (type(value) is bool or (type(value) in (int, float) and math.isfinite(value)))}
                    item["rule"] = {key: value for key, value in rule.items()
                        if key in {"max_elapsed_ms", "max_event_loop_lag_ms"}
                        and type(value) in (int, float) and math.isfinite(value)}
            projected.append(item)
    return projected


def _normalized_timestamp(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(timezone.utc).isoformat()


def _diagnosis_prompt(incident_uid: str, service_name: str, opened_at: str,
                      evidence: Any) -> str:
    trigger_samples = _diagnosis_trigger_samples(evidence)
    sample_context = json.dumps(trigger_samples, ensure_ascii=True, separators=(",", ":"))
    is_up = all(row.get("signal_kind") == "prometheus_up" for row in trigger_samples)
    phenomenon = ("至少一个匹配实例的 up 值为 0。" if is_up else "已登记的业务或桌面运行时检查连续异常。")
    return (
        f"监察器在 {opened_at} 起连续三次新鲜检查发现服务 {service_name} " + phenomenon +
        f"事件 {incident_uid} 持久化的触发样本摘要为 {sample_context}。"
        "这些时间和值只界定观察到的现象，不能单独证明根因；请结合当前已配置的现场只读工具调查，"
        "把现场证据与参考资料分开，区分已确认原因、已定位故障层和未查明事项；"
        "不要把监控现象当成根因，也不要执行修复或变更。"
    )


@contextmanager
def _single_process_lock():
    lock_path = Path(settings.BASE_DIR) / "data" / "ops-watch.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    handle = lock_path.open("a+b")
    handle.seek(0, os.SEEK_END)
    if handle.tell() == 0:
        handle.write(b"0")
        handle.flush()
    handle.seek(0)
    try:
        if os.name == "nt":
            import msvcrt
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            unlock = lambda: msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            unlock = lambda: fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    except OSError:
        handle.close()
        yield False
        return
    try:
        yield True
    finally:
        unlock()
        handle.close()


async def _diagnose_incident(incident_uid: str, service_name: str, semaphore: asyncio.Semaphore):
    from src.agent.aiops import aiops_service

    async with semaphore:
        with SessionLocal() as db:
            incident = db.query(OpsWatchIncident).filter_by(incident_uid=incident_uid).one_or_none()
            if not incident or incident.diagnosis_status != "pending":
                return
            if incident.status != "open":
                incident.diagnosis_status = "skipped"
                db.commit()
                return
            incident.diagnosis_status = "running"
            opened_at = incident.opened_at.isoformat()
            evidence = incident.evidence
            db.commit()

        prompt = _diagnosis_prompt(incident_uid, service_name, opened_at, evidence)
        report = None
        thread_id = None
        status = "failed"
        try:
            async for event in aiops_service.execute(
                user_input=prompt,
                session_id=f"watch-{incident_uid[:18]}",
                user_id=None,
                terminal_enabled=False,
                persist_run=True,
            ):
                new_thread_id = event.get("thread_id")
                if new_thread_id and new_thread_id != thread_id:
                    thread_id = new_thread_id
                    # execute yields its status before the planner starts.
                    # Persist the principal binding before consuming that work.
                    with SessionLocal() as db:
                        db.query(OpsWatchIncident).filter_by(incident_uid=incident_uid).update(
                            {"diagnosis_thread_id": thread_id})
                        db.commit()
                if event.get("type") == "complete":
                    report = event.get("response", "")
                    status = "completed"
                elif event.get("type") == "pending_review":
                    report = event.get("draft") or event.get("response") or ""
                    status = "pending_review"
                elif event.get("type") == "error":
                    report = event.get("response") or event.get("message", "诊断失败")
        except asyncio.CancelledError:
            status = "interrupted"
            report = "自动诊断已中断，可核对事件后重新发起诊断"
            raise
        except Exception as exc:
            report = f"自动诊断失败（{type(exc).__name__}）"
        finally:
            with SessionLocal() as db:
                incident = db.query(OpsWatchIncident).filter_by(incident_uid=incident_uid).one_or_none()
                if incident:
                    incident.diagnosis_status = status
                    incident.diagnosis_thread_id = thread_id
                    incident.diagnosis_report = report
                    if status == "interrupted":
                        _interrupt_linked_run(db, thread_id)
                    db.commit()


async def run_continuous_watch() -> None:
    """Run one durable watcher; repeated unknown samples never count as recovery."""
    if not settings.OPS_WATCH_ENABLED:
        return
    services = list(dict.fromkeys(name.strip() for name in settings.OPS_WATCH_SERVICES.split(",") if name.strip()))
    if not services:
        logger.error("OPS_WATCH_ENABLED is true but OPS_WATCH_SERVICES is empty")
        return
    from src.agent.aiops.watch_signals import parse_checks, poll_probe_check
    try:
        probe_checks = parse_checks(settings.OPS_WATCH_PROBE_CHECKS, services)
        collector = None
        if probe_checks:
            from src.probe.windows.config import load_config
            from src.probe.windows.collector import WindowsCollector
            collector = WindowsCollector(load_config(settings.OPS_WATCH_PROBE_CONFIG))
            for name, check in probe_checks.items():
                if check["kind"] == "http":
                    dep = collector.config.dependency(check["dependency"])
                    if not dep.health_scheme:
                        raise ValueError("business checks require an HTTP health entry")
                else:
                    from src.probe.windows.config import allowed_text_path
                    if not allowed_text_path(collector.config, name, check["path"]):
                        raise ValueError("desktop snapshot must be a configured Probe text log")
    except (ValueError, OSError, TypeError):
        logger.exception("Invalid continuous monitor Probe checks; watcher not started")
        return
    if settings.OPS_WATCH_INTERVAL_SECONDS < 5 or settings.OPS_WATCH_STALE_AFTER_SECONDS < settings.OPS_WATCH_INTERVAL_SECONDS:
        logger.error("Invalid continuous monitor interval or stale-sample limit")
        return

    while True:
        with _single_process_lock() as acquired:
            if not acquired:
                logger.info("Continuous monitor is already running in another process; retrying")
            else:
                from mcp_servers.prometheus_client import PrometheusClient, use_prometheus_backend
                client = PrometheusClient() if use_prometheus_backend() else None
                _reset_after_restart()
                diagnosis_semaphore = asyncio.Semaphore(1)
                diagnosis_tasks: set[asyncio.Task] = set()
                try:
                    while True:
                        try:
                            now = datetime.now(timezone.utc)
                            async def poll(service_name):
                                try:
                                    if service_name in probe_checks:
                                        return await asyncio.to_thread(poll_probe_check, collector, service_name, probe_checks[service_name])
                                    if client:
                                        return await asyncio.to_thread(client.query_up, service_name)
                                    return {"data_source": "unavailable", "samples": [], "error": "Prometheus backend is not configured"}
                                except Exception as exc:
                                    return {"data_source": "unavailable", "samples": [], "error": type(exc).__name__}
                            payloads = await asyncio.gather(*[poll(name) for name in services])
                            for service_name, payload in zip(services, payloads):
                                with SessionLocal() as db:
                                    result = record_observation(
                                        db, service_name, payload, datetime.now(timezone.utc),
                                        settings.OPS_WATCH_STALE_AFTER_SECONDS,
                                    )
                                if (result["transition"] == "opened" and settings.OPS_WATCH_AUTO_DIAGNOSE):
                                    task = asyncio.create_task(_diagnose_incident(
                                        result["incident_id"], service_name, diagnosis_semaphore))
                                    diagnosis_tasks.add(task)
                                    task.add_done_callback(diagnosis_tasks.discard)
                        except asyncio.CancelledError:
                            raise
                        except Exception as exc:
                            logger.warning("Continuous monitor poll failed (error_type=%s); retrying",
                                           type(exc).__name__)
                        await asyncio.sleep(settings.OPS_WATCH_INTERVAL_SECONDS)
                except asyncio.CancelledError:
                    for task in diagnosis_tasks:
                        task.cancel()
                    if diagnosis_tasks:
                        await asyncio.gather(*diagnosis_tasks, return_exceptions=True)
                    raise
        await asyncio.sleep(settings.OPS_WATCH_INTERVAL_SECONDS)
