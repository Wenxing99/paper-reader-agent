#!/usr/bin/env python3
"""OpenAI-compatible local bridge backed by `codex exec`."""

from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import subprocess
import sys
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any


ANSI_ESCAPE_RE = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8765
DEFAULT_MODEL = os.environ.get("CODEX_BRIDGE_DEFAULT_MODEL") or os.environ.get("PAPER_READER_MODEL", "gpt-5.4-mini")
DEFAULT_REASONING_RAW = os.environ.get("CODEX_BRIDGE_DEFAULT_REASONING_EFFORT", "")
DEFAULT_TIMEOUT_SEC = int(os.environ.get("CODEX_BRIDGE_TIMEOUT_SEC", "900"))
DEFAULT_STREAM_CHUNK_SIZE = int(os.environ.get("CODEX_BRIDGE_STREAM_CHUNK_SIZE", "900"))
SUPPORTED_REASONING_EFFORTS = ("minimal", "low", "medium", "high", "xhigh")


class BridgeError(RuntimeError):
    def __init__(self, message: str, *, code: str = "bridge_error", status: int = 500) -> None:
        super().__init__(message)
        self.code = code
        self.status = status


def parse_command(raw: str) -> list[str]:
    raw = (raw or "").strip()
    if not raw:
        return ["codex"]
    if Path(raw).exists():
        return _wrap_windows_shell_script([raw])
    return _wrap_windows_shell_script(shlex.split(raw, posix=os.name != "nt"))


def _wrap_windows_shell_script(parts: list[str]) -> list[str]:
    if os.name != "nt" or not parts:
        return parts
    first = str(parts[0] or "").strip()
    suffix = Path(first).suffix.lower()
    if suffix in {".cmd", ".bat"}:
        return ["cmd", "/c", *parts]
    return parts


def ensure_workdir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


def strip_ansi(text: str) -> str:
    return ANSI_ESCAPE_RE.sub("", text or "")


def parse_model_spec(raw_model: str) -> tuple[str, str | None]:
    model = (raw_model or "").strip() or DEFAULT_MODEL
    lowered = model.lower()

    for effort in sorted(SUPPORTED_REASONING_EFFORTS, key=len, reverse=True):
        suffix = f"@{effort}"
        if lowered.endswith(suffix):
            base = model[: -len(suffix)].strip()
            if base:
                return base, effort

    for effort in sorted(SUPPORTED_REASONING_EFFORTS, key=len, reverse=True):
        suffix = f"-{effort}"
        if lowered.endswith(suffix):
            base = model[: -len(suffix)].strip()
            if base:
                return base, effort

    return model, None


def normalize_reasoning_effort(raw_effort: Any, *, allow_disable: bool) -> str | None:
    effort = str(raw_effort or "").strip().lower()
    if effort in {"", "default"}:
        return None
    if effort == "median":
        effort = "medium"
    if allow_disable and effort in {"none", "off", "disabled"}:
        return ""
    if effort not in SUPPORTED_REASONING_EFFORTS:
        supported = ", ".join(SUPPORTED_REASONING_EFFORTS)
        raise BridgeError(
            f"Unsupported reasoning effort `{effort}`. Supported values: {supported}, or `none` to disable override.",
            code="invalid_reasoning_effort",
            status=400,
        )
    return effort


def flatten_message_content(content: Any) -> tuple[str, bool]:
    if content is None:
        return "", False
    if isinstance(content, str):
        return content, False
    if not isinstance(content, list):
        return str(content), False

    text_parts: list[str] = []
    saw_image = False

    for part in content:
        if isinstance(part, str):
            text_parts.append(part)
            continue
        if not isinstance(part, dict):
            text_parts.append(str(part))
            continue

        part_type = str(part.get("type") or "").lower()
        if part_type in {"text", "input_text", "output_text"}:
            text_parts.append(str(part.get("text") or ""))
            continue
        if part_type in {"image_url", "input_image", "image"}:
            saw_image = True
            continue

        if "text" in part:
            text_parts.append(str(part.get("text") or ""))
        else:
            text_parts.append(json.dumps(part, ensure_ascii=False))

    return "".join(text_parts), saw_image


