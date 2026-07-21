from .access import (
    handle_access_role_policies_get,
    handle_access_role_policy_save,
    handle_access_user_delete,
    handle_access_user_upsert,
    handle_access_users_get,
)
from .analysis import (
    handle_analysis_history_delete,
    handle_analysis_history_get,
    handle_analysis_run,
    handle_analysis_run_async,
    handle_analysis_run_cancel,
    handle_analysis_run_status,
    handle_analysis_task_get,
    run_analysis,
)
from .approvals import (
    handle_capability_approval_request,
    handle_capability_approval_review,
    handle_capability_approvals_get,
)
from .attachments import handle_attachment_content_get, handle_report_image_upload
from .application import handle_application_action_post, handle_application_module_get
from .capabilities import handle_platform_capabilities_get
from .daily_email import handle_daily_email_generate, handle_daily_email_get, handle_daily_email_send
from .data_acquisition import (
    handle_acquisition_artifact_get,
    handle_acquisition_job_create,
    handle_acquisition_executions_get,
    handle_acquisition_metadata_refresh,
    handle_acquisition_metadata_status_get,
    handle_acquisition_repair_review,
    handle_acquisition_run,
    handle_acquisition_script_create,
    handle_acquisition_script_review,
    handle_acquisition_source_create,
    handle_acquisition_scheduled_task,
    handle_acquisition_sql_parse,
    handle_data_acquisition_get,
    handle_latest_acquisition_csv_get,
)
from .asr import (
    FUN_ASR_REALTIME_PATH,
    FUN_ASR_RUNTIME_CONFIG_PATH,
    handle_fun_asr_realtime_websocket,
    handle_fun_asr_runtime_config_get,
)
from .assets import (
    handle_data_asset_item_delete,
    handle_data_asset_raw_file_upload,
    handle_data_asset_item_review,
    handle_data_asset_item_upsert,
    handle_data_assets_get,
)
from .audit import handle_audit_logs_get
from .auth import (
    handle_auth_login,
    handle_auth_logout,
    handle_auth_me,
    handle_auth_oidc_callback,
    handle_auth_oidc_start,
    handle_auth_refresh,
    handle_auth_register,
)
from .automation import (
    handle_automation_get,
    handle_automation_run_cancel,
    handle_automation_run_create,
    handle_automation_run_get,
    handle_automation_task_create,
    handle_automation_task_update,
    handle_notification_provider_callback,
    handle_subscription_create,
    handle_subscription_delete,
    handle_subscription_update,
    handle_subscriptions_get,
)
from .mcp import (
    handle_mcp_call,
    handle_mcp_servers_get,
    handle_mcp_stream_get,
    handle_mcp_stream_post,
    handle_mcp_tools_get,
)
from .knowledge import (
    handle_knowledge_document_create,
    handle_knowledge_document_review,
    handle_knowledge_document_upload,
    handle_knowledge_documents_get,
    handle_knowledge_search_get,
)
from .lineage import handle_lineage_get
from .metrics import (
    handle_metric_dictionary_delete,
    handle_metric_dictionary_get,
    handle_metric_dictionary_replace,
    handle_metric_dictionary_upsert,
)
from .memory import handle_memory_candidate_create, handle_memory_candidate_review, handle_memory_get
from .market import (
    handle_market_entity_create,
    handle_market_evaluate,
    handle_market_event_status,
    handle_market_get,
    handle_market_observation_create,
    handle_market_rule_create,
    handle_market_source_create,
)
from .navigation import handle_navigation_get
from .operating_snapshot import handle_operating_snapshot_get
from .reports import (
    handle_report_analysis_result_delete,
    handle_report_analysis_result_upsert,
    handle_report_analysis_results_get,
    handle_report_comment_create,
    handle_report_comment_delete,
    handle_report_comment_mutate,
    handle_report_comments_get,
    handle_report_comments_replace,
    handle_weekly_report_learning_get,
    handle_weekly_report_learning_review,
    handle_weekly_report_version_analyze,
    handle_weekly_report_version_save,
    handle_weekly_report_versions_get,
)
from .settings import (
    handle_system_config_get,
    handle_system_data_connection_delete,
    handle_system_data_connection_test,
    handle_system_data_connection_upsert,
    handle_system_model_delete,
    handle_system_model_test,
    handle_system_model_upsert,
    handle_system_param_upsert,
    handle_system_speech_integration_delete,
    handle_system_speech_integration_test,
    handle_system_speech_integration_upsert,
)
from .tenants import handle_tenants_get
from .traces import handle_trace_spans_get

