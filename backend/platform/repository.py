from __future__ import annotations

import json
import hashlib
import sqlite3
from pathlib import Path
from backend.platform.storage import connect_sqlite
from typing import Any, Protocol

from backend.platform.observability import RuntimeEvent, TraceSpan
from backend.platform.orchestration import AnalysisTask


class AnalysisTaskRepository(Protocol):
    def save_task(self, task: AnalysisTask) -> None:
        ...

    def get_task(self, task_id: str) -> dict[str, Any] | None:
        ...

    def get_task_by_request(self, tenant_id: str, request_id: str) -> dict[str, Any] | None:
        ...

    def list_tasks(self, tenant_id: str, user_id: str, limit: int = 50) -> list[dict[str, Any]]:
        ...

    def execution_nodes(self, tenant_id: str, user_id: str, task_id: str) -> list[dict[str, Any]]:
        ...

    def delete_task(self, tenant_id: str, user_id: str, task_id: str) -> bool:
        ...

    def save_trace_spans(self, spans: list[TraceSpan]) -> None:
        ...

    def save_runtime_event(self, event: RuntimeEvent) -> None:
        ...

    def runtime_summary(self) -> dict[str, Any]:
        ...

    def save_model_call_fact(
        self,
        tenant_id: str,
        subject_type: str,
        subject_id: str,
        actor_user_id: str,
        invocation: dict[str, Any],
        revision: int = 1,
    ) -> dict[str, Any] | None:
        ...


class InMemoryAnalysisTaskRepository:
    def __init__(self) -> None:
        self._tasks: dict[str, dict[str, Any]] = {}
        self._trace_spans: list[dict[str, Any]] = []
        self._runtime_events: list[dict[str, Any]] = []
        self._model_calls: list[dict[str, Any]] = []

    def save_task(self, task: AnalysisTask) -> None:
        payload = serialize_task(task)
        self._tasks[task.task_id] = payload
        for model_call in _model_calls_from_payload(payload):
            if not any(item["model_call_id"] == model_call["model_call_id"] for item in self._model_calls):
                self._model_calls.append(model_call)

    def get_task(self, task_id: str) -> dict[str, Any] | None:
        task = self._tasks.get(task_id)
        return dict(task) if task else None

    def get_task_by_request(self, tenant_id: str, request_id: str) -> dict[str, Any] | None:
        return next(
            (
                dict(task)
                for task in self._tasks.values()
                if task.get("tenant_id") == tenant_id and task.get("request_id") == request_id
            ),
            None,
        )

    def list_tasks(self, tenant_id: str, user_id: str, limit: int = 50) -> list[dict[str, Any]]:
        tasks = [
            dict(task)
            for task in self._tasks.values()
            if task.get("tenant_id") == tenant_id and task.get("user_id") == user_id
        ]
        return sorted(tasks, key=lambda item: str(item.get("updated_at") or item.get("created_at") or ""), reverse=True)[:limit]

    def execution_nodes(self, tenant_id: str, user_id: str, task_id: str) -> list[dict[str, Any]]:
        task = self._tasks.get(task_id)
        if not task or task.get("tenant_id") != tenant_id or task.get("user_id") != user_id:
            return []
        nodes: list[dict[str, Any]] = []
        previous_code = ""
        for index, step in enumerate(task.get("plan") or []):
            step_code = _analysis_step_code(index, step)
            dependencies = list(step.get("dependencies") or ([previous_code] if previous_code else []))
            nodes.append({
                "step_code": step_code,
                "sequence_no": index,
                "step_type": _analysis_step_type(str(step.get("agent") or "Agent"), str(step.get("action") or "run")),
                "status": str(step.get("status") or "succeeded"),
                "input_refs": [{"depends_on": item} for item in dependencies],
                "output_refs": [{"response_snapshot_pointer": f"/plan/{index}"}],
                "attempt_no": max(1, int(step.get("attempt_no") or 1)),
                "skill_version": str(step.get("skill_version") or "pinned"),
                "error_code": str(step.get("error_code") or ""),
            })
            previous_code = step_code
        return nodes

    def delete_task(self, tenant_id: str, user_id: str, task_id: str) -> bool:
        task = self._tasks.get(task_id)
        if not task or task.get("tenant_id") != tenant_id or task.get("user_id") != user_id:
            return False
        trace_id = str(task.get("trace_id") or "")
        del self._tasks[task_id]
        if trace_id:
            self._trace_spans = [item for item in self._trace_spans if item.get("trace_id") != trace_id]
        for model_call in self._model_calls:
            if model_call.get("analysis_task_id") == task_id:
                model_call["analysis_task_id"] = ""
        return True

    def save_trace_spans(self, spans: list[TraceSpan]) -> None:
        self._trace_spans.extend(serialize_trace_span(span) for span in spans)

    def trace_spans(self, trace_id: str | None = None) -> list[dict[str, Any]]:
        return [dict(item) for item in self._trace_spans if trace_id is None or item["trace_id"] == trace_id]

    def trace_belongs_to_tenant(self, tenant_id: str, trace_id: str) -> bool:
        return any(
            task.get("tenant_id") == tenant_id and task.get("trace_id") == trace_id
            for task in self._tasks.values()
        ) or any(
            event.get("tenant_id") == tenant_id and event.get("trace_id") == trace_id
            for event in self._runtime_events
        )

    def save_runtime_event(self, event: RuntimeEvent) -> None:
        self._runtime_events.append(serialize_runtime_event(event))

    def runtime_summary(self) -> dict[str, Any]:
        return summarize_runtime_events(self._runtime_events)

    def model_calls(self, tenant_id: str | None = None) -> list[dict[str, Any]]:
        return [
            dict(item)
            for item in self._model_calls
            if tenant_id is None or item["tenant_id"] == tenant_id
        ]

    def save_model_call_fact(
        self,
        tenant_id: str,
        subject_type: str,
        subject_id: str,
        actor_user_id: str,
        invocation: dict[str, Any],
        revision: int = 1,
    ) -> dict[str, Any] | None:
        model_call = _external_model_call(
            tenant_id, subject_type, subject_id, actor_user_id, invocation, revision
        )
        if model_call and not any(
            item["model_call_id"] == model_call["model_call_id"] for item in self._model_calls
        ):
            self._model_calls.append(model_call)
        return dict(model_call) if model_call else None