def build_prompt(messages: list[dict[str, Any]]) -> str:
    prompt_parts = [
        "You are the assistant behind a local OpenAI-compatible bridge for paper-reader-agent.",
        "Return only the assistant reply for the conversation below.",
        "Do not mention the bridge, Codex, CLI commands, or tool execution unless the conversation explicitly asks for them.",
        "Preserve Markdown formatting when appropriate.",
        "",
        "Conversation:",
    ]

    for message in messages:
        role = str(message.get("role") or "user").strip().lower() or "user"
        content, saw_image = flatten_message_content(message.get("content"))
        if saw_image:
            raise BridgeError(
                "This local Codex bridge currently supports text-only requests.",
                code="unsupported_multimodal",
                status=400,
            )
        prompt_parts.append(f"<{role}>\n{content}\n</{role}>")

    prompt_parts.append("<assistant>")
    return "\n\n".join(prompt_parts)


def build_codex_commands(
    command_prefix: list[str],
    *,
    model: str,
    reasoning_effort: str | None,
    sandbox_mode: str,
    extra_args: list[str],
) -> list[list[str]]:
    base = [
        *command_prefix,
        "exec",
        "--skip-git-repo-check",
        "--sandbox",
        sandbox_mode,
    ]
    if reasoning_effort:
        base.extend(["-c", f"model_reasoning_effort={reasoning_effort}"])
    base.extend([*extra_args, "-m", model])
    return [
        [*base, "--output-last-message", "-"],
        [*base, "-"],
    ]


def probe_command_launchable(command_prefix: list[str], *, workdir: Path) -> None:
    try:
        subprocess.run(
            [*command_prefix, "--version"],
            cwd=str(workdir),
            text=True,
            capture_output=True,
            timeout=15,
            encoding="utf-8",
            errors="replace",
            shell=False,
        )
    except FileNotFoundError as exc:
        raise BridgeError(
            "Unable to find a runnable `codex` command. Set CODEX_BRIDGE_COMMAND to your Codex CLI executable.",
            code="codex_not_found",
            status=500,
        ) from exc
    except PermissionError as exc:
        raise BridgeError(
            "Unable to execute the configured Codex CLI. On Windows, prefer a non-WindowsApps Codex CLI such as AppData\\Roaming\\npm\\codex.cmd, or point CODEX_BRIDGE_COMMAND to a standalone executable in scripts\\codex_bridge.local.cmd.",
            code="codex_not_executable",
            status=500,
        ) from exc
    except subprocess.TimeoutExpired:
        return


