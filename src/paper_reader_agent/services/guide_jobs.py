from __future__ import annotations

from concurrent.futures import Future, ThreadPoolExecutor
from datetime import datetime, timezone
from threading import Lock
from typing import Any

from paper_reader_agent.config import AppConfig
from paper_reader_agent.models import PaperRecord
from paper_reader_agent.services.library import save_paper
from paper_reader_agent.services.papers import ensure_text_cache, generate_reading_guide, load_reading_guide
from paper_reader_agent.services.storage import guide_status_path, metadata_path, read_json, write_json


GUIDE_JOB_EXECUTOR = ThreadPoolExecutor(max_workers=1, thread_name_prefix="reading-guide")
GUIDE_JOB_LOCK = Lock()
GUIDE_JOB_FUTURES: dict[str, Future[Any]] = {}
GUIDE_STEPS: tuple[dict[str, str], ...] = (
    {
        "id": "prepare_text",
        "label": "\u8bfb\u53d6\u8bba\u6587",
        "message": "\u8bfb\u53d6\u8bba\u6587\u5e76\u51c6\u5907\u53ef\u7528\u4e8e\u6574\u7bc7\u7406\u89e3\u7684\u6587\u672c\u5c42\u3002",
    },
    {
        "id": "build_context",
        "label": "\u6784\u5efa\u5168\u6587\u4e0a\u4e0b\u6587",
        "message": "\u6574\u7406\u6574\u7bc7\u8bba\u6587\u7684\u5173\u952e\u6bb5\u843d\u3001\u9875\u7801\u7ebf\u7d22\u4e0e\u4e0a\u4e0b\u6587\u3002",
    },
    {
        "id": "draft_guide",
        "label": "\u751f\u6210\u5206\u6bb5\u6458\u8981",
        "message": "\u63d0\u70bc\u80cc\u666f\u3001\u95ee\u9898\u3001\u65b9\u6cd5\u3001\u7ed3\u679c\u4e0e\u5c40\u9650\u7b49\u5173\u952e\u90e8\u5206\u3002",
    },
    {
        "id": "finalize",
        "label": "\u5408\u6210\u9605\u8bfb\u5bfc\u56fe",
        "message": "\u6574\u7406\u6210\u5de6\u680f\u53ef\u8bfb\u7684\u7ed3\u6784\u5316\u9605\u8bfb\u5bfc\u56fe\u3002",
    },
)
STEP_INDEX = {step["id"]: index for index, step in enumerate(GUIDE_STEPS)}


def load_reading_guide_status(config: AppConfig, paper_id: str) -> dict[str, Any] | None:
    payload = read_json(guide_status_path(config, paper_id), None)
    return payload if isinstance(payload, dict) else None


def get_reading_guide_status(config: AppConfig, record: PaperRecord) -> dict[str, Any]:
    stored = load_reading_guide_status(config, record.id) or {}
    updated_at = str(stored.get("updated_at") or record.updated_at or _now_iso())
    stage = _normalize_stage_id(stored.get("stage"))

    if record.guide_state == "running":
        return _status_payload("running", stage or "prepare_text", updated_at=updated_at)

    if record.guide_state == "failed":
        return _status_payload(
            "failed",
            stage or "prepare_text",
            updated_at=updated_at,
            error=str(stored.get("error") or "\u9605\u8bfb\u5bfc\u56fe\u751f\u6210\u5931\u8d25\u3002"),
        )

    if record.guide_state == "ready" and load_reading_guide(config, record.id):
        return _status_payload("ready", "finalize", updated_at=updated_at)

    if record.guide_state == "stale":
        return _status_payload("stale", None, updated_at=updated_at)

    return _status_payload("idle", None, updated_at=updated_at)


def queue_reading_guide_generation(
    config: AppConfig,
    bridge: dict[str, str],
    record: PaperRecord,
    *,
    force: bool = False,
) -> tuple[PaperRecord, dict[str, Any], dict[str, Any] | None]:
    existing_guide = load_reading_guide(config, record.id)
    if existing_guide and record.guide_state == "ready" and not force:
        return record, get_reading_guide_status(config, record), existing_guide

    with GUIDE_JOB_LOCK:
        existing_future = GUIDE_JOB_FUTURES.get(record.id)
        if existing_future and not existing_future.done():
            return record, get_reading_guide_status(config, record), None

        record.guide_state = "running"
        record.updated_at = _now_iso()
        save_paper(config, record)
        _write_status(config, record.id, _status_payload("running", "prepare_text", updated_at=record.updated_at))

        future = GUIDE_JOB_EXECUTOR.submit(_run_guide_job, config, dict(bridge), record.id, force)
        GUIDE_JOB_FUTURES[record.id] = future
        future.add_done_callback(lambda finished, paper_id=record.id: _complete_guide_job(config, paper_id, finished))

    return record, get_reading_guide_status(config, record), None


