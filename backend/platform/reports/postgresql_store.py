from __future__ import annotations

import hashlib
import json
import re
from contextlib import contextmanager
from datetime import date, datetime, timezone
from typing import Any, Iterator
from uuid import uuid4

from backend.platform.database.identity import PostgreSQLIdentityResolver
from backend.platform.database.postgresql import PostgreSQLConnectionPool

from .store import (
    CommentRevisionConflict,
    _learning_candidate,
    _normalize_analysis_result,
    _normalize_comments,
    _normalize_daily_report_run,
    _normalize_weekly_ai_task,
    _prepare_weekly_report_version,
    _resolved_reason,
    _server_comment_from_draft,
)


class PostgreSQLReportStore:
    """Normalized production reports, immutable versions and comment state machine."""

    def __init__(self, pool: PostgreSQLConnectionPool, *, owns_pool: bool = False) -> None:
        self.pool = pool
        self.owns_pool = owns_pool

    def close(self) -> None:
        if self.owns_pool:
            self.pool.close()

    # Saved analysis references -------------------------------------------------
    def list_analysis_results(self, tenant_id: str, actor_user_id: str | None = None) -> list[dict[str, Any]]:
        with self.pool.connection() as connection:
            tenant_key = PostgreSQLIdentityResolver.tenant_id(connection, tenant_id)
            actor_key = PostgreSQLIdentityResolver.user_id(connection, actor_user_id, required=False) if actor_user_id else None
            with connection.cursor() as cursor:
                cursor.execute(
                    self._saved_analysis_select()
                    + " WHERE s.tenant_id=%s AND s.archived_at IS NULL"
                    + (" AND (s.owner_user_id=%s OR s.visibility='tenant')" if actor_user_id else "")
                    + " ORDER BY s.created_at DESC LIMIT 500",
                    (tenant_key, actor_key) if actor_user_id else (tenant_key,),
                )
                rows = cursor.fetchall()
        return [self._saved_analysis_row(row) for row in rows]

    def upsert_analysis_result(self, tenant_id: str, result: dict[str, Any], updated_by: str | None = None) -> dict[str, Any]:
        normalized = _normalize_analysis_result(result)
        if not updated_by:
            raise ValueError("saved_analysis_owner_required")
        with self._transaction() as connection:
            tenant_key = PostgreSQLIdentityResolver.tenant_id(connection, tenant_id)
            actor_key = PostgreSQLIdentityResolver.user_id(connection, updated_by)
            task_key = self._analysis_task_uuid(connection, tenant_key, normalized["analysisTaskId"])
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT owner_user_id FROM platform_saved_analysis_results WHERE tenant_id=%s AND saved_result_key=%s FOR UPDATE",
                    (tenant_key, normalized["id"]),
                )
                existing = cursor.fetchone()
                if existing and _value(existing, "owner_user_id", 0) != actor_key:
                    raise PermissionError("saved_analysis_owner_required")
                cursor.execute(
                    """
                    INSERT INTO platform_saved_analysis_results(
                        tenant_id,saved_result_key,analysis_task_id,owner_user_id,title,visibility,folder,tags,created_by
                    ) VALUES (%s,%s,%s,%s,%s,%s,'','[]'::jsonb,%s)
                    ON CONFLICT (tenant_id,saved_result_key) DO UPDATE SET
                        analysis_task_id=EXCLUDED.analysis_task_id,title=EXCLUDED.title,
                        visibility=EXCLUDED.visibility,archived_at=NULL,updated_at=now(),
                        lock_version=platform_saved_analysis_results.lock_version+1
                    """,
                    (tenant_key,normalized["id"],task_key,actor_key,normalized["title"],normalized["visibility"],actor_key),
                )
        saved = next((item for item in self.list_analysis_results(tenant_id, updated_by) if item["id"] == normalized["id"]), None)
        if saved is None:
            raise RuntimeError("saved_analysis_persistence_failed")
        return saved

    def delete_analysis_result(self, tenant_id: str, result_id: str, actor_user_id: str | None = None) -> bool:
        with self._transaction() as connection:
            tenant_key = PostgreSQLIdentityResolver.tenant_id(connection, tenant_id)
            actor_key = PostgreSQLIdentityResolver.user_id(connection, actor_user_id, required=False) if actor_user_id else None
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE platform_saved_analysis_results SET archived_at=now(),updated_at=now(),lock_version=lock_version+1
                    WHERE tenant_id=%s AND saved_result_key=%s AND archived_at IS NULL
                    """ + (" AND owner_user_id=%s" if actor_user_id else ""),
                    (tenant_key,result_id,actor_key) if actor_user_id else (tenant_key,result_id),
                )
                return cursor.rowcount > 0

    # Immutable weekly report versions -----------------------------------------
    def list_weekly_report_versions(self, tenant_id: str, actor_user_id: str | None = None) -> list[dict[str, Any]]:
        with self.pool.connection() as connection:
            tenant_key = PostgreSQLIdentityResolver.tenant_id(connection, tenant_id)
            actor_key = PostgreSQLIdentityResolver.user_id(connection, actor_user_id, required=False) if actor_user_id else None
            with connection.cursor() as cursor:
                cursor.execute(
                    self._version_select()
                    + " WHERE v.tenant_id=%s AND v.status<>'archived'"
                    + (" AND (r.owner_user_id=%s OR r.visibility='tenant')" if actor_user_id else "")
                    + " ORDER BY v.saved_at DESC,v.created_at DESC LIMIT 100",
                    (tenant_key,actor_key) if actor_user_id else (tenant_key,),
                )
                rows=cursor.fetchall()
                return [self._version_from_row(connection,row) for row in rows]

    def get_weekly_report_version(self, tenant_id: str, version_id: str) -> dict[str, Any] | None:
        with self.pool.connection() as connection:
            tenant_key=PostgreSQLIdentityResolver.tenant_id(connection,tenant_id)
            with connection.cursor() as cursor:
                cursor.execute(self._version_select()+" WHERE v.tenant_id=%s AND v.report_version_key=%s AND v.status<>'archived'",(tenant_key,version_id))
                row=cursor.fetchone()
            return self._version_from_row(connection,row) if row else None

    def save_weekly_report_version(self, tenant_id: str, version: dict[str, Any], updated_by: str | None = None) -> dict[str, Any]:
        normalized=_prepare_weekly_report_version(tenant_id,version,updated_by)
        if not updated_by: raise ValueError("weekly_report_owner_required")
        with self._transaction() as connection:
            tenant_key=PostgreSQLIdentityResolver.tenant_id(connection,tenant_id)
            actor_key=PostgreSQLIdentityResolver.user_id(connection,updated_by)
            with connection.cursor() as cursor:
                cursor.execute("SELECT version_checksum FROM platform_weekly_report_versions WHERE tenant_id=%s AND report_version_key=%s",(tenant_key,normalized["id"]))
                existing=cursor.fetchone()
                if existing:
                    if str(_value(existing,"version_checksum",0))!=normalized["contentHash"]:
                        raise ValueError("immutable_weekly_report_version_conflict")
                    result=self._version_by_key(connection,tenant_key,normalized["id"])
                    return result
                report_key=self._ensure_report(connection,tenant_key,normalized["reportId"],normalized,actor_key)
                cursor.execute("SELECT report_version_key FROM platform_weekly_report_versions WHERE report_id=%s AND version_checksum=%s",(report_key,normalized["contentHash"]))
                duplicate=cursor.fetchone()
                if duplicate:
                    result=self._version_by_key(connection,tenant_key,str(_value(duplicate,"report_version_key",0)))
                    result["deduplicated"]=True
                    return result
                cursor.execute("SELECT COALESCE(MAX(version_no),0)+1 AS next_version FROM platform_weekly_report_versions WHERE report_id=%s",(report_key,))
                revision=int(_value(cursor.fetchone(),"next_version",0))
                parent_key=None
                if normalized.get("parentVersionId"):
                    parent_key=self._version_uuid(connection,tenant_key,str(normalized["parentVersionId"]),required=False)
                period_start,period_end=_period(normalized.get("report") or {})
                metadata=_version_metadata(normalized)
                snapshot=_snapshot_at(normalized.get("report") or {},normalized["savedAt"])
                cursor.execute(
                    """
                    INSERT INTO platform_weekly_report_versions(
                        tenant_id,report_version_key,report_id,version_no,parent_version_id,
                        period_start,period_end,status,version_checksum,data_snapshot_at,
                        document_metadata,evidence_summary,saved_at,created_by
                    ) VALUES (%s,%s,%s,%s,%s,%s,%s,'draft',%s,%s,%s::jsonb,%s::jsonb,%s,%s)
                    RETURNING report_version_id
                    """,
                    (tenant_key,normalized["id"],report_key,revision,parent_key,period_start,period_end,normalized["contentHash"],snapshot,_json(metadata),_json(normalized["evidenceSummary"]),_parse_datetime(normalized["savedAt"]),actor_key),
                )
                version_key=_value(cursor.fetchone(),"report_version_id",0)
                self._insert_blocks(cursor,tenant_key,version_key,normalized.get("report") or {},actor_key)
                cursor.execute("UPDATE platform_reports SET current_version_no=%s,updated_at=now(),lock_version=lock_version+1 WHERE report_id=%s",(revision,report_key))
        result=self.get_weekly_report_version(tenant_id,normalized["id"])
        if result is None: raise RuntimeError("weekly_report_persistence_failed")
        return result

    def archive_expired(self, tenant_id: str, cutoff: datetime) -> dict[str,int]:
        with self._transaction() as connection:
            tenant_key=PostgreSQLIdentityResolver.tenant_id(connection,tenant_id)
            with connection.cursor() as cursor:
                cursor.execute("UPDATE platform_saved_analysis_results SET archived_at=now(),updated_at=now(),lock_version=lock_version+1 WHERE tenant_id=%s AND archived_at IS NULL AND created_at<%s",(tenant_key,cutoff))
                result_count=cursor.rowcount
                cursor.execute("UPDATE platform_weekly_report_versions SET status='archived',updated_at=now(),lock_version=lock_version+1 WHERE tenant_id=%s AND status<>'archived' AND saved_at<%s",(tenant_key,cutoff))
                version_count=cursor.rowcount
        return {"analysis_results":result_count,"weekly_versions":version_count}

    # Comment state machine -----------------------------------------------------
    def get_report_comments(self, tenant_id: str, report_id: str) -> list[dict[str,Any]]:
        with self.pool.connection() as connection:
            tenant_key=PostgreSQLIdentityResolver.tenant_id(connection,tenant_id)
            report_key=self._report_uuid(connection,tenant_key,report_id,required=False)
            return self._comments(connection,tenant_key,report_key) if report_key else []

    def get_comment_revision(self, tenant_id: str, report_id: str) -> int:
        with self.pool.connection() as connection:
            tenant_key=PostgreSQLIdentityResolver.tenant_id(connection,tenant_id)
            report_key=self._report_uuid(connection,tenant_key,report_id,required=False)
            return self._revision(connection,report_key) if report_key else 0

    def replace_report_comments(self, tenant_id: str, report_id: str, comments: list[dict[str,Any]], updated_by: str | None=None, expected_revision: int | None=None) -> list[dict[str,Any]]:
        if not updated_by: raise ValueError("report_comment_actor_required")
        normalized=_normalize_comments(comments)
        with self._transaction() as connection:
            tenant_key=PostgreSQLIdentityResolver.tenant_id(connection,tenant_id)
            actor_key=PostgreSQLIdentityResolver.user_id(connection,updated_by)
            report_key=self._ensure_placeholder_report(connection,tenant_key,report_id,actor_key)
            current=self._lock_revision(connection,report_key)
            if expected_revision is not None and int(expected_revision)!=current: raise CommentRevisionConflict(current)
            with connection.cursor() as cursor:
                cursor.execute("UPDATE platform_report_comments SET status='deleted',updated_at=now(),lock_version=lock_version+1 WHERE report_id=%s AND status<>'deleted'",(report_key,))
                for item in normalized:
                    author_key=PostgreSQLIdentityResolver.user_id(connection,str(item.get("author") or updated_by),required=False) or actor_key
                    anchor=_comment_anchor(item)
                    comment_key=str(item["id"])
                    cursor.execute(
                        """
                        INSERT INTO platform_report_comments(
                            tenant_id,comment_key,report_id,author_user_id,comment_body,anchor,status,
                            resolved_by,resolved_at,created_by
                        ) VALUES (%s,%s,%s,%s,%s,%s::jsonb,%s,%s,%s,%s)
                        ON CONFLICT (tenant_id,comment_key) DO UPDATE SET
                            comment_body=EXCLUDED.comment_body,anchor=EXCLUDED.anchor,status=EXCLUDED.status,
                            resolved_by=EXCLUDED.resolved_by,resolved_at=EXCLUDED.resolved_at,
                            updated_at=now(),lock_version=platform_report_comments.lock_version+1
                        """,
                        (tenant_key,comment_key,report_key,author_key,item["text"],_json(anchor),item["status"],actor_key if item["status"]=="resolved" else None,_parse_datetime(item.get("resolvedAt")) if item.get("resolvedAt") else None,actor_key),
                    )
            visible=self._comments(connection,tenant_key,report_key)
            self._write_revision(connection,tenant_key,report_key,current+1,visible,actor_key)
            return visible

    def create_report_comment(self, tenant_id: str, report_id: str, draft: dict[str,Any], actor_user_id: str, expected_revision: int, client_request_id: str) -> dict[str,Any]:
        if not client_request_id: raise ValueError("comment_client_request_id_required")
        with self._transaction() as connection:
            tenant_key=PostgreSQLIdentityResolver.tenant_id(connection,tenant_id)
            actor_key=PostgreSQLIdentityResolver.user_id(connection,actor_user_id)
            report_key=self._ensure_placeholder_report(connection,tenant_key,report_id,actor_key)
            current=self._lock_revision(connection,report_key)
            with connection.cursor() as cursor:
                cursor.execute("SELECT comment_key FROM platform_report_comments WHERE tenant_id=%s AND report_id=%s AND client_request_id=%s",(tenant_key,report_key,client_request_id))
                replay=cursor.fetchone()
            if replay:
                comments=self._comments(connection,tenant_key,report_key)
                comment=next(item for item in comments if item["id"]==str(_value(replay,"comment_key",0)))
                return _mutation(comment,comments,current,True)
            if int(expected_revision)!=current: raise CommentRevisionConflict(current)
            comment=_server_comment_from_draft(draft,actor_user_id,client_request_id)
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO platform_report_comments(
                        tenant_id,comment_key,client_request_id,report_id,author_user_id,
                        comment_body,anchor,status,created_by
                    ) VALUES (%s,%s,%s,%s,%s,%s,%s::jsonb,'open',%s)
                    """,
                    (tenant_key,comment["id"],client_request_id,report_key,actor_key,comment["text"],_json(_comment_anchor(comment)),actor_key),
                )
            comments=self._comments(connection,tenant_key,report_key)
            self._write_revision(connection,tenant_key,report_key,current+1,comments,actor_key)
            created=next(item for item in comments if item["id"]==comment["id"])
            return _mutation(created,comments,current+1)

    def mutate_report_comment(self, tenant_id: str, report_id: str, comment_id: str, action: str, payload: dict[str,Any], actor_user_id: str, expected_revision: int, client_request_id: str="") -> dict[str,Any]:
        with self._transaction() as connection:
            tenant_key=PostgreSQLIdentityResolver.tenant_id(connection,tenant_id)
            actor_key=PostgreSQLIdentityResolver.user_id(connection,actor_user_id)
            report_key=self._report_uuid(connection,tenant_key,report_id)
            current=self._lock_revision(connection,report_key)
            if int(expected_revision)!=current: raise CommentRevisionConflict(current)
            with connection.cursor() as cursor:
                cursor.execute("SELECT comment_id,author_user_id,status,anchor FROM platform_report_comments WHERE tenant_id=%s AND report_id=%s AND comment_key=%s AND status<>'deleted' FOR UPDATE",(tenant_key,report_key,comment_id))
                row=cursor.fetchone()
                if not row: raise KeyError("report_comment_not_found")
                changed=True
                if action=="resolve":
                    anchor=_json_value(_value(row,"anchor",3),{})
                    reason=_resolved_reason(payload.get("reason"))
                    if str(_value(row,"status",2))=="resolved" and anchor.get("resolvedReason")==reason: changed=False
                    else:
                        anchor["resolvedReason"]=reason
                        cursor.execute("UPDATE platform_report_comments SET status='resolved',resolved_by=%s,resolved_at=now(),anchor=%s::jsonb,updated_at=now(),lock_version=lock_version+1 WHERE comment_id=%s",(actor_key,_json(anchor),_value(row,"comment_id",0)))
                elif action=="reopen":
                    if str(_value(row,"status",2)) in {"open","reopened"}: changed=False
                    else: cursor.execute("UPDATE platform_report_comments SET status='reopened',resolved_by=NULL,resolved_at=NULL,updated_at=now(),lock_version=lock_version+1 WHERE comment_id=%s",(_value(row,"comment_id",0),))
                elif action=="reply":
                    body=str(payload.get("text") or "").strip()
                    if not body: raise ValueError("report_comment_reply_text_required")
                    if not client_request_id: raise ValueError("comment_client_request_id_required")
                    cursor.execute("SELECT reply_id FROM platform_report_comment_replies WHERE tenant_id=%s AND comment_id=%s AND client_request_id=%s",(tenant_key,_value(row,"comment_id",0),client_request_id))
                    if cursor.fetchone(): changed=False
                    else:
                        cursor.execute("INSERT INTO platform_report_comment_replies(tenant_id,reply_key,client_request_id,comment_id,author_user_id,reply_body,status,created_by) VALUES (%s,%s,%s,%s,%s,%s,'active',%s)",(tenant_key,f"reply_{uuid4().hex}",client_request_id,_value(row,"comment_id",0),actor_key,body,actor_key))
                        cursor.execute("UPDATE platform_report_comments SET updated_at=now(),lock_version=lock_version+1 WHERE comment_id=%s",(_value(row,"comment_id",0),))
                elif action=="delete":
                    if _value(row,"author_user_id",1)!=actor_key: raise PermissionError("report_comment_author_required")
                    cursor.execute("UPDATE platform_report_comments SET status='deleted',updated_at=now(),lock_version=lock_version+1 WHERE comment_id=%s",(_value(row,"comment_id",0),))
                else: raise ValueError("unsupported_report_comment_action")
            comments=self._comments(connection,tenant_key,report_key)
            revision=current
            if changed:
                revision=current+1
                self._write_revision(connection,tenant_key,report_key,revision,comments,actor_key)
            updated=next((item for item in comments if item["id"]==comment_id),None)
            if action=="delete": updated={"id":comment_id,"status":"deleted"}
            if updated is None: raise KeyError("report_comment_not_found")
            return _mutation(updated,comments,revision,not changed)

    # Weekly AI learning --------------------------------------------------------
    def list_weekly_ai_tasks(self, tenant_id: str) -> list[dict[str,Any]]:
        with self.pool.connection() as connection:
            tenant_key=PostgreSQLIdentityResolver.tenant_id(connection,tenant_id)
            with connection.cursor() as cursor:
                cursor.execute(self._weekly_ai_select()+" WHERE w.tenant_id=%s ORDER BY w.updated_at DESC LIMIT 100",(tenant_key,))
                rows=cursor.fetchall()
        return [self._weekly_ai_row(row) for row in rows]

    def get_weekly_ai_task(self, tenant_id: str, version_id: str) -> dict[str,Any] | None:
        with self.pool.connection() as connection:
            tenant_key=PostgreSQLIdentityResolver.tenant_id(connection,tenant_id)
            version_key=self._version_uuid(connection,tenant_key,version_id,required=False)
            if not version_key: return None
            with connection.cursor() as cursor:
                cursor.execute(self._weekly_ai_select()+" WHERE w.tenant_id=%s AND w.report_version_id=%s",(tenant_key,version_key))
                row=cursor.fetchone()
        return self._weekly_ai_row(row) if row else None

    def upsert_weekly_ai_task(self, tenant_id: str, task: dict[str,Any], updated_by: str | None=None) -> dict[str,Any]:
        normalized=_normalize_weekly_ai_task(task)
        if not updated_by: raise ValueError("weekly_ai_actor_required")
        with self._transaction() as connection:
            tenant_key=PostgreSQLIdentityResolver.tenant_id(connection,tenant_id)
            actor_key=PostgreSQLIdentityResolver.user_id(connection,updated_by)
            version_key=self._version_uuid(connection,tenant_key,normalized["version_id"])
            status={"待分析":"queued","分析中":"running","已完成":"succeeded","分析失败":"failed"}[normalized["status"]]
            input_hash=hashlib.sha256(_json(normalized["input_snapshot"]).encode()).hexdigest()
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO weekly_report_ai_analysis_task(
                        tenant_id,weekly_ai_task_key,report_version_id,task_type,status,input_hash,
                        input_snapshot,debate_result,final_result,error_summary,started_at,finished_at,created_by
                    ) VALUES (%s,%s,%s,'weekly_learning',%s,%s,%s::jsonb,%s::jsonb,%s::jsonb,%s,
                        CASE WHEN %s='running' THEN now() END,CASE WHEN %s IN ('succeeded','failed','cancelled') THEN now() END,%s)
                    ON CONFLICT (report_version_id) DO UPDATE SET
                        weekly_ai_task_key=EXCLUDED.weekly_ai_task_key,status=EXCLUDED.status,input_hash=EXCLUDED.input_hash,
                        input_snapshot=EXCLUDED.input_snapshot,debate_result=EXCLUDED.debate_result,
                        final_result=EXCLUDED.final_result,error_summary=EXCLUDED.error_summary,
                        started_at=COALESCE(weekly_report_ai_analysis_task.started_at,EXCLUDED.started_at),
                        finished_at=EXCLUDED.finished_at,updated_at=now(),lock_version=weekly_report_ai_analysis_task.lock_version+1
                    """,
                    (tenant_key,normalized["id"],version_key,status,input_hash,_json(normalized["input_snapshot"]),_json(normalized["debate_result"]),_json(normalized["final_result"]),normalized["error_message"] or None,status,status,actor_key),
                )
        result=self.get_weekly_ai_task(tenant_id,normalized["version_id"])
        if result is None: raise RuntimeError("weekly_ai_task_persistence_failed")
        return result

    def create_learning_candidate(self, tenant_id: str, version_id: str, candidate_type: str, content: dict[str,Any], evidence_summary: dict[str,Any], confidence: float, created_by: str) -> dict[str,Any]:
        candidate=_learning_candidate(tenant_id,version_id,candidate_type,content,evidence_summary,confidence,created_by)
        with self._transaction() as connection:
            tenant_key=PostgreSQLIdentityResolver.tenant_id(connection,tenant_id)
            actor_key=PostgreSQLIdentityResolver.user_id(connection,created_by)
            version_key=self._version_uuid(connection,tenant_key,version_id)
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO platform_report_learning_candidates(
                        tenant_id,learning_candidate_key,report_version_id,candidate_type,candidate_content,
                        evidence,confidence,content_hash,status,created_by
                    ) VALUES (%s,%s,%s,%s,%s::jsonb,%s::jsonb,%s,%s,'pending_review',%s)
                    ON CONFLICT (report_version_id,candidate_type,content_hash) DO NOTHING
                    """,
                    (tenant_key,candidate["learning_candidate_id"],version_key,candidate_type,_json(content),_json(evidence_summary),candidate["confidence"],candidate["content_hash"],actor_key),
                )
                cursor.execute("SELECT learning_candidate_key FROM platform_report_learning_candidates WHERE report_version_id=%s AND candidate_type=%s AND content_hash=%s",(version_key,candidate_type,candidate["content_hash"]))
                key=str(_value(cursor.fetchone(),"learning_candidate_key",0))
        return self._learning_by_key(tenant_id,key)

    def list_learning_candidates(self, tenant_id: str, status: str | None=None) -> list[dict[str,Any]]:
        mapped={"candidate":"pending_review","review":"pending_review"}.get(str(status),status) if status else None
        with self.pool.connection() as connection:
            tenant_key=PostgreSQLIdentityResolver.tenant_id(connection,tenant_id)
            with connection.cursor() as cursor:
                cursor.execute(self._learning_select()+" WHERE c.tenant_id=%s"+(" AND c.status=%s" if mapped else "")+" ORDER BY c.created_at DESC",(tenant_key,mapped) if mapped else (tenant_key,))
                rows=cursor.fetchall()
        return [self._learning_row(row) for row in rows]

    def review_learning_candidate(self, tenant_id: str, candidate_id: str, decision: str, reviewer: str) -> dict[str,Any]:
        if decision not in {"approve","reject"}: raise ValueError("invalid_report_learning_review_decision")
        with self._transaction() as connection:
            tenant_key=PostgreSQLIdentityResolver.tenant_id(connection,tenant_id)
            reviewer_key=PostgreSQLIdentityResolver.user_id(connection,reviewer)
            with connection.cursor() as cursor:
                cursor.execute("SELECT learning_candidate_id,status,created_by FROM platform_report_learning_candidates WHERE tenant_id=%s AND learning_candidate_key=%s FOR UPDATE",(tenant_key,candidate_id))
                row=cursor.fetchone()
                if not row: raise KeyError("report_learning_candidate_not_found")
                if str(_value(row,"status",1))!="pending_review": raise ValueError("report_learning_candidate_is_not_pending")
                if _value(row,"created_by",2)==reviewer_key: raise PermissionError("four_eyes_report_learning_review_required")
                cursor.execute("UPDATE platform_report_learning_candidates SET status=%s,reviewed_by=%s,reviewed_at=now(),updated_at=now(),lock_version=lock_version+1 WHERE learning_candidate_id=%s",("approved" if decision=="approve" else "rejected",reviewer_key,_value(row,"learning_candidate_id",0)))
        return self._learning_by_key(tenant_id,candidate_id)

    def mark_learning_candidate_applied(self, tenant_id: str, candidate_id: str) -> dict[str,Any]:
        with self._transaction() as connection:
            tenant_key=PostgreSQLIdentityResolver.tenant_id(connection,tenant_id)
            with connection.cursor() as cursor:
                cursor.execute("UPDATE platform_report_learning_candidates SET status='applied',updated_at=now(),lock_version=lock_version+1 WHERE tenant_id=%s AND learning_candidate_key=%s AND status='approved'",(tenant_key,candidate_id))
                if cursor.rowcount!=1: raise ValueError("approved_report_learning_candidate_required")
        return self._learning_by_key(tenant_id,candidate_id)

    # Daily immutable email artifacts ------------------------------------------
    def create_daily_report_run(self, tenant_id: str, payload: dict[str,Any], created_by: str) -> dict[str,Any]:
        normalized=_normalize_daily_report_run(tenant_id,payload,created_by)
        with self._transaction() as connection:
            tenant_key=PostgreSQLIdentityResolver.tenant_id(connection,tenant_id)
            actor_key=PostgreSQLIdentityResolver.user_id(connection,created_by)
            version_key=self._version_uuid(connection,tenant_key,normalized["source_report_version_id"])
            artifact_key=self._artifact_uuid(connection,tenant_key,normalized["body_artifact_id"])
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO platform_daily_report_runs(
                        tenant_id,daily_report_run_key,owner_user_id,report_date,source_report_version_id,
                        subject,body_artifact_id,content_hash,evidence_summary,preview_text,status,created_by
                    ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s,'generated',%s)
                    ON CONFLICT (tenant_id,owner_user_id,report_date,content_hash) DO NOTHING
                    """,
                    (tenant_key,normalized["daily_report_run_id"],actor_key,normalized["report_date"],version_key,normalized["subject"],artifact_key,normalized["content_hash"],_json(normalized["evidence_summary"]),normalized["preview_text"],actor_key),
                )
                cursor.execute("SELECT daily_report_run_key FROM platform_daily_report_runs WHERE tenant_id=%s AND owner_user_id=%s AND report_date=%s AND content_hash=%s",(tenant_key,actor_key,normalized["report_date"],normalized["content_hash"]))
                key=str(_value(cursor.fetchone(),"daily_report_run_key",0))
        return self.get_daily_report_run(tenant_id,key,created_by)

    def list_daily_report_runs(self, tenant_id: str, owner_user_id: str) -> list[dict[str,Any]]:
        with self.pool.connection() as connection:
            tenant_key=PostgreSQLIdentityResolver.tenant_id(connection,tenant_id)
            owner_key=PostgreSQLIdentityResolver.user_id(connection,owner_user_id)
            with connection.cursor() as cursor:
                cursor.execute(self._daily_select()+" WHERE d.tenant_id=%s AND d.owner_user_id=%s ORDER BY d.report_date DESC,d.created_at DESC LIMIT 100",(tenant_key,owner_key))
                rows=cursor.fetchall()
        return [_row(row) for row in rows]

    def get_daily_report_run(self, tenant_id: str, run_id: str, owner_user_id: str) -> dict[str,Any]:
        with self.pool.connection() as connection:
            tenant_key=PostgreSQLIdentityResolver.tenant_id(connection,tenant_id)
            owner_key=PostgreSQLIdentityResolver.user_id(connection,owner_user_id)
            with connection.cursor() as cursor:
                cursor.execute(self._daily_select()+" WHERE d.tenant_id=%s AND d.daily_report_run_key=%s AND d.owner_user_id=%s",(tenant_key,run_id,owner_key))
                row=cursor.fetchone()
        if not row: raise KeyError("daily_report_run_not_found")
        return _row(row)

    def update_daily_report_run(self, tenant_id: str, run_id: str, owner_user_id: str, *, status: str, outbox_event_id: str | None=None) -> dict[str,Any]:
        if status not in {"generated","queued","sending","delivered","failed"}: raise ValueError("invalid_daily_report_status")
        with self._transaction() as connection:
            tenant_key=PostgreSQLIdentityResolver.tenant_id(connection,tenant_id)
            owner_key=PostgreSQLIdentityResolver.user_id(connection,owner_user_id)
            outbox_key=self._outbox_uuid(connection,tenant_key,outbox_event_id) if outbox_event_id else None
            with connection.cursor() as cursor:
                cursor.execute("UPDATE platform_daily_report_runs SET status=%s,outbox_event_id=COALESCE(%s,outbox_event_id),updated_at=now(),lock_version=lock_version+1 WHERE tenant_id=%s AND daily_report_run_key=%s AND owner_user_id=%s",(status,outbox_key,tenant_key,run_id,owner_key))
                if cursor.rowcount!=1: raise KeyError("daily_report_run_not_found")
        return self.get_daily_report_run(tenant_id,run_id,owner_user_id)

    # SQL projections and internal helpers -------------------------------------
    @staticmethod
    def _saved_analysis_select() -> str:
        return """SELECT s.saved_result_key AS id,s.title,t.user_query AS query,t.response_snapshot,
            s.created_at AS saved_at,t.task_key AS analysis_task_id,owner.external_subject AS owner_user_id,s.visibility
            FROM platform_saved_analysis_results s JOIN platform_analysis_tasks t ON t.analysis_task_id=s.analysis_task_id
            JOIN platform_user_profiles owner ON owner.user_id=s.owner_user_id"""

    @staticmethod
    def _saved_analysis_row(row: Any) -> dict[str,Any]:
        snapshot=_json_value(_value(row,"response_snapshot",3),{})
        return {"id":str(_value(row,"id",0)),"title":str(_value(row,"title",1)),"query":str(_value(row,"query",2)),
            "plan":str(snapshot.get("plan") or ""),"summary":str(snapshot.get("summary") or snapshot.get("answer") or ""),
            "visualTypes":snapshot.get("visualTypes") if isinstance(snapshot.get("visualTypes"),dict) else {"primary":"bar","secondary":"table"},
            "savedAt":_iso(_value(row,"saved_at",4)),"analysisTaskId":str(_value(row,"analysis_task_id",5)),
            "ownerUserId":str(_value(row,"owner_user_id",6)),"visibility":str(_value(row,"visibility",7)),"rows":[]}

    @staticmethod
    def _version_select() -> str:
        return """SELECT v.report_version_key,r.report_key,r.report_name,v.saved_at,v.version_checksum,
            parent.report_version_key AS parent_version_id,v.version_no,v.status,v.document_metadata,
            v.evidence_summary,owner.external_subject AS owner_user_id,r.visibility,v.report_version_id
            FROM platform_weekly_report_versions v JOIN platform_reports r ON r.report_id=v.report_id
            JOIN platform_user_profiles owner ON owner.user_id=r.owner_user_id
            LEFT JOIN platform_weekly_report_versions parent ON parent.report_version_id=v.parent_version_id"""

    def _version_from_row(self, connection: Any, row: Any) -> dict[str,Any]:
        metadata=_json_value(_value(row,"document_metadata",8),{})
        report=dict(metadata.get("report") or {})
        sections=[]
        with connection.cursor() as cursor:
            cursor.execute("SELECT section_code,report_block_key,block_type,content FROM platform_report_blocks WHERE report_version_id=%s ORDER BY sequence_no,created_at",(_value(row,"report_version_id",12),))
            blocks=cursor.fetchall()
        by_section: dict[str,list[dict[str,Any]]]={}
        for block in blocks:
            content=_json_value(_value(block,"content",3),{})
            by_section.setdefault(str(_value(block,"section_code",0)),[]).append(content)
        for section_meta in metadata.get("sections") or []:
            if not isinstance(section_meta,dict): continue
            section=dict(section_meta)
            section["blocks"]=by_section.pop(str(section.get("id") or "main"),[])
            sections.append(section)
        for code,leftovers in by_section.items(): sections.append({"id":code,"name":code,"blocks":leftovers})
        report["sections"]=sections
        return {"id":str(_value(row,"report_version_key",0)),"name":str(_value(row,"report_name",2)),
            "savedAt":_iso(_value(row,"saved_at",3)),"tenantId":"","reportId":str(_value(row,"report_key",1)),
            "report":report,"comments":[],"ownerUserId":str(_value(row,"owner_user_id",10)),
            "contentHash":str(_value(row,"version_checksum",4)),"parentVersionId":str(_value(row,"parent_version_id",5) or "") or None,
            "revisionNo":int(_value(row,"version_no",6)),"lifecycleStatus":"saved" if str(_value(row,"status",7))=="draft" else str(_value(row,"status",7)),
            "publicationStatus":"ready" if bool(_json_value(_value(row,"evidence_summary",9),{}).get("publishable")) else "review_required",
            "evidenceSummary":_json_value(_value(row,"evidence_summary",9),{}),"visibility":str(_value(row,"visibility",11))}

    def _version_by_key(self,connection:Any,tenant_key:Any,key:str)->dict[str,Any]:
        with connection.cursor() as cursor:
            cursor.execute(self._version_select()+" WHERE v.tenant_id=%s AND v.report_version_key=%s",(tenant_key,key)); row=cursor.fetchone()
        if not row: raise KeyError("weekly_report_version_not_found")
        return self._version_from_row(connection,row)

    @staticmethod
    def _insert_blocks(cursor:Any,tenant_key:Any,version_key:Any,report:dict[str,Any],actor_key:Any)->None:
        sequence=0
        for section in report.get("sections") or []:
            if not isinstance(section,dict): continue
            section_code=str(section.get("id") or f"section_{sequence}")[:120]
            for block in section.get("blocks") or []:
                if not isinstance(block,dict): continue
                block_code=str(block.get("id") or f"block_{sequence}")[:160]
                raw_type=str(block.get("type") or "text")
                block_type=raw_type if raw_type in {"text","table","chart","conclusion","image","todo_summary"} else "text"
                content_hash=hashlib.sha256(_json(block).encode()).hexdigest()
                cursor.execute("INSERT INTO platform_report_blocks(tenant_id,report_block_key,report_version_id,section_code,block_code,block_type,sequence_no,content,content_hash,generation_status,created_by) VALUES (%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s,%s,%s)",(tenant_key,block_code,version_key,section_code,block_code,block_type,sequence,_json(block),content_hash,"generated" if block.get("analysis") else "manual",actor_key))
                sequence+=1

    def _comments(self,connection:Any,tenant_key:Any,report_key:Any)->list[dict[str,Any]]:
        with connection.cursor() as cursor:
            cursor.execute("""SELECT c.comment_id,c.comment_key,c.client_request_id,c.comment_body,c.anchor,c.status,
                author.external_subject AS author,c.created_at,c.resolved_at,resolver.external_subject AS resolved_by,c.lock_version
                FROM platform_report_comments c JOIN platform_user_profiles author ON author.user_id=c.author_user_id
                LEFT JOIN platform_user_profiles resolver ON resolver.user_id=c.resolved_by
                WHERE c.tenant_id=%s AND c.report_id=%s AND c.status<>'deleted' ORDER BY c.created_at""",(tenant_key,report_key))
            rows=cursor.fetchall()
            result=[]
            for row in rows:
                cursor.execute("""SELECT r.reply_key AS id,author.external_subject AS author,r.created_at AS time,r.reply_body AS text
                    FROM platform_report_comment_replies r JOIN platform_user_profiles author ON author.user_id=r.author_user_id
                    WHERE r.comment_id=%s AND r.status='active' ORDER BY r.created_at""",(_value(row,"comment_id",0),))
                replies=[_row(reply) for reply in cursor.fetchall()]
                anchor=_json_value(_value(row,"anchor",4),{})
                item={"id":str(_value(row,"comment_key",1)),"clientRequestId":str(_value(row,"client_request_id",2) or ""),
                    "status":str(_value(row,"status",5)),"author":str(_value(row,"author",6)),"time":_iso(_value(row,"created_at",7)),
                    "text":str(_value(row,"comment_body",3)),"replies":replies,"lockVersion":int(_value(row,"lock_version",10))}
                item.update({k:v for k,v in anchor.items() if v not in (None,"")})
                if _value(row,"resolved_at",8): item["resolvedAt"]=_iso(_value(row,"resolved_at",8))
                if _value(row,"resolved_by",9): item["resolvedBy"]=str(_value(row,"resolved_by",9))
                result.append(item)
        return result

    @staticmethod
    def _revision(connection:Any,report_key:Any)->int:
        if not report_key: return 0
        with connection.cursor() as cursor:
            cursor.execute("SELECT COALESCE(MAX(revision_no),0) AS revision FROM platform_report_comment_revisions WHERE report_id=%s",(report_key,)); row=cursor.fetchone()
        return int(_value(row,"revision",0))

    @staticmethod
    def _lock_revision(connection:Any,report_key:Any)->int:
        with connection.cursor() as cursor:
            cursor.execute("SELECT report_id FROM platform_reports WHERE report_id=%s FOR UPDATE",(report_key,))
        return PostgreSQLReportStore._revision(connection,report_key)

    @staticmethod
    def _write_revision(connection:Any,tenant_key:Any,report_key:Any,revision:int,comments:list[dict[str,Any]],actor_key:Any)->None:
        digest=hashlib.sha256(_json(comments).encode()).hexdigest()
        with connection.cursor() as cursor:
            cursor.execute("INSERT INTO platform_report_comment_revisions(tenant_id,report_id,revision_no,snapshot_hash,created_by) VALUES (%s,%s,%s,%s,%s)",(tenant_key,report_key,revision,digest,actor_key))

    @staticmethod
    def _weekly_ai_select()->str:
        return """SELECT w.weekly_ai_task_key AS id,v.report_version_key AS version_id,w.status,w.input_snapshot,
            w.debate_result,w.final_result,w.error_summary,creator.external_subject AS created_by,
            w.created_at,w.updated_at FROM weekly_report_ai_analysis_task w
            JOIN platform_weekly_report_versions v ON v.report_version_id=w.report_version_id
            LEFT JOIN platform_user_profiles creator ON creator.user_id=w.created_by"""

    @staticmethod
    def _weekly_ai_row(row:Any)->dict[str,Any]:
        status={"queued":"待分析","running":"分析中","review_required":"分析中","succeeded":"已完成","failed":"分析失败","cancelled":"分析失败"}.get(str(_value(row,"status",2)),str(_value(row,"status",2)))
        return {"id":str(_value(row,"id",0)),"tenant_id":"","version_id":str(_value(row,"version_id",1)),"status":status,
            "input_snapshot":_json_value(_value(row,"input_snapshot",3),{}),"debate_result":_json_value(_value(row,"debate_result",4),{}),
            "final_result":_json_value(_value(row,"final_result",5),{}),"error_message":str(_value(row,"error_summary",6) or ""),
            "created_by":str(_value(row,"created_by",7) or ""),"updated_by":str(_value(row,"created_by",7) or ""),
            "created_at":_iso(_value(row,"created_at",8)),"updated_at":_iso(_value(row,"updated_at",9))}

    @staticmethod
    def _learning_select()->str:
        return """SELECT c.learning_candidate_key AS learning_candidate_id,v.report_version_key AS version_id,
            c.candidate_type,c.candidate_content,c.content_hash,c.evidence AS evidence_summary,c.confidence,c.status,
            reviewer.external_subject AS reviewed_by,c.reviewed_at,creator.external_subject AS created_by,c.created_at,c.updated_at
            FROM platform_report_learning_candidates c JOIN platform_weekly_report_versions v ON v.report_version_id=c.report_version_id
            LEFT JOIN platform_user_profiles reviewer ON reviewer.user_id=c.reviewed_by
            LEFT JOIN platform_user_profiles creator ON creator.user_id=c.created_by"""

    @staticmethod
    def _learning_row(row:Any)->dict[str,Any]:
        result=_row(row); result["status"]="candidate" if result.get("status")=="pending_review" else result.get("status"); return result

    def _learning_by_key(self,tenant_id:str,key:str)->dict[str,Any]:
        with self.pool.connection() as connection:
            tenant_key=PostgreSQLIdentityResolver.tenant_id(connection,tenant_id)
            with connection.cursor() as cursor:
                cursor.execute(self._learning_select()+" WHERE c.tenant_id=%s AND c.learning_candidate_key=%s",(tenant_key,key)); row=cursor.fetchone()
        if not row: raise KeyError("report_learning_candidate_not_found")
        return self._learning_row(row)

    @staticmethod
    def _daily_select()->str:
        return """SELECT d.daily_report_run_key AS daily_report_run_id,tenant.tenant_code AS tenant_id,
            owner.external_subject AS owner_user_id,d.report_date,v.report_version_key AS source_report_version_id,
            d.subject,a.artifact_key AS body_artifact_id,d.content_hash,d.evidence_summary,d.preview_text,d.status,
            e.outbox_event_key AS outbox_event_id,creator.external_subject AS created_by,d.created_at,d.updated_at
            FROM platform_daily_report_runs d JOIN platform_tenants tenant ON tenant.tenant_id=d.tenant_id
            JOIN platform_user_profiles owner ON owner.user_id=d.owner_user_id
            JOIN platform_weekly_report_versions v ON v.report_version_id=d.source_report_version_id
            JOIN platform_data_artifacts a ON a.artifact_id=d.body_artifact_id
            LEFT JOIN platform_outbox_events e ON e.outbox_event_id=d.outbox_event_id
            LEFT JOIN platform_user_profiles creator ON creator.user_id=d.created_by"""

    @staticmethod
    def _analysis_task_uuid(connection:Any,tenant_key:Any,key:str)->Any:
        return _lookup(connection,"platform_analysis_tasks","analysis_task_id","task_key",tenant_key,key,"analysis_task_not_found")

    @staticmethod
    def _version_uuid(connection:Any,tenant_key:Any,key:str,required:bool=True)->Any|None:
        try: return _lookup(connection,"platform_weekly_report_versions","report_version_id","report_version_key",tenant_key,key,"weekly_report_version_not_found")
        except KeyError:
            if required: raise
            return None

    @staticmethod
    def _artifact_uuid(connection:Any,tenant_key:Any,key:str)->Any:
        return _lookup(connection,"platform_data_artifacts","artifact_id","artifact_key",tenant_key,key,"data_artifact_not_found")

    @staticmethod
    def _outbox_uuid(connection:Any,tenant_key:Any,key:str)->Any:
        return _lookup(connection,"platform_outbox_events","outbox_event_id","outbox_event_key",tenant_key,key,"outbox_event_not_found")

    @staticmethod
    def _report_uuid(connection:Any,tenant_key:Any,key:str,required:bool=True)->Any|None:
        try: return _lookup(connection,"platform_reports","report_id","report_key",tenant_key,key,"report_not_found")
        except KeyError:
            if required: raise
            return None

    @staticmethod
    def _ensure_report(connection:Any,tenant_key:Any,report_id:str,normalized:dict[str,Any],actor_key:Any)->Any:
        report=normalized.get("report") or {}
        with connection.cursor() as cursor:
            cursor.execute("""INSERT INTO platform_reports(tenant_id,report_key,report_code,report_name,report_type,owner_user_id,template_config,visibility,status,created_by)
                VALUES (%s,%s,%s,%s,'weekly',%s,'{}'::jsonb,'tenant','active',%s)
                ON CONFLICT (tenant_id,report_key) DO UPDATE SET report_name=EXCLUDED.report_name,updated_at=now(),lock_version=platform_reports.lock_version+1
                RETURNING report_id""",(tenant_key,report_id,report_id,str(normalized.get("name") or report_id)[:500],actor_key,actor_key))
            return _value(cursor.fetchone(),"report_id",0)

    @staticmethod
    def _ensure_placeholder_report(connection:Any,tenant_key:Any,report_id:str,actor_key:Any)->Any:
        with connection.cursor() as cursor:
            cursor.execute("""INSERT INTO platform_reports(tenant_id,report_key,report_code,report_name,report_type,owner_user_id,template_config,visibility,status,created_by)
                VALUES (%s,%s,%s,%s,'weekly',%s,'{}'::jsonb,'tenant','active',%s)
                ON CONFLICT (tenant_id,report_key) DO UPDATE SET updated_at=platform_reports.updated_at RETURNING report_id""",(tenant_key,report_id,report_id,report_id[:500],actor_key,actor_key))
            return _value(cursor.fetchone(),"report_id",0)

    @contextmanager
    def _transaction(self)->Iterator[Any]:
        with self.pool.connection() as connection:
            try: yield connection; connection.commit()
            except BaseException: connection.rollback(); raise


def _lookup(connection:Any,table:str,id_field:str,key_field:str,tenant_key:Any,key:str,error:str)->Any:
    allowed={("platform_analysis_tasks","analysis_task_id","task_key"),("platform_weekly_report_versions","report_version_id","report_version_key"),("platform_data_artifacts","artifact_id","artifact_key"),("platform_outbox_events","outbox_event_id","outbox_event_key"),("platform_reports","report_id","report_key")}
    if (table,id_field,key_field) not in allowed: raise ValueError("unsafe_report_lookup")
    with connection.cursor() as cursor:
        cursor.execute(f"SELECT {id_field} FROM {table} WHERE tenant_id=%s AND {key_field}=%s",(tenant_key,key)); row=cursor.fetchone()
    if not row: raise KeyError(error)
    return _value(row,id_field,0)


def _version_metadata(normalized:dict[str,Any])->dict[str,Any]:
    report=dict(normalized.get("report") or {}); sections=[]
    for section in report.pop("sections",[]) if isinstance(report.get("sections"),list) else []:
        if isinstance(section,dict):
            meta={k:v for k,v in section.items() if k!="blocks"}; meta.setdefault("id",f"section_{len(sections)}"); sections.append(meta)
    return {"report":report,"sections":sections}


def _period(report:dict[str,Any])->tuple[date,date]:
    text=str(report.get("period") or "")
    values=re.findall(r"\d{4}[-/]\d{1,2}[-/]\d{1,2}",text)
    if len(values)>=2:
        return tuple(date.fromisoformat(value.replace("/","-")) for value in values[:2])  # type: ignore[return-value]
    for start_key,end_key in (("periodStart","periodEnd"),("startDate","endDate")):
        if report.get(start_key) and report.get(end_key): return date.fromisoformat(str(report[start_key])[:10]),date.fromisoformat(str(report[end_key])[:10])
    raise ValueError("weekly_report_period_required")


def _snapshot_at(report:dict[str,Any],saved_at:Any)->datetime:
    for key in ("dataSnapshotAt","generatedAt","snapshotAt"):
        if report.get(key): return _parse_datetime(report[key])
    return _parse_datetime(saved_at)


def _parse_datetime(value:Any)->datetime:
    if isinstance(value,datetime): return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    text=str(value or "").strip().replace("Z","+00:00").replace("/","-")
    try: parsed=datetime.fromisoformat(text)
    except ValueError:
        try: parsed=datetime.strptime(text,"%Y-%m-%d %H:%M")
        except ValueError as exc: raise ValueError("invalid_report_datetime") from exc
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _comment_anchor(item:dict[str,Any])->dict[str,Any]:
    keys=("targetId","targetLabel","targetKind","selectedText","blockId","itemId","rangeStart","rangeEnd","anchorTop","resolvedReason")
    return {key:item[key] for key in keys if item.get(key) not in (None,"")}


def _mutation(comment:dict[str,Any],comments:list[dict[str,Any]],revision:int,replay:bool=False)->dict[str,Any]:
    return {"comment":json.loads(json.dumps(comment,ensure_ascii=False)),"comments":json.loads(json.dumps(comments,ensure_ascii=False)),"revision":revision,"idempotent_replay":replay}


def _row(row:Any)->dict[str,Any]:
    if not isinstance(row,dict): return {}
    return {str(key):_convert(value) for key,value in row.items()}


def _convert(value:Any)->Any:
    if isinstance(value,(datetime,date)): return value.isoformat()
    return value


def _json_value(value:Any,default:Any)->Any:
    if value is None:return default
    if isinstance(value,(dict,list)):return value
    try:return json.loads(value)
    except (TypeError,json.JSONDecodeError):return default


def _value(row:Any,key:str,index:int)->Any:
    if isinstance(row,dict):return row[key]
    try:return row[key]
    except (TypeError,KeyError,IndexError):return row[index]


def _json(value:Any)->str:
    return json.dumps(value,ensure_ascii=False,sort_keys=True,default=str,separators=(",",":"))


def _iso(value:Any)->str:
    return value.isoformat() if isinstance(value,(datetime,date)) else str(value or "")