def run_codex(
    prompt: str,
    *,
    model: str,
    requested_reasoning_effort: str | None,
    state: "BridgeState",
) -> str:
    errors: list[str] = []
    parsed_model, alias_effort = parse_model_spec(model)
    alias_effort = normalize_reasoning_effort(alias_effort, allow_disable=False) if alias_effort else None
    reasoning_effort = (
        requested_reasoning_effort
        if requested_reasoning_effort is not None
        else alias_effort
        if alias_effort is not None
        else state.default_reasoning_effort
    )

    for index, command in enumerate(
        build_codex_commands(
            state.command_prefix,
            model=parsed_model,
            reasoning_effort=reasoning_effort or None,
            sandbox_mode=state.sandbox_mode,
            extra_args=state.extra_args,
        )
    ):
        try:
            completed = subprocess.run(
                command,
                input=prompt,
                cwd=str(state.workdir),
                text=True,
                capture_output=True,
                timeout=state.timeout_sec,
                encoding="utf-8",
                errors="replace",
                shell=False,
            )
        except FileNotFoundError as exc:
            raise BridgeError(
                "Unable to find a runnable `codex` command. Set CODEX_BRIDGE_COMMAND to your Codex CLI executable.",
                code="codex_not_found",
                status=500,
            ) from exc
        except PermissionError as exc:
            raise BridgeError(
                "Unable to execute the configured Codex CLI. On Windows, prefer a non-WindowsApps Codex CLI such as AppData\\Roaming\\npm\\codex.cmd.",
                code="codex_not_executable",
                status=500,
            ) from exc
        except subprocess.TimeoutExpired as exc:
            raise BridgeError(
                f"Codex did not finish within {state.timeout_sec} seconds.",
                code="codex_timeout",
                status=504,
            ) from exc

        stdout = strip_ansi((completed.stdout or "").strip())
        stderr = strip_ansi((completed.stderr or "").strip())

        if completed.returncode == 0 and stdout:
            return stdout

        if reasoning_effort:
            lowered = stderr.lower()
            if "model_reasoning_effort" in lowered and any(
                token in lowered for token in ["unknown", "invalid", "unexpected", "unrecognized"]
            ):
                raise BridgeError(
                    "This Codex CLI build does not support reasoning-effort overrides yet. Update Codex or use the model default.",
                    code="unsupported_reasoning_effort",
                    status=400,
                )

        if index == 0 and "--output-last-message" in " ".join(command):
            lowered = stderr.lower()
            if any(token in lowered for token in ["output-last-message", "unexpected argument", "unknown option"]):
                errors.append(stderr or "Codex CLI does not support --output-last-message")
                continue

        detail = stderr or stdout or f"exit code {completed.returncode}"
        errors.append(detail)

    raise BridgeError(
        "Codex bridge request failed: " + " | ".join(errors[-2:]),
        code="codex_exec_failed",
        status=502,
    )


def split_stream_text(text: str, max_chars: int) -> list[str]:
    if not text:
        return []

    chunks: list[str] = []
    remaining = text
    while len(remaining) > max_chars:
        cut = remaining.rfind("\n", 0, max_chars)
        if cut <= 0:
            cut = remaining.rfind(" ", 0, max_chars)
        if cut <= 0:
            cut = max_chars
        chunks.append(remaining[:cut])
        remaining = remaining[cut:]
    if remaining:
        chunks.append(remaining)
    return chunks


def completion_payload(text: str, *, model: str, request_id: str) -> dict[str, Any]:
    now = int(time.time())
    return {
        "id": request_id,
        "object": "chat.completion",
        "created": now,
        "model": model,
        "choices": [
            {
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": text,
                },
                "finish_reason": "stop",
            }
        ],
        "usage": {
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
        },
    }


def extract_requested_reasoning(payload: dict[str, Any]) -> str | None:
    if "reasoning_effort" in payload:
        return normalize_reasoning_effort(payload.get("reasoning_effort"), allow_disable=True)
    reasoning = payload.get("reasoning")
    if isinstance(reasoning, dict) and "effort" in reasoning:
        return normalize_reasoning_effort(reasoning.get("effort"), allow_disable=True)
    return None


class BridgeState:
    def __init__(
        self,
        *,
        command_prefix: list[str],
        workdir: Path,
        sandbox_mode: str,
        timeout_sec: int,
        stream_chunk_size: int,
        api_token: str,
        extra_args: list[str],
        default_reasoning_effort: str | None,
    ) -> None:
        self.command_prefix = command_prefix
        self.workdir = workdir
        self.sandbox_mode = sandbox_mode
        self.timeout_sec = timeout_sec
        self.stream_chunk_size = max(1, stream_chunk_size)
        self.api_token = api_token
        self.extra_args = extra_args
        self.default_reasoning_effort = default_reasoning_effort


class CodexBridgeHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "PaperReaderCodexBridge/0.1"

    @property
    def state(self) -> BridgeState:
        return self.server.state  # type: ignore[attr-defined]

    def log_message(self, fmt: str, *args: Any) -> None:
        sys.stderr.write(
            "[paper-reader-bridge] %s - - [%s] %s\n"
            % (self.address_string(), self.log_date_time_string(), fmt % args)
        )

    def end_headers(self) -> None:
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        super().end_headers()

    def do_OPTIONS(self) -> None:
        self.send_response(204)
        self.end_headers()

    def do_GET(self) -> None:
        if self.path in {"/health", "/v1/health"}:
            self._send_json(
                200,
                {
                    "ok": True,
                    "command": self.state.command_prefix,
                    "workdir": str(self.state.workdir),
                    "sandbox": self.state.sandbox_mode,
                    "default_model": DEFAULT_MODEL,
                    "default_reasoning_effort": self.state.default_reasoning_effort or "",
                },
            )
            return

        if self.path == "/v1/models":
            self._send_json(
                200,
                {
                    "object": "list",
                    "data": [
                        {
                            "id": DEFAULT_MODEL,
                            "object": "model",
                            "owned_by": "paper-reader-codex-bridge",
                        }
                    ],
                },
            )
            return

        self._send_error(BridgeError("Not found", code="not_found", status=404))

    def do_POST(self) -> None:
        try:
            self._check_auth()
            if self.path != "/v1/chat/completions":
                raise BridgeError("Not found", code="not_found", status=404)

            payload = self._read_json_body()
            messages = payload.get("messages")
            if not isinstance(messages, list) or not messages:
                raise BridgeError(
                    "Request body must include a non-empty `messages` array.",
                    code="invalid_request_error",
                    status=400,
                )

            model = str(payload.get("model") or DEFAULT_MODEL).strip() or DEFAULT_MODEL
            requested_reasoning_effort = extract_requested_reasoning(payload)
            prompt = build_prompt(messages)
            response_text = run_codex(
                prompt,
                model=model,
                requested_reasoning_effort=requested_reasoning_effort,
                state=self.state,
            )
            request_id = f"chatcmpl-{uuid.uuid4().hex}"

            if payload.get("stream"):
                self._send_stream(response_text, model=model, request_id=request_id)
                return

            self._send_json(200, completion_payload(response_text, model=model, request_id=request_id))
        except BridgeError as exc:
            self._send_error(exc)
        except json.JSONDecodeError:
            self._send_error(
                BridgeError(
                    "Request body is not valid JSON.",
                    code="invalid_json",
                    status=400,
                )
            )
        except BrokenPipeError:
            pass
        except Exception as exc:  # pragma: no cover
            self._send_error(BridgeError(str(exc), code="internal_error", status=500))

    def _check_auth(self) -> None:
        token = self.state.api_token
        if not token:
            return

        auth_header = self.headers.get("Authorization", "")
        if auth_header != f"Bearer {token}":
            raise BridgeError(
                "Missing or invalid bearer token for the local Codex bridge.",
                code="unauthorized",
                status=401,
            )

    def _read_json_body(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length") or "0")
        raw = self.rfile.read(length)
        data = json.loads(raw.decode("utf-8"))
        if not isinstance(data, dict):
            raise BridgeError(
                "Request JSON must be an object.",
                code="invalid_request_error",
                status=400,
            )
        return data

    def _send_json(self, status: int, payload: dict[str, Any]) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)
        self.wfile.flush()

    def _send_error(self, exc: BridgeError) -> None:
        payload = {
            "error": {
                "message": str(exc),
                "type": "invalid_request_error" if exc.status < 500 else "server_error",
                "code": exc.code,
            }
        }
        self._send_json(exc.status, payload)

    def _send_stream(self, text: str, *, model: str, request_id: str) -> None:
        created = int(time.time())
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "close")
        self.end_headers()

        role_event = {
            "id": request_id,
            "object": "chat.completion.chunk",
            "created": created,
            "model": model,
            "choices": [
                {
                    "index": 0,
                    "delta": {"role": "assistant"},
                    "finish_reason": None,
                }
            ],
        }
        self._write_sse(role_event)

        for chunk in split_stream_text(text, self.state.stream_chunk_size):
            event = {
                "id": request_id,
                "object": "chat.completion.chunk",
                "created": created,
                "model": model,
                "choices": [
                    {
                        "index": 0,
                        "delta": {"content": chunk},
                        "finish_reason": None,
                    }
                ],
            }
            self._write_sse(event)

        final_event = {
            "id": request_id,
            "object": "chat.completion.chunk",
            "created": created,
            "model": model,
            "choices": [
                {
                    "index": 0,
                    "delta": {},
                    "finish_reason": "stop",
                }
            ],
        }
        self._write_sse(final_event)
        self.wfile.write(b"data: [DONE]\n\n")
        self.wfile.flush()

    def _write_sse(self, payload: dict[str, Any]) -> None:
        line = f"data: {json.dumps(payload, ensure_ascii=False)}\n\n".encode("utf-8")
        self.wfile.write(line)
        self.wfile.flush()


