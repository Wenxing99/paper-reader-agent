from __future__ import annotations

import base64
import json
import re
from pathlib import Path
from typing import Any

from paper_reader_agent.services.bridge import request_chat_completion

REPO_ROOT = Path(__file__).resolve().parents[3]
FORMULA_DEBUG_DIR = REPO_ROOT / ".tmp" / "formula-stage"

MATH_SYMBOLS = set(
    "=<>"
    "\u2264\u2265\u2248\u2260"
    "\u00b1\u00d7\u00f7"
    "\u2211\u220f\u222b\u221a\u221e"
    "\u2208\u2200\u2203\u2202\u2207"
    "\u03bb\u03bc\u03c3\u03c0\u03b8\u03b1\u03b2\u03b3\u03b4\u03a9"
    "_^{}[]()|"
)
MATH_TOKEN_RE = re.compile(
    r"(?:\\[A-Za-z]+|\b(?:theorem|lemma|corollary|proposition|proof|algorithm|min|max|argmin|argmax|sqrt|ceil|floor|log|exp)\b|[A-Za-z0-9]\s*[=<>]\s*[A-Za-z0-9])",
    re.IGNORECASE,
)
SECTION_RE = re.compile(r"(?im)^(CONFIDENCE|LATEX|TRANSCRIPT|WARNINGS):[ \t]*(.*)$")
LATEX_FENCE_RE = re.compile(r"```(?:latex)?[ \t]*\n?(.*?)```", re.IGNORECASE | re.DOTALL)
INLINE_LATEX_RE = re.compile(r"\\\((.+?)\\\)", re.DOTALL)
DISPLAY_LATEX_RE = re.compile(r"\\\[(.+?)\\\]", re.DOTALL)
FENCED_LATEX_BLOCK_RE = re.compile(r"```latex\s*(.*?)```", re.IGNORECASE | re.DOTALL)
PSEUDO_DISPLAY_MATH_RE = re.compile(r"\[\s*([^\[\]\n]{3,400})\s*\]")
PSEUDO_INLINE_MATH_RE = re.compile(r"\(([^()\n]{1,120})\)")
PROTECTED_MATH_RE = re.compile(r"\$\$.*?\$\$|\$[^$\n]+\$", re.DOTALL)
DISPLAY_DOLLAR_RE = re.compile(r"\$\$\s*(.*?)\s*\$\$", re.DOTALL)
TAG_RE = re.compile(r"\\tag\{([^}]+)\}")


def should_use_formula_stage(selected_text: str) -> bool:
    text = str(selected_text or "").strip()
    if len(text) < 18:
        return False

    symbol_hits = sum(1 for char in text if char in MATH_SYMBOLS)
    has_token = bool(MATH_TOKEN_RE.search(text))
    has_multiple_lines = text.count("\n") >= 1

    if symbol_hits >= 2:
        return True
    if symbol_hits >= 1 and has_token:
        return True
    if symbol_hits >= 1 and has_multiple_lines:
        return True
    return False


def request_formula_stage_a(
    bridge: dict[str, str],
    *,
    image_path: Path,
    selected_text: str,
) -> dict[str, Any]:
    data_url = image_path_to_data_url(image_path)
    raw = request_chat_completion(
        bridge,
        messages=[
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": build_formula_stage_a_prompt(selected_text)},
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": data_url,
                        },
                    },
                ],
            },
        ],
        max_tokens=1400,
        temperature=0.1,
        timeout_sec=90,
    )
    return parse_formula_stage_a_output(raw)


def has_formula_stage_a_content(payload: dict[str, Any] | None) -> bool:
    if not isinstance(payload, dict):
        return False
    return bool(str(payload.get("latex") or "").strip())


