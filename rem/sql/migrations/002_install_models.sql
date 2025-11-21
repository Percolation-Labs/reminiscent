-- REM Model Schema (install_models.sql)
-- Generated from Pydantic models
-- Source directory: src/rem/models/entities
-- Generated at: 2025-11-18T22:29:28.066745
--
-- DO NOT EDIT MANUALLY - Regenerate with: rem schema generate
--
-- This script creates:
-- 1. Primary entity tables
-- 2. Embeddings tables (embeddings_<table>)
-- 3. KV_STORE triggers for cache maintenance
-- 4. Indexes (foreground only, background indexes separate)

-- ============================================================================
-- PREREQUISITES CHECK
-- ============================================================================

DO $$
BEGIN
    -- Check that install.sql has been run
    IF NOT EXISTS (SELECT 1 FROM pg_tables WHERE tablename = 'kv_store') THEN
        RAISE EXCEPTION 'KV_STORE table not found. Run sql/install.sql first.';
    END IF;

    IF NOT EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'vector') THEN
        RAISE EXCEPTION 'pgvector extension not found. Run sql/install.sql first.';
    END IF;

    RAISE NOTICE 'Prerequisites check passed';
END $$;

-- ======================================================================
-- USERS (Model: User)
-- ======================================================================

CREATE TABLE IF NOT EXISTS users (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    tenant_id VARCHAR(100) NOT NULL,
    user_id VARCHAR(256),
    name VARCHAR(256) NOT NULL,
    email VARCHAR(256),
    role VARCHAR(256),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    deleted_at TIMESTAMP,
    graph_edges JSONB DEFAULT '[]'::jsonb,
    metadata JSONB DEFAULT '{}'::jsonb
);

CREATE INDEX idx_users_tenant ON users (tenant_id);
CREATE INDEX idx_users_user ON users (user_id);
CREATE INDEX idx_users_graph_edges ON users USING GIN (graph_edges);
CREATE INDEX idx_users_metadata ON users USING GIN (metadata);

-- KV_STORE trigger for users
-- Trigger function to maintain KV_STORE for users
CREATE OR REPLACE FUNCTION fn_users_kv_store_upsert()
RETURNS TRIGGER AS $$
BEGIN
    IF (TG_OP = 'DELETE') THEN
        -- Remove from KV_STORE on delete
        DELETE FROM kv_store
        WHERE entity_id = OLD.id;
        RETURN OLD;
    ELSIF (TG_OP = 'INSERT' OR TG_OP = 'UPDATE') THEN
        -- Upsert to KV_STORE
        INSERT INTO kv_store (
            entity_key,
            entity_type,
            entity_id,
            tenant_id,
            user_id,
            content_summary,
            metadata,
            updated_at
        ) VALUES (
            NEW.name,
            'users',
            NEW.id,
            NEW.tenant_id,
            NEW.user_id,
            COALESCE(NEW.email || ' ' || COALESCE(NEW.role, ''), ''),
            NEW.metadata,
            CURRENT_TIMESTAMP
        )
        ON CONFLICT (tenant_id, entity_key)
        DO UPDATE SET
            entity_id = EXCLUDED.entity_id,
            user_id = EXCLUDED.user_id,
            content_summary = EXCLUDED.content_summary,
            metadata = EXCLUDED.metadata,
            updated_at = CURRENT_TIMESTAMP;

        RETURN NEW;
    END IF;
END;
$$ LANGUAGE plpgsql;

-- Create trigger
DROP TRIGGER IF EXISTS trg_users_kv_store ON users;
CREATE TRIGGER trg_users_kv_store
AFTER INSERT OR UPDATE OR DELETE ON users
FOR EACH ROW EXECUTE FUNCTION fn_users_kv_store_upsert();

-- ======================================================================
-- MOMENTS (Model: Moment)
-- ======================================================================

CREATE TABLE IF NOT EXISTS moments (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    tenant_id VARCHAR(100) NOT NULL,
    user_id VARCHAR(256),
    name VARCHAR(256) NOT NULL,
    moment_type VARCHAR(256),
    category VARCHAR(256),
    starts_timestamp TIMESTAMP NOT NULL,
    ends_timestamp TIMESTAMP,
    present_persons JSONB DEFAULT '{}'::jsonb,
    emotion_tags TEXT[] DEFAULT ARRAY[]::TEXT[],
    topic_tags TEXT[] DEFAULT ARRAY[]::TEXT[],
    summary TEXT,
    source_resource_ids TEXT[] DEFAULT ARRAY[]::TEXT[],
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    deleted_at TIMESTAMP,
    graph_edges JSONB DEFAULT '[]'::jsonb,
    metadata JSONB DEFAULT '{}'::jsonb
);

