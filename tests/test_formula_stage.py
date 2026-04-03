from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from unittest import mock


REPO_ROOT = Path(__file__).resolve().parent
if REPO_ROOT.name == "tests":
    REPO_ROOT = REPO_ROOT.parent
SRC_ROOT = REPO_ROOT / "src"

if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

import paper_reader_agent.services.formula_stage as formula_stage
from paper_reader_agent.services.formula_stage import (
    build_formula_stage_b_prompt,
    has_formula_stage_a_content,
    normalize_stage_b_markdown,
    parse_formula_stage_a_output,
    request_formula_stage_b,
    should_use_formula_stage,
)


class FormulaStageTests(unittest.TestCase):
    def test_should_use_formula_stage_for_math_heavy_selection(self) -> None:
        text = "Theorem 1 states that ||x - y|| <= C / sqrt(n) for all x in R^d."
        self.assertTrue(should_use_formula_stage(text))

    def test_should_not_use_formula_stage_for_plain_prose(self) -> None:
        text = "This paragraph only explains the motivation and background of the paper in plain language."
        self.assertFalse(should_use_formula_stage(text))

    def test_has_formula_stage_a_content_requires_latex(self) -> None:
        self.assertTrue(has_formula_stage_a_content({"latex": r"\alpha + \beta"}))
        self.assertFalse(has_formula_stage_a_content({"latex": "   "}))
        self.assertFalse(has_formula_stage_a_content(None))

    def test_build_formula_stage_b_prompt_requires_katex_friendly_delimiters(self) -> None:
        prompt = build_formula_stage_b_prompt(
            selected_text="noisy <= text",
            mode="explain",
            stage_a_result={
                "latex": "\\[\n\\mathbb{E}\\, d_F(S(\\hat A_0^L), S(A_0)) \\le C / L^{1/2}.\n\\]",
                "confidence": "high",
                "warnings": ["One calligraphic symbol is best-effort."],
            },
        )
        self.assertIn("Recovered LaTeX transcription:", prompt)
        self.assertIn(r"\mathbb{E}\, d_F", prompt)
        self.assertIn("Format every inline formula as `$...$`", prompt)
        self.assertIn("Format every standalone formula as `$$...$$`", prompt)
        self.assertIn("Use these exact Chinese section headings:", prompt)
        self.assertIn("1. 一句话总结", prompt)
        self.assertIn("2. 这个公式 / 定理在说什么", prompt)
        self.assertIn("copy it directly instead of rewriting its LaTeX", prompt)
        self.assertIn("Do not alter backslashes, braces, subscripts, superscripts", prompt)
        self.assertIn("Do not leave bare LaTeX commands in prose.", prompt)
        self.assertIn("Never use plain parentheses like `(L)` or square brackets like `[ ... ]`", prompt)
        self.assertIn("Keep `_` for subscripts", prompt)
        self.assertIn(r"prefer `\ast` over raw `*`", prompt)
        self.assertIn("wrap the target symbol in braces", prompt)
        self.assertIn("Recovered display equations:", prompt)
        self.assertIn("{{DISPLAY_EQ_1}}", prompt)
        self.assertIn("Do not write standalone formulas or long display equations from scratch", prompt)

    def test_build_formula_stage_b_prompt_includes_short_tagged_display_equation_placeholder(self) -> None:
        prompt = build_formula_stage_b_prompt(
            selected_text="noisy text",
            mode="explain",
            stage_a_result={
                "latex": "\\[\n\\hat{u}(\\lambda)=\\arg\\min_{u \\in \\mathbb{R}^n} H\\bigl(u,\\{Y_i\\}_{i=1}^n,\\lambda\\bigr). \\tag{11}\n\\]",
                "confidence": "high",
                "warnings": [],
            },
        )
        self.assertIn("Recovered display equations:", prompt)
        self.assertIn("{{DISPLAY_EQ_1}}", prompt)
        self.assertIn(r"\arg\min", prompt)
        self.assertIn(r"\tag{11}", prompt)


    def test_build_formula_stage_b_prompt_includes_standalone_formula_placeholder(self) -> None:
        prompt = build_formula_stage_b_prompt(
            selected_text="noisy text",
            mode="explain",
            stage_a_result={
                "latex": r"\hat{u}(\lambda)=\arg\min_{u \in \mathbb{R}^n} H\bigl(u,\{Y_i\}_{i=1}^n,\lambda\bigr). \tag{11}",
                "confidence": "high",
                "warnings": [],
            },
        )
        self.assertIn("Recovered display equations:", prompt)
        self.assertIn("{{DISPLAY_EQ_1}}", prompt)
        self.assertIn(r"\arg\min", prompt)
        self.assertIn(r"\tag{11}", prompt)
    def test_normalize_stage_b_markdown_converts_inline_delimiters(self) -> None:
        result = normalize_stage_b_markdown(r"The key object is \(\Pi^\infty\) and the rate is \(L^{-1/2}\).")
        self.assertEqual(result, r"The key object is $\Pi^\infty$ and the rate is $L^{-1/2}$.")

    def test_normalize_stage_b_markdown_converts_display_delimiters(self) -> None:
        source = "Theorem:\n\\[\\mathbb{E} d_F(S(\\hat A), S(A_0)) \\le C\\]\nDone."
        result = normalize_stage_b_markdown(source)
        expected = "Theorem:\n$$\n" + r"\mathbb{E} d_F(S(\hat{A}), S(A_0)) \le C" + "\n$$\nDone."
        self.assertEqual(result, expected)

    def test_normalize_stage_b_markdown_promotes_standalone_tagged_equation_to_display_math(self) -> None:
        source = r"\hat{u}(\lambda)=\arg\min_{u \in \mathbb{R}^n} H\bigl(u,\{Y_i\}_{i=1}^n,\lambda\bigr). \tag{11}"
        result = normalize_stage_b_markdown(source)
        expected = "$$\n" + source + "\n$$"
        self.assertEqual(result, expected)

    def test_normalize_stage_b_markdown_converts_latex_fence_to_display_math(self) -> None:
        result = normalize_stage_b_markdown("```latex\n\\frac{1}{\\sqrt{L}}\n```")
        self.assertEqual(result, "$$\n\\frac{1}{\\sqrt{L}}\n$$")

    def test_normalize_stage_b_markdown_converts_pseudo_inline_math(self) -> None:
        result = normalize_stage_b_markdown("The rate is (L^{-1/2}) and the target is (\\Pi^\\infty).")
        self.assertEqual(result, "The rate is $L^{-1/2}$ and the target is $\\Pi^\\infty$.")

    def test_normalize_stage_b_markdown_converts_pseudo_display_math(self) -> None:
        source = "The key matrix is [ \\Pi^\\infty = \\mathbb{E}(P_{\\ell,*}P_{\\ell,*}^\\top) ]."
        result = normalize_stage_b_markdown(source)
        expected = "The key matrix is $$\n" + r"\Pi^\infty = \mathbb{E}(P_{\ell,\ast}P_{\ell,\ast}^\top)" + "\n$$."
        self.assertEqual(result, expected)

    def test_normalize_stage_b_markdown_keeps_subscript_underscore(self) -> None:
        result = normalize_stage_b_markdown("The estimate is $P_a$.")
        self.assertEqual(result, "The estimate is $P_a$.")

    def test_normalize_stage_b_markdown_wraps_common_style_commands_in_braces(self) -> None:
        result = normalize_stage_b_markdown(r"Estimate: $\hat K + \mathbb P(A)$ and set $\mathcal Q$. ")
        self.assertEqual(result, r"Estimate: $\hat{K} + \mathbb{P}(A)$ and set $\mathcal{Q}$." )

    def test_normalize_stage_b_markdown_normalizes_existing_display_math_content(self) -> None:
        source = "$$\n\\Pi^\\infty = \\mathbb{E}(P_{\\ell,*}P_{\\ell,*}^\\top)\n$$"
        result = normalize_stage_b_markdown(source)
        expected = "$$\n" + r"\Pi^\infty = \mathbb{E}(P_{\ell,\ast}P_{\ell,\ast}^\top)" + "\n$$"
        self.assertEqual(result, expected)
    def test_request_formula_stage_b_injects_display_equation_placeholder(self) -> None:
        with mock.patch.object(
            formula_stage,
            "request_chat_completion",
            return_value="Prefix {{DISPLAY_EQ_1}} suffix",
        ):
            result = request_formula_stage_b(
                {"api_url": "http://127.0.0.1:8765/v1", "model": "gpt-5.4", "api_key": "", "reasoning_effort": ""},
                selected_text="noisy text",
                context_text="paper context",
                mode="explain",
                stage_a_result={
                    "latex": r"\[" + "\n" + r"\mathbb{P}(\hat K(\lambda)=K)" + "\n" + r"\]",
                    "confidence": "high",
                    "warnings": [],
                },
            )

        self.assertIn("Prefix $$\n\\mathbb{P}(\\hat{K}(\\lambda)=K)\n$$ suffix", result)


    def test_request_formula_stage_b_prefers_stage_a_display_equation(self) -> None:
        with mock.patch.object(
            formula_stage,
            "request_chat_completion",
            return_value=(
                "Theorem bound:\n"
                "$$\n"
                r"\mathbb{E} d_F\bigl(S(\hat{A}_0^L), S(A_0)\bigr) \le 2 d_0^{1/2} \left\lVert \Pi^\infty - A_0 A_0^\top \right\rVert\mathrm{op}) + \frac{2(2\pi)^{1/2} d_0^{1/2} d p}{L^{1/2}}."
                "\n$$"
            ),
        ):
            result = request_formula_stage_b(
                {"api_url": "http://127.0.0.1:8765/v1", "model": "gpt-5.4", "api_key": "", "reasoning_effort": ""},
                selected_text="noisy text",
                context_text="paper context",
                mode="explain",
                stage_a_result={
                    "latex": (
                        "\\textbf{Theorem 1.} We have\n"
                        "\\[\n"
                        r"\mathbb{E}\, d_F\bigl(S(\hat A_0^L), S(A_0)\bigr)" + "\n"
                        r"\le 2 d_0^{1/2} \left\| \Pi^\infty - A_0 A_0^\top \right\|_{\mathrm{op}} + \frac{2(2\pi)^{1/2} d_0^{1/2} d p}{L^{1/2}}." + "\n"
                        "\\]"
                    ),
                    "confidence": "high",
                    "warnings": [],
                },
            )

        self.assertIn("$$\n\\mathbb{E}\\, d_F", result)
        self.assertIn(r"\right\|_{\mathrm{op}}", result)
        self.assertNotIn(r"\right\rVert\mathrm{op})", result)


    def test_request_formula_stage_b_prefers_stage_a_standalone_formula(self) -> None:
        with mock.patch.object(
            formula_stage,
            "request_chat_completion",
            return_value=(
                "Optimization problem:\n"
                "$$\n"
                r"\hat{u}(\lambda)=\arg\min_{u \in \mathbb{R}^n} H\bigl(u,\{Y_i\}_{i=1}^n,\lambda\bigr). \tag{11}"
                "\n$$"
            ),
        ):
            result = request_formula_stage_b(
                {"api_url": "http://127.0.0.1:8765/v1", "model": "gpt-5.4", "api_key": "", "reasoning_effort": ""},
                selected_text="noisy text",
                context_text="paper context",
                mode="explain",
                stage_a_result={
                    "latex": (
                        "Theorem 3 defines the estimate as:\n"
                        r"\hat{u}(\lambda)=\arg\min_{u \in \mathbb{R}^n} H\bigl(u,\{Y_i\}_{i=1}^n,\lambda\bigr). \tag{11}"
                    ),
                    "confidence": "high",
                    "warnings": [],
                },
            )

        self.assertIn("$$\n\\hat{u}(\\lambda)=\\arg\\min", result)
        self.assertIn(r"\tag{11}", result)


    def test_request_formula_stage_b_prefers_tagged_stage_a_formula_even_when_display_counts_differ(self) -> None:
        with mock.patch.object(
            formula_stage,
            "request_chat_completion",
            return_value=(
                "Optimization problem:\n"
                "$$\n"
                r"\hat{u}(\lambda)=\arg\min_{u \in \mathbb{R}^n} H\bigl(u,\{Y_i\}_{i=1}^n,\lambda\bigr) \tag{11}"
                "\n$$\n"
                "Probability bound:\n"
                "$$\n"
                r"\mathbb{P}[\hat{K}(\lambda)=K] \ge 1-e n^{3-c}"
                "\n$$"
            ),
        ):
            result = request_formula_stage_b(
                {"api_url": "http://127.0.0.1:8765/v1", "model": "gpt-5.4", "api_key": "", "reasoning_effort": ""},
                selected_text="noisy text",
                context_text="paper context",
                mode="explain",
                stage_a_result={
                    "latex": (
                        "Theorem 3 defines the estimate as:\n"
                        r"\hat{u}(\lambda)=\arg\min_{u \in \mathbb{R}^n} H\bigl(u,\{Y_i\}_{i=1}^n,\lambda\bigr). \tag{11}"
                    ),
                    "confidence": "high",
                    "warnings": [],
                },
            )

        self.assertIn("$$\n\\hat{u}(\\lambda)=\\arg\\min", result)
        self.assertIn(r"\tag{11}", result)
        self.assertIn(r"\mathbb{P}[\hat{K}(\lambda)=K]", result)
    def test_request_formula_stage_b_normalizes_output_once_locally(self) -> None:
        with mock.patch.object(
            formula_stage,
            "request_chat_completion",
            return_value="The key object is (\\Pi^\\infty), the rate is (L^{-1/2}), and the bound is [ \\frac{1}{\\sqrt{L}} ].",
        ) as mocked_request:
            result = request_formula_stage_b(
                {"api_url": "http://127.0.0.1:8765/v1", "model": "gpt-5.4", "api_key": "", "reasoning_effort": ""},
                selected_text="noisy text",
                context_text="paper context",
                mode="explain",
                stage_a_result={"latex": r"\Pi^\infty", "confidence": "high", "warnings": []},
            )

        expected = "The key object is $\\Pi^\\infty$, the rate is $L^{-1/2}$, and the bound is $$\n\\frac{1}{\\sqrt{L}}\n$$."
        self.assertEqual(result, expected)
        mocked_request.assert_called_once()

    def test_parse_formula_stage_a_output_keeps_full_crop_latex(self) -> None:
        raw = (
            "CONFIDENCE: high\n"
            "LATEX:\n"
            r"\textbf{Theorem 1.}\quad \hat A_0^L := \hat A_0 = (U_1,\ldots,U_{d_0})" + "\n"
            "```latex\n"
            r"\mathbb{E}\, d_F\!\bigl(S(\hat A_0^L), S(A_0)\bigr) \le 2 d_0^{1/2}." + "\n"
            "```\n"
            "The surrounding text defines the finite-L output and infinite-simulation quantity.\n"
            "WARNINGS:\n"
            "- minor ambiguity\n"
            "- none\n"
        )
        payload = parse_formula_stage_a_output(raw)
        self.assertIn(r"\textbf{Theorem 1.}", payload["latex"])
        self.assertIn(r"\mathbb{E}\, d_F", payload["latex"])
        self.assertEqual(payload["confidence"], "high")
        self.assertEqual(payload["warnings"], ["minor ambiguity"])
        self.assertIn("finite-L output", payload["transcript"])

    def test_parse_formula_stage_a_output_keeps_json_fallback(self) -> None:
        raw = json.dumps(
            {
                "latex": r"\alpha + \beta",
                "transcript": "Theorem statement",
                "confidence": "high",
                "warnings": ["minor ambiguity"],
            }
        )
        payload = parse_formula_stage_a_output(raw)
        self.assertEqual(payload["latex"], r"\alpha + \beta")
        self.assertEqual(payload["transcript"], "Theorem statement")
        self.assertEqual(payload["confidence"], "high")
        self.assertEqual(payload["warnings"], ["minor ambiguity"])

    def test_parse_formula_stage_a_output_falls_back_for_unstructured_text(self) -> None:
        payload = parse_formula_stage_a_output("not-json-but-still-useful")
        self.assertEqual(payload["latex"], "not-json-but-still-useful")
        self.assertEqual(payload["confidence"], "low")
        self.assertTrue(payload["warnings"])


if __name__ == "__main__":
    unittest.main()