def request_formula_stage_b(
    bridge: dict[str, str],
    *,
    selected_text: str,
    context_text: str,
    mode: str,
    stage_a_result: dict[str, Any],
) -> str:
    if mode not in {"explain", "translate"}:
        raise ValueError(f"Unsupported Stage B mode: {mode}")

    answer = request_chat_completion(
        bridge,
        messages=[
            {
                "role": "system",
                "content": (
                    "You are an academic reading assistant. Respond in Simplified Chinese. "
                    "For math-heavy selections, treat the recovered LaTeX transcription as the primary representation "
                    "of the selected crop. Use the provided paper context to ground the answer. "
                    "Do not mention crop images, OCR, Stage A, Stage B, or internal pipeline details in the final answer "
                    "unless a recognition warning materially changes the interpretation."
                ),
            },
            {
                "role": "system",
                "content": f"Paper context:\n{context_text}",
            },
            {
                "role": "user",
                "content": build_formula_stage_b_prompt(
                    selected_text=selected_text,
                    mode=mode,
                    stage_a_result=stage_a_result,
                ),
            },
        ],
        max_tokens=1200,
        temperature=0.2,
    )
    normalized = normalize_stage_b_markdown(answer)
    with_placeholders = _inject_display_equation_placeholders(normalized, stage_a_result)
    final_answer = _prefer_stage_a_display_equations(with_placeholders, stage_a_result)
    _write_formula_stage_debug(
        mode=mode,
        selected_text=selected_text,
        stage_a_result=stage_a_result,
        raw_answer=answer,
        normalized_answer=normalized,
        placeholder_answer=with_placeholders,
        final_answer=final_answer,
    )
    return final_answer