CREATE INDEX idx_moments_tenant ON moments (tenant_id);
CREATE INDEX idx_moments_user ON moments (user_id);
CREATE INDEX idx_moments_graph_edges ON moments USING GIN (graph_edges);
CREATE INDEX idx_moments_metadata ON moments USING GIN (metadata);

-- Embeddings for moments
CREATE TABLE IF NOT EXISTS embeddings_moments (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    entity_id UUID NOT NULL REFERENCES moments(id) ON DELETE CASCADE,
    field_name VARCHAR(100) NOT NULL,
    provider VARCHAR(50) NOT NULL DEFAULT 'openai',
    model VARCHAR(100) NOT NULL DEFAULT 'text-embedding-3-small',
    embedding vector(1536) NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    -- Unique: one embedding per entity per field per provider
    UNIQUE (entity_id, field_name, provider)
);

-- Index for entity lookup (get all embeddings for entity)
CREATE INDEX idx_embeddings_moments_entity ON embeddings_moments (entity_id);

-- Index for field + provider lookup
CREATE INDEX idx_embeddings_moments_field_provider ON embeddings_moments (field_name, provider);

-- HNSW index for vector similarity search (created in background)
-- Note: This will be created by background thread after data load
-- CREATE INDEX idx_embeddings_moments_vector_hnsw ON embeddings_moments
-- USING hnsw (embedding vector_cosine_ops);

-- KV_STORE trigger for moments
-- Trigger function to maintain KV_STORE for moments
CREATE OR REPLACE FUNCTION fn_moments_kv_store_upsert()
RETURNS TRIGGER AS $$
BEGIN
    IF (TG_OP = 'DELETE') THEN
        -- Remove from KV_STORE on delete
        DELETE FROM kv_store
        WHERE entity_id = OLD.id;
        RETURN OLD;
    ELSIF (TG_OP = 'INSERT' OR TG_OP = 'UPDATE') THEN
        -- Upsert to KV_STORE
        INSERT INTO kv_store (
            entity_key,
            entity_type,
            entity_id,
            tenant_id,
            user_id,
            content_summary,
            metadata,
            updated_at
        ) VALUES (
            NEW.name,
            'moments',
            NEW.id,
            NEW.tenant_id,
            NEW.user_id,
            COALESCE(NEW.summary, ''),
            NEW.metadata,
            CURRENT_TIMESTAMP
        )
        ON CONFLICT (tenant_id, entity_key)
        DO UPDATE SET
            entity_id = EXCLUDED.entity_id,
            user_id = EXCLUDED.user_id,
            content_summary = EXCLUDED.content_summary,
            metadata = EXCLUDED.metadata,
            updated_at = CURRENT_TIMESTAMP;

        RETURN NEW;
    END IF;
END;
$$ LANGUAGE plpgsql;

-- Create trigger
DROP TRIGGER IF EXISTS trg_moments_kv_store ON moments;
CREATE TRIGGER trg_moments_kv_store
AFTER INSERT OR UPDATE OR DELETE ON moments
FOR EACH ROW EXECUTE FUNCTION fn_moments_kv_store_upsert();

-- ======================================================================
-- PERSONS (Model: Person)
-- ======================================================================

CREATE TABLE IF NOT EXISTS persons (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    tenant_id VARCHAR(100) NOT NULL,
    user_id VARCHAR(256),
    name VARCHAR(256) NOT NULL,
    role VARCHAR(256),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    deleted_at TIMESTAMP,
    graph_edges JSONB DEFAULT '[]'::jsonb,
    metadata JSONB DEFAULT '{}'::jsonb
);

CREATE INDEX idx_persons_tenant ON persons (tenant_id);
CREATE INDEX idx_persons_user ON persons (user_id);
CREATE INDEX idx_persons_graph_edges ON persons USING GIN (graph_edges);
CREATE INDEX idx_persons_metadata ON persons USING GIN (metadata);

