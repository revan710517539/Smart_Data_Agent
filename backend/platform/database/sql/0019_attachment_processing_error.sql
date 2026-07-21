-- Preserve a stable parse/OCR failure code without copying document content.

ALTER TABLE platform_file_attachments ADD COLUMN processing_error TEXT NOT NULL DEFAULT '';
