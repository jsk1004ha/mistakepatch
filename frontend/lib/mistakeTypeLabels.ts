import type { MistakeType } from "@/lib/types";

export const MISTAKE_TYPE_LABELS: Record<MistakeType, string> = {
  CONDITION_MISSED: "조건 누락",
  SIGN_ERROR: "부호 실수",
  UNIT_ERROR: "단위 실수",
  DEFINITION_CONFUSION: "정의 혼동",
  ALGEBRA_ERROR: "대수/전개 실수",
  LOGIC_GAP: "논리 연결 부족",
  CASE_MISS: "케이스 누락",
  GRAPH_MISREAD: "그래프 오독",
  ARITHMETIC_ERROR: "산술 실수",
  FINAL_FORM_ERROR: "최종형태 오류",
};

export function formatMistakeType(type: MistakeType): string {
  return MISTAKE_TYPE_LABELS[type] ?? type;
}

export function formatMistakeTag(tag: string): string {
  if (tag in MISTAKE_TYPE_LABELS) {
    return MISTAKE_TYPE_LABELS[tag as MistakeType];
  }
  return tag;
}