-- KV_STORE trigger for persons
-- Trigger function to maintain KV_STORE for persons
CREATE OR REPLACE FUNCTION fn_persons_kv_store_upsert()
RETURNS TRIGGER AS $$
BEGIN
    IF (TG_OP = 'DELETE') THEN
        -- Remove from KV_STORE on delete
        DELETE FROM kv_store
        WHERE entity_id = OLD.id;
        RETURN OLD;
    ELSIF (TG_OP = 'INSERT' OR TG_OP = 'UPDATE') THEN
        -- Upsert to KV_STORE
        INSERT INTO kv_store (
            entity_key,
            entity_type,
            entity_id,
            tenant_id,
            user_id,
            content_summary,
            metadata,
            updated_at
        ) VALUES (
            NEW.name,
            'persons',
            NEW.id,
            NEW.tenant_id,
            NEW.user_id,
            COALESCE(NEW.role, ''),
            NEW.metadata,
            CURRENT_TIMESTAMP
        )
        ON CONFLICT (tenant_id, entity_key)
        DO UPDATE SET
            entity_id = EXCLUDED.entity_id,
            user_id = EXCLUDED.user_id,
            content_summary = EXCLUDED.content_summary,
            metadata = EXCLUDED.metadata,
            updated_at = CURRENT_TIMESTAMP;

        RETURN NEW;
    END IF;
END;
$$ LANGUAGE plpgsql;

-- Create trigger
DROP TRIGGER IF EXISTS trg_persons_kv_store ON persons;
CREATE TRIGGER trg_persons_kv_store
AFTER INSERT OR UPDATE OR DELETE ON persons
FOR EACH ROW EXECUTE FUNCTION fn_persons_kv_store_upsert();

-- ======================================================================
-- RESOURCES (Model: Resource)
-- ======================================================================

CREATE TABLE IF NOT EXISTS resources (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    tenant_id VARCHAR(100) NOT NULL,
    user_id VARCHAR(256),
    name VARCHAR(256) NOT NULL,
    uri VARCHAR(256),
    ordinal INTEGER,
    content TEXT,
    timestamp TIMESTAMP,
    category VARCHAR(256),
    related_entities JSONB DEFAULT '{}'::jsonb,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    deleted_at TIMESTAMP,
    graph_edges JSONB DEFAULT '[]'::jsonb,
    metadata JSONB DEFAULT '{}'::jsonb
);

CREATE INDEX idx_resources_tenant ON resources (tenant_id);
CREATE INDEX idx_resources_user ON resources (user_id);
CREATE INDEX idx_resources_graph_edges ON resources USING GIN (graph_edges);
CREATE INDEX idx_resources_metadata ON resources USING GIN (metadata);

-- Embeddings for resources
CREATE TABLE IF NOT EXISTS embeddings_resources (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    entity_id UUID NOT NULL REFERENCES resources(id) ON DELETE CASCADE,
    field_name VARCHAR(100) NOT NULL,
    provider VARCHAR(50) NOT NULL DEFAULT 'openai',
    model VARCHAR(100) NOT NULL DEFAULT 'text-embedding-3-small',
    embedding vector(1536) NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    -- Unique: one embedding per entity per field per provider
    UNIQUE (entity_id, field_name, provider)
);

-- Index for entity lookup (get all embeddings for entity)
CREATE INDEX idx_embeddings_resources_entity ON embeddings_resources (entity_id);

-- Index for field + provider lookup
CREATE INDEX idx_embeddings_resources_field_provider ON embeddings_resources (field_name, provider);

-- HNSW index for vector similarity search (created in background)
-- Note: This will be created by background thread after data load
-- CREATE INDEX idx_embeddings_resources_vector_hnsw ON embeddings_resources
-- USING hnsw (embedding vector_cosine_ops);

-- KV_STORE trigger for resources
-- Trigger function to maintain KV_STORE for resources
CREATE OR REPLACE FUNCTION fn_resources_kv_store_upsert()
RETURNS TRIGGER AS $$
BEGIN
    IF (TG_OP = 'DELETE') THEN
        -- Remove from KV_STORE on delete
        DELETE FROM kv_store
        WHERE entity_id = OLD.id;
        RETURN OLD;
    ELSIF (TG_OP = 'INSERT' OR TG_OP = 'UPDATE') THEN
        -- Upsert to KV_STORE
        INSERT INTO kv_store (
            entity_key,
            entity_type,
            entity_id,
            tenant_id,
            user_id,
            content_summary,
            metadata,
            updated_at
        ) VALUES (
            NEW.uri,
            'resources',
            NEW.id,
            NEW.tenant_id,
            NEW.user_id,
            COALESCE(NEW.content, ''),
            NEW.metadata,
            CURRENT_TIMESTAMP
        )
        ON CONFLICT (tenant_id, entity_key)
        DO UPDATE SET
            entity_id = EXCLUDED.entity_id,
            user_id = EXCLUDED.user_id,
            content_summary = EXCLUDED.content_summary,
            metadata = EXCLUDED.metadata,
            updated_at = CURRENT_TIMESTAMP;

        RETURN NEW;
    END IF;