class SQLiteAnalysisTaskRepository:
    """Durable repository for tasks and trace spans.

    This is intentionally SQLite-compatible for local deployment. The table shape
    mirrors the PostgreSQL-oriented schema so it can be promoted without changing
    callers.
    """

    def __init__(self, db_path: str | Path, initialize: bool = True) -> None:
        self.db_path = str(db_path)
        self._conn = connect_sqlite(self.db_path)
        self._conn.row_factory = sqlite3.Row
        if initialize:
            self.init_schema()

    def close(self) -> None:
        self._conn.close()

    def init_schema(self) -> None:
        self._conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS platform_analysis_tasks (
                task_id TEXT PRIMARY KEY,
                tenant_id TEXT NOT NULL,
                user_id TEXT NOT NULL,
                question TEXT NOT NULL,
                task_type TEXT NOT NULL,
                analysis_plan TEXT NOT NULL DEFAULT '{}',
                plan TEXT NOT NULL DEFAULT '[]',
                skill_results TEXT NOT NULL DEFAULT '[]',
                knowledge_refs TEXT NOT NULL DEFAULT '[]',
                conclusions TEXT NOT NULL DEFAULT '[]',
                review TEXT NOT NULL DEFAULT '{}',
                trace_id TEXT,
                status TEXT NOT NULL DEFAULT 'completed',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS platform_trace_spans (
                span_id TEXT NOT NULL,
                trace_id TEXT NOT NULL,
                span_name TEXT NOT NULL,
                inputs TEXT NOT NULL DEFAULT '{}',
                outputs TEXT NOT NULL DEFAULT '{}',
                status TEXT NOT NULL DEFAULT 'ok',
                created_at TEXT NOT NULL,
                PRIMARY KEY (trace_id, span_id)
            );

            CREATE TABLE IF NOT EXISTS platform_runtime_events (
                event_id TEXT PRIMARY KEY,
                trace_id TEXT NOT NULL,
                event_type TEXT NOT NULL,
                tenant_id TEXT NOT NULL,
                user_id TEXT NOT NULL,
                status TEXT NOT NULL,
                latency_ms INTEGER NOT NULL DEFAULT 0,
                fallback_used INTEGER NOT NULL DEFAULT 0,
                detail TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_platform_analysis_tasks_tenant_user
                ON platform_analysis_tasks(tenant_id, user_id);
            CREATE INDEX IF NOT EXISTS idx_platform_trace_spans_trace
                ON platform_trace_spans(trace_id);
            CREATE INDEX IF NOT EXISTS idx_platform_runtime_events_created
                ON platform_runtime_events(created_at);
            """
        )
        self._conn.commit()

    def save_task(self, task: AnalysisTask) -> None:
        payload = serialize_task(task)
        with self._conn:
            self._conn.execute(
                """
                INSERT INTO platform_analysis_tasks(
                    task_id, tenant_id, user_id, question, task_type, analysis_plan,
                    plan, skill_results, knowledge_refs, conclusions, review, trace_id,
                    status, request_id, execution_id, revision, parent_execution_id,
                    execution_mode, manual_edits, agent_group_state, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(task_id) DO UPDATE SET
                    analysis_plan = excluded.analysis_plan,
                    plan = excluded.plan,
                    skill_results = excluded.skill_results,
                    knowledge_refs = excluded.knowledge_refs,
                    conclusions = excluded.conclusions,
                    review = excluded.review,
                    trace_id = excluded.trace_id,
                    status = excluded.status,
                    execution_mode = excluded.execution_mode,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (
                    payload["task_id"],
                    payload["tenant_id"],
                    payload["user_id"],
                    payload["question"],
                    payload["task_type"],
                    json.dumps(payload["analysis_plan"], ensure_ascii=False, sort_keys=True),
                    json.dumps(payload["plan"], ensure_ascii=False, sort_keys=True),
                    json.dumps(payload["skill_results"], ensure_ascii=False, sort_keys=True),
                    json.dumps(payload["knowledge_refs"], ensure_ascii=False, sort_keys=True),
                    json.dumps(payload["conclusions"], ensure_ascii=False, sort_keys=True),
                    json.dumps(payload["review"], ensure_ascii=False, sort_keys=True),
                    payload["trace_id"],
                    payload["status"],
                    payload["request_id"],
                    payload["execution_id"],
                    payload["revision"],
                    payload["parent_execution_id"],
                    payload["execution_mode"],
                    json.dumps(payload["manual_edits"], ensure_ascii=False, sort_keys=True),
                    json.dumps(payload["agent_group_state"], ensure_ascii=False, sort_keys=True),
                ),
            )
            self._persist_execution_facts(payload)

    def get_task(self, task_id: str) -> dict[str, Any] | None:
        row = self._conn.execute(
            """
            SELECT task_id, tenant_id, user_id, question, task_type, analysis_plan,
                   plan, skill_results, knowledge_refs, conclusions, review, trace_id, status,
                   request_id, execution_id, revision, parent_execution_id, execution_mode
                   , manual_edits, agent_group_state, created_at, updated_at
            FROM platform_analysis_tasks
            WHERE task_id = ?
            """,
            (task_id,),
        ).fetchone()
        if row is None:
            return None
        return {
            "task_id": row["task_id"],
            "tenant_id": row["tenant_id"],
            "user_id": row["user_id"],
            "question": row["question"],
            "task_type": row["task_type"],
            "analysis_plan": json.loads(row["analysis_plan"]),
            "plan": json.loads(row["plan"]),
            "skill_results": json.loads(row["skill_results"]),
            "knowledge_refs": json.loads(row["knowledge_refs"]),
            "conclusions": json.loads(row["conclusions"]),
            "review": json.loads(row["review"]),
            "trace_id": row["trace_id"],
            "status": row["status"],
            "request_id": row["request_id"],
            "execution_id": row["execution_id"] or row["task_id"],
            "revision": row["revision"],
            "parent_execution_id": row["parent_execution_id"],
            "execution_mode": row["execution_mode"],
            "manual_edits": json.loads(row["manual_edits"] or "{}"),
            "agent_group_state": json.loads(row["agent_group_state"] or "{}"),
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }

    def get_task_by_request(self, tenant_id: str, request_id: str) -> dict[str, Any] | None:
        row = self._conn.execute(
            "SELECT task_id FROM platform_analysis_tasks WHERE tenant_id = ? AND request_id = ?",
            (tenant_id, request_id),
        ).fetchone()
        return self.get_task(str(row["task_id"])) if row else None

    def list_tasks(self, tenant_id: str, user_id: str, limit: int = 50) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            """
            SELECT task_id FROM platform_analysis_tasks
            WHERE tenant_id = ? AND user_id = ?
            ORDER BY updated_at DESC, created_at DESC LIMIT ?
            """,
            (tenant_id, user_id, max(1, min(int(limit), 200))),
        ).fetchall()
        return [task for row in rows if (task := self.get_task(str(row["task_id"]))) is not None]

    def delete_task(self, tenant_id: str, user_id: str, task_id: str) -> bool:
        row = self._conn.execute(
            "SELECT trace_id FROM platform_analysis_tasks WHERE task_id = ? AND tenant_id = ? AND user_id = ?",
            (task_id, tenant_id, user_id),
        ).fetchone()
        if row is None:
            return False
        trace_id = str(row["trace_id"] or "")
        with self._conn:
            if trace_id:
                self._conn.execute("DELETE FROM platform_trace_spans WHERE trace_id = ?", (trace_id,))
            cursor = self._conn.execute(
                "DELETE FROM platform_analysis_tasks WHERE task_id = ? AND tenant_id = ? AND user_id = ?",
                (task_id, tenant_id, user_id),
            )
        return cursor.rowcount > 0

    def _persist_execution_facts(self, payload: dict[str, Any]) -> None:
        results = payload.get("skill_results") if isinstance(payload.get("skill_results"), list) else []
        result = results[0] if results and isinstance(results[0], dict) else {}
        semantic = result.get("semantic_info") if isinstance(result.get("semantic_info"), dict) else {}
        evidence = result.get("evidence") if isinstance(result.get("evidence"), dict) else {}
        data = result.get("data") if isinstance(result.get("data"), list) else []
        executed_sql = str(evidence.get("executed_sql") or "")
        query_id = f"{payload['task_id']}:query:{payload['revision']}"
        result_hash = _content_hash(data)
        query_status = (
            "failed"
            if payload.get("status") == "failed"
            else "cancelled" if payload.get("status") == "cancelled"
            else "succeeded" if evidence.get("sql_executed") else "not_executed_mock"
        )
        self._conn.execute(
            """
            INSERT OR IGNORE INTO platform_analysis_queries(
                analysis_query_id, tenant_id, analysis_task_id, execution_id,
                query_revision, dataset_id, connection_id, compiled_sql,
                sql_executed, sql_hash, parameters, policy_snapshot, status,
                result_hash, row_count, summary
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                query_id,
                payload["tenant_id"],
                payload["task_id"],
                payload["execution_id"],
                payload["revision"],
                str(semantic.get("dataset_id") or ""),
                str(semantic.get("connection_id") or ""),
                executed_sql,
                1 if evidence.get("sql_executed") else 0,
                str(evidence.get("executed_sql_sha256") or ""),
                json.dumps(evidence.get("parameters") or {}, ensure_ascii=False, sort_keys=True),
                json.dumps(semantic.get("metric_access") or {}, ensure_ascii=False, sort_keys=True),
                query_status,
                result_hash,
                len(data),
                json.dumps(
                    {
                        "totals": evidence.get("totals") or {},
                        "full_group_count": semantic.get("full_group_count"),
                        "returned_group_count": semantic.get("returned_group_count"),
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                ),
            ),
        )
        for model_call in _model_calls_from_payload(payload):
            self._conn.execute(
                """
                INSERT OR IGNORE INTO platform_model_calls(
                    model_call_id, tenant_id, subject_type, subject_id,
                    analysis_task_id, execution_id,
                    revision, model_integration_id, provider_model_name,
                    prompt_template_id, request_hash, response_hash, status,
                    input_tokens, output_tokens, usage_source, cost_amount,
                    latency_ms, error_code, created_by
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    model_call["model_call_id"],
                    model_call["tenant_id"],
                    model_call["subject_type"],
                    model_call["subject_id"],
                    model_call["analysis_task_id"],
                    model_call["execution_id"],
                    model_call["revision"],
                    model_call["model_integration_id"],
                    model_call["provider_model_name"],
                    model_call["prompt_template_id"],
                    model_call["request_hash"],
                    model_call["response_hash"],
                    model_call["status"],
                    model_call["input_tokens"],
                    model_call["output_tokens"],
                    model_call["usage_source"],
                    model_call["cost_amount"],
                    model_call["latency_ms"],
                    model_call["error_code"],
                    model_call["created_by"],
                ),
            )
        artifacts = {
            "plan": payload.get("analysis_plan") or {},
            "python_script": {"script": result.get("python_script") or ""},
            "chart": result.get("visualization_artifact") or {},
            "conclusion": {"items": payload.get("conclusions") or []},
            "review": payload.get("review") or {},
        }
        for artifact_type, content in artifacts.items():
            content_hash = _content_hash(content)
            self._conn.execute(
                """
                INSERT OR IGNORE INTO platform_analysis_artifacts(
                    analysis_artifact_id, tenant_id, analysis_task_id, execution_id,
                    revision, artifact_type, execution_status, content, content_hash
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    f"{payload['task_id']}:artifact:{payload['revision']}:{artifact_type}",
                    payload["tenant_id"],
                    payload["task_id"],
                    payload["execution_id"],
                    payload["revision"],
                    artifact_type,
                    "verified" if payload.get("status") == "completed" else "draft",
                    json.dumps(content, ensure_ascii=False, sort_keys=True),
                    content_hash,
                ),
            )
        if evidence.get("evidence_id"):
            self._conn.execute(
                """
                INSERT OR IGNORE INTO platform_analysis_evidence(
                    analysis_evidence_id, tenant_id, analysis_task_id, execution_id,
                    evidence_type, evidence_ref_id, observed_value, evidence_hash,
                    freshness_status
                ) VALUES (?, ?, ?, ?, 'aggregate', ?, ?, ?, ?)
                """,
                (
                    str(evidence["evidence_id"]),
                    payload["tenant_id"],
                    payload["task_id"],
                    payload["execution_id"],
                    query_id,
                    json.dumps(evidence.get("totals") or {}, ensure_ascii=False, sort_keys=True),
                    _content_hash(evidence),
                    _freshness_status(evidence.get("source_snapshot")),
                ),
            )
        review = payload.get("review") if isinstance(payload.get("review"), dict) else {}
        checks = review.get("checks") if isinstance(review.get("checks"), dict) else {}
        passed_count = sum(1 for value in checks.values() if value is True)
        score = passed_count / len(checks) if checks else 0.0
        review_hash = _content_hash(review)
        self._conn.execute(
            """
            INSERT OR IGNORE INTO platform_evaluations(
                evaluation_id, tenant_id, analysis_task_id, execution_id, revision,
                evaluation_type, status, score, checks, evaluated_artifact_hash
            ) VALUES (?, ?, ?, ?, ?, 'overall', ?, ?, ?, ?)
            """,
            (
                f"{payload['task_id']}:evaluation:{payload['revision']}:overall",
                payload["tenant_id"],
                payload["task_id"],
                payload["execution_id"],
                payload["revision"],
                "passed" if review.get("status") == "passed" else "warning",
                score,
                json.dumps(checks, ensure_ascii=False, sort_keys=True),
                review_hash,
            ),
        )

    def save_trace_spans(self, spans: list[TraceSpan]) -> None:
        with self._conn:
            self._conn.executemany(
                """
                INSERT OR REPLACE INTO platform_trace_spans(
                    span_id, trace_id, span_name, inputs, outputs, status, created_at,
                    parent_span_id, span_kind, ended_at, duration_ms, error_code
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        span.span_id,
                        span.trace_id,
                        span.name,
                        json.dumps(span.inputs, ensure_ascii=False, sort_keys=True),
                        json.dumps(span.outputs, ensure_ascii=False, sort_keys=True),
                        span.status,
                        span.created_at,
                        span.parent_span_id,
                        span.span_kind,
                        span.ended_at,
                        span.duration_ms,
                        span.error_code,
                    )
                    for span in spans
                ],
            )

    def trace_spans(self, trace_id: str | None = None) -> list[dict[str, Any]]:
        query = """
            SELECT span_id, trace_id, span_name, inputs, outputs, status, created_at,
                   parent_span_id, span_kind, ended_at, duration_ms, error_code
            FROM platform_trace_spans
        """
        parameters: tuple[str, ...] = ()
        if trace_id:
            query += " WHERE trace_id = ?"
            parameters = (trace_id,)
        query += " ORDER BY trace_id, created_at, span_id"
        return [
            {
                **dict(row),
                "name": row["span_name"],
                "inputs": json.loads(row["inputs"] or "{}"),
                "outputs": json.loads(row["outputs"] or "{}"),
            }
            for row in self._conn.execute(query, parameters).fetchall()
        ]

    def trace_belongs_to_tenant(self, tenant_id: str, trace_id: str) -> bool:
        row = self._conn.execute(
            """
            SELECT 1 FROM platform_analysis_tasks WHERE tenant_id = ? AND trace_id = ?
            UNION ALL
            SELECT 1 FROM platform_runtime_events WHERE tenant_id = ? AND trace_id = ?
            LIMIT 1
            """,
            (tenant_id, trace_id, tenant_id, trace_id),
        ).fetchone()
        return row is not None

    def save_runtime_event(self, event: RuntimeEvent) -> None:
        with self._conn:
            self._conn.execute(
                """
                INSERT OR REPLACE INTO platform_runtime_events(
                    event_id, trace_id, event_type, tenant_id, user_id, status,
                    latency_ms, fallback_used, detail, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event.event_id,
                    event.trace_id,
                    event.event_type,
                    event.tenant_id,
                    event.user_id,
                    event.status,
                    event.latency_ms,
                    1 if event.fallback_used else 0,
                    json.dumps(event.detail, ensure_ascii=False, sort_keys=True),
                    event.created_at,
                ),
            )

    def runtime_summary(self) -> dict[str, Any]:
        aggregate = self._conn.execute(
            """
            SELECT COUNT(*) AS sample_size,
                   SUM(CASE WHEN status = 'ok' THEN 1 ELSE 0 END) AS ok_count,
                   SUM(CASE WHEN status = 'error' THEN 1 ELSE 0 END) AS error_count,
                   SUM(CASE WHEN status = 'cancelled' THEN 1 ELSE 0 END) AS cancelled_count,
                   SUM(CASE WHEN fallback_used = 1 THEN 1 ELSE 0 END) AS fallback_count,
                   COALESCE(SUM(latency_ms), 0) AS latency_sum_ms
            FROM platform_runtime_events
            """
        ).fetchone()
        last = self._conn.execute(
            """
            SELECT status, latency_ms, created_at
            FROM platform_runtime_events
            ORDER BY created_at DESC, event_id DESC LIMIT 1
            """
        ).fetchone()
        total = int(aggregate["sample_size"] or 0)
        latency_sum_ms = int(aggregate["latency_sum_ms"] or 0)
        return {
            "sample_size": total,
            "ok_count": int(aggregate["ok_count"] or 0),
            "error_count": int(aggregate["error_count"] or 0),
            "cancelled_count": int(aggregate["cancelled_count"] or 0),
            "fallback_count": int(aggregate["fallback_count"] or 0),
            "latency_sum_ms": latency_sum_ms,
            "avg_latency_ms": round(latency_sum_ms / total, 2) if total else 0,
            "last_status": last["status"] if last else None,
            "last_latency_ms": last["latency_ms"] if last else None,
            "last_seen_at": last["created_at"] if last else None,
        }

    def model_calls(self, tenant_id: str | None = None) -> list[dict[str, Any]]:
        query = """
            SELECT model_call_id, tenant_id, subject_type, subject_id,
                   analysis_task_id, execution_id,
                   revision, model_integration_id, provider_model_name,
                   prompt_template_id, request_hash, response_hash, status,
                   input_tokens, output_tokens, usage_source, cost_amount,
                   latency_ms, error_code, created_by, created_at
            FROM platform_model_calls
        """
        parameters: tuple[str, ...] = ()
        if tenant_id is not None:
            query += " WHERE tenant_id = ?"
            parameters = (tenant_id,)
        query += " ORDER BY created_at, model_call_id"
        return [dict(row) for row in self._conn.execute(query, parameters).fetchall()]

    def save_model_call_fact(
        self,
        tenant_id: str,
        subject_type: str,
        subject_id: str,
        actor_user_id: str,
        invocation: dict[str, Any],
        revision: int = 1,
    ) -> dict[str, Any] | None:
        model_call = _external_model_call(
            tenant_id, subject_type, subject_id, actor_user_id, invocation, revision
        )
        if not model_call:
            return None
        with self._conn:
            self._conn.execute(
                """
                INSERT OR IGNORE INTO platform_model_calls(
                    model_call_id, tenant_id, subject_type, subject_id,
                    analysis_task_id, execution_id, revision,
                    model_integration_id, provider_model_name, prompt_template_id,
                    request_hash, response_hash, status, input_tokens,
                    output_tokens, usage_source, cost_amount, latency_ms,
                    error_code, created_by
                ) VALUES (?, ?, ?, ?, NULL, '', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    model_call["model_call_id"], model_call["tenant_id"],
                    model_call["subject_type"], model_call["subject_id"],
                    model_call["revision"], model_call["model_integration_id"],
                    model_call["provider_model_name"], model_call["prompt_template_id"],
                    model_call["request_hash"], model_call["response_hash"],
                    model_call["status"], model_call["input_tokens"],
                    model_call["output_tokens"], model_call["usage_source"],
                    model_call["cost_amount"], model_call["latency_ms"],
                    model_call["error_code"], model_call["created_by"],
                ),
            )
        return model_call


