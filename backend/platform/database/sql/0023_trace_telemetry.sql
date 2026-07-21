ALTER TABLE platform_trace_spans ADD COLUMN parent_span_id TEXT;
ALTER TABLE platform_trace_spans ADD COLUMN span_kind TEXT NOT NULL DEFAULT 'internal';
ALTER TABLE platform_trace_spans ADD COLUMN ended_at TEXT;
ALTER TABLE platform_trace_spans ADD COLUMN duration_ms INTEGER NOT NULL DEFAULT 0 CHECK (duration_ms >= 0);
ALTER TABLE platform_trace_spans ADD COLUMN error_code TEXT NOT NULL DEFAULT '';

CREATE INDEX IF NOT EXISTS idx_platform_trace_spans_parent
    ON platform_trace_spans(trace_id, parent_span_id, created_at);
