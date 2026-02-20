import { Fragment, type ReactNode } from "react";

const COMMAND_MAP: Record<string, string> = {
  "\\times": "×",
  "\\cdot": "·",
  "\\div": "÷",
  "\\pm": "±",
  "\\leq": "≤",
  "\\geq": "≥",
  "\\neq": "≠",
  "\\approx": "≈",
  "\\sim": "∼",
  "\\infty": "∞",
  "\\to": "→",
  "\\rightarrow": "→",
};

function stripSystemMarkers(text: string): string {
  return text
    .replace(/\[(?:step|rule):[^\]]+\]/gi, " ")
    .replace(/\s{2,}/g, " ")
    .trim();
}

function replaceLatexBasics(text: string): string {
  let normalized = stripSystemMarkers(text)
    .replace(/\$\$/g, "")
    .replace(/\$/g, "")
    .replace(/\\left/g, "")
    .replace(/\\right/g, "")
    .replace(/\\text\s*\{([^{}]+)\}/g, "$1")
    .replace(/\\sqrt\s*\{([^{}]+)\}/g, "√($1)")
    .replace(/\\sqrt\s*([A-Za-z0-9]+)/g, "√($1)")
    .replace(/\\,/g, " ")
    .replace(/\\\(/g, "")
    .replace(/\\\)/g, "")
    .replace(/\\\[/g, "")
    .replace(/\\\]/g, "");

  // Normalize truncated fractional exponents like `9^1/4)` -> `9^(1/4)`.
  normalized = normalized.replace(/\^([0-9]+\/[0-9]+)\)/g, "^($1)");

  const fracPattern = /\\frac\s*\{([^{}]+)\}\s*\{([^{}]+)\}/g;
  let next = normalized.replace(fracPattern, "($1)/($2)");
  while (next !== normalized) {
    normalized = next;
    next = normalized.replace(fracPattern, "($1)/($2)");
  }

  while (normalized.endsWith(")") && normalized.split("(").length < normalized.split(")").length) {
    normalized = normalized.slice(0, -1);
  }

  return normalized;
}

function readGrouped(
  text: string,
  start: number,
  open: string,
  close: string,
): { value: string; end: number } | null {
  if (text[start] !== open) return null;
  let depth = 0;
  for (let idx = start; idx < text.length; idx += 1) {
    const ch = text[idx];
    if (ch === open) depth += 1;
    if (ch === close) depth -= 1;
    if (depth === 0) {
      return { value: text.slice(start + 1, idx), end: idx };
    }
  }
  return null;
}

function readToken(text: string, start: number): { value: string; end: number } | null {
  let end = start;
  while (end < text.length && /[A-Za-z0-9+\-*/.=]/.test(text[end])) {
    end += 1;
  }
  if (end === start) return null;
  return { value: text.slice(start, end), end: end - 1 };
}

function renderMathNodes(rawText: string): ReactNode[] {
  const text = replaceLatexBasics(rawText);
  const nodes: ReactNode[] = [];
  let buffer = "";
  let key = 0;

  const flush = () => {
    if (!buffer) return;
    nodes.push(<Fragment key={`t-${key++}`}>{buffer}</Fragment>);
    buffer = "";
  };

  let i = 0;
  while (i < text.length) {
    const ch = text[i];

    if (ch === "^" || ch === "_") {
      const mode = ch;
      const next = text[i + 1];
      let token: { value: string; end: number } | null = null;
      if (next === "{") token = readGrouped(text, i + 1, "{", "}");
      else if (next === "(") token = readGrouped(text, i + 1, "(", ")");
      else token = readToken(text, i + 1);

      if (token) {
        flush();
        const content = token.value.trim();
        if (mode === "^") {
          nodes.push(<sup key={`sup-${key++}`}>{content}</sup>);
        } else {
          nodes.push(<sub key={`sub-${key++}`}>{content}</sub>);
        }
        i = token.end + 1;
        continue;
      }
    }

    if (ch === "\\") {
      let end = i + 1;
      while (end < text.length && /[A-Za-z]/.test(text[end])) {
        end += 1;
      }
      const command = text.slice(i, end);
      const replacement = COMMAND_MAP[command];
      if (replacement) {
        flush();
        nodes.push(<Fragment key={`cmd-${key++}`}>{replacement}</Fragment>);
        i = end;
        continue;
      }
    }

    buffer += ch;
    i += 1;
  }
  flush();
  return nodes;
}

export function MathText({ text }: { text: string }) {
  return <span className="mathText">{renderMathNodes(text)}</span>;
}
