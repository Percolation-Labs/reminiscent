-- REM Model Schema (install_models.sql)
-- Generated from Pydantic models
-- Source: directory: src/rem/models/entities
-- Generated at: 2025-11-27T12:00:40.135678
--
-- DO NOT EDIT MANUALLY - Regenerate with: rem db schema generate
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
        RAISE EXCEPTION 'KV_STORE table not found. Run migrations/001_install.sql first.';
    END IF;

    IF NOT EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'vector') THEN
        RAISE EXCEPTION 'pgvector extension not found. Run migrations/001_install.sql first.';
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
    tier TEXT,
    anonymous_ids TEXT[] DEFAULT ARRAY[]::TEXT[],
    sec_policy JSONB DEFAULT '{}'::jsonb,
    summary TEXT,
    interests TEXT[] DEFAULT ARRAY[]::TEXT[],
    preferred_topics TEXT[] DEFAULT ARRAY[]::TEXT[],
    activity_level VARCHAR(256),
    last_active_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    deleted_at TIMESTAMP,
    graph_edges JSONB DEFAULT '[]'::jsonb,
    metadata JSONB DEFAULT '{}'::jsonb,
    tags TEXT[] DEFAULT ARRAY[]::TEXT[]
);

CREATE INDEX idx_users_tenant ON users (tenant_id);
CREATE INDEX idx_users_user ON users (user_id);
CREATE INDEX idx_users_graph_edges ON users USING GIN (graph_edges);
CREATE INDEX idx_users_metadata ON users USING GIN (metadata);
CREATE INDEX idx_users_tags ON users USING GIN (tags);