END;
$$ LANGUAGE plpgsql;

-- Create trigger
DROP TRIGGER IF EXISTS trg_resources_kv_store ON resources;
CREATE TRIGGER trg_resources_kv_store
AFTER INSERT OR UPDATE OR DELETE ON resources
FOR EACH ROW EXECUTE FUNCTION fn_resources_kv_store_upsert();

-- ======================================================================
-- MESSAGES (Model: Message)
-- ======================================================================

CREATE TABLE IF NOT EXISTS messages (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    tenant_id VARCHAR(100) NOT NULL,
    user_id VARCHAR(256),
    content TEXT NOT NULL,
    message_type TEXT,
    session_id TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    deleted_at TIMESTAMP,
    graph_edges JSONB DEFAULT '[]'::jsonb,
    metadata JSONB DEFAULT '{}'::jsonb
);

CREATE INDEX idx_messages_tenant ON messages (tenant_id);
CREATE INDEX idx_messages_user ON messages (user_id);
CREATE INDEX idx_messages_graph_edges ON messages USING GIN (graph_edges);
CREATE INDEX idx_messages_metadata ON messages USING GIN (metadata);

-- Embeddings for messages
CREATE TABLE IF NOT EXISTS embeddings_messages (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    entity_id UUID NOT NULL REFERENCES messages(id) ON DELETE CASCADE,
    field_name VARCHAR(100) NOT NULL,
    provider VARCHAR(50) NOT NULL DEFAULT 'openai',
    model VARCHAR(100) NOT NULL DEFAULT 'text-embedding-3-small',
    embedding vector(1536) NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    -- Unique: one embedding per entity per field per provider
    UNIQUE (entity_id, field_name, provider)
);

-- Index for entity lookup (get all embeddings for entity)
CREATE INDEX idx_embeddings_messages_entity ON embeddings_messages (entity_id);

-- Index for field + provider lookup
CREATE INDEX idx_embeddings_messages_field_provider ON embeddings_messages (field_name, provider);

-- HNSW index for vector similarity search (created in background)
-- Note: This will be created by background thread after data load
-- CREATE INDEX idx_embeddings_messages_vector_hnsw ON embeddings_messages
-- USING hnsw (embedding vector_cosine_ops);

-- KV_STORE trigger for messages
-- Trigger function to maintain KV_STORE for messages
CREATE OR REPLACE FUNCTION fn_messages_kv_store_upsert()
RETURNS TRIGGER AS $$
BEGIN
    IF (TG_OP = 'DELETE') THEN
        -- Remove from KV_STORE on delete
        DELETE FROM kv_store
        WHERE entity_id = OLD.id;
        RETURN OLD;
    ELSIF (TG_OP = 'INSERT' OR TG_OP = 'UPDATE') THEN
        -- Upsert to KV_STORE
        INSERT INTO kv_store (
            entity_key,
            entity_type,
            entity_id,
            tenant_id,
            user_id,
            content_summary,
            metadata,
            updated_at
        ) VALUES (
            NEW.content,
            'messages',
            NEW.id,
            NEW.tenant_id,
            NEW.user_id,
            COALESCE(NEW.content, ''),
            NEW.metadata,
            CURRENT_TIMESTAMP
        )
        ON CONFLICT (tenant_id, entity_key)
        DO UPDATE SET
            entity_id = EXCLUDED.entity_id,
            user_id = EXCLUDED.user_id,
            content_summary = EXCLUDED.content_summary,
            metadata = EXCLUDED.metadata,
            updated_at = CURRENT_TIMESTAMP;

        RETURN NEW;
    END IF;
END;
$$ LANGUAGE plpgsql;

-- Create trigger
DROP TRIGGER IF EXISTS trg_messages_kv_store ON messages;
CREATE TRIGGER trg_messages_kv_store
AFTER INSERT OR UPDATE OR DELETE ON messages
FOR EACH ROW EXECUTE FUNCTION fn_messages_kv_store_upsert();