def serialize_task(task: AnalysisTask) -> dict[str, Any]:
    return {
        "task_id": task.task_id,
        "request_id": task.request_id,
        "execution_id": task.execution_id,
        "revision": task.revision,
        "parent_execution_id": task.parent_execution_id,
        "execution_mode": task.execution_mode,
        "status": task.status,
        "tenant_id": task.tenant_id,
        "user_id": task.user_id,
        "question": task.question,
        "task_type": task.task_type,
        "analysis_plan": task.analysis_plan,
        "plan": [step.__dict__ for step in task.plan],
        "skill_results": task.skill_results,
        "knowledge_refs": task.knowledge_refs,
        "conclusions": task.conclusions,
        "review": task.review,
        "trace_id": task.trace_id,
        "manual_edits": task.manual_edits,
        "agent_group_state": task.agent_group_state,
    }


def _model_calls_from_payload(payload: dict[str, Any]) -> list[dict[str, Any]]:
    results = payload.get("skill_results") if isinstance(payload.get("skill_results"), list) else []
    result = results[0] if results and isinstance(results[0], dict) else {}
    intelligent = result.get("intelligent_analysis") if isinstance(result.get("intelligent_analysis"), dict) else {}
    stages = (
        ("planning", "analysis_planning", intelligent.get("planning_invocation")),
        ("final", "analysis_task", intelligent.get("model_invocation")),
    )
    calls: list[dict[str, Any]] = []
    for stage, subject_type, raw_invocation in stages:
        invocation = raw_invocation if isinstance(raw_invocation, dict) else {}
        model_call = _analysis_model_call_from_invocation(payload, invocation, stage, subject_type)
        if model_call:
            calls.append(model_call)
    return calls