-- Embeddings for users
CREATE TABLE IF NOT EXISTS embeddings_users (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    entity_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
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
CREATE INDEX idx_embeddings_users_entity ON embeddings_users (entity_id);

-- Index for field + provider lookup
CREATE INDEX idx_embeddings_users_field_provider ON embeddings_users (field_name, provider);

-- HNSW index for vector similarity search (created in background)
-- Note: This will be created by background thread after data load
-- CREATE INDEX idx_embeddings_users_vector_hnsw ON embeddings_users
-- USING hnsw (embedding vector_cosine_ops);

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
        -- Upsert to KV_STORE (O(1) lookup by entity_key)
        INSERT INTO kv_store (
            entity_key,
            entity_type,
            entity_id,
            tenant_id,
            user_id,
            metadata,
            graph_edges,
            updated_at
        ) VALUES (
            NEW.name::VARCHAR,
            'users',
            NEW.id,
            NEW.tenant_id,
            NEW.user_id,
            NEW.metadata,
            COALESCE(NEW.graph_edges, '[]'::jsonb),
            CURRENT_TIMESTAMP
        )
        ON CONFLICT (tenant_id, entity_key)
        DO UPDATE SET
            entity_id = EXCLUDED.entity_id,
            user_id = EXCLUDED.user_id,
            metadata = EXCLUDED.metadata,
            graph_edges = EXCLUDED.graph_edges,
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
-- IMAGE_RESOURCES (Model: ImageResource)
-- ======================================================================

CREATE TABLE IF NOT EXISTS image_resources (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    tenant_id VARCHAR(100) NOT NULL,
    user_id VARCHAR(256),
    name VARCHAR(256),
    uri VARCHAR(256),
    ordinal INTEGER,
    content TEXT,
    timestamp TIMESTAMP,
    category VARCHAR(256),
    related_entities JSONB DEFAULT '{}'::jsonb,
    image_width INTEGER,
    image_height INTEGER,
    image_format VARCHAR(256),
    vision_description TEXT,
    vision_provider VARCHAR(256),
    vision_model VARCHAR(256),
    clip_embedding JSONB,
    clip_dimensions INTEGER,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    deleted_at TIMESTAMP,
    graph_edges JSONB DEFAULT '[]'::jsonb,
    metadata JSONB DEFAULT '{}'::jsonb,
    tags TEXT[] DEFAULT ARRAY[]::TEXT[]
);

CREATE INDEX idx_image_resources_tenant ON image_resources (tenant_id);
CREATE INDEX idx_image_resources_user ON image_resources (user_id);
CREATE INDEX idx_image_resources_graph_edges ON image_resources USING GIN (graph_edges);
CREATE INDEX idx_image_resources_metadata ON image_resources USING GIN (metadata);
CREATE INDEX idx_image_resources_tags ON image_resources USING GIN (tags);

-- Embeddings for image_resources
CREATE TABLE IF NOT EXISTS embeddings_image_resources (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    entity_id UUID NOT NULL REFERENCES image_resources(id) ON DELETE CASCADE,
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
CREATE INDEX idx_embeddings_image_resources_entity ON embeddings_image_resources (entity_id);

-- Index for field + provider lookup
CREATE INDEX idx_embeddings_image_resources_field_provider ON embeddings_image_resources (field_name, provider);

-- HNSW index for vector similarity search (created in background)
-- Note: This will be created by background thread after data load
-- CREATE INDEX idx_embeddings_image_resources_vector_hnsw ON embeddings_image_resources
-- USING hnsw (embedding vector_cosine_ops);

-- KV_STORE trigger for image_resources
-- Trigger function to maintain KV_STORE for image_resources
CREATE OR REPLACE FUNCTION fn_image_resources_kv_store_upsert()
RETURNS TRIGGER AS $$
BEGIN
    IF (TG_OP = 'DELETE') THEN
        -- Remove from KV_STORE on delete
        DELETE FROM kv_store
        WHERE entity_id = OLD.id;
        RETURN OLD;
    ELSIF (TG_OP = 'INSERT' OR TG_OP = 'UPDATE') THEN
        -- Upsert to KV_STORE (O(1) lookup by entity_key)
        INSERT INTO kv_store (
            entity_key,
            entity_type,
            entity_id,
            tenant_id,
            user_id,
            metadata,
            graph_edges,
            updated_at
        ) VALUES (
            NEW.name::VARCHAR,
            'image_resources',
            NEW.id,
            NEW.tenant_id,
            NEW.user_id,
            NEW.metadata,
            COALESCE(NEW.graph_edges, '[]'::jsonb),
            CURRENT_TIMESTAMP
        )
        ON CONFLICT (tenant_id, entity_key)
        DO UPDATE SET
            entity_id = EXCLUDED.entity_id,
            user_id = EXCLUDED.user_id,
            metadata = EXCLUDED.metadata,
            graph_edges = EXCLUDED.graph_edges,
            updated_at = CURRENT_TIMESTAMP;

        RETURN NEW;
    END IF;
END;
$$ LANGUAGE plpgsql;

-- Create trigger
DROP TRIGGER IF EXISTS trg_image_resources_kv_store ON image_resources;
CREATE TRIGGER trg_image_resources_kv_store
AFTER INSERT OR UPDATE OR DELETE ON image_resources
FOR EACH ROW EXECUTE FUNCTION fn_image_resources_kv_store_upsert();

-- ======================================================================
-- FEEDBACKS (Model: Feedback)
-- ======================================================================

CREATE TABLE IF NOT EXISTS feedbacks (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    tenant_id VARCHAR(100) NOT NULL,
    user_id VARCHAR(256),
    session_id VARCHAR(256) NOT NULL,
    message_id VARCHAR(256),
    rating INTEGER,
    categories TEXT[] DEFAULT ARRAY[]::TEXT[],
    comment TEXT,
    trace_id VARCHAR(256),
    span_id VARCHAR(256),
    phoenix_synced BOOLEAN,
    phoenix_annotation_id VARCHAR(256),
    annotator_kind VARCHAR(256),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    deleted_at TIMESTAMP,
    graph_edges JSONB DEFAULT '[]'::jsonb,
    metadata JSONB DEFAULT '{}'::jsonb,
    tags TEXT[] DEFAULT ARRAY[]::TEXT[]
);

CREATE INDEX idx_feedbacks_tenant ON feedbacks (tenant_id);
CREATE INDEX idx_feedbacks_user ON feedbacks (user_id);
CREATE INDEX idx_feedbacks_graph_edges ON feedbacks USING GIN (graph_edges);
CREATE INDEX idx_feedbacks_metadata ON feedbacks USING GIN (metadata);
CREATE INDEX idx_feedbacks_tags ON feedbacks USING GIN (tags);

-- KV_STORE trigger for feedbacks
-- Trigger function to maintain KV_STORE for feedbacks
CREATE OR REPLACE FUNCTION fn_feedbacks_kv_store_upsert()
RETURNS TRIGGER AS $$
BEGIN
    IF (TG_OP = 'DELETE') THEN
        -- Remove from KV_STORE on delete
        DELETE FROM kv_store
        WHERE entity_id = OLD.id;
        RETURN OLD;
    ELSIF (TG_OP = 'INSERT' OR TG_OP = 'UPDATE') THEN
        -- Upsert to KV_STORE (O(1) lookup by entity_key)
        INSERT INTO kv_store (
            entity_key,
            entity_type,
            entity_id,
            tenant_id,
            user_id,
            metadata,
            graph_edges,
            updated_at
        ) VALUES (
            NEW.id::VARCHAR,
            'feedbacks',
            NEW.id,
            NEW.tenant_id,
            NEW.user_id,
            NEW.metadata,
            COALESCE(NEW.graph_edges, '[]'::jsonb),
            CURRENT_TIMESTAMP
        )
        ON CONFLICT (tenant_id, entity_key)
        DO UPDATE SET
            entity_id = EXCLUDED.entity_id,
            user_id = EXCLUDED.user_id,
            metadata = EXCLUDED.metadata,
            graph_edges = EXCLUDED.graph_edges,
            updated_at = CURRENT_TIMESTAMP;

        RETURN NEW;
    END IF;
END;
$$ LANGUAGE plpgsql;

-- Create trigger
DROP TRIGGER IF EXISTS trg_feedbacks_kv_store ON feedbacks;
CREATE TRIGGER trg_feedbacks_kv_store
AFTER INSERT OR UPDATE OR DELETE ON feedbacks
FOR EACH ROW EXECUTE FUNCTION fn_feedbacks_kv_store_upsert();

-- ======================================================================
-- MOMENTS (Model: Moment)
-- ======================================================================

CREATE TABLE IF NOT EXISTS moments (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    tenant_id VARCHAR(100) NOT NULL,
    user_id VARCHAR(256),
    name VARCHAR(256),
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
    metadata JSONB DEFAULT '{}'::jsonb,
    tags TEXT[] DEFAULT ARRAY[]::TEXT[]
);

CREATE INDEX idx_moments_tenant ON moments (tenant_id);
CREATE INDEX idx_moments_user ON moments (user_id);
CREATE INDEX idx_moments_graph_edges ON moments USING GIN (graph_edges);
CREATE INDEX idx_moments_metadata ON moments USING GIN (metadata);
CREATE INDEX idx_moments_tags ON moments USING GIN (tags);

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
        -- Upsert to KV_STORE (O(1) lookup by entity_key)
        INSERT INTO kv_store (
            entity_key,
            entity_type,
            entity_id,
            tenant_id,
            user_id,
            metadata,
            graph_edges,
            updated_at
        ) VALUES (
            NEW.name::VARCHAR,
            'moments',
            NEW.id,
            NEW.tenant_id,
            NEW.user_id,
            NEW.metadata,
            COALESCE(NEW.graph_edges, '[]'::jsonb),
            CURRENT_TIMESTAMP
        )
        ON CONFLICT (tenant_id, entity_key)
        DO UPDATE SET
            entity_id = EXCLUDED.entity_id,
            user_id = EXCLUDED.user_id,
            metadata = EXCLUDED.metadata,
            graph_edges = EXCLUDED.graph_edges,
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
    metadata JSONB DEFAULT '{}'::jsonb,
    tags TEXT[] DEFAULT ARRAY[]::TEXT[]
);

CREATE INDEX idx_persons_tenant ON persons (tenant_id);
CREATE INDEX idx_persons_user ON persons (user_id);
CREATE INDEX idx_persons_graph_edges ON persons USING GIN (graph_edges);
CREATE INDEX idx_persons_metadata ON persons USING GIN (metadata);
CREATE INDEX idx_persons_tags ON persons USING GIN (tags);

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
        -- Upsert to KV_STORE (O(1) lookup by entity_key)
        INSERT INTO kv_store (
            entity_key,
            entity_type,
            entity_id,
            tenant_id,
            user_id,
            metadata,
            graph_edges,
            updated_at
        ) VALUES (
            NEW.id::VARCHAR,
            'persons',
            NEW.id,
            NEW.tenant_id,
            NEW.user_id,
            NEW.metadata,
            COALESCE(NEW.graph_edges, '[]'::jsonb),
            CURRENT_TIMESTAMP
        )
        ON CONFLICT (tenant_id, entity_key)
        DO UPDATE SET
            entity_id = EXCLUDED.entity_id,
            user_id = EXCLUDED.user_id,
            metadata = EXCLUDED.metadata,
            graph_edges = EXCLUDED.graph_edges,
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
-- SESSIONS (Model: Session)
-- ======================================================================

CREATE TABLE IF NOT EXISTS sessions (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    tenant_id VARCHAR(100) NOT NULL,
    user_id VARCHAR(256),
    name VARCHAR(256) NOT NULL,
    mode TEXT,
    description TEXT,
    original_trace_id VARCHAR(256),
    settings_overrides JSONB,
    prompt TEXT,
    agent_schema_uri VARCHAR(256),
    message_count INTEGER,
    total_tokens INTEGER,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    deleted_at TIMESTAMP,
    graph_edges JSONB DEFAULT '[]'::jsonb,
    metadata JSONB DEFAULT '{}'::jsonb,
    tags TEXT[] DEFAULT ARRAY[]::TEXT[]
);

CREATE INDEX idx_sessions_tenant ON sessions (tenant_id);
CREATE INDEX idx_sessions_user ON sessions (user_id);
CREATE INDEX idx_sessions_graph_edges ON sessions USING GIN (graph_edges);
CREATE INDEX idx_sessions_metadata ON sessions USING GIN (metadata);
CREATE INDEX idx_sessions_tags ON sessions USING GIN (tags);

-- Embeddings for sessions
CREATE TABLE IF NOT EXISTS embeddings_sessions (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    entity_id UUID NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
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
CREATE INDEX idx_embeddings_sessions_entity ON embeddings_sessions (entity_id);

-- Index for field + provider lookup
CREATE INDEX idx_embeddings_sessions_field_provider ON embeddings_sessions (field_name, provider);

-- HNSW index for vector similarity search (created in background)
-- Note: This will be created by background thread after data load
-- CREATE INDEX idx_embeddings_sessions_vector_hnsw ON embeddings_sessions
-- USING hnsw (embedding vector_cosine_ops);

-- KV_STORE trigger for sessions
-- Trigger function to maintain KV_STORE for sessions
CREATE OR REPLACE FUNCTION fn_sessions_kv_store_upsert()
RETURNS TRIGGER AS $$
BEGIN
    IF (TG_OP = 'DELETE') THEN
        -- Remove from KV_STORE on delete
        DELETE FROM kv_store
        WHERE entity_id = OLD.id;
        RETURN OLD;
    ELSIF (TG_OP = 'INSERT' OR TG_OP = 'UPDATE') THEN
        -- Upsert to KV_STORE (O(1) lookup by entity_key)
        INSERT INTO kv_store (
            entity_key,
            entity_type,
            entity_id,
            tenant_id,
            user_id,
            metadata,
            graph_edges,
            updated_at
        ) VALUES (
            NEW.name::VARCHAR,
            'sessions',
            NEW.id,
            NEW.tenant_id,
            NEW.user_id,
            NEW.metadata,
            COALESCE(NEW.graph_edges, '[]'::jsonb),
            CURRENT_TIMESTAMP
        )
        ON CONFLICT (tenant_id, entity_key)
        DO UPDATE SET
            entity_id = EXCLUDED.entity_id,
            user_id = EXCLUDED.user_id,
            metadata = EXCLUDED.metadata,
            graph_edges = EXCLUDED.graph_edges,
            updated_at = CURRENT_TIMESTAMP;

        RETURN NEW;
    END IF;
END;
$$ LANGUAGE plpgsql;

-- Create trigger
DROP TRIGGER IF EXISTS trg_sessions_kv_store ON sessions;
CREATE TRIGGER trg_sessions_kv_store
AFTER INSERT OR UPDATE OR DELETE ON sessions
FOR EACH ROW EXECUTE FUNCTION fn_sessions_kv_store_upsert();

-- ======================================================================
-- RESOURCES (Model: Resource)
-- ======================================================================

CREATE TABLE IF NOT EXISTS resources (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    tenant_id VARCHAR(100) NOT NULL,
    user_id VARCHAR(256),
    name VARCHAR(256),
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
    metadata JSONB DEFAULT '{}'::jsonb,
    tags TEXT[] DEFAULT ARRAY[]::TEXT[]
);

CREATE INDEX idx_resources_tenant ON resources (tenant_id);
CREATE INDEX idx_resources_user ON resources (user_id);
CREATE INDEX idx_resources_graph_edges ON resources USING GIN (graph_edges);
CREATE INDEX idx_resources_metadata ON resources USING GIN (metadata);
CREATE INDEX idx_resources_tags ON resources USING GIN (tags);

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
        -- Upsert to KV_STORE (O(1) lookup by entity_key)
        INSERT INTO kv_store (
            entity_key,
            entity_type,
            entity_id,
            tenant_id,
            user_id,
            metadata,
            graph_edges,
            updated_at
        ) VALUES (
            NEW.name::VARCHAR,
            'resources',
            NEW.id,
            NEW.tenant_id,
            NEW.user_id,
            NEW.metadata,
            COALESCE(NEW.graph_edges, '[]'::jsonb),
            CURRENT_TIMESTAMP
        )
        ON CONFLICT (tenant_id, entity_key)
        DO UPDATE SET
            entity_id = EXCLUDED.entity_id,
            user_id = EXCLUDED.user_id,
            metadata = EXCLUDED.metadata,
            graph_edges = EXCLUDED.graph_edges,
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
    message_type VARCHAR(256),
    session_id VARCHAR(256),
    prompt TEXT,
    model VARCHAR(256),
    token_count INTEGER,
    trace_id VARCHAR(256),
    span_id VARCHAR(256),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    deleted_at TIMESTAMP,
    graph_edges JSONB DEFAULT '[]'::jsonb,
    metadata JSONB DEFAULT '{}'::jsonb,
    tags TEXT[] DEFAULT ARRAY[]::TEXT[]
);

CREATE INDEX idx_messages_tenant ON messages (tenant_id);
CREATE INDEX idx_messages_user ON messages (user_id);
CREATE INDEX idx_messages_graph_edges ON messages USING GIN (graph_edges);
CREATE INDEX idx_messages_metadata ON messages USING GIN (metadata);
CREATE INDEX idx_messages_tags ON messages USING GIN (tags);

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
        -- Upsert to KV_STORE (O(1) lookup by entity_key)
        INSERT INTO kv_store (
            entity_key,
            entity_type,
            entity_id,
            tenant_id,
            user_id,
            metadata,
            graph_edges,
            updated_at
        ) VALUES (
            NEW.id::VARCHAR,
            'messages',
            NEW.id,
            NEW.tenant_id,
            NEW.user_id,
            NEW.metadata,
            COALESCE(NEW.graph_edges, '[]'::jsonb),
            CURRENT_TIMESTAMP
        )
        ON CONFLICT (tenant_id, entity_key)
        DO UPDATE SET
            entity_id = EXCLUDED.entity_id,
            user_id = EXCLUDED.user_id,
            metadata = EXCLUDED.metadata,
            graph_edges = EXCLUDED.graph_edges,
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
    metadata JSONB DEFAULT '{}'::jsonb,
    tags TEXT[] DEFAULT ARRAY[]::TEXT[]
);

