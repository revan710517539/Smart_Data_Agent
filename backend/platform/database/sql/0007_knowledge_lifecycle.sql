-- Normalize the legacy single-row knowledge store into immutable versions,
-- searchable chunks, governed attachments and citation facts.

ALTER TABLE platform_knowledge_documents RENAME TO platform_knowledge_documents_legacy;

CREATE TABLE platform_knowledge_documents (
    tenant_id TEXT NOT NULL,
    document_id TEXT NOT NULL,
    document_code TEXT NOT NULL,
    title TEXT NOT NULL,
    document_type TEXT NOT NULL CHECK (document_type IN (
        'metric_rule','business_rule','report','case','manual','policy','market','other'
    )),
    owner_user_id TEXT NOT NULL,
    classification TEXT NOT NULL DEFAULT 'internal' CHECK (classification IN ('public','internal','confidential','restricted')),
    domains TEXT NOT NULL DEFAULT '[]',
    tags TEXT NOT NULL DEFAULT '[]',
    current_version_no INTEGER NOT NULL DEFAULT 0 CHECK (current_version_no >= 0),
    status TEXT NOT NULL DEFAULT 'draft' CHECK (status IN ('draft','processing','review','active','failed','archived')),
    created_by TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (tenant_id, document_id),
    UNIQUE (tenant_id, document_code)
);

CREATE TABLE platform_knowledge_versions (
    tenant_id TEXT NOT NULL,
    knowledge_version_id TEXT NOT NULL,
    document_id TEXT NOT NULL,
    version_no INTEGER NOT NULL CHECK (version_no > 0),
    source_attachment_id TEXT,
    content_artifact_id TEXT,
    content_hash TEXT NOT NULL CHECK (length(content_hash) = 64),
    language TEXT NOT NULL DEFAULT 'zh-CN',
    parser_name TEXT,
    processing_status TEXT NOT NULL DEFAULT 'pending' CHECK (processing_status IN ('pending','scanning','parsing','indexing','ready','failed')),
    published_at TEXT,
    reviewed_by TEXT,
    created_by TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (tenant_id, knowledge_version_id),
    UNIQUE (tenant_id, document_id, version_no),
    FOREIGN KEY (tenant_id, document_id)
        REFERENCES platform_knowledge_documents(tenant_id, document_id) ON DELETE CASCADE
);

CREATE TABLE platform_knowledge_chunks (
    tenant_id TEXT NOT NULL,
    chunk_id TEXT NOT NULL,
    knowledge_version_id TEXT NOT NULL,
    chunk_no INTEGER NOT NULL CHECK (chunk_no >= 0),
    content TEXT NOT NULL,
    content_hash TEXT NOT NULL CHECK (length(content_hash) = 64),
    token_count INTEGER NOT NULL DEFAULT 0,
    heading_path TEXT NOT NULL DEFAULT '[]',
    keywords TEXT NOT NULL DEFAULT '[]',
    locator TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    PRIMARY KEY (tenant_id, chunk_id),
    UNIQUE (tenant_id, knowledge_version_id, chunk_no),
    FOREIGN KEY (tenant_id, knowledge_version_id)
        REFERENCES platform_knowledge_versions(tenant_id, knowledge_version_id) ON DELETE CASCADE
);

CREATE TABLE platform_file_attachments (
    tenant_id TEXT NOT NULL,
    attachment_id TEXT NOT NULL,
    artifact_id TEXT NOT NULL,
    owner_user_id TEXT NOT NULL,
    resource_type TEXT NOT NULL,
    resource_id TEXT NOT NULL,
    file_name TEXT NOT NULL,
    detected_content_type TEXT NOT NULL,
    scan_status TEXT NOT NULL DEFAULT 'pending' CHECK (scan_status IN ('pending','clean','infected','failed')),
    processing_status TEXT NOT NULL DEFAULT 'pending' CHECK (processing_status IN ('pending','processing','ready','failed')),
    classification TEXT NOT NULL DEFAULT 'internal',
    created_by TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (tenant_id, attachment_id),
    FOREIGN KEY (tenant_id, artifact_id)
        REFERENCES platform_data_artifacts(tenant_id, artifact_id) ON DELETE RESTRICT
);

CREATE TABLE platform_knowledge_citations (
    tenant_id TEXT NOT NULL,
    citation_id TEXT NOT NULL,
    chunk_tenant_id TEXT NOT NULL,
    chunk_id TEXT NOT NULL,
    resource_type TEXT NOT NULL,
    resource_id TEXT NOT NULL,
    quote_hash TEXT NOT NULL CHECK (length(quote_hash) = 64),
    locator TEXT NOT NULL DEFAULT '{}',
    relevance_score REAL CHECK (relevance_score >= 0 AND relevance_score <= 1),
    created_by TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (tenant_id, citation_id),
    UNIQUE (tenant_id, chunk_id, resource_type, resource_id),
    FOREIGN KEY (chunk_tenant_id, chunk_id)
        REFERENCES platform_knowledge_chunks(tenant_id, chunk_id) ON DELETE RESTRICT
);

CREATE INDEX idx_knowledge_documents_status
    ON platform_knowledge_documents(tenant_id, status, updated_at DESC);
CREATE INDEX idx_knowledge_chunks_version
    ON platform_knowledge_chunks(tenant_id, knowledge_version_id, chunk_no);
CREATE INDEX idx_knowledge_chunks_hash
    ON platform_knowledge_chunks(tenant_id, content_hash);
CREATE INDEX idx_knowledge_citations_resource
    ON platform_knowledge_citations(tenant_id, resource_type, resource_id);
