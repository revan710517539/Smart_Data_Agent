UPDATE platform_model_integrations
SET status = 'disabled',
    updated_at = CURRENT_TIMESTAMP(6),
    lock_version = lock_version + 1
WHERE status <> 'disabled'
  AND RIGHT(integration_code, CHAR_LENGTH('model_default_intelligent_analysis_relay')) =
      'model_default_intelligent_analysis_relay';