CREATE INDEX idx_files_tenant ON files (tenant_id);
CREATE INDEX idx_files_user ON files (user_id);
CREATE INDEX idx_files_graph_edges ON files USING GIN (graph_edges);
CREATE INDEX idx_files_metadata ON files USING GIN (metadata);
CREATE INDEX idx_files_tags ON files USING GIN (tags);

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
        -- Upsert to KV_STORE (O(1) lookup by entity_key)
        INSERT INTO kv_store (
            entity_key,
            entity_type,
            entity_id,
            tenant_id,
            user_id,
            metadata,
            graph_edges,
            updated_at
        ) VALUES (
            NEW.id::VARCHAR,
            'files',
            NEW.id,
            NEW.tenant_id,
            NEW.user_id,
            NEW.metadata,
            COALESCE(NEW.graph_edges, '[]'::jsonb),
            CURRENT_TIMESTAMP
        )
        ON CONFLICT (tenant_id, entity_key)
        DO UPDATE SET
            entity_id = EXCLUDED.entity_id,
            user_id = EXCLUDED.user_id,
            metadata = EXCLUDED.metadata,
            graph_edges = EXCLUDED.graph_edges,
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
-- ONTOLOGIES (Model: Ontology)
-- ======================================================================

CREATE TABLE IF NOT EXISTS ontologies (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    tenant_id VARCHAR(100) NOT NULL,
    user_id VARCHAR(256),
    name VARCHAR(256) NOT NULL,
    file_id UUID NOT NULL,
    agent_schema_id VARCHAR(256) NOT NULL,
    provider_name VARCHAR(256) NOT NULL,
    model_name VARCHAR(256) NOT NULL,
    extracted_data JSONB NOT NULL,
    confidence_score DOUBLE PRECISION,
    extraction_timestamp VARCHAR(256),
    embedding_text TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    deleted_at TIMESTAMP,
    graph_edges JSONB DEFAULT '[]'::jsonb,
    metadata JSONB DEFAULT '{}'::jsonb,
    tags TEXT[] DEFAULT ARRAY[]::TEXT[]
);

