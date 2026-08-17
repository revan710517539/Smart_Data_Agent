ALTER TABLE platform_message_board_entries
  ADD COLUMN status VARCHAR(24) NOT NULL DEFAULT 'new' AFTER attachment_ids,
  ADD COLUMN archived_at DATETIME(6) NULL AFTER status;

CREATE INDEX idx_platform_message_board_status
  ON platform_message_board_entries (status, updated_at, message_id);