GET_ROUTE_HANDLERS = {
    "/mcp": handle_mcp_stream_get,
    "/api/auth/me": handle_auth_me,
    "/api/auth/oidc/start": handle_auth_oidc_start,
    "/api/auth/oidc/callback": handle_auth_oidc_callback,
    "/api/tenants": handle_tenants_get,
    "/api/navigation": handle_navigation_get,
    "/api/platform/capabilities": handle_platform_capabilities_get,
    FUN_ASR_REALTIME_PATH: handle_fun_asr_realtime_websocket,
    FUN_ASR_RUNTIME_CONFIG_PATH: handle_fun_asr_runtime_config_get,
    "/api/mcp/servers": handle_mcp_servers_get,
    "/api/mcp/tools": handle_mcp_tools_get,
    "/api/reports/analysis-results": handle_report_analysis_results_get,
    "/api/reports/comments": handle_report_comments_get,
    "/api/reports/weekly-versions": handle_weekly_report_versions_get,
    "/api/reports/weekly-learning": handle_weekly_report_learning_get,
    "/api/access/users": handle_access_users_get,
    "/api/access/role-policies": handle_access_role_policies_get,
    "/api/audit-logs": handle_audit_logs_get,
    "/api/system-config": handle_system_config_get,
    "/api/metric-dictionary": handle_metric_dictionary_get,
    "/api/data-assets": handle_data_assets_get,
    "/api/lineage": handle_lineage_get,
    "/api/data-acquisition": handle_data_acquisition_get,
    "/api/data-acquisition/latest-csv": handle_latest_acquisition_csv_get,
    "/api/data-acquisition/artifact": handle_acquisition_artifact_get,
    "/api/data-acquisition/metadata-status": handle_acquisition_metadata_status_get,
    "/api/data-acquisition/executions": handle_acquisition_executions_get,
    "/api/knowledge/documents": handle_knowledge_documents_get,
    "/api/knowledge/search": handle_knowledge_search_get,
    "/api/memory": handle_memory_get,
    "/api/automation": handle_automation_get,
    "/api/automation/run": handle_automation_run_get,
    "/api/analysis/task": handle_analysis_task_get,
    "/api/analysis/history": handle_analysis_history_get,
    "/api/analysis/run-status": handle_analysis_run_status,
    "/api/subscriptions": handle_subscriptions_get,
    "/api/market-monitoring": handle_market_get,
    "/api/email-daily": handle_daily_email_get,
    "/api/operating-snapshot": handle_operating_snapshot_get,
    "/api/attachments/content": handle_attachment_content_get,
    "/api/application/module": handle_application_module_get,
    "/api/capability-approvals": handle_capability_approvals_get,
    "/api/traces": handle_trace_spans_get,
}

