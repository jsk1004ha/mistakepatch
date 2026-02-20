from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1]))

from app.models import MistakeType, Severity
from app.services.analyzer import (
    ConsensusMeta,
    ExtractedStep,
    VerificationFinding,
    VerificationReport,
    _apply_answer_verdict_policy,
    _apply_verified_wrong_final_cap,
    _collapse_same_line_boxes,
    _ensure_mistake_coverage,
    _extract_last_rhs_numeric_value,
    _extract_last_x_value,
    _apply_uncertainty_policy,
    _dedupe_mistakes_by_step_rule,
    _enforce_evidence_gate,
    _equations_equivalent,
    _normalize_equation_text,
    _parse_linear_equation,
    _reconcile_score_from_deductions,
)


class AnalyzerGuardrailsTestCase(unittest.TestCase):
    def test_linear_equation_equivalence(self) -> None:
        first = _parse_linear_equation("x+1=4")
        second = _parse_linear_equation("x=4-1")
        third = _parse_linear_equation("x=5")
        self.assertIsNotNone(first)
        self.assertIsNotNone(second)
        self.assertIsNotNone(third)
        assert first is not None and second is not None and third is not None
        self.assertTrue(_equations_equivalent(first, second))
        self.assertFalse(_equations_equivalent(first, third))

    def test_evidence_gate_blocks_unproven_deduction(self) -> None:
        result = {
            "mistakes": [
                {
                    "type": MistakeType.logic_gap.value,
                    "severity": Severity.med.value,
                    "points_deducted": 0.8,
                    "evidence": "근거가 부족해 보완 설명이 필요합니다.",
                    "fix_instruction": "다시 확인",
                    "location_hint": "첫 줄",
                    "highlight": {"mode": "tap", "shape": "circle"},
                }
            ],
            "missing_info": [],
        }
        report = VerificationReport(
            steps=[ExtractedStep(step_id="s1", text="x+1=4", equation="x+1=4")],
            findings=[],
            expected_x=3.0,
            observed_x=3.0,
            confidence=0.9,
            requires_review=False,
        )
        _enforce_evidence_gate(result, report)
        self.assertEqual(result["mistakes"][0]["points_deducted"], 0.0)
        self.assertIn("[step:s1]", result["mistakes"][0]["evidence"])
        self.assertIn("[rule:RULE_EQUIV_TRANSFORM]", result["mistakes"][0]["evidence"])

    def test_dedupe_caps_per_step_rule(self) -> None:
        result = {
            "mistakes": [
                {
                    "type": MistakeType.logic_gap.value,
                    "severity": Severity.med.value,
                    "points_deducted": 0.5,
                    "evidence": "[step:s2][rule:RULE_EQUIV_TRANSFORM] 근거: 해가 다릅니다.",
                    "fix_instruction": "전개 점검",
                    "location_hint": "둘째 줄",
                    "highlight": {"mode": "tap", "shape": "circle"},
                },
                {
                    "type": MistakeType.logic_gap.value,
                    "severity": Severity.high.value,
                    "points_deducted": 0.9,
                    "evidence": "[step:s2][rule:RULE_EQUIV_TRANSFORM] 근거: 동일 규칙 중복 감점.",
                    "fix_instruction": "전개 재검토",
                    "location_hint": "둘째 줄",
                    "highlight": {"mode": "tap", "shape": "circle"},
                },
            ]
        }
        _dedupe_mistakes_by_step_rule(result)
        self.assertEqual(len(result["mistakes"]), 1)
        self.assertEqual(result["mistakes"][0]["points_deducted"], 0.9)

    def test_uncertainty_policy_holds_deduction(self) -> None:
        result = {
            "score_total": 5.0,
            "rubric_scores": {
                "conditions": 1.0,
                "modeling": 1.0,
                "logic": 1.0,
                "calculation": 1.0,
                "final": 1.0,
            },
            "mistakes": [
                {
                    "type": MistakeType.final_form_error.value,
                    "severity": Severity.high.value,
                    "points_deducted": 1.6,
                    "evidence": "[step:s3][rule:RULE_FINAL_SUBSTITUTION] 근거: 대입 불일치",
                    "fix_instruction": "검산",
                    "location_hint": "마지막 줄",
                    "highlight": {"mode": "tap", "shape": "circle"},
                }
            ],
            "next_checklist": ["검산"],
            "confidence": 0.4,
            "missing_info": [],
        }
        report = VerificationReport(
            steps=[ExtractedStep(step_id="s1", text="x+1=4", equation="x+1=4")],
            findings=[],
            expected_x=3.0,
            observed_x=None,
            confidence=0.2,
            requires_review=True,
        )
        _apply_uncertainty_policy(
            result=result,
            report=report,
            consensus_meta=ConsensusMeta(
                runs_requested=3,
                runs_used=3,
                agreement=0.42,
                score_spread=1.8,
            ),
        )
        self.assertEqual(result["mistakes"][0]["points_deducted"], 0.0)
        self.assertGreaterEqual(result["score_total"], 8.0)
        self.assertTrue(any("검토 필요" in item for item in result["missing_info"]))

    def test_extract_last_x_value_parses_expression(self) -> None:
        text = "x+1=4\nx=4-1\nx=3"
        self.assertEqual(_extract_last_x_value(text), 3.0)
        text2 = "x+1=4\nx=4+1"
        self.assertEqual(_extract_last_x_value(text2), 5.0)

    def test_extract_last_rhs_numeric_value_without_variable_symbol(self) -> None:
        text = "k+1=4\nk=4+1\nk=5"
        self.assertEqual(_extract_last_rhs_numeric_value(text), 5.0)

    def test_extract_last_rhs_numeric_value_handles_ocr_digit_noise(self) -> None:
        text = "x+1=4\nx=4+l\nx=S"
        self.assertEqual(_extract_last_rhs_numeric_value(text), 5.0)

    def test_reconcile_score_from_deductions_caps_only(self) -> None:
        result = {
            "score_total": 8.0,
            "rubric_scores": {
                "conditions": 1.6,
                "modeling": 1.6,
                "logic": 1.6,
                "calculation": 1.6,
                "final": 1.6,
            },
            "mistakes": [
                {
                    "type": MistakeType.logic_gap.value,
                    "severity": Severity.low.value,
                    "points_deducted": 0.0,
                    "evidence": "[step:s1][rule:RULE_REVIEW_REQUIRED] 근거: 보류",
                    "fix_instruction": "검토",
                    "location_hint": "전체",
                    "highlight": {"mode": "tap", "shape": "circle"},
                }
            ],
        }
        _reconcile_score_from_deductions(result)
        self.assertEqual(result["score_total"], 8.0)

    def test_reconcile_score_from_deductions_lowers_when_needed(self) -> None:
        result = {
            "score_total": 9.4,
            "rubric_scores": {
                "conditions": 2.0,
                "modeling": 2.0,
                "logic": 2.0,
                "calculation": 1.8,
                "final": 1.6,
            },
            "mistakes": [
                {
                    "type": MistakeType.final_form_error.value,
                    "severity": Severity.high.value,
                    "points_deducted": 2.0,
                    "evidence": "[step:s3][rule:RULE_FINAL_SUBSTITUTION] 근거: 불일치",
                    "fix_instruction": "검산",
                    "location_hint": "마지막",
                    "highlight": {"mode": "tap", "shape": "circle"},
                }
            ],
        }
        _reconcile_score_from_deductions(result)
        self.assertLessEqual(result["score_total"], 8.0)

    def test_uncertainty_policy_caps_perfect_score(self) -> None:
        result = {
            "score_total": 10.0,
            "rubric_scores": {
                "conditions": 2.0,
                "modeling": 2.0,
                "logic": 2.0,
                "calculation": 2.0,
                "final": 2.0,
            },
            "mistakes": [
                {
                    "type": MistakeType.logic_gap.value,
                    "severity": Severity.med.value,
                    "points_deducted": 0.5,
                    "evidence": "[step:s2][rule:RULE_EQUIV_TRANSFORM] 근거: 확인 불가",
                    "fix_instruction": "검토",
                    "location_hint": "중간",
                    "highlight": {"mode": "tap", "shape": "circle"},
                }
            ],
            "next_checklist": ["검토"],
            "confidence": 0.7,
            "missing_info": [],
        }
        report = VerificationReport(
            steps=[ExtractedStep(step_id="s1", text="x+1=4", equation="x+1=4")],
            findings=[],
            expected_x=3.0,
            observed_x=None,
            confidence=0.25,
            requires_review=True,
        )
        _apply_uncertainty_policy(
            result=result,
            report=report,
            consensus_meta=ConsensusMeta(
                runs_requested=3,
                runs_used=3,
                agreement=0.5,
                score_spread=2.0,
            ),
        )
        self.assertLessEqual(result["score_total"], 8.8)
        self.assertGreaterEqual(result["score_total"], 8.0)

    def test_normalize_equation_text_supports_arrow(self) -> None:
        self.assertEqual(_normalize_equation_text("x+1->4"), "x+1=4")
        self.assertEqual(_normalize_equation_text("x+1=>4"), "x+1=4")
        self.assertEqual(_normalize_equation_text("x+1>4"), "x+1=4")

    def test_uncertainty_policy_does_not_hold_verified_failure(self) -> None:
        result = {
            "score_total": 9.5,
            "rubric_scores": {
                "conditions": 2.0,
                "modeling": 2.0,
                "logic": 1.8,
                "calculation": 1.9,
                "final": 1.8,
            },
            "mistakes": [
                {
                    "type": MistakeType.final_form_error.value,
                    "severity": Severity.high.value,
                    "points_deducted": 1.5,
                    "evidence": "[step:s3][rule:RULE_FINAL_SUBSTITUTION] 근거: 대입 불일치 반례: x=5, expected=x=3",
                    "fix_instruction": "검산",
                    "location_hint": "마지막",
                    "highlight": {"mode": "tap", "shape": "circle"},
                }
            ],
            "next_checklist": ["검산"],
            "confidence": 0.2,
            "missing_info": [],
        }
        report = VerificationReport(
            steps=[
                ExtractedStep(step_id="s1", text="x+1=4", equation="x+1=4"),
                ExtractedStep(step_id="s2", text="x=4+1", equation="x=4+1"),
                ExtractedStep(step_id="s3", text="x=5", equation="x=5"),
            ],
            findings=[
                VerificationFinding(
                    step_id="s3",
                    rule="RULE_FINAL_SUBSTITUTION",
                    passed=False,
                    reason="최종 답 대입 시 원식이 성립하지 않습니다.",
                    counterexample="x=5, expected=x=3",
                ),
            ],
            expected_x=3.0,
            observed_x=5.0,
            confidence=0.2,
            requires_review=True,
        )
        _apply_uncertainty_policy(
            result=result,
            report=report,
            consensus_meta=ConsensusMeta(
                runs_requested=3,
                runs_used=3,
                agreement=0.4,
                score_spread=2.4,
            ),
        )
        self.assertGreater(result["mistakes"][0]["points_deducted"], 0.0)

    def test_verified_wrong_final_cap_forces_low_score(self) -> None:
        result = {
            "score_total": 9.8,
            "rubric_scores": {
                "conditions": 2.0,
                "modeling": 2.0,
                "logic": 2.0,
                "calculation": 2.0,
                "final": 1.8,
            },
            "mistakes": [],
            "confidence": 0.85,
        }
        report = VerificationReport(
            steps=[
                ExtractedStep(step_id="s1", text="x+1=4", equation="x+1=4"),
                ExtractedStep(step_id="s2", text="x=4+1", equation="x=4+1"),
                ExtractedStep(step_id="s3", text="x=5", equation="x=5"),
            ],
            findings=[
                VerificationFinding(
                    step_id="s3",
                    rule="RULE_FINAL_SUBSTITUTION",
                    passed=False,
                    reason="최종 답 대입 시 원식이 성립하지 않습니다.",
                    counterexample="x=5, expected=x=3",
                ),
            ],
            expected_x=3.0,
            observed_x=5.0,
            confidence=0.8,
            requires_review=False,
        )
        _apply_verified_wrong_final_cap(result, report)
        self.assertLessEqual(result["score_total"], 7.0)
        self.assertEqual(result["mistakes"][0]["type"], MistakeType.final_form_error.value)
        self.assertGreaterEqual(result["mistakes"][0]["points_deducted"], 1.8)

    def test_answer_verdict_policy_sets_incorrect_band(self) -> None:
        result = {
            "score_total": 9.0,
            "rubric_scores": {
                "conditions": 1.8,
                "modeling": 1.6,
                "logic": 1.4,
                "calculation": 1.5,
                "final": 0.4,
            },
            "mistakes": [],
        }
        report = VerificationReport(
            steps=[],
            findings=[
                VerificationFinding(
                    step_id="s3",
                    rule="RULE_FINAL_SUBSTITUTION",
                    passed=False,
                    reason="최종 답 대입 시 원식 불일치",
                    counterexample="x=5, expected=x=3",
                )
            ],
            expected_x=3.0,
            observed_x=5.0,
            confidence=0.9,
            requires_review=False,
        )
        _apply_answer_verdict_policy(result, report)
        self.assertEqual(result["answer_verdict"], "incorrect")
        self.assertLessEqual(result["score_total"], 7.0)

    def test_answer_verdict_policy_sets_correct_band(self) -> None:
        result = {
            "score_total": 6.2,
            "rubric_scores": {
                "conditions": 1.6,
                "modeling": 1.5,
                "logic": 1.7,
                "calculation": 1.8,
                "final": 1.9,
            },
            "mistakes": [],
        }
        report = VerificationReport(
            steps=[],
            findings=[
                VerificationFinding(
                    step_id="s3",
                    rule="RULE_FINAL_SUBSTITUTION",
                    passed=True,
                    reason="대입 성립",
                    counterexample=None,
                )
            ],
            expected_x=3.0,
            observed_x=3.0,
            confidence=0.9,
            requires_review=False,
        )
        _apply_answer_verdict_policy(result, report)
        self.assertEqual(result["answer_verdict"], "correct")
        self.assertGreaterEqual(result["score_total"], 7.0)

    def test_answer_verdict_policy_marks_incorrect_on_transform_counterexample(self) -> None:
        result = {
            "score_total": 8.8,
            "rubric_scores": {
                "conditions": 1.8,
                "modeling": 1.8,
                "logic": 1.5,
                "calculation": 1.8,
                "final": 1.9,
            },
            "mistakes": [],
        }
        report = VerificationReport(
            steps=[
                ExtractedStep(step_id="s1", text="x+1=4", equation="x+1=4"),
                ExtractedStep(step_id="s2", text="x=4+1", equation="x=4+1"),
                ExtractedStep(step_id="s3", text="x=5", equation="x=5"),
            ],
            findings=[
                VerificationFinding(
                    step_id="s2",
                    rule="RULE_EQUIV_TRANSFORM",
                    passed=False,
                    reason="연속 식 변형 전후의 해가 일치하지 않습니다.",
                    counterexample="s1=x=3, s2=x=5",
                ),
            ],
            expected_x=None,
            observed_x=5.0,
            confidence=0.85,
            requires_review=False,
        )
        _apply_answer_verdict_policy(result, report)
        self.assertEqual(result["answer_verdict"], "incorrect")
        self.assertIn("중간 식 변형", result["answer_verdict_reason"])

    def test_answer_verdict_policy_keeps_unknown_when_verification_missing(self) -> None:
        result = {
            "score_total": 2.5,
            "rubric_scores": {
                "conditions": 0.5,
                "modeling": 0.5,
                "logic": 0.5,
                "calculation": 0.5,
                "final": 0.5,
            },
            "mistakes": [],
        }
        report = VerificationReport(
            steps=[],
            findings=[],
            expected_x=None,
            observed_x=None,
            confidence=0.1,
            requires_review=False,
        )
        _apply_answer_verdict_policy(result, report)
        self.assertEqual(result["answer_verdict"], "unknown")
        self.assertIn("검증 정보 부족", result["answer_verdict_reason"])

    def test_answer_verdict_policy_does_not_promote_unknown_to_correct_by_score(self) -> None:
        result = {
            "score_total": 9.3,
            "rubric_scores": {
                "conditions": 1.8,
                "modeling": 1.8,
                "logic": 1.9,
                "calculation": 1.8,
                "final": 2.0,
            },
            "mistakes": [],
        }
        report = VerificationReport(
            steps=[],
            findings=[],
            expected_x=None,
            observed_x=None,
            confidence=0.6,
            requires_review=False,
        )
        _apply_answer_verdict_policy(result, report)
        self.assertEqual(result["answer_verdict"], "unknown")
        self.assertNotEqual(result["answer_verdict"], "correct")
        self.assertEqual(result["score_total"], 9.3)

    def test_answer_verdict_policy_preserves_existing_incorrect_signal(self) -> None:
        result = {
            "score_total": 5.0,
            "answer_verdict": "incorrect",
            "answer_verdict_reason": "틀림: 단순식 검산 결과 x=5, 기대값 x=3",
            "rubric_scores": {
                "conditions": 1.0,
                "modeling": 1.0,
                "logic": 1.0,
                "calculation": 1.0,
                "final": 0.8,
            },
            "mistakes": [],
        }
        report = VerificationReport(
            steps=[],
            findings=[],
            expected_x=None,
            observed_x=None,
            confidence=0.4,
            requires_review=False,
        )
        _apply_answer_verdict_policy(result, report)
        self.assertEqual(result["answer_verdict"], "incorrect")
        self.assertIn("보조 검산", result["answer_verdict_reason"])

    def test_ensure_mistake_coverage_fills_deduction_gap(self) -> None:
        result = {
            "score_total": 0.8,
            "rubric_scores": {
                "conditions": 0.16,
                "modeling": 0.16,
                "logic": 0.16,
                "calculation": 0.16,
                "final": 0.16,
            },
            "mistakes": [
                {
                    "type": MistakeType.logic_gap.value,
                    "severity": Severity.low.value,
                    "points_deducted": 0.0,
                    "evidence": "[step:s0][rule:RULE_GENERAL_CONSISTENCY] 근거: 보류",
                    "fix_instruction": "검토",
                    "location_hint": "중간",
                    "highlight": {"mode": "ocr_box", "shape": "box"},
                }
            ],
        }
        report = VerificationReport(
            steps=[],
            findings=[],
            expected_x=None,
            observed_x=None,
            confidence=0.2,
            requires_review=False,
        )
        _ensure_mistake_coverage(result, report)
        deductions = [m["points_deducted"] for m in result["mistakes"]]
        self.assertTrue(all(p > 0 for p in deductions))
        self.assertGreaterEqual(len(result["mistakes"]), 3)
        total_deduction = sum(deductions)
        self.assertAlmostEqual(total_deduction, 9.2, delta=0.05)
        self.assertEqual(result["score_total"], 0.8)

    def test_ensure_mistake_coverage_normalizes_overflow_sum(self) -> None:
        result = {
            "score_total": 0.8,
            "rubric_scores": {
                "conditions": 0.2,
                "modeling": 0.2,
                "logic": 0.2,
                "calculation": 0.2,
                "final": 0.2,
            },
            "mistakes": [
                {
                    "type": MistakeType.condition_missed.value,
                    "severity": Severity.med.value,
                    "points_deducted": 0.6,
                    "evidence": "[step:s1][rule:RULE_RUBRIC_CONDITIONS] 근거: 조건 누락",
                    "fix_instruction": "조건 재검토",
                    "location_hint": "첫 줄",
                    "highlight": {"mode": "ocr_box", "shape": "box"},
                },
                {
                    "type": MistakeType.logic_gap.value,
                    "severity": Severity.med.value,
                    "points_deducted": 0.5,
                    "evidence": "[step:s2][rule:RULE_EQUIV_TRANSFORM] 근거: 논리 비약",
                    "fix_instruction": "전개 재검토",
                    "location_hint": "중간 줄",
                    "highlight": {"mode": "ocr_box", "shape": "box"},
                },
                *[
                    {
                        "type": MistakeType.arithmetic_error.value,
                        "severity": Severity.high.value,
                        "points_deducted": 1.8,
                        "evidence": f"[step:s{idx + 2}][rule:RULE_RUBRIC_CALC] 근거: 계산 오류",
                        "fix_instruction": "계산 재검토",
                        "location_hint": "계산 줄",
                        "highlight": {"mode": "ocr_box", "shape": "box"},
                    }
                    for idx in range(5)
                ],
            ],
        }
        report = VerificationReport(
            steps=[],
            findings=[],
            expected_x=None,
            observed_x=None,
            confidence=0.3,
            requires_review=False,
        )
        _ensure_mistake_coverage(result, report)
        deductions = [m["points_deducted"] for m in result["mistakes"]]
        self.assertEqual(round(sum(deductions), 1), 9.2)
        self.assertEqual(result["score_total"], 0.8)
        self.assertTrue(all(abs((p * 10) - round(p * 10)) < 1e-8 for p in deductions))

    def test_ensure_mistake_coverage_skips_synthetic_for_verified_correct(self) -> None:
        result = {
            "score_total": 9.5,
            "answer_verdict": "correct",
            "rubric_scores": {
                "conditions": 2.0,
                "modeling": 2.0,
                "logic": 1.5,
                "calculation": 2.0,
                "final": 2.0,
            },
            "mistakes": [],
        }
        report = VerificationReport(
            steps=[],
            findings=[
                VerificationFinding(
                    step_id="s3",
                    rule="RULE_FINAL_SUBSTITUTION",
                    passed=True,
                    reason="대입 성립",
                    counterexample=None,
                )
            ],
            expected_x=3.0,
            observed_x=3.0,
            confidence=0.8,
            requires_review=False,
        )
        _ensure_mistake_coverage(result, report)
        self.assertEqual(result["mistakes"], [])
        self.assertEqual(result["score_total"], 9.5)

    def test_collapse_same_line_boxes_merges_overlap(self) -> None:
        merged = _collapse_same_line_boxes(
            [
                {"mode": "ocr_box", "shape": "box", "x": 0.50, "y": 0.30, "w": 0.70, "h": 0.12},
                {"mode": "ocr_box", "shape": "box", "x": 0.51, "y": 0.34, "w": 0.72, "h": 0.11},
                {"mode": "ocr_box", "shape": "box", "x": 0.52, "y": 0.62, "w": 0.68, "h": 0.12},
            ]
        )
        self.assertEqual(len(merged), 2)
        self.assertGreater(merged[0]["h"], 0.12)


if __name__ == "__main__":
    unittest.main()
