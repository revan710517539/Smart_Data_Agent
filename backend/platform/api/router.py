from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Literal


HTTPMethod = Literal["GET", "POST", "PUT", "DELETE"]


@dataclass(frozen=True)
class RouteSpec:
    method: HTTPMethod
    path: str
    name: str
    domain: str
    description: str
    auth_required: bool = True

    @property
    def operation_id(self) -> str:
        return f"{self.method.lower()}_{self.name}"


class APIRouteRegistry:
    """Central API contract catalog.

    The current local server still uses stdlib HTTP handlers for easy startup,
    but every externally callable route is registered here so frontend code,
    tests, and future gateway/proxy adapters have one source of truth.
    """

    def __init__(self, routes: tuple[RouteSpec, ...]) -> None:
        self._routes = routes

    def list_routes(self) -> list[dict[str, object]]:
        return [
            {
                **asdict(route),
                "operation_id": route.operation_id,
            }
            for route in self._routes
        ]

    def has_route(self, method: str, path: str) -> bool:
        return any(route.method == method.upper() and route.path == path for route in self._routes)

    def openapi_summary(self) -> dict[str, object]:
        domains = sorted({route.domain for route in self._routes})
        return {
            "service": "smart-data-agent-api",
            "version": "local",
            "route_count": len(self._routes),
            "domains": domains,
            "routes": self.list_routes(),
        }

    def openapi_document(self) -> dict[str, object]:
        paths: dict[str, dict[str, object]] = {}
        for route in self._routes:
            operation: dict[str, object] = {
                "operationId": route.operation_id,
                "summary": route.description,
                "tags": [route.domain],
                "responses": {
                    "200": {
                        "description": "Successful response",
                        "content": {"application/json": {"schema": {"type": "object"}}},
                    },
                    "400": {"description": "Invalid request"},
                    "401": {"description": "Authentication required"},
                    "403": {"description": "Permission denied"},
                    "500": {"description": "Internal error with stable request ID"},
                },
                "security": [{"sessionCookie": []}] if route.auth_required else [],
            }
            if route.method in {"POST", "PUT", "DELETE"}:
                operation["requestBody"] = {
                    "required": route.method in {"POST", "PUT"},
                    "content": {"application/json": {"schema": {"type": "object"}}},
                }
            paths.setdefault(route.path, {})[route.method.lower()] = operation
        return {
            "openapi": "3.1.0",
            "info": {
                "title": "Smart Data Agent API",
                "version": "1.0.0",
                "description": "Governed data analysis, reporting, acquisition and automation API.",
            },
            "servers": [{"url": "/"}],
            "tags": [{"name": domain} for domain in sorted({route.domain for route in self._routes})],
            "paths": paths,
            "components": {
                "securitySchemes": {
                    "sessionCookie": {"type": "apiKey", "in": "cookie", "name": "sda_session"}
                }
            },
        }


