ALTER TABLE platform_message_board_entries
  ADD COLUMN append_content VARCHAR(5000) NOT NULL DEFAULT '' AFTER archived_at;