def _model_call_from_payload(payload: dict[str, Any]) -> dict[str, Any] | None:
    """Backward-compatible accessor for the final analysis call."""

    calls = _model_calls_from_payload(payload)
    return next((item for item in calls if item["subject_type"] == "analysis_task"), None)


def _analysis_model_call_from_invocation(
    payload: dict[str, Any],
    invocation: dict[str, Any],
    stage: str,
    subject_type: str,
) -> dict[str, Any] | None:
    raw_model_id = str(invocation.get("model_id") or "").strip()
    model_id, separator, legacy_submodel = raw_model_id.partition("::")
    request_hash = str(invocation.get("request_hash") or "").strip().lower()
    if not model_id or len(request_hash) != 64:
        return None
    raw_status = str(invocation.get("status") or "failed").strip().lower()
    if raw_status == "connected":
        status = "succeeded"
    elif raw_status in {"mock", "skipped"}:
        status = "degraded"
    elif raw_status == "cancelled":
        status = "cancelled"
    else:
        status = "failed"
    response_hash = str(invocation.get("response_hash") or "").strip().lower()
    if len(response_hash) != 64:
        response_hash = ""
    revision = max(1, _safe_int(payload.get("revision"), 1))
    task_id = str(payload.get("task_id") or "")
    return {
        "model_call_id": f"{task_id}:model:{revision}:{stage}",
        "tenant_id": str(payload.get("tenant_id") or ""),
        "subject_type": subject_type,
        "subject_id": task_id,
        "analysis_task_id": task_id,
        "execution_id": str(payload.get("execution_id") or task_id),
        "revision": revision,
        "model_integration_id": model_id,
        "provider_model_name": str(invocation.get("used_model") or (legacy_submodel if separator else "")),
        "prompt_template_id": str(invocation.get("prompt_template_id") or "") or None,
        "request_hash": request_hash,
        "response_hash": response_hash,
        "status": status,
        "input_tokens": max(0, _safe_int(invocation.get("input_tokens"), 0)),
        "output_tokens": max(0, _safe_int(invocation.get("output_tokens"), 0)),
        "usage_source": "provider" if invocation.get("usage_source") == "provider" else "estimated",
        "cost_amount": max(0.0, _safe_float(invocation.get("cost_amount"), 0.0)),
        "latency_ms": max(0, _safe_int(invocation.get("latency_ms"), 0)),
        "error_code": str(invocation.get("error_code") or ""),
        "created_by": str(payload.get("user_id") or ""),
    }


