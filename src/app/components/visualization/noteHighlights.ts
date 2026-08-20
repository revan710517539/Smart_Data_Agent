export type NoteFieldKind = "metric" | "dimension" | "field";

export type NoteFieldTerm = {
  token: string;
  field: string;
  kind: NoteFieldKind;
  color: string;
};

export type NoteHighlightPart = {
  text: string;
  term?: NoteFieldTerm;
};

const kindColor: Record<NoteFieldKind, string> = {
  metric: "#147d4f",
  dimension: "#0a66c2",
  field: "#9a5a09",
};

export function noteFieldTerms({
  fields,
  metricFields,
  dimensionFields,
  labels,
}: {
  fields: string[];
  metricFields: string[];
  dimensionFields: string[];
  labels: Record<string, string>;
}): NoteFieldTerm[] {
  const metrics = new Set(metricFields);
  const dimensions = new Set(dimensionFields);
  const terms: NoteFieldTerm[] = [];
  const seen = new Set<string>();
  for (const field of fields) {
    const kind: NoteFieldKind = metrics.has(field) ? "metric" : dimensions.has(field) ? "dimension" : "field";
    for (const token of [labels[field] || "", field]) {
      const trimmed = token.trim();
      if (trimmed.length < 2 || /^\d+$/.test(trimmed) || seen.has(trimmed)) continue;
      seen.add(trimmed);
      terms.push({ token: trimmed, field, kind, color: kindColor[kind] });
    }
  }
  return terms.sort((left, right) => right.token.length - left.token.length || left.token.localeCompare(right.token, "zh-CN"));
}

export function highlightNoteText(text: string, terms: NoteFieldTerm[]): NoteHighlightPart[] {
  if (!text) return [];
  const owner = new Array<number>(text.length).fill(-1);
  terms.forEach((term, index) => {
    if (!term.token) return;
    let from = 0;
    while (from <= text.length - term.token.length) {
      const start = text.indexOf(term.token, from);
      if (start < 0) break;
      if (owner.slice(start, start + term.token.length).every((value) => value < 0)) {
        for (let offset = 0; offset < term.token.length; offset += 1) owner[start + offset] = index;
      }
      from = start + 1;
    }
  });
  const parts: NoteHighlightPart[] = [];
  let cursor = 0;
  while (cursor < text.length) {
    const mark = owner[cursor];
    if (mark < 0) {
      let end = cursor + 1;
      while (end < text.length && owner[end] < 0) end += 1;
      parts.push({ text: text.slice(cursor, end) });
      cursor = end;
      continue;
    }
    const term = terms[mark];
    parts.push({ text: text.slice(cursor, cursor + term.token.length), term });
    cursor += term.token.length;
  }
  return parts;
}
