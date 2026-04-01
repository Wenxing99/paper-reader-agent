from __future__ import annotations

from typing import Any

from flask import Flask, jsonify, render_template, request, send_file, url_for

from paper_reader_agent.config import load_config
from paper_reader_agent.services.bridge import request_chat_completion, resolve_bridge_config
from paper_reader_agent.services.context import build_chat_context, build_selection_context
from paper_reader_agent.services.library import get_paper, import_uploaded_pdf, list_papers, scan_library
from paper_reader_agent.services.papers import (
    build_document_payload,
    ensure_page_cache,
    ensure_text_cache,
    generate_reading_guide,
    kickoff_text_cache_warmup,
    load_all_pages,
    load_page,
    load_reading_guide,
    render_page_image,
)
from paper_reader_agent.services.storage import ensure_repo_dirs


def create_app() -> Flask:
    app = Flask(__name__, template_folder="templates", static_folder="static")
    app.config["MAX_CONTENT_LENGTH"] = 200 * 1024 * 1024
    config = load_config()
    app.config["PAPER_READER_CONFIG"] = config
    ensure_repo_dirs(config)

    @app.get("/")
    def index() -> str:
        return render_template(
            "index.html",
            default_bridge_url=config.bridge_url,
            default_model=config.model,
            default_reasoning_effort=config.reasoning_effort,
        )

    @app.get("/api/health")
    def health():
        return jsonify(
            {
                "ok": True,
                "default_bridge_url": config.bridge_url,
                "default_model": config.model,
                "default_reasoning_effort": config.reasoning_effort,
                "host": config.host,
                "port": config.port,
            }
        )

    @app.get("/api/papers")
    def papers_index():
        records = list_papers(config)
        return jsonify({"papers": [_paper_payload(config, record, include_guide=False) for record in records]})

    @app.post("/api/library/import")
    def import_pdf():
        file = request.files.get("file")
        if not file:
            return _error("请选择一个 PDF 文件。", 400)
        try:
            record = import_uploaded_pdf(config, file)
            record = kickoff_text_cache_warmup(config, record)
        except Exception as error:
            return _error(f"导入 PDF 失败: {error}", 400)
        return jsonify({"paper": _paper_payload(config, record, include_guide=True)})

    @app.post("/api/library/scan")
    def scan_library_route():
        payload = request.get_json(silent=True) or {}
        folder_path = str(payload.get("folder_path") or "").strip()
        if not folder_path:
            return _error("请先提供论文目录路径。", 400)
        try:
            records = scan_library(config, folder_path)
        except Exception as error:
            return _error(str(error), 400)
        return jsonify(
            {
                "library_path": folder_path,
                "papers": [_paper_payload(config, record, include_guide=False) for record in records],
            }
        )

    @app.get("/api/papers/<paper_id>")
    def paper_detail(paper_id: str):
        try:
            record = get_paper(config, paper_id)
            record = kickoff_text_cache_warmup(config, record)
        except Exception as error:
            return _error(str(error), 400)
        return jsonify({"paper": _paper_payload(config, record, include_guide=True)})

    @app.get("/api/papers/<paper_id>/pages/<int:page_number>")
    def page_detail(paper_id: str, page_number: int):
        try:
            record = get_paper(config, paper_id)
            record, page = ensure_page_cache(config, record, page_number)
        except Exception as error:
            return _error(str(error), 400)
        page["image_url"] = url_for("page_image", paper_id=paper_id, page_number=page_number)
        return jsonify({"page": page, "paper": _paper_payload(config, record, include_guide=False)})

    @app.get("/api/papers/<paper_id>/pages/<int:page_number>/image")
    def page_image(paper_id: str, page_number: int):
        try:
            record = get_paper(config, paper_id)
            image_path = render_page_image(config, record, page_number)
        except Exception as error:
            return _error(str(error), 400)
        return send_file(image_path, mimetype="image/png", download_name=f"page-{page_number:04d}.png")

    @app.get("/api/papers/<paper_id>/source")
    def paper_source(paper_id: str):
        try:
            record = get_paper(config, paper_id)
        except Exception as error:
            return _error(str(error), 404)
        return send_file(
            record.source_path,
            mimetype="application/pdf",
            download_name=record.filename or f"{paper_id}.pdf",
            conditional=True,
        )

    @app.post("/api/papers/<paper_id>/reading-guide")
    def reading_guide_route(paper_id: str):
        payload = request.get_json(silent=True) or {}
        force = bool(payload.get("force"))
        bridge = resolve_bridge_config(config, payload)
        try:
            record = ensure_text_cache(config, get_paper(config, paper_id))
            guide = generate_reading_guide(config, bridge, record, force=force)
        except Exception as error:
            return _error(f"生成阅读导图失败: {error}", 500)
        return jsonify({"reading_guide": guide, "paper": _paper_payload(config, record, include_guide=True)})

    @app.post("/api/papers/<paper_id>/chat")
    def paper_chat(paper_id: str):
        payload = request.get_json(silent=True) or {}
        messages = payload.get("messages") or []
        current_page = int(payload.get("page") or 0)
        if not isinstance(messages, list) or not messages:
            return _error("请至少发送一条聊天消息。", 400)

        bridge = resolve_bridge_config(config, payload)
        try:
            record = ensure_text_cache(config, get_paper(config, paper_id))
            guide = load_reading_guide(config, paper_id)
            pages = load_all_pages(config, paper_id)
        except Exception as error:
            return _error(str(error), 400)

        question = _last_user_message(messages)
        context_text = build_chat_context(
            config,
            paper_title=record.title,
            reading_guide=guide,
            pages=pages,
            question=question,
            current_page=current_page,
        )
        prepared_messages = [
            {
                "role": "system",
                "content": (
                    "You are a paper reading companion. Respond in Simplified Chinese. "
                    "Use the provided full-paper context as the main reference. "
                    "Current page is optional supporting context, not the main anchor. "
                    "If the context is insufficient, say so clearly instead of inventing facts."
                ),
            },
            {
                "role": "system",
                "content": f"论文上下文：\n{context_text}",
            },
        ]
        prepared_messages.extend(_prepare_conversation(messages))

        try:
            answer = request_chat_completion(
                bridge,
                messages=prepared_messages,
                max_tokens=1300,
                temperature=0.3,
            )
        except Exception as error:
            return _error(f"聊天失败: {error}", 500)
        return jsonify({"text": answer})

    @app.post("/api/papers/<paper_id>/selection-action")
    def selection_action(paper_id: str):
        payload = request.get_json(silent=True) or {}
        selected_text = str(payload.get("text") or "").strip()
        mode = str(payload.get("mode") or "explain").strip().lower()
        page_number = int(payload.get("page") or 0)
        if not selected_text:
            return _error("没有收到选中的文本。", 400)
        if mode not in {"explain", "translate"}:
            return _error("不支持的 selection action。", 400)

        bridge = resolve_bridge_config(config, payload)
        try:
            record = ensure_text_cache(config, get_paper(config, paper_id))
            guide = load_reading_guide(config, paper_id)
            page_payload = load_page(config, paper_id, page_number) if page_number > 0 else None
        except Exception as error:
            return _error(str(error), 400)

        context_text = build_selection_context(
            config,
            paper_title=record.title,
            reading_guide=guide,
            page_payload=page_payload,
        )
        prompt = _selection_prompt(selected_text, mode)

        try:
            answer = request_chat_completion(
                bridge,
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "You are an academic reading assistant. Respond in Simplified Chinese. "
                            "Use the paper context to ground the explanation or translation."
                        ),
                    },
                    {
                        "role": "system",
                        "content": f"论文上下文：\n{context_text}",
                    },
                    {
                        "role": "user",
                        "content": prompt,
                    },
                ],
                max_tokens=1000,
                temperature=0.2,
            )
        except Exception as error:
            return _error(f"选中文本处理失败: {error}", 500)
        return jsonify({"text": answer})

    return app