def _write_formula_stage_debug(
    *,
    mode: str,
    selected_text: str,
    stage_a_result: dict[str, Any],
    raw_answer: str,
    normalized_answer: str,
    placeholder_answer: str,
    final_answer: str,
) -> None:
    try:
        FORMULA_DEBUG_DIR.mkdir(parents=True, exist_ok=True)
        stage_a_latex = str((stage_a_result or {}).get("latex") or "")
        payload = {
            "mode": mode,
            "selected_text": selected_text,
            "stage_a_confidence": str((stage_a_result or {}).get("confidence") or ""),
            "stage_a_warnings": list((stage_a_result or {}).get("warnings") or []),
            "stage_a_latex": stage_a_latex,
            "reusable_equations": _select_reusable_display_equations(_extract_stage_a_reusable_equations(stage_a_latex)),
            "raw_stage_b_answer": raw_answer,
            "normalized_stage_b_answer": normalized_answer,
            "placeholder_stage_b_answer": placeholder_answer,
            "final_stage_b_answer": final_answer,
        }
        (FORMULA_DEBUG_DIR / "last-stage-b-debug.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except Exception:
        return


def image_path_to_data_url(image_path: Path) -> str:
    suffix = image_path.suffix.lower()
    mime = {
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".webp": "image/webp",
    }.get(suffix)
    if not mime:
        raise ValueError(f"Unsupported crop image format: {suffix or 'unknown'}")
    payload = base64.b64encode(image_path.read_bytes()).decode("ascii")
    return f"data:{mime};base64,{payload}"


def build_formula_stage_a_prompt(selected_text: str) -> str:
    return "\n".join(
        [
            "Transcribe the entire selected paper crop into one best-effort LaTeX rendition.",
            "Return plain text only, using exactly this structure:",
            "CONFIDENCE: high|medium|low",
            "LATEX:",
            "```latex",
            "<one complete LaTeX transcription for the whole crop>",
            "```",
            "WARNINGS:",
            "- <one warning per line, or '- none'>",
            "Rules:",
            "- Do not return JSON.",
            "- Do not add a TRANSCRIPT section.",
            "- Do not summarize or select only the main formulas.",
            "- Transcribe the whole crop as faithfully as possible, including prose, theorem labels, definitions, notation, constraints, and displayed equations.",
            "- Prefer one complete latex block for the entire crop.",
            "- Preserve math symbols and theorem labels carefully.",
            "- If some symbols are uncertain, keep the best guess in `LATEX` and explain the uncertainty in `WARNINGS`.",
            "- Keep the response faithful to the crop rather than explanatory.",
            "Noisy text extracted from the PDF selection (may be corrupted):",
            selected_text,
        ]
    )


def build_formula_stage_b_prompt(*, selected_text: str, mode: str, stage_a_result: dict[str, Any]) -> str:
    latex = str(stage_a_result.get("latex") or "").strip()
    confidence = str(stage_a_result.get("confidence") or "").strip().lower() or "medium"
    transcript = str(stage_a_result.get("transcript") or "").strip()
    warnings = [
        str(item or "").strip()
        for item in (stage_a_result.get("warnings") or [])
        if str(item or "").strip()
    ]
    warning_block = "\n".join(f"- {item}" for item in warnings) if warnings else "- none"
    display_equations = _select_reusable_display_equations(_extract_stage_a_reusable_equations(latex))

    if mode == "translate":
        task_lines = [
            "Translate the following math-heavy paper selection into fluent Simplified Chinese Markdown.",
            "Use `Recovered LaTeX transcription` as the primary representation; use `Noisy selected text` only as a secondary hint.",
            "Preserve formulas, theorem labels, variable names, and mathematical notation.",
            "Format every inline formula as `$...$`.",
            "Format every standalone formula as `$$...$$`.",
            "Keep `_` for subscripts; use `\\_` only for a literal underscore character.",
            "When a star is used as a wildcard or index symbol inside math, prefer `\\ast` over raw `*`.",
            "When using commands like `\\hat`, `\\tilde`, `\\bar`, `\\mathbb`, or `\\mathcal`, wrap the target symbol in braces, for example `\\hat{K}` or `\\mathbb{P}`.",
            "When you show a standalone formula or displayed equation that already appears in `Recovered LaTeX transcription`, copy it directly instead of rewriting its LaTeX.",
            "Prefer exact symbol and sequence notation copied from `Recovered LaTeX transcription`; do not invent new shorthand for indexed families unless copied exactly.",
            "Do not alter backslashes, braces, subscripts, superscripts, or delimiter commands inside copied equations unless absolutely necessary.",
            "Do not leave bare LaTeX commands in prose.",
            "Never use plain parentheses like `(L)` or square brackets like `[ ... ]` as math delimiters; use `$...$` or `$$...$$` instead.",
            "Long formulas should be placed on their own lines instead of being embedded in a paragraph.",
            "Do not write standalone formulas or long display equations from scratch when a recovered version already exists. If you need to reference a recovered standalone/display equation, use its placeholder token exactly, such as `{{DISPLAY_EQ_1}}`, on its own line.",
            "Do not mention the crop image, recognition process, internal stages, or system drafts.",
            "Only mention uncertainty if `Recognition warnings` materially changes the meaning.",
            "After the translation, add one short sentence describing the role of this passage in the paper.",
            "Return Markdown only.",
        ]
    else:
        task_lines = [
            "Explain the following math-heavy paper selection in Simplified Chinese Markdown.",
            "Use `Recovered LaTeX transcription` as the primary representation; use `Noisy selected text` only as a secondary hint.",
            "Format every inline formula as `$...$`.",
            "Format every standalone formula as `$$...$$`.",
            "Keep `_` for subscripts; use `\\_` only for a literal underscore character.",
            "When a star is used as a wildcard or index symbol inside math, prefer `\\ast` over raw `*`.",
            "When using commands like `\\hat`, `\\tilde`, `\\bar`, `\\mathbb`, or `\\mathcal`, wrap the target symbol in braces, for example `\\hat{K}` or `\\mathbb{P}`.",
            "When you show a standalone formula or displayed equation that already appears in `Recovered LaTeX transcription`, copy it directly instead of rewriting its LaTeX.",
            "Prefer exact symbol and sequence notation copied from `Recovered LaTeX transcription`; do not invent new shorthand for indexed families unless copied exactly.",
            "Do not alter backslashes, braces, subscripts, superscripts, or delimiter commands inside copied equations unless absolutely necessary.",
            "Do not leave bare LaTeX commands in prose.",
            "Never use plain parentheses like `(L)` or square brackets like `[ ... ]` as math delimiters; use `$...$` or `$$...$$` instead.",
            "Long formulas should be placed on their own lines instead of being embedded in a paragraph.",
            "Do not write standalone formulas or long display equations from scratch when a recovered version already exists. If you need to reference a recovered standalone/display equation, use its placeholder token exactly, such as `{{DISPLAY_EQ_1}}`, on its own line.",
            "Do not mention the crop image, recognition process, internal stages, or system drafts.",
            "Only mention uncertainty if `Recognition warnings` materially changes the interpretation.",
            "Use these exact Chinese section headings:",
            "1. \u4e00\u53e5\u8bdd\u603b\u7ed3",
            "2. \u8fd9\u4e2a\u516c\u5f0f / \u5b9a\u7406\u5728\u8bf4\u4ec0\u4e48",
            "3. \u5fc5\u8981\u7b26\u53f7\u6216\u91cf\u7684\u8bf4\u660e",
            "4. \u8fd9\u6bb5\u5185\u5bb9\u5728\u6574\u7bc7\u8bba\u6587\u91cc\u7684\u4f5c\u7528",
            "Do not invent assumptions that are not supported by the paper context.",
            "Return Markdown only.",
        ]

    sections = [
        "\n".join(task_lines),
        "Recovered LaTeX transcription:",
        "```latex",
        latex,
        "```",
        f"Recognition confidence: {confidence}",
        "Recognition warnings:",
        warning_block,
    ]

    if display_equations:
        sections.extend(["Recovered display equations:"])
        for index, equation in enumerate(display_equations, start=1):
            sections.extend([f"{{{{DISPLAY_EQ_{index}}}}}", "```latex", equation, "```"] )

    if transcript:
        sections.extend(
            [
                "Additional transcription notes:",
                transcript,
            ]
        )

    sections.extend(
        [
            "Noisy selected text:",
            selected_text,
        ]
    )
    return "\n".join(sections)


def normalize_stage_b_markdown(text: str) -> str:
    value = str(text or "").replace("\r\n", "\n").strip()
    if not value:
        return value

    value = FENCED_LATEX_BLOCK_RE.sub(lambda match: _display_math_block(match.group(1)), value)
    value = DISPLAY_LATEX_RE.sub(lambda match: _display_math_block(match.group(1)), value)
    value = INLINE_LATEX_RE.sub(lambda match: _inline_math(match.group(1)), value)
    value = _normalize_standalone_math_lines(value)
    value = _normalize_pseudo_math_outside_existing_delimiters(value)
    value = _normalize_markdown_sensitive_math_tokens(value)
    return value


def parse_formula_stage_a_output(raw: str) -> dict[str, Any]:
    text = str(raw or "").strip()

    labeled = _parse_labeled_output(text)
    if labeled is not None:
        return labeled

    cleaned = _extract_json_object(text)
    try:
        payload = json.loads(cleaned)
    except Exception:
        return {
            "latex": text,
            "transcript": "",
            "confidence": "low",
            "warnings": ["Model did not return parseable Stage A sections; preserved raw Stage A output."],
        }
    return normalize_formula_stage_a(payload)


def normalize_formula_stage_a(payload: dict[str, Any]) -> dict[str, Any]:
    latex = str(payload.get("latex") or "").strip()
    transcript = str(payload.get("transcript") or payload.get("plain_text") or "").strip()
    confidence = str(payload.get("confidence") or "").strip().lower()
    if confidence not in {"high", "medium", "low"}:
        confidence = "medium" if (latex or transcript) else "low"

    warnings_raw = payload.get("warnings") or []
    warnings: list[str] = []
    if isinstance(warnings_raw, list):
        for item in warnings_raw:
            text = str(item or "").strip()
            if text and text.lower() != "none":
                warnings.append(text)
    else:
        text = str(warnings_raw or "").strip()
        if text and text.lower() != "none":
            warnings.append(text)

    return {
        "latex": latex,
        "transcript": transcript,
        "confidence": confidence,
        "warnings": warnings,
    }


def _parse_labeled_output(text: str) -> dict[str, Any] | None:
    matches = list(SECTION_RE.finditer(text))
    if not matches:
        return None

    sections: dict[str, str] = {}
    for index, match in enumerate(matches):
        label = match.group(1).upper()
        inline_value = (match.group(2) or "").strip()
        body_start = match.end()
        body_end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        body = text[body_start:body_end].strip()
        combined = "\n".join(part for part in [inline_value, body] if part).strip()
        sections[label] = combined

    latex, latex_extra = _extract_latex_and_extra(sections.get("LATEX", ""))
    transcript = sections.get("TRANSCRIPT", "").strip()
    if latex_extra and not transcript:
        transcript = latex_extra
    elif latex_extra and latex_extra not in transcript:
        transcript = "\n\n".join(part for part in [transcript, latex_extra] if part).strip()

    confidence = _normalize_confidence(sections.get("CONFIDENCE", ""))
    warnings = _parse_warning_lines(sections.get("WARNINGS", ""))

    if not any([latex, transcript, warnings, confidence]):
        return None

    return normalize_formula_stage_a(
        {
            "latex": latex,
            "transcript": transcript,
            "confidence": confidence,
            "warnings": warnings,
        }
    )


def _extract_latex_and_extra(text: str) -> tuple[str, str]:
    value = text.strip()
    if not value:
        return "", ""

    matches = list(LATEX_FENCE_RE.finditer(value))
    if not matches:
        return value, ""

    latex_parts: list[str] = []
    extra_parts: list[str] = []
    cursor = 0

    for index, match in enumerate(matches):
        outside = value[cursor:match.start()].strip()
        if outside:
            if index == 0 or _looks_like_latex_content(outside):
                latex_parts.append(outside)
            else:
                extra_parts.append(outside)

        block = match.group(1).strip()
        if block:
            latex_parts.append(block)
        cursor = match.end()

    tail = value[cursor:].strip()
    if tail:
        if _looks_like_explanatory_text(tail):
            extra_parts.append(tail)
        elif _looks_like_latex_content(tail):
            latex_parts.append(tail)
        else:
            extra_parts.append(tail)

    latex = "\n\n".join(part for part in latex_parts if part).strip()
    extra = "\n\n".join(part for part in extra_parts if part).strip()
    return latex, extra


def _looks_like_latex_content(text: str) -> bool:
    value = text.strip()
    if not value:
        return False
    if re.search(r"\\[A-Za-z]+", value):
        return True
    if sum(1 for char in value if char in MATH_SYMBOLS) >= 3:
        return True
    if re.search(r"\b(?:Theorem|Lemma|Corollary|Proposition|Proof)\b", value):
        return True
    return False


def _looks_like_explanatory_text(text: str) -> bool:
    value = text.strip().lower()
    return value.startswith((
        "the surrounding text",
        "the theorem",
        "the text says",
        "this theorem",
        "this crop",
        "the excerpt",
        "this excerpt",
    ))


def _display_math_block(value: str) -> str:
    content = _normalize_math_token_content(value.strip())
    if not content:
        return ""
    return f"$$\n{content}\n$$"


def _inline_math(value: str) -> str:
    content = _normalize_math_token_content(value.strip())
    if not content:
        return ""
    return f"${content}$"


def _normalize_markdown_sensitive_math_tokens(text: str) -> str:
    def replace(match: re.Match[str]) -> str:
        token = match.group(0)
        if token.startswith("$$"):
            content = token[2:-2]
            normalized = _normalize_math_token_content(content)
            return f"$${normalized}$$"
        content = token[1:-1]
        normalized = _normalize_math_token_content(content)
        return f"${normalized}$"

    return PROTECTED_MATH_RE.sub(replace, text)


def _normalize_math_token_content(text: str) -> str:
    value = text
    value = re.sub(r'(?<=,)\s*\\dot\s*\{?\s*s\s*\}?\s*(?=,)', r'\\ldots', value)
    value = re.sub(r'(?<=,)\*', lambda _: r'\ast', value)
    value = re.sub(r'(?<=\{)\*(?=\})', lambda _: r'\ast', value)
    value = re.sub(r'(?<=_)\*(?=[^A-Za-z]|$)', lambda _: r'\ast', value)

    # Prefer braced forms for a small set of common style commands.
    value = re.sub(r'\\(hat|tilde|bar|check|breve|vec|dot|ddot|widehat|widetilde)\s+(?!\{)([A-Za-z])', r'\\\1{\2}', value)
    value = re.sub(r'\\(mathbb|mathcal|mathbf|mathrm|mathsf|mathtt|mathfrak)\s+(?!\{)([A-Za-z])', r'\\\1{\2}', value)
    value = re.sub(r'\\(hat|tilde|bar|check|breve|vec|dot|ddot|widehat|widetilde)(?!\{)([A-Za-z])\b', r'\\\1{\2}', value)
    value = re.sub(r'\\(mathbb|mathcal|mathbf|mathrm|mathsf|mathtt|mathfrak)(?!\{)([A-Za-z])\b', r'\\\1{\2}', value)
    return value


def _normalize_pseudo_math_outside_existing_delimiters(text: str) -> str:
    parts: list[str] = []
    cursor = 0
    for match in PROTECTED_MATH_RE.finditer(text):
        outside = text[cursor:match.start()]
        if outside:
            outside = PSEUDO_DISPLAY_MATH_RE.sub(_normalize_pseudo_display_match, outside)
            outside = _normalize_pseudo_inline_outside_existing_delimiters(outside)
            parts.append(outside)
        parts.append(match.group(0))
        cursor = match.end()

    tail = text[cursor:]
    if tail:
        tail = PSEUDO_DISPLAY_MATH_RE.sub(_normalize_pseudo_display_match, tail)
        tail = _normalize_pseudo_inline_outside_existing_delimiters(tail)
        parts.append(tail)
    return "".join(parts)


def _normalize_standalone_math_lines(text: str) -> str:
    lines = text.split("\n")
    normalized_lines: list[str] = []
    inside_display = False

    for line in lines:
        stripped = line.strip()
        if stripped == "$$":
            normalized_lines.append(line)
            inside_display = not inside_display
            continue

        if inside_display:
            normalized_lines.append(line)
            continue

        if _looks_like_standalone_math_line(line):
            normalized_lines.append(_display_math_block(line))
        else:
            normalized_lines.append(line)

    return "\n".join(normalized_lines)


def _normalize_pseudo_inline_outside_existing_delimiters(text: str) -> str:
    parts: list[str] = []
    cursor = 0
    for match in PROTECTED_MATH_RE.finditer(text):
        outside = text[cursor:match.start()]
        if outside:
            outside = PSEUDO_INLINE_MATH_RE.sub(_normalize_pseudo_inline_match, outside)
            parts.append(outside)
        parts.append(match.group(0))
        cursor = match.end()

    tail = text[cursor:]
    if tail:
        tail = PSEUDO_INLINE_MATH_RE.sub(_normalize_pseudo_inline_match, tail)
        parts.append(tail)
    return "".join(parts)


def _normalize_pseudo_display_match(match: re.Match[str]) -> str:
    content = match.group(1).strip()
    if not _looks_like_display_math_fragment(content):
        return match.group(0)
    return _display_math_block(content)


def _normalize_pseudo_inline_match(match: re.Match[str]) -> str:
    content = match.group(1).strip()
    if not _looks_like_inline_math_fragment(content):
        return match.group(0)
    return _inline_math(content)


def _looks_like_display_math_fragment(text: str) -> bool:
    value = text.strip()
    if not value or "$" in value:
        return False
    if re.search(r"\\[A-Za-z]+", value):
        return True
    if any(char in value for char in "=<>_^{}|/"):
        return True
    return False


def _looks_like_inline_math_fragment(text: str) -> bool:
    value = text.strip()
    if not value or "$" in value or " " in value:
        return False
    if re.search(r"\\[A-Za-z]+", value):
        return True
    if any(char in value for char in "_^{}=<>|/"):
        return True
    if re.fullmatch(r"[A-Za-z]", value):
        return True
    if re.fullmatch(r"[A-Za-z](?:_[A-Za-z0-9]+)?", value):
        return True
    return False


def _looks_like_standalone_math_line(text: str) -> bool:
    value = text.strip()
    if not value:
        return False
    if value.startswith(("$$", "- ", "* ", "1. ", "2. ", "3. ", "4. ")):
        return False
    if "$" in value:
        return False
    if len(value) < 12:
        return False
    if not value.startswith("\\"):
        return False

    if re.search(r"\\tag\{", value):
        return True
    if re.search(r"\\(?:argmin|argmax|min|max)\b", value) and "=" in value:
        return True
    if re.search(r"(?:=|\\(?:le|ge)|\\to|\\infty)", value):
        return True
    return False


def _normalize_confidence(text: str) -> str:
    value = str(text or "").strip().lower()
    if value.startswith("high"):
        return "high"
    if value.startswith("medium"):
        return "medium"
    if value.startswith("low"):
        return "low"
    return value



def _inject_display_equation_placeholders(text: str, stage_a_result: dict[str, Any]) -> str:
    value = str(text or "")
    display_equations = _select_reusable_display_equations(
        _extract_stage_a_reusable_equations(str((stage_a_result or {}).get("latex") or ""))
    )
    if not display_equations:
        return value

    for index, equation in enumerate(display_equations, start=1):
        value = value.replace(f"{{{{DISPLAY_EQ_{index}}}}}", _display_math_block(equation))
    return value


def _prefer_stage_a_display_equations(text: str, stage_a_result: dict[str, Any]) -> str:
    stage_a_latex = str((stage_a_result or {}).get("latex") or "").strip()
    if not stage_a_latex:
        return text

    preferred_blocks = _select_reusable_display_equations(_extract_stage_a_reusable_equations(stage_a_latex))
    if not preferred_blocks:
        return text

    matches = list(DISPLAY_DOLLAR_RE.finditer(text))
    if not matches:
        return text

    tagged_preferred = {
        tag: block
        for block in preferred_blocks
        if (tag := _extract_equation_tag(block))
    }
    if tagged_preferred:
        parts: list[str] = []
        cursor = 0
        replaced_any = False
        for match in matches:
            parts.append(text[cursor:match.start()])
            candidate = match.group(1).strip()
            tag = _extract_equation_tag(candidate)
            if tag and tag in tagged_preferred:
                parts.append(_display_math_block(tagged_preferred[tag]))
                replaced_any = True
            else:
                parts.append(match.group(0))
            cursor = match.end()
        parts.append(text[cursor:])
        if replaced_any:
            return "".join(parts)

    if len(matches) != len(preferred_blocks):
        return text

    parts = []
    cursor = 0
    for index, match in enumerate(matches):
        parts.append(text[cursor:match.start()])
        if index < len(preferred_blocks):
            parts.append(_display_math_block(preferred_blocks[index]))
        else:
            parts.append(match.group(0))
        cursor = match.end()
    parts.append(text[cursor:])
    return "".join(parts)


def _extract_stage_a_display_equations(text: str) -> list[str]:
    blocks: list[str] = []

    for match in DISPLAY_LATEX_RE.finditer(text):
        content = match.group(1).strip()
        if content:
            blocks.append(content)

    for match in DISPLAY_DOLLAR_RE.finditer(text):
        content = match.group(1).strip()
        if content and content not in blocks:
            blocks.append(content)

    return blocks


def _extract_stage_a_reusable_equations(text: str) -> list[str]:
    value = str(text or "")
    blocks = _extract_stage_a_display_equations(value)
    outside = DISPLAY_LATEX_RE.sub("", value)
    outside = DISPLAY_DOLLAR_RE.sub("", outside)

    for line in outside.splitlines():
        candidate = line.strip()
        if candidate and _looks_like_standalone_math_line(candidate) and candidate not in blocks:
            blocks.append(candidate)

    return blocks


def _select_reusable_display_equations(blocks: list[str]) -> list[str]:
    selected: list[str] = []
    for block in blocks:
        if _looks_like_complex_display_equation(block):
            selected.append(block)
    return selected


def _extract_equation_tag(text: str) -> str | None:
    match = TAG_RE.search(str(text or ""))
    if not match:
        return None
    return match.group(1).strip() or None


def _looks_like_complex_display_equation(text: str) -> bool:
    value = str(text or "").strip()
    if not value:
        return False

    command_count = len(re.findall(r"\\[A-Za-z]+", value))
    if re.search(r"\\tag\{", value):
        return True
    if re.search(r"\\(?:argmin|argmax)\b", value):
        return True
    if len(value) >= 90:
        return True
    if command_count >= 8:
        return True
    if re.search(r"\\mathbb\{(?:P|E)\}", value) and re.search(r"[=<>]|\\(?:le|ge|forall|exists)", value):
        return True
    if re.search(r"\\mathbb\{(?:R|S)\}", value) and re.search(r"\\(?:le|ge|frac|forall|exists)", value):
        return True
    if re.search(r"\\(?:frac|forall|exists|sum|prod|int)", value) and re.search(r"[=<>]|\\(?:le|ge)", value):
        return True
    return False


def _parse_warning_lines(text: str) -> list[str]:
    value = str(text or "").strip()
    if not value:
        return []

    warnings: list[str] = []
    for line in value.splitlines():
        cleaned = line.strip()
        if cleaned.startswith("- "):
            cleaned = cleaned[2:].strip()
        elif cleaned.startswith("*"):
            cleaned = cleaned[1:].strip()
        if cleaned and cleaned.lower() != "none":
            warnings.append(cleaned)
    return warnings


def _extract_json_object(raw: str) -> str:
    text = str(raw or "").strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if len(lines) >= 3 and lines[0].startswith("```") and lines[-1].startswith("```"):
            text = "\n".join(lines[1:-1]).strip()
            if text.lower().startswith("json\n"):
                text = text[5:]

    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end >= start:
        return text[start : end + 1]
    return text