API_ROUTE_REGISTRY = APIRouteRegistry(
    (
        RouteSpec("GET", "/api/health", "health", "runtime", "Runtime health, auth mode, data mode and recent metrics.", False),
        RouteSpec("GET", "/api/capability-approvals", "capability_approvals_get", "governance", "List tenant high-risk capability approval requests."),
        RouteSpec("POST", "/api/capability-approval", "capability_approval_request", "governance", "Request a hash-bound approval for one high-risk Skill or MCP call."),
        RouteSpec("POST", "/api/capability-approval/review", "capability_approval_review", "governance", "Approve or reject a capability request under four-eyes control."),
        RouteSpec("GET", "/api/live", "liveness", "runtime", "Process liveness probe.", False),
        RouteSpec("GET", "/api/ready", "readiness", "runtime", "Critical dependency and worker readiness probe.", False),
        RouteSpec("GET", "/api/metrics", "metrics", "runtime", "Prometheus-compatible runtime counters.", False),
        RouteSpec("GET", "/api/routes", "routes", "runtime", "Machine-readable API route catalog.", False),
        RouteSpec("GET", "/api/openapi.json", "openapi", "runtime", "OpenAPI 3.1 API contract.", False),
        RouteSpec("GET", "/api/lineage", "lineage_get", "governance", "Traverse tenant-scoped upstream or downstream lineage for a governed entity."),
        RouteSpec("GET", "/api/traces", "trace_spans_get", "observability", "Read tenant-scoped OpenTelemetry-compatible spans for one trace."),
        RouteSpec("POST", "/api/auth/login", "auth_login", "auth", "Development-only email login; strict mode requires enterprise identity.", False),
        RouteSpec("POST", "/api/auth/login-survey", "auth_login_survey", "auth", "Persist a bounded, tenant-scoped login-page survey with idempotent pre-login delivery.", False),
        RouteSpec("POST", "/api/auth/register", "auth_register", "auth", "Submit a development registration request for super-admin approval; strict mode requires administrator provisioning.", False),
        RouteSpec("POST", "/api/auth/password", "auth_password_change", "auth", "Change the authenticated account password."),
        RouteSpec("POST", "/api/auth/logout", "auth_logout", "auth", "Clear the HttpOnly platform session cookie.", False),
        RouteSpec("POST", "/api/auth/refresh", "auth_refresh", "auth", "Rotate refresh token and issue a new short-lived access session.", False),
        RouteSpec("GET", "/api/auth/me", "auth_me", "auth", "Return the authoritative current session profile."),
        RouteSpec("GET", "/api/auth/oidc/start", "auth_oidc_start", "auth", "Start OIDC authorization-code flow with PKCE.", False),
        RouteSpec("GET", "/api/auth/oidc/callback", "auth_oidc_callback", "auth", "Consume OIDC authorization code and create a device session.", False),
        RouteSpec("GET", "/api/tenants", "tenants_get", "tenancy", "List active operating tenants for login and tenant selectors.", False),
        RouteSpec("POST", "/api/tenants", "tenants_create", "tenancy", "Create an operating tenant and seed default administrator and operator roles."),
        RouteSpec("PUT", "/api/tenants", "tenants_update", "tenancy", "Rename an operating tenant in the shared catalog."),
        RouteSpec("DELETE", "/api/tenants", "tenants_delete", "tenancy", "Close an operating tenant and remove its default roles from the catalog."),
        RouteSpec("GET", "/api/navigation", "navigation_get", "navigation", "Menu tree filtered by current user's permissions."),
        RouteSpec("POST", "/api/interaction-events", "interaction_event_create", "observability", "Append one bounded authenticated product interaction event."),
        RouteSpec("GET", "/api/message-board", "message_board_get", "message_board", "List the current user's tenant and page scoped product messages."),
        RouteSpec("POST", "/api/message-board", "message_board_create", "message_board", "Create one product message authored by the authenticated user."),
        RouteSpec("PUT", "/api/message-board", "message_board_update", "message_board", "Update one owned product message with optimistic locking."),
        RouteSpec("DELETE", "/api/message-board", "message_board_delete", "message_board", "Permanently delete one owned product message with optimistic locking."),
        RouteSpec("PUT", "/api/message-board/archive", "message_board_archive", "message_board", "Archive one owned product message and mark it completed."),
        RouteSpec("POST", "/api/message-board/image", "message_board_image_upload", "message_board", "Store and scan one screenshot for an owned product message draft."),
        RouteSpec("GET", "/api/message-board/attachment", "message_board_attachment_get", "message_board", "Read an authorized clean message-board screenshot."),
        RouteSpec("GET", "/api/message-board/admin", "message_board_admin_get", "message_board", "List all tenant product messages for the global super administrator."),
        RouteSpec("PUT", "/api/message-board/admin/status", "message_board_admin_status_update", "message_board", "Update one product message status as the global super administrator."),
        RouteSpec("PUT", "/api/message-board/admin/append-content", "message_board_admin_append_content_update", "message_board", "Update one product message appendix as the global super administrator."),
        RouteSpec("GET", "/api/message-board/admin/export", "message_board_admin_export", "message_board", "Download adopted product messages as an Excel workbook for the global super administrator."),
        RouteSpec("GET", "/api/platform/capabilities", "platform_capabilities_get", "runtime", "List configured and implemented Agent, Skill and MCP capabilities."),
        RouteSpec("POST", "/api/analysis/run", "analysis_run", "analysis", "Run governed semantic analysis workflow."),
        RouteSpec("POST", "/api/analysis/uploaded-source", "analysis_uploaded_source", "analysis", "Classify an uploaded analysis file as a data source, text document, or unsupported media."),
        RouteSpec("POST", "/api/agent-supervisor/chat", "supervisor_chat", "analysis", "Reply to Agent supervisor conversation with the selected text model."),
        RouteSpec("POST", "/api/analysis/run-async", "analysis_run_async", "analysis", "Enqueue governed analysis and return a durable run handle."),
        RouteSpec("GET", "/api/analysis/run-status", "analysis_run_status", "analysis", "Poll the owner-scoped status and result references of an asynchronous analysis."),
        RouteSpec("GET", "/api/analysis/history", "analysis_history_get", "analysis", "List owner-scoped analysis executions or inspect one execution and its trace."),
        RouteSpec("DELETE", "/api/analysis/history", "analysis_history_delete", "analysis", "Delete one owner-scoped completed analysis execution and its trace."),
        RouteSpec("POST", "/api/analysis/run-cancel", "analysis_run_cancel", "analysis", "Cancel an owner-scoped queued or running analysis."),
        RouteSpec("GET", "/api/analysis/task", "analysis_task_get", "analysis", "Read an owned completed analysis task by durable ID."),
        RouteSpec("GET", "/api/analysis/workspaces", "analysis_workspace_get", "analysis", "Read one owned analysis workspace and its branchable thread tree."),
        RouteSpec("POST", "/api/analysis/workspaces", "analysis_workspace_upsert", "analysis", "Create or refresh one page/report analysis workspace."),
        RouteSpec("POST", "/api/analysis/threads/archive", "analysis_thread_archive", "analysis", "Archive one owned analysis thread while keeping remaining history."),
        RouteSpec("POST", "/api/analysis/threads/branches", "analysis_thread_branch", "analysis", "Create an owned chart, metric or data-point analysis branch."),
        RouteSpec("POST", "/api/analysis/threads/turns", "analysis_turn_append", "analysis", "Append one immutable turn to an owned active thread."),
        RouteSpec("POST", "/api/analysis/threads/merge", "analysis_threads_merge", "analysis", "Merge selected branch conclusions into a new target-thread turn."),
        RouteSpec("POST", "/api/analysis/visualization-plan", "analysis_visualization_plan", "analysis", "Select a safe visualization from intent and bounded result rows."),
        RouteSpec("GET", "/api/analysis/artifacts/trust", "analysis_artifact_trust", "analysis", "Read a trusted artifact manifest for one owned analysis task."),
        RouteSpec("GET", "/api/analysis/executions/nodes", "analysis_execution_nodes", "analysis", "Read the durable execution DAG nodes for one owned analysis task."),
        RouteSpec("POST", "/api/attachments/image", "report_image_upload", "reports", "Store, scan and bind one report image attachment."),
        RouteSpec("GET", "/api/attachments/content", "attachment_content_get", "reports", "Read an authorized clean report image attachment."),
        RouteSpec("GET", "/api/asr/fun-asr/realtime", "fun_asr_realtime", "speech", "Proxy Fun-ASR realtime transcription over WebSocket."),
        RouteSpec("GET", "/api/asr/fun-asr/runtime-config", "fun_asr_runtime_config", "speech", "Resolve the current executable Fun-ASR integration without exposing credentials."),
        RouteSpec("GET", "/api/mcp/servers", "mcp_servers_get", "mcp", "List registered MCP servers."),
        RouteSpec("GET", "/api/mcp/tools", "mcp_tools_get", "mcp", "List registered MCP tools."),
        RouteSpec("POST", "/api/mcp/call", "mcp_call", "mcp", "Call a registered MCP tool through the governed gateway."),
        RouteSpec("GET", "/mcp", "mcp_stream_get", "mcp", "MCP Streamable HTTP endpoint; returns 405 when optional SSE is unavailable."),
        RouteSpec("POST", "/mcp", "mcp_stream_post", "mcp", "MCP 2025-11-25 Streamable HTTP JSON-RPC transport."),
        RouteSpec("GET", "/api/reports/analysis-results", "report_analysis_results_get", "reports", "List saved analysis results for report embedding."),
        RouteSpec("POST", "/api/reports/analysis-result", "report_analysis_result_upsert", "reports", "Save an analysis result snapshot for weekly report embedding."),
        RouteSpec("POST", "/api/reports/analysis-result/save-weekly", "report_analysis_result_save_weekly", "reports", "Make an owned analysis report selectable in the weekly report."),
        RouteSpec("POST", "/api/reports/analysis-result/save-experience", "report_analysis_result_save_experience", "reports", "Create an owner-scoped experience-memory candidate from a saved analysis report."),
        RouteSpec("POST", "/api/integrations/reports", "external_report_import", "integrations", "Import a token-bound report from an external analysis channel."),
        RouteSpec("GET", "/api/integrations/workbuddy/context", "workbuddy_context_get", "integrations", "Read active SDA context and explicitly shared raw-table metadata for one WorkBuddy binding."),
        RouteSpec("POST", "/api/integrations/workbuddy/data", "workbuddy_data_get", "integrations", "Read a bounded projection of one explicitly shared SDA raw table."),
        RouteSpec("POST", "/api/integrations/workbuddy/evidence", "workbuddy_evidence_ingest", "integrations", "Ingest WorkBuddy analysis evidence as review-only memory and Skill learning material."),
        RouteSpec("GET", "/api/integrations/codex/context", "codex_context_get", "integrations", "Read active SDA context and explicitly shared raw-table metadata for one Codex binding."),
        RouteSpec("POST", "/api/integrations/codex/data", "codex_data_get", "integrations", "Read a bounded projection of one explicitly shared SDA raw table for Codex."),
        RouteSpec("POST", "/api/integrations/codex/evidence", "codex_evidence_ingest", "integrations", "Ingest Codex analysis evidence as review-only memory and Skill learning material."),
        RouteSpec("GET", "/api/integrations/qwork/context", "qwork_context_get", "integrations", "Read active SDA context and explicitly shared raw-table metadata for one QWork binding."),
        RouteSpec("POST", "/api/integrations/qwork/data", "qwork_data_get", "integrations", "Read a bounded projection of one explicitly shared SDA raw table for QWork."),
        RouteSpec("POST", "/api/integrations/qwork/evidence", "qwork_evidence_ingest", "integrations", "Ingest QWork analysis evidence as review-only memory and Skill learning material."),
        RouteSpec("POST", "/api/integrations/bridge/enrollment/start", "bridge_enrollment_start", "integrations", "Start a short-lived Bridge device authorization transaction.", auth_required=False),
        RouteSpec("GET", "/api/integrations/bridge/enrollment/verify", "bridge_enrollment_verify", "integrations", "Show the one-click Bridge device approval page.", auth_required=False),
        RouteSpec("GET", "/api/integrations/bridge/enrollment/preview", "bridge_enrollment_preview", "integrations", "Read safe metadata for one short-lived Bridge device authorization.", auth_required=False),
        RouteSpec("POST", "/api/integrations/bridge/enrollment/approve", "bridge_enrollment_approve", "integrations", "Approve one Bridge device for the current authenticated user and tenant."),
        RouteSpec("POST", "/api/integrations/bridge/enrollment/poll", "bridge_enrollment_poll", "integrations", "Poll and consume an approved Bridge device authorization exactly once.", auth_required=False),
        RouteSpec("GET", "/api/integrations/bridge/distribution/manifest", "bridge_distribution_manifest_get", "integrations", "Read the public version, checksum and platform contract for the self-contained Bridge package.", auth_required=False),
        RouteSpec("GET", "/api/integrations/bridge/distribution/package", "bridge_distribution_package_get", "integrations", "Download the self-contained WorkBuddy, Codex and QWork Bridge package.", auth_required=False),
        RouteSpec("GET", "/api/integrations/bridge/distribution/package.sha256", "bridge_distribution_checksum_get", "integrations", "Read the SHA-256 checksum for the current Bridge package.", auth_required=False),
        RouteSpec("GET", "/api/integrations/bridge/bindings", "bridge_bindings_get", "integrations", "List active Bridge device bindings owned by the current user."),
        RouteSpec("GET", "/api/integrations/bridge/manifest", "bridge_manifest_get", "integrations", "Discover the current four-module backend connector manifest without reinstalling clients."),
        RouteSpec("POST", "/api/integrations/bridge/binding/revoke", "bridge_binding_revoke", "integrations", "Revoke one owned Bridge device binding."),
        RouteSpec("POST", "/api/integrations/bridge/context", "bridge_system_context", "integrations", "Read one exact registered system's authorized context."),
        RouteSpec("POST", "/api/integrations/bridge/read", "bridge_system_read", "integrations", "Read an allowlisted resource from one exact registered system."),
        RouteSpec("POST", "/api/integrations/bridge/action", "bridge_system_action", "integrations", "Execute one allowlisted idempotent backend configuration action."),
        RouteSpec("POST", "/api/integrations/bridge/sync", "bridge_system_sync", "integrations", "Synchronize one analysis package to an exact registered system."),
        RouteSpec("POST", "/api/integrations/bridge/evidence", "bridge_system_evidence", "integrations", "Return bounded operation evidence to the owning system's governed learning path."),
        RouteSpec("DELETE", "/api/reports/analysis-result", "report_analysis_result_delete", "reports", "Delete a saved analysis result snapshot."),
        RouteSpec("GET", "/api/reports/comments", "report_comments_get", "reports", "Get report comment snapshot."),
        RouteSpec("POST", "/api/reports/comment", "report_comment_create", "reports", "Create one server-authored report comment."),
        RouteSpec("PUT", "/api/reports/comment", "report_comment_mutate", "reports", "Resolve, reopen or reply to one report comment with optimistic revision."),
        RouteSpec("DELETE", "/api/reports/comment", "report_comment_delete", "reports", "Soft-delete an owned report comment."),
        RouteSpec("PUT", "/api/reports/comments", "report_comments_replace_legacy", "reports", "Legacy snapshot replacement endpoint retained for migration only."),
        RouteSpec("GET", "/api/reports/weekly-versions", "weekly_report_versions_get", "reports", "List saved weekly report versions and their AI analysis tasks."),
        RouteSpec("POST", "/api/reports/weekly-version", "weekly_report_version_save", "reports", "Save a weekly report version and optionally trigger self-learning analysis."),
        RouteSpec("POST", "/api/reports/weekly-version/analyze", "weekly_report_version_analyze", "reports", "Re-run weekly report self-learning analysis for a saved version."),
        RouteSpec("GET", "/api/reports/weekly-learning", "weekly_report_learning_get", "reports", "Get weekly report self-learning task results."),
        RouteSpec("POST", "/api/reports/weekly-learning/review", "weekly_report_learning_review", "reports", "Review and explicitly apply a report learning candidate."),
        RouteSpec("GET", "/api/access/users", "access_users_get", "access", "List users and roles visible in current tenant."),
        RouteSpec("POST", "/api/access/user", "access_user_upsert", "access", "Create or update user profile and tenant role assignments."),
        RouteSpec("DELETE", "/api/access/user", "access_user_delete", "access", "Delete a user profile and role assignments."),
        RouteSpec("GET", "/api/access/role-policies", "access_role_policies_get", "access", "List institution role-policy configuration."),
        RouteSpec("POST", "/api/access/role-policy", "access_role_policy_save", "access", "Save institution role-policy configuration and regenerate RBAC policies."),
        RouteSpec("GET", "/api/audit-logs", "audit_logs_get", "audit", "List recent governed operation audit events."),
        RouteSpec("GET", "/api/system-config", "system_config_get", "settings", "List model and speech-to-text integrations."),
        RouteSpec("POST", "/api/system-config/model", "system_model_upsert", "settings", "Create or update model integration."),
        RouteSpec("POST", "/api/system-config/model/test", "system_model_test", "settings", "Validate model integration connectivity and available submodels."),
        RouteSpec("DELETE", "/api/system-config/model", "system_model_delete", "settings", "Delete model integration."),
        RouteSpec("POST", "/api/system-config/speech-integration", "system_speech_integration_upsert", "settings", "Create or update speech-to-text integration."),
        RouteSpec("POST", "/api/system-config/speech-integration/test", "system_speech_integration_test", "settings", "Validate speech-to-text integration connectivity."),
        RouteSpec("DELETE", "/api/system-config/speech-integration", "system_speech_integration_delete", "settings", "Delete speech-to-text integration."),
        RouteSpec("POST", "/api/system-config/system-param", "system_param_upsert", "settings", "Create or update system data parameter."),
        RouteSpec("GET", "/api/metric-dictionary", "metric_dictionary_get", "metrics", "List tenant metric dictionary."),
        RouteSpec("PUT", "/api/metric-dictionary", "metric_dictionary_replace", "metrics", "Replace tenant metric dictionary."),
        RouteSpec("POST", "/api/metric-dictionary", "metric_dictionary_upsert", "metrics", "Create or update a metric dictionary item."),
        RouteSpec("POST", "/api/metric-dictionary/import", "metric_dictionary_import", "metrics", "Import a validated Excel metric batch atomically; reject duplicate names without writing records."),
        RouteSpec("DELETE", "/api/metric-dictionary", "metric_dictionary_delete", "metrics", "Delete a metric dictionary item."),
        RouteSpec("GET", "/api/semantic/metric-versions", "metric_versions_get", "metrics", "List immutable semantic versions for one metric."),
        RouteSpec("POST", "/api/semantic/metric-versions", "metric_version_create", "metrics", "Create a validated draft semantic metric version."),
        RouteSpec("GET", "/api/semantic/metric-versions/diff", "metric_version_diff", "metrics", "Compare two immutable metric versions."),
        RouteSpec("GET", "/api/semantic/metric-versions/impact", "metric_version_impact", "metrics", "List report, Skill, task and cache impact for a metric."),
        RouteSpec("POST", "/api/semantic/metric-versions/transition", "metric_version_transition", "metrics", "Submit, publish, reject or archive a metric version under four-eyes control."),
        RouteSpec("POST", "/api/semantic/metric-versions/rollback", "metric_version_rollback", "metrics", "Create a new draft from a historical metric version."),
        RouteSpec("GET", "/api/data-assets", "data_assets_get", "assets", "List raw tables, topic tables, intents, experiences and knowledge files."),
        RouteSpec("GET", "/api/data-assets/page-data/multi-institution-candidates", "multi_institution_page_data_candidates_get", "assets", "List explicitly related, schema-identical raw-table groups across the current account's authorized institutions."),
        RouteSpec("GET", "/api/data-assets/table-relationships/catalog", "table_relationship_catalog_get", "assets", "List authorized institutions and raw tables for the governed table-relationship builder."),
        RouteSpec("GET", "/api/data-assets/page-data/rows", "page_data_rows_get", "assets", "Read a bounded, schema-validated projection for one active page-data asset."),
        RouteSpec("GET", "/api/data-assets/page-data/workspace", "page_data_workspace_get", "assets", "Read assigned page-data assets, layout and bounded rows for one consumer page in a single request."),
        RouteSpec("POST", "/api/customer-segment/list/preview", "customer_segment_list_preview", "application", "Validate an Excel customer-number list and return only bounded counts before confirmation."),
        RouteSpec("POST", "/api/customer-segment/list/confirm", "customer_segment_list_confirm", "application", "Persist a confirmed deduplicated customer-number list as an owner-scoped analysis filter."),
        RouteSpec("POST", "/api/data-assets/raw-table/external-reference", "raw_table_external_reference_update", "assets", "Set the SDA-side external-reference consent for one read-only CSV source."),
        RouteSpec("GET", "/api/topic-data", "topic_data_get", "assets", "Read a mapped self-analysis history, shortcut or topic-table data snapshot."),
        RouteSpec("POST", "/api/data-assets/raw-file", "data_asset_raw_file_upload", "assets", "Upload and register an immutable raw-table source file."),
        RouteSpec("POST", "/api/data-assets/item", "data_asset_item_upsert", "assets", "Create or update a tenant data asset configuration item."),
        RouteSpec("POST", "/api/data-assets/item/review", "data_asset_item_review", "assets", "Approve or reject an immutable data asset version under four-eyes control."),
        RouteSpec("DELETE", "/api/data-assets/item", "data_asset_item_delete", "assets", "Delete a tenant data asset configuration item."),
        RouteSpec("GET", "/api/data-acquisition", "data_acquisition_get", "ingestion", "List tenant-scoped source systems, immutable scripts, jobs, runs and repair proposals."),
        RouteSpec("POST", "/api/data-acquisition/source", "data_acquisition_source_create", "ingestion", "Register an internal, Yushu, smart-operation, warehouse, file or licensed market source."),
        RouteSpec("POST", "/api/data-acquisition/script", "data_acquisition_script_create", "ingestion", "Create an immutable acquisition script version pending four-eyes review."),
        RouteSpec("POST", "/api/data-acquisition/script/review", "data_acquisition_script_review", "ingestion", "Approve, reject or revoke an immutable acquisition script version."),
        RouteSpec("POST", "/api/data-acquisition/job", "data_acquisition_job_create", "ingestion", "Create a realtime or offline acquisition job against one verified connection and approved script."),
        RouteSpec("POST", "/api/data-acquisition/run", "data_acquisition_run", "ingestion", "Execute an idempotent governed acquisition run and materialize a quality-gated immutable CSV."),
        RouteSpec("GET", "/api/data-acquisition/latest-csv", "data_acquisition_latest_csv", "ingestion", "Resolve the latest fresh CSV by topic_table_id and org_id."),
        RouteSpec("GET", "/api/data-acquisition/artifact", "data_acquisition_artifact", "ingestion", "Download a tenant-authorized active acquisition artifact with hash verification."),
        RouteSpec("POST", "/api/data-acquisition/repair/review", "data_acquisition_repair_review", "ingestion", "Review a repair proposal; an approval creates a new immutable script version."),
        RouteSpec("POST", "/api/data-acquisition/sql/parse", "data_acquisition_sql_parse", "ingestion", "Parse and validate one read-only SQL statement into raw tables, fields, joins and lineage."),
        RouteSpec("POST", "/api/data-acquisition/metadata/refresh", "data_acquisition_metadata_refresh", "ingestion", "Refresh normal or cascaded raw-table metadata for one governed topic table."),
        RouteSpec("GET", "/api/data-acquisition/metadata-status", "data_acquisition_metadata_status", "ingestion", "Read topic metadata status, linked raw tables and latest schema projection."),
        RouteSpec("GET", "/api/data-acquisition/executions", "data_acquisition_executions", "ingestion", "List sanitized acquisition execution logs, optionally filtered by topic table."),
        RouteSpec("POST", "/api/data-acquisition/scheduled-task", "data_acquisition_scheduled_task", "ingestion", "Bind a governed offline acquisition job to an acquisition.run automation task."),
        RouteSpec("GET", "/api/data-crawler-schedule", "data_crawler_schedule_get", "ingestion", "Read the current tenant raw-table binding, SQL time parameters and SDA schedule."),
        RouteSpec("GET", "/api/data-crawler-schedule/statuses", "data_crawler_schedule_statuses_get", "ingestion", "List active tenant-scoped Data Crawler schedules for raw-table list status labels."),
        RouteSpec("PUT", "/api/data-crawler-schedule", "data_crawler_schedule_save", "ingestion", "Save a tenant-scoped SDA schedule and claim Data Crawler control without mutating source SQL."),
        RouteSpec("POST", "/api/data-crawler-schedule/test", "data_crawler_schedule_test", "ingestion", "Test tenant-scoped Data Crawler connectivity, SQL binding, CSV receipt and temporal parameters without saving or executing."),
        RouteSpec("POST", "/api/data-crawler-schedule/refresh", "data_crawler_schedule_refresh", "ingestion", "Run the bound Data Crawler SQL once, matching the SQL editor Run action, and return template parameters for SDA schedule configuration."),
        RouteSpec("GET", "/api/data-crawler-schedule/execution", "data_crawler_schedule_execution_get", "ingestion", "Read one Data Crawler SQL execution started from the SDA schedule tab."),
        RouteSpec("POST", "/api/data-crawler-schedule/execute", "data_crawler_schedule_execute", "ingestion", "Immediately dispatch one tenant-scoped Data Crawler SQL execution."),
        RouteSpec("DELETE", "/api/data-crawler-schedule", "data_crawler_schedule_delete", "ingestion", "Disable the SDA schedule and release its Data Crawler control claim."),
        RouteSpec("GET", "/api/knowledge/documents", "knowledge_documents_get", "knowledge", "List tenant knowledge document identities, current immutable versions and review state."),
        RouteSpec("GET", "/api/knowledge/search", "knowledge_search", "knowledge", "Search active tenant knowledge and return bounded chunks with locators."),
        RouteSpec("POST", "/api/knowledge/document", "knowledge_document_create", "knowledge", "Create a text knowledge document as a review candidate."),
        RouteSpec("POST", "/api/knowledge/document/upload", "knowledge_document_upload", "knowledge", "Scan, parse, chunk and stage a supported file as a review candidate."),
        RouteSpec("POST", "/api/knowledge/document/review", "knowledge_document_review", "knowledge", "Approve, reject or archive a knowledge version under four-eyes control."),
        RouteSpec("GET", "/api/memory", "memory_get", "memory", "List active memories visible to the current subject or pending candidates for authorized reviewers."),
        RouteSpec("POST", "/api/memory/candidate", "memory_candidate_create", "memory", "Create a deduplicated evidence-backed memory candidate."),
        RouteSpec("POST", "/api/memory/candidate/review", "memory_candidate_review", "memory", "Approve, reject, request changes, supersede or expire a memory candidate."),
        RouteSpec("GET", "/api/automation", "automation_get", "automation", "List durable automation task definitions, registered handlers and recent runs."),
        RouteSpec("POST", "/api/automation/task", "automation_task_create", "automation", "Create a validated manual, scheduled or event-driven automation task."),
        RouteSpec("PUT", "/api/automation/task", "automation_task_update", "automation", "Update an owned automation definition with optimistic locking."),
        RouteSpec("POST", "/api/automation/run", "automation_run_create", "automation", "Enqueue an idempotent automation run for worker execution."),
        RouteSpec("GET", "/api/automation/run", "automation_run_get", "automation", "Poll an owned durable automation run."),
        RouteSpec("POST", "/api/automation/run/cancel", "automation_run_cancel", "automation", "Cancel an owned queued, retrying or running automation run."),
        RouteSpec("GET", "/api/subscriptions", "subscriptions_get", "notifications", "List the current user's subscriptions and in-app delivery history."),
        RouteSpec("POST", "/api/subscription", "subscription_create", "notifications", "Create an encrypted in-app, email or HTTPS webhook subscription."),
        RouteSpec("GET", "/api/teams/connection", "teams_connection_get", "notifications", "Read the current user's safe 360Teams connection state."),
        RouteSpec("POST", "/api/teams/connection/auth/start", "teams_connection_authorization_start", "notifications", "Start a user-owned 360Teams connection authorization."),
        RouteSpec("POST", "/api/teams/connection/auth/poll", "teams_connection_authorization_poll", "notifications", "Complete a user-owned 360Teams connection authorization."),
        RouteSpec("POST", "/api/teams/metric-subscription/enable", "teams_metric_subscription_enable", "notifications", "Enable a daily metric self-subscription using an existing 360Teams connection."),
        RouteSpec("POST", "/api/teams/metric-subscription/test", "teams_metric_subscription_test", "notifications", "Send the current Teams metric template immediately to the connected account without creating a subscription."),
        RouteSpec("POST", "/api/teams/metric-subscription/auth/start", "teams_metric_subscription_authorization_start", "notifications", "Start 360Teams authorization for a daily metric self-message."),
        RouteSpec("POST", "/api/teams/metric-subscription/auth/poll", "teams_metric_subscription_authorization_poll", "notifications", "Complete 360Teams authorization and create a daily metric self-subscription."),
        RouteSpec("PUT", "/api/subscription", "subscription_update", "notifications", "Update an owned subscription with optimistic concurrency."),
        RouteSpec("DELETE", "/api/subscription", "subscription_delete", "notifications", "Soft-disable an owned subscription."),
        RouteSpec("POST", "/api/provider-callbacks/notification", "notification_provider_callback", "notifications", "Receive an HMAC-authenticated idempotent provider receipt."),
        RouteSpec("GET", "/api/market-monitoring", "market_monitoring_get", "market", "List licensed sources, entities, rules and evidence-backed market events."),
        RouteSpec("POST", "/api/market-monitoring/source", "market_source_create", "market", "Bind a licensed market source system to the monitoring domain."),
        RouteSpec("POST", "/api/market-monitoring/entity", "market_entity_create", "market", "Create a governed institution, product, industry, region or index identity."),
        RouteSpec("POST", "/api/market-monitoring/observation", "market_observation_create", "market", "Ingest an idempotent market observation backed by an active immutable artifact."),
        RouteSpec("POST", "/api/market-monitoring/rule", "market_rule_create", "market", "Create a typed threshold or change-percent market monitoring rule."),
        RouteSpec("POST", "/api/market-monitoring/evaluate", "market_evaluate", "market", "Evaluate active rules and create cooldown-controlled evidence events."),
        RouteSpec("POST", "/api/market-monitoring/event/status", "market_event_status", "market", "Acknowledge, suppress or resolve a market monitoring event."),
        RouteSpec("GET", "/api/email-daily", "email_daily_get", "reports", "List the current user's evidence-backed daily email artifacts and delivery state."),
        RouteSpec("GET", "/api/operating-snapshot", "operating_snapshot_get", "application", "Build an evidence-backed page snapshot from governed semantic datasets."),
        RouteSpec("POST", "/api/email-daily/generate", "email_daily_generate", "reports", "Generate an immutable daily email body from a publishable report version."),
        RouteSpec("POST", "/api/email-daily/send", "email_daily_send", "reports", "Enqueue an idempotent daily email outbox event for configured subscriptions."),
        RouteSpec("GET", "/api/application/module", "application_module_get", "application", "Get persisted state and recent actions for a page module."),
        RouteSpec("POST", "/api/application/action", "application_action_post", "application", "Execute and audit a page-level application action."),
    )
)
