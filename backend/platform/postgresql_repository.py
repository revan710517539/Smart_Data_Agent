from __future__ import annotations

import json
from contextlib import contextmanager
from datetime import datetime
from typing import Any, Iterator

from backend.platform.database.identity import PostgreSQLIdentityResolver
from backend.platform.database.postgresql import PostgreSQLConnectionPool
from backend.platform.observability import RuntimeEvent, TraceSpan
from backend.platform.orchestration import AnalysisTask

from .repository import (
    AnalysisTaskRepository,
    _content_hash,
    _external_model_call,
    _freshness_status,
    _model_call_from_payload,
    _model_calls_from_payload,
    serialize_runtime_event,
    serialize_task,
    serialize_trace_span,
)


class PostgreSQLAnalysisTaskRepository(AnalysisTaskRepository):
    """Production analysis aggregate plus normalized query/evidence/telemetry facts."""

    def __init__(self, pool: PostgreSQLConnectionPool, *, owns_pool: bool = False) -> None:
        self.pool = pool
        self.owns_pool = owns_pool

    def close(self) -> None:
        if self.owns_pool:
            self.pool.close()

    def save_task(self, task: AnalysisTask) -> None:
        payload = serialize_task(task)
        with self._transaction() as connection:
            tenant_key = PostgreSQLIdentityResolver.tenant_id(connection, payload["tenant_id"])
            user_key = PostgreSQLIdentityResolver.user_id(connection, payload["user_id"])
            context_snapshot = {
                "task_type": payload["task_type"],
                "execution_id": payload["execution_id"],
                "parent_execution_id": payload["parent_execution_id"],
                "manual_edits": payload["manual_edits"],
                "agent_group_state": payload["agent_group_state"],
            }
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO platform_analysis_tasks(
                        tenant_id, task_key, request_id, trace_id, requested_by, question,
                        execution_mode, status, current_revision, analysis_plan,
                        context_snapshot, response_snapshot, started_at, finished_at, created_by
                    ) VALUES (
                        %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb,
                        %s::jsonb, %s::jsonb, now(), CASE WHEN %s IN ('succeeded','failed','cancelled') THEN now() END, %s
                    )
                    ON CONFLICT(task_key) DO UPDATE SET
                        trace_id = EXCLUDED.trace_id,
                        execution_mode = EXCLUDED.execution_mode,
                        status = EXCLUDED.status,
                        current_revision = EXCLUDED.current_revision,
                        analysis_plan = EXCLUDED.analysis_plan,
                        context_snapshot = EXCLUDED.context_snapshot,
                        response_snapshot = EXCLUDED.response_snapshot,
                        finished_at = EXCLUDED.finished_at,
                        updated_at = now(), lock_version = platform_analysis_tasks.lock_version + 1
                    RETURNING analysis_task_id
                    """,
                    (
                        tenant_key,
                        str(payload["task_id"])[:100],
                        str(payload["request_id"] or payload["task_id"])[:100],
                        str(payload["trace_id"] or payload["task_id"])[:100],
                        user_key,
                        payload["question"],
                        _execution_mode(payload["execution_mode"]),
                        _task_status(payload["status"]),
                        max(1, int(payload["revision"])),
                        _json(payload["analysis_plan"]),
                        _json(context_snapshot),
                        _json(payload),
                        _task_status(payload["status"]),
                        user_key,
                    ),
                )
                task_key = _value(cursor.fetchone(), "analysis_task_id", 0)
            self._persist_steps(connection, tenant_key, user_key, task_key, payload)
            self._persist_execution_facts(connection, tenant_key, user_key, task_key, payload)

    def get_task(self, task_id: str) -> dict[str, Any] | None:
        with self.pool.connection() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT a.response_snapshot, a.task_key, t.tenant_code,
                       u.external_subject AS user_code, a.request_id, a.trace_id,
                       a.status, a.execution_mode, a.current_revision
                FROM platform_analysis_tasks a
                JOIN platform_tenants t ON t.tenant_id = a.tenant_id
                JOIN platform_user_profiles u ON u.user_id = a.requested_by
                WHERE a.task_key = %s
                """,
                (task_id,),
            )
            row = cursor.fetchone()
        return self._task_from_row(row) if row else None

    def get_task_by_request(self, tenant_id: str, request_id: str) -> dict[str, Any] | None:
        with self.pool.connection() as connection:
            tenant_key = PostgreSQLIdentityResolver.tenant_id(connection, tenant_id, required=False)
            if tenant_key is None:
                return None
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT a.response_snapshot, a.task_key, t.tenant_code,
                           u.external_subject AS user_code, a.request_id, a.trace_id,
                           a.status, a.execution_mode, a.current_revision, a.updated_at
                    FROM platform_analysis_tasks a
                    JOIN platform_tenants t ON t.tenant_id = a.tenant_id
                    JOIN platform_user_profiles u ON u.user_id = a.requested_by
                    WHERE a.tenant_id = %s AND a.request_id = %s
                    """,
                    (tenant_key, request_id),
                )
                row = cursor.fetchone()
        return self._task_from_row(row) if row else None

    def list_tasks(self, tenant_id: str, user_id: str, limit: int = 50) -> list[dict[str, Any]]:
        with self.pool.connection() as connection:
            tenant_key = PostgreSQLIdentityResolver.tenant_id(connection, tenant_id, required=False)
            user_key = PostgreSQLIdentityResolver.user_id(connection, user_id, required=False)
            if tenant_key is None or user_key is None:
                return []
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT a.response_snapshot, a.task_key, t.tenant_code,
                           u.external_subject AS user_code, a.request_id, a.trace_id,
                           a.status, a.execution_mode, a.current_revision, a.updated_at
                    FROM platform_analysis_tasks a
                    JOIN platform_tenants t ON t.tenant_id = a.tenant_id
                    JOIN platform_user_profiles u ON u.user_id = a.requested_by
                    WHERE a.tenant_id = %s AND a.requested_by = %s
                    ORDER BY a.updated_at DESC, a.created_at DESC LIMIT %s
                    """,
                    (tenant_key, user_key, max(1, min(int(limit), 200))),
                )
                rows = cursor.fetchall()
        tasks: list[dict[str, Any]] = []
        for row in rows:
            task = self._task_from_row(row)
            task["created_at"] = _iso(_value(row, "updated_at", 9))
            task["updated_at"] = task["created_at"]
            tasks.append(task)
        return tasks

    def delete_task(self, tenant_id: str, user_id: str, task_id: str) -> bool:
        with self._transaction() as connection:
            tenant_key = PostgreSQLIdentityResolver.tenant_id(connection, tenant_id, required=False)
            user_key = PostgreSQLIdentityResolver.user_id(connection, user_id, required=False)
            if tenant_key is None or user_key is None:
                return False
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT analysis_task_id, trace_id
                    FROM platform_analysis_tasks
                    WHERE tenant_id = %s AND requested_by = %s AND task_key = %s
                    FOR UPDATE
                    """,
                    (tenant_key, user_key, task_id),
                )
                row = cursor.fetchone()
                if row is None:
                    return False
                analysis_task_id = _value(row, "analysis_task_id", 0)
                trace_id = str(_value(row, "trace_id", 1) or "")
                if trace_id:
                    cursor.execute(
                        "DELETE FROM platform_trace_spans WHERE tenant_id = %s AND trace_id = %s",
                        (tenant_key, trace_id),
                    )
                cursor.execute(
                    "DELETE FROM platform_analysis_tasks WHERE analysis_task_id = %s",
                    (analysis_task_id,),
                )
                return cursor.rowcount > 0

    def save_trace_spans(self, spans: list[TraceSpan]) -> None:
        if not spans:
            return
        by_trace: dict[str, list[TraceSpan]] = {}
        for span in spans:
            by_trace.setdefault(span.trace_id, []).append(span)
        with self._transaction() as connection:
            for trace_id, trace_spans in by_trace.items():
                tenant_key, actor_key = self._trace_owner(connection, trace_id)
                for span in trace_spans:
                    fact = serialize_trace_span(span)
                    attributes = {"inputs": fact["inputs"], "outputs": fact["outputs"]}
                    with connection.cursor() as cursor:
                        cursor.execute(
                            """
                            INSERT INTO platform_trace_spans(
                                tenant_id, span_key, trace_id, span_name, span_kind, status,
                                started_at, ended_at, duration_ms, attributes, error_code, created_by
                            ) VALUES (
                                %s, %s, %s, %s, %s, %s, %s::timestamptz, %s::timestamptz,
                                %s, %s::jsonb, %s, %s
                            )
                            ON CONFLICT (tenant_id, trace_id, span_key) DO UPDATE SET
                                span_name = EXCLUDED.span_name, span_kind = EXCLUDED.span_kind,
                                status = EXCLUDED.status, ended_at = EXCLUDED.ended_at,
                                duration_ms = EXCLUDED.duration_ms, attributes = EXCLUDED.attributes,
                                error_code = EXCLUDED.error_code, updated_at = now(),
                                lock_version = platform_trace_spans.lock_version + 1
                            """,
                            (
                                tenant_key, fact["span_id"], trace_id, fact["name"],
                                fact["span_kind"] or "internal", _span_status(fact["status"]),
                                fact["created_at"], fact["ended_at"], fact["duration_ms"],
                                _json(attributes), fact["error_code"] or None, actor_key,
                            ),
                        )
                for span in trace_spans:
                    if not span.parent_span_id:
                        continue
                    with connection.cursor() as cursor:
                        cursor.execute(
                            """
                            UPDATE platform_trace_spans child
                            SET parent_span_id = parent.span_id, updated_at = now()
                            FROM platform_trace_spans parent
                            WHERE child.tenant_id = %s AND child.trace_id = %s AND child.span_key = %s
                              AND parent.tenant_id = child.tenant_id AND parent.trace_id = child.trace_id
                              AND parent.span_key = %s
                            """,
                            (tenant_key, trace_id, span.span_id, span.parent_span_id),
                        )

    def trace_spans(self, trace_id: str | None = None) -> list[dict[str, Any]]:
        params: tuple[Any, ...] = ()
        where = ""
        if trace_id:
            where = "WHERE s.trace_id = %s"
            params = (trace_id,)
        with self.pool.connection() as connection, connection.cursor() as cursor:
            cursor.execute(
                f"""
                SELECT s.span_key, s.trace_id, s.span_name, s.attributes, s.status,
                       s.started_at, parent.span_key AS parent_span_key, s.span_kind,
                       s.ended_at, s.duration_ms, s.error_code
                FROM platform_trace_spans s
                LEFT JOIN platform_trace_spans parent ON parent.span_id = s.parent_span_id
                {where}
                ORDER BY s.trace_id, s.started_at, s.span_key
                """,
                params,
            )
            rows = cursor.fetchall()
        return [self._trace_from_row(row) for row in rows]

    def trace_belongs_to_tenant(self, tenant_id: str, trace_id: str) -> bool:
        with self.pool.connection() as connection:
            tenant_key = PostgreSQLIdentityResolver.tenant_id(connection, tenant_id, required=False)
            if tenant_key is None:
                return False
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT 1 FROM platform_analysis_tasks WHERE tenant_id = %s AND trace_id = %s
                    UNION ALL
                    SELECT 1 FROM platform_runtime_events WHERE tenant_id = %s AND trace_id = %s
                    LIMIT 1
                    """,
                    (tenant_key, trace_id, tenant_key, trace_id),
                )
                return cursor.fetchone() is not None

    def save_runtime_event(self, event: RuntimeEvent) -> None:
        fact = serialize_runtime_event(event)
        with self._transaction() as connection:
            tenant_key = PostgreSQLIdentityResolver.tenant_id(connection, fact["tenant_id"])
            user_key = PostgreSQLIdentityResolver.user_id(connection, fact["user_id"], required=False)
            detail = dict(fact["detail"] or {})
            detail["event_id"] = fact["event_id"]
            detail["actor_user_id"] = fact["user_id"]
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO platform_runtime_events(
                        tenant_id, trace_id, event_type, status, latency_ms,
                        fallback_used, detail, occurred_at, created_by
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s::jsonb, %s::timestamptz, %s)
                    """,
                    (
                        tenant_key, fact["trace_id"] or None, fact["event_type"],
                        _runtime_status(fact["status"]), max(0, int(fact["latency_ms"] or 0)),
                        bool(fact["fallback_used"]), _json(detail), fact["created_at"], user_key,
                    ),
                )

    def runtime_summary(self) -> dict[str, Any]:
        with self.pool.connection() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT COUNT(*) AS sample_size,
                       COUNT(*) FILTER (WHERE status = 'ok') AS ok_count,
                       COUNT(*) FILTER (WHERE status = 'error') AS error_count,
                       COUNT(*) FILTER (WHERE status = 'cancelled') AS cancelled_count,
                       COUNT(*) FILTER (WHERE fallback_used) AS fallback_count,
                       COALESCE(SUM(latency_ms), 0) AS latency_sum_ms
                FROM platform_runtime_events
                """
            )
            aggregate = cursor.fetchone()
            cursor.execute(
                """
                SELECT status, latency_ms, occurred_at
                FROM platform_runtime_events
                ORDER BY occurred_at DESC, runtime_event_id DESC LIMIT 1
                """
            )
            last = cursor.fetchone()
        total = int(_value(aggregate, "sample_size", 0) or 0)
        latency_sum = int(_value(aggregate, "latency_sum_ms", 5) or 0)
        return {
            "sample_size": total,
            "ok_count": int(_value(aggregate, "ok_count", 1) or 0),
            "error_count": int(_value(aggregate, "error_count", 2) or 0),
            "cancelled_count": int(_value(aggregate, "cancelled_count", 3) or 0),
            "fallback_count": int(_value(aggregate, "fallback_count", 4) or 0),
            "latency_sum_ms": latency_sum,
            "avg_latency_ms": round(latency_sum / total, 2) if total else 0,
            "last_status": _value(last, "status", 0) if last else None,
            "last_latency_ms": _value(last, "latency_ms", 1) if last else None,
            "last_seen_at": _iso(_value(last, "occurred_at", 2)) if last else None,
        }

    def model_calls(self, tenant_id: str | None = None) -> list[dict[str, Any]]:
        params: tuple[Any, ...] = ()
        where = ""
        if tenant_id is not None:
            with self.pool.connection() as connection:
                tenant_key = PostgreSQLIdentityResolver.tenant_id(connection, tenant_id, required=False)
            if tenant_key is None:
                return []
            where = "WHERE m.tenant_id = %s"
            params = (tenant_key,)
        with self.pool.connection() as connection, connection.cursor() as cursor:
            cursor.execute(
                f"""
                SELECT m.model_call_key, t.tenant_code, m.subject_type, m.subject_id,
                       task.task_key AS analysis_task_key, m.revision,
                       model.integration_code AS model_integration_code,
                       m.provider_model_name, prompt.template_code AS prompt_template_code,
                       m.request_hash, m.response_hash, m.status, m.input_tokens,
                       m.output_tokens, m.usage_source, m.cost_amount, m.latency_ms,
                       m.error_code, creator.external_subject AS created_by, m.created_at
                FROM platform_model_calls m
                JOIN platform_tenants t ON t.tenant_id = m.tenant_id
                JOIN platform_model_integrations model ON model.model_integration_id = m.model_integration_id
                LEFT JOIN platform_analysis_tasks task ON task.analysis_task_id = m.analysis_task_id
                LEFT JOIN platform_prompt_templates prompt ON prompt.prompt_template_id = m.prompt_template_id
                LEFT JOIN platform_user_profiles creator ON creator.user_id = m.created_by
                {where}
                ORDER BY m.created_at, m.model_call_id
                """,
                params,
            )
            rows = cursor.fetchall()
        return [self._model_call_from_row(row) for row in rows]

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
        with self._transaction() as connection:
            tenant_key = PostgreSQLIdentityResolver.tenant_id(connection, tenant_id)
            actor_key = PostgreSQLIdentityResolver.user_id(connection, actor_user_id, required=False)
            self._persist_model_call(connection, tenant_key, actor_key, None, model_call)
        return model_call

    def _persist_steps(self, connection: Any, tenant_key: Any, user_key: Any, task_key: Any, payload: dict[str, Any]) -> None:
        with connection.cursor() as cursor:
            cursor.execute("DELETE FROM platform_analysis_steps WHERE analysis_task_id = %s", (task_key,))
            for index, step in enumerate(payload.get("plan") or []):
                agent = str(step.get("agent") or "Agent")
                action = str(step.get("action") or "run")
                step_type = _step_type(agent, action)
                cursor.execute(
                    """
                    INSERT INTO platform_analysis_steps(
                        tenant_id, analysis_task_id, step_code, sequence_no, step_type,
                        status, input_refs, output_refs, attempt_no, finished_at, created_by
                    ) VALUES (%s, %s, %s, %s, %s, %s, '[]'::jsonb, %s::jsonb, 1, now(), %s)
                    """,
                    (
                        tenant_key, task_key, f"{index:03d}:{agent}:{action}"[:120], index,
                        step_type, "succeeded", _json([{"response_snapshot_pointer": f"/plan/{index}"}]), user_key,
                    ),
                )

    def _persist_execution_facts(
        self,
        connection: Any,
        tenant_key: Any,
        user_key: Any,
        task_key: Any,
        payload: dict[str, Any],
    ) -> None:
        results = payload.get("skill_results") if isinstance(payload.get("skill_results"), list) else []
        result = results[0] if results and isinstance(results[0], dict) else {}
        semantic = result.get("semantic_info") if isinstance(result.get("semantic_info"), dict) else {}
        evidence = result.get("evidence") if isinstance(result.get("evidence"), dict) else {}
        data = result.get("data") if isinstance(result.get("data"), list) else []
        query_key = None
        if semantic.get("dataset_id") and semantic.get("connection_id") and evidence:
            connection_version_key = self._connection_version_id(
                connection, tenant_key, str(semantic["connection_id"])
            )
            dataset_key = self._dataset_id(connection, tenant_key, str(semantic["dataset_id"]))
            compiled = str(evidence.get("executed_sql") or evidence.get("execution_statement") or "semantic_query")
            sql_hash = str(evidence.get("executed_sql_sha256") or _content_hash(compiled))
            query_status = "cancelled" if payload.get("status") == "cancelled" else "failed" if payload.get("status") == "failed" else "succeeded"
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO platform_analysis_queries(
                        tenant_id, analysis_task_id, connection_version_id, dataset_id,
                        query_revision, compiled_sql, sql_hash, parameters, policy_snapshot,
                        status, result_hash, row_count, summary, finished_at, created_by
                    ) VALUES (
                        %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s::jsonb,
                        %s, %s, %s, %s::jsonb, now(), %s
                    )
                    ON CONFLICT (analysis_task_id, query_revision) DO UPDATE SET
                        compiled_sql = EXCLUDED.compiled_sql, sql_hash = EXCLUDED.sql_hash,
                        parameters = EXCLUDED.parameters, policy_snapshot = EXCLUDED.policy_snapshot,
                        status = EXCLUDED.status, result_hash = EXCLUDED.result_hash,
                        row_count = EXCLUDED.row_count, summary = EXCLUDED.summary,
                        finished_at = now(), updated_at = now(),
                        lock_version = platform_analysis_queries.lock_version + 1
                    RETURNING analysis_query_id
                    """,
                    (
                        tenant_key, task_key, connection_version_key, dataset_key,
                        max(1, int(payload["revision"])), compiled, sql_hash,
                        _json(evidence.get("parameters") or {}),
                        _json(semantic.get("metric_access") or {}), query_status,
                        _content_hash(data), len(data),
                        _json({
                            "totals": evidence.get("totals") or {},
                            "full_group_count": semantic.get("full_group_count"),
                            "returned_group_count": semantic.get("returned_group_count"),
                            "sql_executed": bool(evidence.get("sql_executed")),
                        }),
                        user_key,
                    ),
                )
                query_key = _value(cursor.fetchone(), "analysis_query_id", 0)

        artifacts = {
            "plan": payload.get("analysis_plan") or {},
            "python_script": {"script": result.get("python_script") or ""},
            "chart": result.get("visualization_artifact") or {},
            "conclusion": {"items": payload.get("conclusions") or []},
            "review": payload.get("review") or {},
        }
        artifact_ids: dict[str, Any] = {}
        with connection.cursor() as cursor:
            for artifact_type, content in artifacts.items():
                cursor.execute(
                    """
                    INSERT INTO platform_analysis_artifacts(
                        tenant_id, analysis_task_id, revision, artifact_type,
                        execution_status, content, content_hash, created_by
                    ) VALUES (%s, %s, %s, %s, %s, %s::jsonb, %s, %s)
                    ON CONFLICT (analysis_task_id, revision, artifact_type) DO UPDATE SET
                        execution_status = EXCLUDED.execution_status, content = EXCLUDED.content,
                        content_hash = EXCLUDED.content_hash, updated_at = now(),
                        lock_version = platform_analysis_artifacts.lock_version + 1
                    RETURNING analysis_artifact_id
                    """,
                    (
                        tenant_key, task_key, max(1, int(payload["revision"])), artifact_type,
                        "verified" if payload.get("status") == "completed" else "draft",
                        _json(content), _content_hash(content), user_key,
                    ),
                )
                artifact_ids[artifact_type] = _value(cursor.fetchone(), "analysis_artifact_id", 0)

        if evidence.get("evidence_id") and query_key is not None:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO platform_analysis_evidence(
                        tenant_id, evidence_key, analysis_task_id, conclusion_artifact_id,
                        evidence_type, evidence_ref_id, observed_value, evidence_hash,
                        freshness_status, created_by
                    ) VALUES (%s, %s, %s, %s, 'aggregate', %s, %s::jsonb, %s, %s, %s)
                    ON CONFLICT (tenant_id, evidence_key) DO UPDATE SET
                        observed_value = EXCLUDED.observed_value, evidence_hash = EXCLUDED.evidence_hash,
                        freshness_status = EXCLUDED.freshness_status, updated_at = now(),
                        lock_version = platform_analysis_evidence.lock_version + 1
                    """,
                    (
                        tenant_key, str(evidence["evidence_id"])[:200], task_key,
                        artifact_ids.get("conclusion"), query_key,
                        _json(evidence.get("totals") or {}), _content_hash(evidence),
                        _freshness_status(evidence.get("source_snapshot")), user_key,
                    ),
                )

        review = payload.get("review") if isinstance(payload.get("review"), dict) else {}
        checks = review.get("checks") if isinstance(review.get("checks"), dict) else {}
        passed_count = sum(1 for value in checks.values() if value is True)
        score = passed_count / len(checks) if checks else 0.0
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO platform_evaluations(
                    tenant_id, analysis_task_id, revision, evaluation_type, status,
                    score, checks, evaluator_type, evaluator_version,
                    evaluated_artifact_hash, created_by
                ) VALUES (%s, %s, %s, 'overall', %s, %s, %s::jsonb,
                          'deterministic', 'analysis-review-v1', %s, %s)
                ON CONFLICT (analysis_task_id, revision, evaluation_type) DO UPDATE SET
                    status = EXCLUDED.status, score = EXCLUDED.score, checks = EXCLUDED.checks,
                    evaluated_artifact_hash = EXCLUDED.evaluated_artifact_hash,
                    evaluated_at = now(), updated_at = now(),
                    lock_version = platform_evaluations.lock_version + 1
                """,
                (
                    tenant_key, task_key, max(1, int(payload["revision"])),
                    "passed" if review.get("status") == "passed" else "warning",
                    score, _json(checks), _content_hash(review), user_key,
                ),
            )
        for model_call in _model_calls_from_payload(payload):
            self._persist_model_call(connection, tenant_key, user_key, task_key, model_call)

    def _persist_model_call(
        self,
        connection: Any,
        tenant_key: Any,
        actor_key: Any,
        task_key: Any | None,
        model_call: dict[str, Any],
    ) -> None:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT model_integration_id
                FROM platform_model_integrations
                WHERE tenant_id = %s AND integration_code = %s AND status IN ('available','degraded')
                """,
                (tenant_key, model_call["model_integration_id"]),
            )
            row = cursor.fetchone()
            if not row:
                raise KeyError("model_integration_not_available")
            model_key = _value(row, "model_integration_id", 0)
            prompt_key = None
            if model_call.get("prompt_template_id"):
                cursor.execute(
                    """
                    SELECT prompt_template_id FROM platform_prompt_templates
                    WHERE tenant_id = %s AND template_code = %s AND status = 'published'
                    ORDER BY version DESC LIMIT 1
                    """,
                    (tenant_key, model_call["prompt_template_id"]),
                )
                prompt_row = cursor.fetchone()
                prompt_key = _value(prompt_row, "prompt_template_id", 0) if prompt_row else None
            cursor.execute(
                """
                INSERT INTO platform_model_calls(
                    tenant_id, model_call_key, analysis_task_id, subject_type, subject_id,
                    revision, model_integration_id, provider_model_name, prompt_template_id,
                    request_hash, response_hash, status, input_tokens, output_tokens,
                    usage_source, cost_amount, latency_ms, error_code, created_by
                ) VALUES (
                    %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NULLIF(%s, ''),
                    %s, %s, %s, %s, %s, %s, NULLIF(%s, ''), %s
                )
                ON CONFLICT (tenant_id, subject_type, subject_id, revision) DO UPDATE SET
                    model_call_key = EXCLUDED.model_call_key,
                    provider_model_name = EXCLUDED.provider_model_name,
                    response_hash = EXCLUDED.response_hash, status = EXCLUDED.status,
                    input_tokens = EXCLUDED.input_tokens, output_tokens = EXCLUDED.output_tokens,
                    usage_source = EXCLUDED.usage_source, cost_amount = EXCLUDED.cost_amount,
                    latency_ms = EXCLUDED.latency_ms, error_code = EXCLUDED.error_code,
                    updated_at = now(), lock_version = platform_model_calls.lock_version + 1
                """,
                (
                    tenant_key, model_call["model_call_id"][:300], task_key,
                    model_call["subject_type"][:64], model_call["subject_id"][:300],
                    model_call["revision"], model_key, model_call["provider_model_name"][:200],
                    prompt_key, model_call["request_hash"], model_call["response_hash"],
                    model_call["status"], model_call["input_tokens"], model_call["output_tokens"],
                    model_call["usage_source"], model_call["cost_amount"], model_call["latency_ms"],
                    model_call["error_code"][:100], actor_key,
                ),
            )

    @staticmethod
    def _task_from_row(row: Any) -> dict[str, Any]:
        snapshot = _json_value(_value(row, "response_snapshot", 0), {})
        snapshot.update(
            task_id=str(_value(row, "task_key", 1)),
            tenant_id=str(_value(row, "tenant_code", 2)),
            user_id=str(_value(row, "user_code", 3)),
            request_id=str(_value(row, "request_id", 4)),
            trace_id=str(_value(row, "trace_id", 5)),
            revision=int(_value(row, "current_revision", 8)),
        )
        return snapshot

    @staticmethod
    def _trace_from_row(row: Any) -> dict[str, Any]:
        attributes = _json_value(_value(row, "attributes", 3), {})
        started_at = _value(row, "started_at", 5)
        ended_at = _value(row, "ended_at", 8)
        return {
            "span_id": str(_value(row, "span_key", 0)),
            "trace_id": str(_value(row, "trace_id", 1)),
            "span_name": str(_value(row, "span_name", 2)),
            "name": str(_value(row, "span_name", 2)),
            "inputs": attributes.get("inputs", {}),
            "outputs": attributes.get("outputs", {}),
            "status": str(_value(row, "status", 4)),
            "created_at": _iso(started_at),
            "parent_span_id": _value(row, "parent_span_key", 6),
            "span_kind": str(_value(row, "span_kind", 7)),
            "ended_at": _iso(ended_at) if ended_at else None,
            "duration_ms": _value(row, "duration_ms", 9),
            "error_code": _value(row, "error_code", 10),
        }

    @staticmethod
    def _model_call_from_row(row: Any) -> dict[str, Any]:
        return {
            "model_call_id": str(_value(row, "model_call_key", 0)),
            "tenant_id": str(_value(row, "tenant_code", 1)),
            "subject_type": str(_value(row, "subject_type", 2)),
            "subject_id": str(_value(row, "subject_id", 3)),
            "analysis_task_id": _value(row, "analysis_task_key", 4),
            "execution_id": _value(row, "analysis_task_key", 4) or "",
            "revision": int(_value(row, "revision", 5)),
            "model_integration_id": str(_value(row, "model_integration_code", 6)),
            "provider_model_name": str(_value(row, "provider_model_name", 7)),
            "prompt_template_id": _value(row, "prompt_template_code", 8),
            "request_hash": str(_value(row, "request_hash", 9)),
            "response_hash": str(_value(row, "response_hash", 10) or ""),
            "status": str(_value(row, "status", 11)),
            "input_tokens": int(_value(row, "input_tokens", 12)),
            "output_tokens": int(_value(row, "output_tokens", 13)),
            "usage_source": str(_value(row, "usage_source", 14)),
            "cost_amount": float(_value(row, "cost_amount", 15)),
            "latency_ms": int(_value(row, "latency_ms", 16) or 0),
            "error_code": str(_value(row, "error_code", 17) or ""),
            "created_by": str(_value(row, "created_by", 18) or ""),
            "created_at": _iso(_value(row, "created_at", 19)),
        }

    @staticmethod
    def _connection_version_id(connection: Any, tenant_key: Any, connection_code: str) -> Any:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT v.connection_version_id
                FROM platform_data_connections c
                JOIN platform_connection_versions v
                  ON v.connection_id = c.connection_id AND v.version_no = c.current_version_no
                WHERE c.tenant_id = %s AND c.connection_code = %s
                  AND c.status IN ('verified','degraded') AND v.validation_status = 'verified'
                """,
                (tenant_key, connection_code),
            )
            row = cursor.fetchone()
        if not row:
            raise KeyError("analysis_connection_version_not_verified")
        return _value(row, "connection_version_id", 0)

    @staticmethod
    def _dataset_id(connection: Any, tenant_key: Any, dataset_code: str) -> Any:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT dataset_id FROM platform_datasets
                WHERE tenant_id = %s AND dataset_code = %s AND status = 'active'
                """,
                (tenant_key, dataset_code),
            )
            row = cursor.fetchone()
        if not row:
            raise KeyError("analysis_dataset_not_published")
        return _value(row, "dataset_id", 0)

    @staticmethod
    def _trace_owner(connection: Any, trace_id: str) -> tuple[Any, Any | None]:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT tenant_id, requested_by FROM platform_analysis_tasks
                WHERE trace_id = %s ORDER BY updated_at DESC LIMIT 1
                """,
                (trace_id,),
            )
            row = cursor.fetchone()
            if not row:
                cursor.execute(
                    """
                    SELECT tenant_id, created_by FROM platform_runtime_events
                    WHERE trace_id = %s ORDER BY occurred_at DESC LIMIT 1
                    """,
                    (trace_id,),
                )
                row = cursor.fetchone()
        if not row:
            raise KeyError("trace_owner_not_found")
        return _value(row, "tenant_id", 0), _value(row, "requested_by", 1) if _has_key(row, "requested_by") else _value(row, "created_by", 1)

    @contextmanager
    def _transaction(self) -> Iterator[Any]:
        with self.pool.connection() as connection:
            try:
                yield connection
                connection.commit()
            except BaseException:
                connection.rollback()
                raise


def _execution_mode(value: Any) -> str:
    value = str(value or "mock")
    return value if value in {"real", "mock", "degraded"} else "degraded"


def _task_status(value: Any) -> str:
    mapping = {"completed": "succeeded", "ok": "succeeded"}
    value = mapping.get(str(value), str(value))
    return value if value in {"queued", "planning", "running", "review_required", "succeeded", "failed", "cancelled"} else "failed"


def _runtime_status(value: Any) -> str:
    value = str(value or "error")
    return value if value in {"ok", "degraded", "error", "cancelled"} else "error"


def _span_status(value: Any) -> str:
    value = str(value or "unset")
    return value if value in {"unset", "ok", "error"} else "error"


def _step_type(agent: str, action: str) -> str:
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


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str, separators=(",", ":"))


def _json_value(value: Any, default: Any) -> Any:
    if value is None:
        return default
    return json.loads(value) if isinstance(value, str) else dict(value)


def _iso(value: Any) -> str:
    return value.isoformat() if isinstance(value, datetime) else str(value)


def _has_key(row: Any, key: str) -> bool:
    return isinstance(row, dict) and key in row


def _value(row: Any, key: str, index: int) -> Any:
    if isinstance(row, dict):
        return row[key]
    try:
        return row[key]
    except (TypeError, KeyError, IndexError):
        return row[index]