CREATE INDEX idx_ontologies_tenant ON ontologies (tenant_id);
CREATE INDEX idx_ontologies_user ON ontologies (user_id);
CREATE INDEX idx_ontologies_graph_edges ON ontologies USING GIN (graph_edges);
CREATE INDEX idx_ontologies_metadata ON ontologies USING GIN (metadata);
CREATE INDEX idx_ontologies_tags ON ontologies USING GIN (tags);

-- KV_STORE trigger for ontologies
-- Trigger function to maintain KV_STORE for ontologies
CREATE OR REPLACE FUNCTION fn_ontologies_kv_store_upsert()
RETURNS TRIGGER AS $$
BEGIN
    IF (TG_OP = 'DELETE') THEN
        -- Remove from KV_STORE on delete
        DELETE FROM kv_store
        WHERE entity_id = OLD.id;
        RETURN OLD;
    ELSIF (TG_OP = 'INSERT' OR TG_OP = 'UPDATE') THEN
        -- Upsert to KV_STORE (O(1) lookup by entity_key)
        INSERT INTO kv_store (
            entity_key,
            entity_type,
            entity_id,
            tenant_id,
            user_id,
            metadata,
            graph_edges,
            updated_at
        ) VALUES (
            NEW.id::VARCHAR,
            'ontologies',
            NEW.id,
            NEW.tenant_id,
            NEW.user_id,
            NEW.metadata,
            COALESCE(NEW.graph_edges, '[]'::jsonb),
            CURRENT_TIMESTAMP
        )
        ON CONFLICT (tenant_id, entity_key)
        DO UPDATE SET
            entity_id = EXCLUDED.entity_id,
            user_id = EXCLUDED.user_id,
            metadata = EXCLUDED.metadata,
            graph_edges = EXCLUDED.graph_edges,
            updated_at = CURRENT_TIMESTAMP;

        RETURN NEW;
    END IF;