def _external_model_call(
    tenant_id: str,
    subject_type: str,
    subject_id: str,
    actor_user_id: str,
    invocation: dict[str, Any],
    revision: int,
) -> dict[str, Any] | None:
    raw_model_id = str(invocation.get("model_id") or "").strip()
    model_id, separator, legacy_submodel = raw_model_id.partition("::")
    request_hash = str(invocation.get("request_hash") or "").strip().lower()
    subject_type = str(subject_type or "").strip()
    subject_id = str(subject_id or "").strip()
    if not model_id or len(request_hash) != 64 or not subject_type or not subject_id:
        return None
    response_hash = str(invocation.get("response_hash") or "").strip().lower()
    if len(response_hash) != 64:
        response_hash = ""
    raw_status = str(invocation.get("status") or "failed").strip().lower()
    status = (
        "succeeded" if raw_status == "connected"
        else "degraded" if raw_status in {"mock", "skipped"}
        else "cancelled" if raw_status == "cancelled"
        else "failed"
    )
    revision = max(1, _safe_int(revision, 1))
    return {
        "model_call_id": f"{subject_type}:{subject_id}:model:{revision}",
        "tenant_id": str(tenant_id),
        "subject_type": subject_type,
        "subject_id": subject_id,
        "analysis_task_id": None,
        "execution_id": "",
        "revision": revision,
        "model_integration_id": model_id,
        "provider_model_name": str(invocation.get("used_model") or (legacy_submodel if separator else "")),
        "prompt_template_id": str(invocation.get("prompt_template_id") or "") or None,
        "request_hash": request_hash,
        "response_hash": response_hash,
        "status": status,
        "input_tokens": max(0, _safe_int(invocation.get("input_tokens"), 0)),
        "output_tokens": max(0, _safe_int(invocation.get("output_tokens"), 0)),
        "usage_source": "provider" if invocation.get("usage_source") == "provider" else "estimated",
        "cost_amount": max(0.0, _safe_float(invocation.get("cost_amount"), 0.0)),
        "latency_ms": max(0, _safe_int(invocation.get("latency_ms"), 0)),
        "error_code": str(invocation.get("error_code") or ""),
        "created_by": str(actor_user_id),
    }


