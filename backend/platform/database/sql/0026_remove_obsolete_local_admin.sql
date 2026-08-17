-- Retire the synthetic local-development account.  Historical audit and
-- execution records are intentionally retained with their original actor ID;
-- only an active identity, permissions, sessions, and account-scoped model
-- configuration are removed.
DELETE FROM platform_auth_sessions WHERE user_id = 'u_admin';
DELETE FROM auth_role_assignments WHERE user_id = 'u_admin';
DELETE FROM platform_model_integrations WHERE tenant_id = 'account:u_admin';
DELETE FROM platform_speech_integrations WHERE tenant_id = 'account:u_admin';
DELETE FROM platform_user_profiles WHERE user_id = 'u_admin';