END;
$$ LANGUAGE plpgsql;

-- Create trigger
DROP TRIGGER IF EXISTS trg_ontologies_kv_store ON ontologies;
CREATE TRIGGER trg_ontologies_kv_store
AFTER INSERT OR UPDATE OR DELETE ON ontologies
FOR EACH ROW EXECUTE FUNCTION fn_ontologies_kv_store_upsert();

-- ======================================================================
-- ONTOLOGY_CONFIGS (Model: OntologyConfig)
-- ======================================================================

CREATE TABLE IF NOT EXISTS ontology_configs (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    tenant_id VARCHAR(100) NOT NULL,
    user_id VARCHAR(256),
    name VARCHAR(256) NOT NULL,
    agent_schema_id VARCHAR(256) NOT NULL,
    description TEXT,
    mime_type_pattern VARCHAR(256),
    uri_pattern VARCHAR(256),
    tag_filter TEXT[],
    priority INTEGER,
    enabled BOOLEAN,
    provider_name VARCHAR(256),
    model_name VARCHAR(256),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    deleted_at TIMESTAMP,
    graph_edges JSONB DEFAULT '[]'::jsonb,
    metadata JSONB DEFAULT '{}'::jsonb,
    tags TEXT[] DEFAULT ARRAY[]::TEXT[]
);