def _safe_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _safe_float(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _content_hash(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")
    ).hexdigest()


def _analysis_step_code(index: int, step: dict[str, Any]) -> str:
    agent = str(step.get("agent") or "Agent")
    action = str(step.get("action") or "run")
    return f"{index:03d}:{agent}:{action}"[:120]


def _analysis_step_type(agent: str, action: str) -> str:
    text = f"{agent} {action}".lower()
    if "query" in text or "supersonic" in text:
        return "query"
    if "python" in text or "visual" in text:
        return "python"
    if "review" in text or "validate" in text:
        return "review"
    if "skill" in text:
        return "skill"
    if "llm" in text or "model" in text or "insight" in text:
        return "llm"
    return "agent"


def _freshness_status(snapshot: Any) -> str:
    if not isinstance(snapshot, dict) or not snapshot.get("observed_at"):
        return "unknown"
    return "blocked" if snapshot.get("mock") else "fresh"


def serialize_trace_span(span: TraceSpan) -> dict[str, Any]:
    return {
        "trace_id": span.trace_id,
        "span_id": span.span_id,
        "name": span.name,
        "inputs": span.inputs,
        "outputs": span.outputs,
        "status": span.status,
        "created_at": span.created_at,
        "parent_span_id": span.parent_span_id,
        "span_kind": span.span_kind,
        "ended_at": span.ended_at,
        "duration_ms": span.duration_ms,
        "error_code": span.error_code,
    }


def serialize_runtime_event(event: RuntimeEvent) -> dict[str, Any]:
    return {
        "event_id": event.event_id,
        "trace_id": event.trace_id,
        "event_type": event.event_type,
        "tenant_id": event.tenant_id,
        "user_id": event.user_id,
        "status": event.status,
        "latency_ms": event.latency_ms,
        "fallback_used": event.fallback_used,
        "detail": event.detail,
        "created_at": event.created_at,
    }


def summarize_runtime_events(events: list[dict[str, Any]]) -> dict[str, Any]:
    total = len(events)
    ok_count = sum(1 for event in events if event.get("status") == "ok")
    error_count = sum(1 for event in events if event.get("status") == "error")
    cancelled_count = sum(1 for event in events if event.get("status") == "cancelled")
    fallback_count = sum(1 for event in events if event.get("fallback_used"))
    last_event = events[-1] if events else None
    avg_latency_ms = round(sum(int(event.get("latency_ms") or 0) for event in events) / total, 2) if total else 0
    latency_sum_ms = sum(int(event.get("latency_ms") or 0) for event in events)
    return {
        "sample_size": total,
        "ok_count": ok_count,
        "error_count": error_count,
        "cancelled_count": cancelled_count,
        "fallback_count": fallback_count,
        "avg_latency_ms": avg_latency_ms,
        "latency_sum_ms": latency_sum_ms,
        "last_status": last_event.get("status") if last_event else None,
        "last_latency_ms": last_event.get("latency_ms") if last_event else None,
        "last_seen_at": last_event.get("created_at") if last_event else None,
    }