def make_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run a local OpenAI-compatible bridge backed by `codex exec`.",
    )
    parser.add_argument("--host", default=os.environ.get("CODEX_BRIDGE_HOST", DEFAULT_HOST))
    parser.add_argument("--port", type=int, default=int(os.environ.get("CODEX_BRIDGE_PORT", str(DEFAULT_PORT))))
    parser.add_argument(
        "--workdir",
        default=os.environ.get(
            "CODEX_BRIDGE_WORKDIR",
            str(Path(__file__).resolve().parent / ".codex-bridge-workdir"),
        ),
    )
    parser.add_argument(
        "--command",
        default=os.environ.get("CODEX_BRIDGE_COMMAND", "codex"),
        help="Command used to launch the Codex CLI.",
    )
    parser.add_argument(
        "--sandbox",
        default=os.environ.get("CODEX_BRIDGE_SANDBOX", "read-only"),
        help="Sandbox mode passed to `codex exec --sandbox`.",
    )
    parser.add_argument(
        "--timeout-sec",
        type=int,
        default=DEFAULT_TIMEOUT_SEC,
        help="Timeout for each `codex exec` request.",
    )
    parser.add_argument(
        "--stream-chunk-size",
        type=int,
        default=DEFAULT_STREAM_CHUNK_SIZE,
        help="Maximum characters per streamed delta chunk.",
    )
    parser.add_argument(
        "--api-token",
        default=os.environ.get("CODEX_BRIDGE_API_TOKEN", ""),
        help="Optional bearer token required by the bridge.",
    )
    parser.add_argument(
        "--extra-args",
        default=os.environ.get("CODEX_BRIDGE_EXTRA_ARGS", ""),
        help="Extra arguments appended before `-m MODEL -`.",
    )
    return parser


def main() -> int:
    try:
        args = make_parser().parse_args()
        state = BridgeState(
            command_prefix=parse_command(args.command),
            workdir=ensure_workdir(Path(args.workdir).resolve()),
            sandbox_mode=args.sandbox,
            timeout_sec=max(1, args.timeout_sec),
            stream_chunk_size=max(1, args.stream_chunk_size),
            api_token=args.api_token,
            extra_args=shlex.split(args.extra_args, posix=os.name != "nt"),
            default_reasoning_effort=normalize_reasoning_effort(DEFAULT_REASONING_RAW, allow_disable=False),
        )
        probe_command_launchable(state.command_prefix, workdir=state.workdir)

        server = ThreadingHTTPServer((args.host, args.port), CodexBridgeHandler)
        server.state = state  # type: ignore[attr-defined]

        print(
            json.dumps(
                {
                    "ok": True,
                    "host": args.host,
                    "port": args.port,
                    "workdir": str(state.workdir),
                    "command": state.command_prefix,
                    "sandbox": state.sandbox_mode,
                    "default_model": DEFAULT_MODEL,
                    "default_reasoning_effort": state.default_reasoning_effort or "",
                },
                ensure_ascii=False,
            )
        )

        try:
            server.serve_forever()
        except KeyboardInterrupt:
            print("\nShutting down paper-reader Codex bridge...", file=sys.stderr)
        finally:
            server.server_close()
        return 0
    except BridgeError as exc:
        print(f"[paper-reader-agent bridge] {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