-- ======================================================================
-- FILES (Model: File)
-- ======================================================================

CREATE TABLE IF NOT EXISTS files (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    tenant_id VARCHAR(100) NOT NULL,
    user_id VARCHAR(256),
    name VARCHAR(256) NOT NULL,
    uri VARCHAR(256) NOT NULL,
    content TEXT,
    timestamp VARCHAR(256),
    size_bytes INTEGER,
    mime_type VARCHAR(256),
    processing_status VARCHAR(256),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    deleted_at TIMESTAMP,
    graph_edges JSONB DEFAULT '[]'::jsonb,
    metadata JSONB DEFAULT '{}'::jsonb
);

CREATE INDEX idx_files_tenant ON files (tenant_id);
CREATE INDEX idx_files_user ON files (user_id);
CREATE INDEX idx_files_graph_edges ON files USING GIN (graph_edges);
CREATE INDEX idx_files_metadata ON files USING GIN (metadata);

-- Embeddings for files
CREATE TABLE IF NOT EXISTS embeddings_files (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    entity_id UUID NOT NULL REFERENCES files(id) ON DELETE CASCADE,
    field_name VARCHAR(100) NOT NULL,
    provider VARCHAR(50) NOT NULL DEFAULT 'openai',
    model VARCHAR(100) NOT NULL DEFAULT 'text-embedding-3-small',
    embedding vector(1536) NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    -- Unique: one embedding per entity per field per provider
    UNIQUE (entity_id, field_name, provider)
);

-- Index for entity lookup (get all embeddings for entity)
CREATE INDEX idx_embeddings_files_entity ON embeddings_files (entity_id);

-- Index for field + provider lookup
CREATE INDEX idx_embeddings_files_field_provider ON embeddings_files (field_name, provider);

-- HNSW index for vector similarity search (created in background)
-- Note: This will be created by background thread after data load
-- CREATE INDEX idx_embeddings_files_vector_hnsw ON embeddings_files
-- USING hnsw (embedding vector_cosine_ops);

-- KV_STORE trigger for files
-- Trigger function to maintain KV_STORE for files
CREATE OR REPLACE FUNCTION fn_files_kv_store_upsert()
RETURNS TRIGGER AS $$
BEGIN
    IF (TG_OP = 'DELETE') THEN
        -- Remove from KV_STORE on delete
        DELETE FROM kv_store
        WHERE entity_id = OLD.id;
        RETURN OLD;
    ELSIF (TG_OP = 'INSERT' OR TG_OP = 'UPDATE') THEN
        -- Upsert to KV_STORE
        INSERT INTO kv_store (
            entity_key,
            entity_type,
            entity_id,
            tenant_id,
            user_id,
            content_summary,
            metadata,
            updated_at
        ) VALUES (
            NEW.name,
            'files',
            NEW.id,
            NEW.tenant_id,
            NEW.user_id,
            COALESCE(NEW.content, ''),
            NEW.metadata,
            CURRENT_TIMESTAMP
        )
        ON CONFLICT (tenant_id, entity_key)
        DO UPDATE SET
            entity_id = EXCLUDED.entity_id,
            user_id = EXCLUDED.user_id,
            content_summary = EXCLUDED.content_summary,
            metadata = EXCLUDED.metadata,
            updated_at = CURRENT_TIMESTAMP;

        RETURN NEW;
    END IF;
END;
$$ LANGUAGE plpgsql;

-- Create trigger
DROP TRIGGER IF EXISTS trg_files_kv_store ON files;
CREATE TRIGGER trg_files_kv_store
AFTER INSERT OR UPDATE OR DELETE ON files
FOR EACH ROW EXECUTE FUNCTION fn_files_kv_store_upsert();

-- ======================================================================
-- SCHEMAS (Model: Schema)
-- ======================================================================

CREATE TABLE IF NOT EXISTS schemas (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    tenant_id VARCHAR(100) NOT NULL,
    user_id VARCHAR(256),
    name VARCHAR(256) NOT NULL,
    content TEXT,
    spec JSONB NOT NULL,
    category VARCHAR(256),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    deleted_at TIMESTAMP,
    graph_edges JSONB DEFAULT '[]'::jsonb,
    metadata JSONB DEFAULT '{}'::jsonb
);

