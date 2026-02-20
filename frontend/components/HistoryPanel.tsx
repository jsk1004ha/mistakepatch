"use client";

import type { HistoryItem } from "@/lib/types";
import type { MistakeType } from "@/lib/types";
import { formatMistakeType } from "@/lib/mistakeTypeLabels";

interface HistoryPanelProps {
  items: HistoryItem[];
  topTags: Array<{ type: MistakeType; count: number }>;
  onSelect: (analysisId: string) => Promise<void>;
}

export function HistoryPanel({ items, topTags, onSelect }: HistoryPanelProps) {
  return (
    <section className="panel">
      <h2>히스토리</h2>
      {items.length === 0 && <p>아직 분석 기록이 없습니다.</p>}
      {items.length > 0 && (
        <div className="historyList">
          {items.map((item) => (
            <button
              type="button"
              key={item.analysis_id}
              className="historyItem"
              onClick={() => onSelect(item.analysis_id)}
            >
              <div>
                <strong>{item.subject === "math" ? "수학" : "물리"}</strong>
                <span>{new Date(item.created_at).toLocaleString()}</span>
              </div>
              <div>
                <span>{item.score_total !== null ? `${item.score_total.toFixed(1)}점` : "채점중"}</span>
                {item.top_tag && <small title={item.top_tag}>#{formatMistakeType(item.top_tag)}</small>}
              </div>
            </button>
          ))}
        </div>
      )}

      <h3>실수 Top3</h3>
      <ul className="topTagList">
        {topTags.map((tag) => (
          <li key={tag.type}>
            <span title={tag.type}>{formatMistakeType(tag.type)}</span>
            <strong>{tag.count}</strong>
          </li>
        ))}
      </ul>
    </section>
  );
}