def _paper_payload(config, record, *, include_guide):
    payload = build_document_payload(config, record, include_guide=include_guide)
    payload["pdf_url"] = url_for("paper_source", paper_id=record.id)
    return payload


def _prepare_conversation(messages: list[dict[str, Any]]) -> list[dict[str, str]]:
    prepared: list[dict[str, str]] = []
    for item in messages[-12:]:
        if not isinstance(item, dict):
            continue
        role = str(item.get("role") or "").strip().lower()
        content = str(item.get("content") or "").strip()
        if role not in {"user", "assistant"} or not content:
            continue
        prepared.append({"role": role, "content": content})
    return prepared


def _last_user_message(messages: list[dict[str, Any]]) -> str:
    for item in reversed(messages):
        if isinstance(item, dict) and str(item.get("role") or "").strip().lower() == "user":
            return str(item.get("content") or "").strip()
    return ""


def _selection_prompt(text: str, mode: str) -> str:
    if mode == "translate":
        return "\n".join(
            [
                "请把下面这段论文内容翻译成流畅的简体中文。",
                "保留公式、符号、变量名和引用编号。",
                "翻译完成后，再补一句“这段在整篇论文里的作用”。",
                "不要使用表格。",
                "文本：",
                text,
            ]
        )
    return "\n".join(
        [
            "请解释下面这段论文内容，用简体中文输出。",
            "结构：",
            "1. 一句话概括",
            "2. 通俗解释",
            "3. 必要时补充术语说明",
            "不要编造文中没有的信息。",
            "文本：",
            text,
        ]
    )


def _error(message: str, status: int):
    return jsonify({"ok": False, "message": message}), status