CREATE INDEX idx_ontology_configs_tenant ON ontology_configs (tenant_id);
CREATE INDEX idx_ontology_configs_user ON ontology_configs (user_id);
CREATE INDEX idx_ontology_configs_graph_edges ON ontology_configs USING GIN (graph_edges);
CREATE INDEX idx_ontology_configs_metadata ON ontology_configs USING GIN (metadata);
CREATE INDEX idx_ontology_configs_tags ON ontology_configs USING GIN (tags);

-- Embeddings for ontology_configs
CREATE TABLE IF NOT EXISTS embeddings_ontology_configs (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    entity_id UUID NOT NULL REFERENCES ontology_configs(id) ON DELETE CASCADE,
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
CREATE INDEX idx_embeddings_ontology_configs_entity ON embeddings_ontology_configs (entity_id);

-- Index for field + provider lookup
CREATE INDEX idx_embeddings_ontology_configs_field_provider ON embeddings_ontology_configs (field_name, provider);

-- HNSW index for vector similarity search (created in background)
-- Note: This will be created by background thread after data load
-- CREATE INDEX idx_embeddings_ontology_configs_vector_hnsw ON embeddings_ontology_configs
-- USING hnsw (embedding vector_cosine_ops);

-- KV_STORE trigger for ontology_configs
-- Trigger function to maintain KV_STORE for ontology_configs
CREATE OR REPLACE FUNCTION fn_ontology_configs_kv_store_upsert()
RETURNS TRIGGER AS $$
BEGIN
    IF (TG_OP = 'DELETE') THEN
        -- Remove from KV_STORE on delete
        DELETE FROM kv_store
        WHERE entity_id = OLD.id;
        RETURN OLD;
    ELSIF (TG_OP = 'INSERT' OR TG_OP = 'UPDATE') THEN
        -- Upsert to KV_STORE (O(1) lookup by entity_key)
        INSERT INTO kv_store (
            entity_key,
            entity_type,
            entity_id,
            tenant_id,
            user_id,
            metadata,
            graph_edges,
            updated_at
        ) VALUES (
            NEW.id::VARCHAR,
            'ontology_configs',
            NEW.id,
            NEW.tenant_id,
            NEW.user_id,
            NEW.metadata,
            COALESCE(NEW.graph_edges, '[]'::jsonb),
            CURRENT_TIMESTAMP
        )
        ON CONFLICT (tenant_id, entity_key)
        DO UPDATE SET
            entity_id = EXCLUDED.entity_id,
            user_id = EXCLUDED.user_id,
            metadata = EXCLUDED.metadata,
            graph_edges = EXCLUDED.graph_edges,
            updated_at = CURRENT_TIMESTAMP;

        RETURN NEW;
    END IF;
END;
$$ LANGUAGE plpgsql;

-- Create trigger
DROP TRIGGER IF EXISTS trg_ontology_configs_kv_store ON ontology_configs;
CREATE TRIGGER trg_ontology_configs_kv_store
AFTER INSERT OR UPDATE OR DELETE ON ontology_configs
FOR EACH ROW EXECUTE FUNCTION fn_ontology_configs_kv_store_upsert();

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
    provider_configs JSONB DEFAULT '{}'::jsonb,
    embedding_fields TEXT[] DEFAULT ARRAY[]::TEXT[],
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    deleted_at TIMESTAMP,
    graph_edges JSONB DEFAULT '[]'::jsonb,
    metadata JSONB DEFAULT '{}'::jsonb,
    tags TEXT[] DEFAULT ARRAY[]::TEXT[]
);

