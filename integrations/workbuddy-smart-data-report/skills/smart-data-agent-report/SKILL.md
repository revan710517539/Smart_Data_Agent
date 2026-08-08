---
name: smart-data-agent-report
description: Publish a completed WorkBuddy analysis as a visual Smart Data Agent report.
---

# Smart Data Agent report publisher

When the user asks to synchronize an analysis to Smart Data Agent, publish a
structured report. Do not upload the conversation transcript. Keep only the
analysis result needed for the report: title, question, method, conclusion,
and rows used by its charts.

1. Build a JSON package at a temporary path. Use the current WorkBuddy session
   ID as `source.run_id` when available; otherwise generate a stable task ID.
2. The package must match this shape:

```json
{
  "source": {
    "channel": "workbuddy",
    "run_id": "workbuddy-session-or-task-id",
    "report_id": "optional-stable-analysis-id"
  },
  "report": {
    "title": "分析报告标题",
    "query": "分析问题",
    "plan": "分析方法与范围",
    "summary": "可直接给业务人员阅读的核心结论",
    "visual_types": {"primary": "bar", "secondary": "table"},
    "rows": [{"维度": "示例", "指标": 1}]
  }
}
```

3. Validate and publish it:

```sh
SDA publish --channel workbuddy --input /tmp/workbuddy-report.json
```

4. Tell the user only the returned report title and report ID. Do not print the
   token, full payload, transcript path, or source rows in the confirmation.

Allowed chart types are `bar`, `line`, `pie`, and `table`. If the analysis has
no reliable quantitative rows, use `table` and an empty list; the Smart Data
Agent report will still show the text conclusion.