CREATE INDEX idx_schemas_tenant ON schemas (tenant_id);
CREATE INDEX idx_schemas_user ON schemas (user_id);
CREATE INDEX idx_schemas_graph_edges ON schemas USING GIN (graph_edges);
CREATE INDEX idx_schemas_metadata ON schemas USING GIN (metadata);

-- Embeddings for schemas
CREATE TABLE IF NOT EXISTS embeddings_schemas (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    entity_id UUID NOT NULL REFERENCES schemas(id) ON DELETE CASCADE,
    field_name VARCHAR(100) NOT NULL,
    provider VARCHAR(50) NOT NULL DEFAULT 'openai',
    model VARCHAR(100) NOT NULL DEFAULT 'text-embedding-3-small',
    embedding vector(1536) NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    -- Unique: one embedding per entity per field per provider
    UNIQUE (entity_id, field_name, provider)
);

-- Index for entity lookup (get all embeddings for entity)
CREATE INDEX idx_embeddings_schemas_entity ON embeddings_schemas (entity_id);

-- Index for field + provider lookup
CREATE INDEX idx_embeddings_schemas_field_provider ON embeddings_schemas (field_name, provider);

-- HNSW index for vector similarity search (created in background)
-- Note: This will be created by background thread after data load
-- CREATE INDEX idx_embeddings_schemas_vector_hnsw ON embeddings_schemas
-- USING hnsw (embedding vector_cosine_ops);

-- KV_STORE trigger for schemas
-- Trigger function to maintain KV_STORE for schemas
CREATE OR REPLACE FUNCTION fn_schemas_kv_store_upsert()
RETURNS TRIGGER AS $$
BEGIN
    IF (TG_OP = 'DELETE') THEN
        -- Remove from KV_STORE on delete
        DELETE FROM kv_store
        WHERE entity_id = OLD.id;
        RETURN OLD;
    ELSIF (TG_OP = 'INSERT' OR TG_OP = 'UPDATE') THEN
        -- Upsert to KV_STORE
        INSERT INTO kv_store (
            entity_key,
            entity_type,
            entity_id,
            tenant_id,
            user_id,
            content_summary,
            metadata,
            updated_at
        ) VALUES (
            NEW.name,
            'schemas',
            NEW.id,
            NEW.tenant_id,
            NEW.user_id,
            COALESCE(NEW.content, ''),
            NEW.metadata,
            CURRENT_TIMESTAMP
        )
        ON CONFLICT (tenant_id, entity_key)
        DO UPDATE SET
            entity_id = EXCLUDED.entity_id,
            user_id = EXCLUDED.user_id,
            content_summary = EXCLUDED.content_summary,
            metadata = EXCLUDED.metadata,
            updated_at = CURRENT_TIMESTAMP;

        RETURN NEW;
    END IF;
END;
$$ LANGUAGE plpgsql;

-- Create trigger
DROP TRIGGER IF EXISTS trg_schemas_kv_store ON schemas;
CREATE TRIGGER trg_schemas_kv_store
AFTER INSERT OR UPDATE OR DELETE ON schemas
FOR EACH ROW EXECUTE FUNCTION fn_schemas_kv_store_upsert();

-- ============================================================================
-- RECORD MIGRATION
-- ============================================================================

INSERT INTO rem_migrations (name, type, version)
VALUES ('install_models.sql', 'models', '1.0.0')
ON CONFLICT (name) DO UPDATE
SET applied_at = CURRENT_TIMESTAMP,
    applied_by = CURRENT_USER;

DO $$
BEGIN
    RAISE NOTICE '============================================================';
    RAISE NOTICE 'REM Model Schema Applied: 7 tables';
    RAISE NOTICE '============================================================';
    RAISE NOTICE '  ✓ files (1 embeddable fields)';
    RAISE NOTICE '  ✓ messages (1 embeddable fields)';
    RAISE NOTICE '  ✓ moments (1 embeddable fields)';
    RAISE NOTICE '  ✓ persons';
    RAISE NOTICE '  ✓ resources (1 embeddable fields)';
    RAISE NOTICE '  ✓ schemas (1 embeddable fields)';
    RAISE NOTICE '  ✓ users';
    RAISE NOTICE '';
    RAISE NOTICE 'Next: Run background indexes if needed';
    RAISE NOTICE '  rem db migrate --background-indexes';
    RAISE NOTICE '============================================================';
END $$;