CREATE INDEX idx_schemas_tenant ON schemas (tenant_id);
CREATE INDEX idx_schemas_user ON schemas (user_id);
CREATE INDEX idx_schemas_graph_edges ON schemas USING GIN (graph_edges);
CREATE INDEX idx_schemas_metadata ON schemas USING GIN (metadata);
CREATE INDEX idx_schemas_tags ON schemas USING GIN (tags);

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
        -- Upsert to KV_STORE (O(1) lookup by entity_key)
        INSERT INTO kv_store (
            entity_key,
            entity_type,
            entity_id,
            tenant_id,
            user_id,
            metadata,
            graph_edges,
            updated_at
        ) VALUES (
            NEW.id::VARCHAR,
            'schemas',
            NEW.id,
            NEW.tenant_id,
            NEW.user_id,
            NEW.metadata,
            COALESCE(NEW.graph_edges, '[]'::jsonb),
            CURRENT_TIMESTAMP
        )
        ON CONFLICT (tenant_id, entity_key)
        DO UPDATE SET
            entity_id = EXCLUDED.entity_id,
            user_id = EXCLUDED.user_id,
            metadata = EXCLUDED.metadata,
            graph_edges = EXCLUDED.graph_edges,
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
    RAISE NOTICE 'REM Model Schema Applied: 12 tables';
    RAISE NOTICE '============================================================';
    RAISE NOTICE '  ✓ feedbacks';
    RAISE NOTICE '  ✓ files (1 embeddable fields)';
    RAISE NOTICE '  ✓ image_resources (1 embeddable fields)';
    RAISE NOTICE '  ✓ messages (1 embeddable fields)';
    RAISE NOTICE '  ✓ moments (1 embeddable fields)';
    RAISE NOTICE '  ✓ ontologies';
    RAISE NOTICE '  ✓ ontology_configs (1 embeddable fields)';
    RAISE NOTICE '  ✓ persons';
    RAISE NOTICE '  ✓ resources (1 embeddable fields)';
    RAISE NOTICE '  ✓ schemas (1 embeddable fields)';
    RAISE NOTICE '  ✓ sessions (1 embeddable fields)';
    RAISE NOTICE '  ✓ users (1 embeddable fields)';
    RAISE NOTICE '';
    RAISE NOTICE 'Next: Run background indexes if needed';
    RAISE NOTICE '  rem db migrate --background-indexes';
    RAISE NOTICE '============================================================';
END $$;