def _run_guide_job(config: AppConfig, bridge: dict[str, str], paper_id: str, force: bool) -> dict[str, Any]:
    record = _load_record(config, paper_id)
    if not record:
        raise FileNotFoundError("\u8bba\u6587\u4e0d\u5b58\u5728\uff0c\u65e0\u6cd5\u751f\u6210\u9605\u8bfb\u5bfc\u56fe\u3002")

    _write_status(config, paper_id, _status_payload("running", "prepare_text"))
    record = ensure_text_cache(config, record)
    record = _load_record(config, paper_id) or record

    def on_stage(stage_id: str) -> None:
        _write_status(config, paper_id, _status_payload("running", stage_id))

    guide = generate_reading_guide(config, bridge, record, force=force, on_stage=on_stage)

    record = _load_record(config, paper_id) or record
    record.guide_state = "ready"
    record.updated_at = _now_iso()
    save_paper(config, record)
    _write_status(config, paper_id, _status_payload("ready", "finalize", updated_at=record.updated_at))
    return guide


def _complete_guide_job(config: AppConfig, paper_id: str, finished: Future[Any]) -> None:
    with GUIDE_JOB_LOCK:
        if GUIDE_JOB_FUTURES.get(paper_id) is finished:
            GUIDE_JOB_FUTURES.pop(paper_id, None)

    if finished.cancelled():
        return

    error = finished.exception()
    if error is None:
        return

    record = _load_record(config, paper_id)
    if not record:
        return

    stored = load_reading_guide_status(config, paper_id) or {}
    failed_stage = _normalize_stage_id(stored.get("stage")) or "prepare_text"
    record.guide_state = "failed"
    record.updated_at = _now_iso()
    save_paper(config, record)
    _write_status(
        config,
        paper_id,
        _status_payload(
            "failed",
            failed_stage,
            updated_at=record.updated_at,
            error=str(error),
        ),
    )


def _status_payload(
    state: str,
    stage_id: str | None,
    *,
    updated_at: str | None = None,
    error: str = "",
) -> dict[str, Any]:
    normalized_state = state if state in {"idle", "stale", "running", "ready", "failed"} else "idle"
    normalized_stage = _normalize_stage_id(stage_id)
    current_index = STEP_INDEX.get(normalized_stage, -1)

    steps: list[dict[str, str]] = []
    for index, step in enumerate(GUIDE_STEPS):
        step_state = "pending"
        if normalized_state == "ready":
            step_state = "complete"
        elif normalized_state == "running":
            if index < current_index:
                step_state = "complete"
            elif index == current_index:
                step_state = "current"
        elif normalized_state == "failed":
            if index < current_index:
                step_state = "complete"
            elif index == current_index:
                step_state = "failed"
        steps.append(
            {
                "id": step["id"],
                "label": step["label"],
                "state": step_state,
            }
        )

    message = {
        "idle": "\u70b9\u51fb\u201c\u751f\u6210\u9605\u8bfb\u5bfc\u56fe\u201d\u540e\uff0c\u8fd9\u91cc\u4f1a\u6309\u9636\u6bb5\u663e\u793a\u8fdb\u5ea6\u3002",
        "stale": "\u8bba\u6587\u5185\u5bb9\u5df2\u66f4\u65b0\uff0c\u5efa\u8bae\u91cd\u65b0\u751f\u6210\u9605\u8bfb\u5bfc\u56fe\u3002",
        "ready": "\u9605\u8bfb\u5bfc\u56fe\u5df2\u51c6\u5907\u597d\u3002",
        "failed": error or "\u9605\u8bfb\u5bfc\u56fe\u751f\u6210\u5931\u8d25\u3002",
    }.get(normalized_state)

    if normalized_state == "running":
        message = _step_message(normalized_stage)

    badge = {
        "idle": "\u5f85\u751f\u6210",
        "stale": "\u5f85\u66f4\u65b0",
        "running": "\u751f\u6210\u4e2d",
        "ready": "\u5df2\u751f\u6210",
        "failed": "\u5931\u8d25",
    }[normalized_state]

    return {
        "state": normalized_state,
        "stage": normalized_stage,
        "stage_label": _step_label(normalized_stage),
        "badge": badge,
        "message": message,
        "steps": steps,
        "error": error if normalized_state == "failed" else "",
        "updated_at": updated_at or _now_iso(),
    }


def _write_status(config: AppConfig, paper_id: str, payload: dict[str, Any]) -> None:
    write_json(guide_status_path(config, paper_id), payload)


def _load_record(config: AppConfig, paper_id: str) -> PaperRecord | None:
    payload = read_json(metadata_path(config, paper_id), None)
    if not isinstance(payload, dict) or not payload:
        return None
    return PaperRecord.from_json(payload)


def _normalize_stage_id(stage_id: Any) -> str | None:
    stage = str(stage_id or "").strip()
    return stage if stage in STEP_INDEX else None


def _step_label(stage_id: str | None) -> str:
    normalized_stage = _normalize_stage_id(stage_id)
    if not normalized_stage:
        return ""
    return GUIDE_STEPS[STEP_INDEX[normalized_stage]]["label"]


def _step_message(stage_id: str | None) -> str:
    normalized_stage = _normalize_stage_id(stage_id)
    if not normalized_stage:
        return "\u6b63\u5728\u51c6\u5907\u9605\u8bfb\u5bfc\u56fe\u3002"
    return GUIDE_STEPS[STEP_INDEX[normalized_stage]]["message"]


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