POST_ROUTE_HANDLERS = {
    "/mcp": handle_mcp_stream_post,
    "/api/auth/login": handle_auth_login,
    "/api/auth/register": handle_auth_register,
    "/api/auth/logout": handle_auth_logout,
    "/api/auth/refresh": handle_auth_refresh,
    "/api/provider-callbacks/notification": handle_notification_provider_callback,
    "/api/analysis/run": handle_analysis_run,
    "/api/analysis/run-async": handle_analysis_run_async,
    "/api/analysis/run-cancel": handle_analysis_run_cancel,
    "/api/system-config/model": handle_system_model_upsert,
    "/api/system-config/model/test": handle_system_model_test,
    "/api/system-config/speech-integration": handle_system_speech_integration_upsert,
    "/api/system-config/speech-integration/test": handle_system_speech_integration_test,
    "/api/system-config/data-connection": handle_system_data_connection_upsert,
    "/api/system-config/data-connection/test": handle_system_data_connection_test,
    "/api/system-config/system-param": handle_system_param_upsert,
    "/api/metric-dictionary": handle_metric_dictionary_upsert,
    "/api/access/user": handle_access_user_upsert,
    "/api/access/role-policy": handle_access_role_policy_save,
    "/api/reports/analysis-result": handle_report_analysis_result_upsert,
    "/api/reports/comment": handle_report_comment_create,
    "/api/reports/weekly-version": handle_weekly_report_version_save,
    "/api/reports/weekly-version/analyze": handle_weekly_report_version_analyze,
    "/api/reports/weekly-learning/review": handle_weekly_report_learning_review,
    "/api/mcp/call": handle_mcp_call,
    "/api/data-assets/item": handle_data_asset_item_upsert,
    "/api/data-assets/raw-file": handle_data_asset_raw_file_upload,
    "/api/data-assets/item/review": handle_data_asset_item_review,
    "/api/data-acquisition/source": handle_acquisition_source_create,
    "/api/data-acquisition/script": handle_acquisition_script_create,
    "/api/data-acquisition/script/review": handle_acquisition_script_review,
    "/api/data-acquisition/job": handle_acquisition_job_create,
    "/api/data-acquisition/run": handle_acquisition_run,
    "/api/data-acquisition/repair/review": handle_acquisition_repair_review,
    "/api/data-acquisition/sql/parse": handle_acquisition_sql_parse,
    "/api/data-acquisition/metadata/refresh": handle_acquisition_metadata_refresh,
    "/api/data-acquisition/scheduled-task": handle_acquisition_scheduled_task,
    "/api/knowledge/document": handle_knowledge_document_create,
    "/api/knowledge/document/upload": handle_knowledge_document_upload,
    "/api/knowledge/document/review": handle_knowledge_document_review,
    "/api/memory/candidate": handle_memory_candidate_create,
    "/api/memory/candidate/review": handle_memory_candidate_review,
    "/api/automation/task": handle_automation_task_create,
    "/api/automation/run": handle_automation_run_create,
    "/api/automation/run/cancel": handle_automation_run_cancel,
    "/api/subscription": handle_subscription_create,
    "/api/market-monitoring/source": handle_market_source_create,
    "/api/market-monitoring/entity": handle_market_entity_create,
    "/api/market-monitoring/observation": handle_market_observation_create,
    "/api/market-monitoring/rule": handle_market_rule_create,
    "/api/market-monitoring/evaluate": handle_market_evaluate,
    "/api/market-monitoring/event/status": handle_market_event_status,
    "/api/email-daily/generate": handle_daily_email_generate,
    "/api/email-daily/send": handle_daily_email_send,
    "/api/application/action": handle_application_action_post,
    "/api/attachments/image": handle_report_image_upload,
    "/api/capability-approval": handle_capability_approval_request,
    "/api/capability-approval/review": handle_capability_approval_review,
}

PUT_ROUTE_HANDLERS = {
    "/api/automation/task": handle_automation_task_update,
    "/api/subscription": handle_subscription_update,
    "/api/reports/comment": handle_report_comment_mutate,
    "/api/reports/comments": handle_report_comments_replace,
    "/api/metric-dictionary": handle_metric_dictionary_replace,
}

DELETE_ROUTE_HANDLERS = {
    "/api/analysis/history": handle_analysis_history_delete,
    "/api/system-config/model": handle_system_model_delete,
    "/api/system-config/speech-integration": handle_system_speech_integration_delete,
    "/api/system-config/data-connection": handle_system_data_connection_delete,
    "/api/access/user": handle_access_user_delete,
    "/api/reports/analysis-result": handle_report_analysis_result_delete,
    "/api/reports/comment": handle_report_comment_delete,
    "/api/subscription": handle_subscription_delete,
    "/api/metric-dictionary": handle_metric_dictionary_delete,
    "/api/data-assets/item": handle_data_asset_item_delete,
}


__all__ = [
    "DELETE_ROUTE_HANDLERS",
    "GET_ROUTE_HANDLERS",
    "POST_ROUTE_HANDLERS",
    "PUT_ROUTE_HANDLERS",
    "run_analysis",
]
