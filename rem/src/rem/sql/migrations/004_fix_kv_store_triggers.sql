-- Fix KV Store triggers to use natural keys (name) instead of UUIDs
-- Date: 2025-11-22
-- Description: Updates triggers for users, moments, and persons to use 'name' as entity_key

-- 1. Fix users trigger
CREATE OR REPLACE FUNCTION fn_users_kv_store_upsert()
RETURNS TRIGGER AS $$
BEGIN
    IF (TG_OP = 'DELETE') THEN
        DELETE FROM kv_store WHERE entity_id = OLD.id;
        RETURN OLD;
    ELSIF (TG_OP = 'INSERT' OR TG_OP = 'UPDATE') THEN
        INSERT INTO kv_store (
            entity_key,
            entity_type,
            entity_id,
            tenant_id,
            user_id,
            metadata,
            updated_at
        ) VALUES (
            NEW.name, -- Use name as key
            'users',
            NEW.id,
            NEW.tenant_id,
            NEW.user_id,
            NEW.metadata,
            CURRENT_TIMESTAMP
        )
        ON CONFLICT (tenant_id, entity_key)
        DO UPDATE SET
            entity_id = EXCLUDED.entity_id,
            user_id = EXCLUDED.user_id,
            metadata = EXCLUDED.metadata,
            updated_at = CURRENT_TIMESTAMP;
        RETURN NEW;
    END IF;
END;
$$ LANGUAGE plpgsql;

-- 2. Fix moments trigger
CREATE OR REPLACE FUNCTION fn_moments_kv_store_upsert()
RETURNS TRIGGER AS $$
BEGIN
    IF (TG_OP = 'DELETE') THEN
        DELETE FROM kv_store WHERE entity_id = OLD.id;
        RETURN OLD;
    ELSIF (TG_OP = 'INSERT' OR TG_OP = 'UPDATE') THEN
        INSERT INTO kv_store (
            entity_key,
            entity_type,
            entity_id,
            tenant_id,
            user_id,
            metadata,
            updated_at
        ) VALUES (
            NEW.name, -- Use name as key
            'moments',
            NEW.id,
            NEW.tenant_id,
            NEW.user_id,
            NEW.metadata,
            CURRENT_TIMESTAMP
        )
        ON CONFLICT (tenant_id, entity_key)
        DO UPDATE SET
            entity_id = EXCLUDED.entity_id,
            user_id = EXCLUDED.user_id,
            metadata = EXCLUDED.metadata,
            updated_at = CURRENT_TIMESTAMP;
        RETURN NEW;
    END IF;
END;
$$ LANGUAGE plpgsql;

-- 3. Fix persons trigger
CREATE OR REPLACE FUNCTION fn_persons_kv_store_upsert()
RETURNS TRIGGER AS $$
BEGIN
    IF (TG_OP = 'DELETE') THEN
        DELETE FROM kv_store WHERE entity_id = OLD.id;
        RETURN OLD;
    ELSIF (TG_OP = 'INSERT' OR TG_OP = 'UPDATE') THEN
        INSERT INTO kv_store (
            entity_key,
            entity_type,
            entity_id,
            tenant_id,
            user_id,
            metadata,
            updated_at
        ) VALUES (
            NEW.name, -- Use name as key
            'persons',
            NEW.id,
            NEW.tenant_id,
            NEW.user_id,
            NEW.metadata,
            CURRENT_TIMESTAMP
        )
        ON CONFLICT (tenant_id, entity_key)
        DO UPDATE SET
            entity_id = EXCLUDED.entity_id,
            user_id = EXCLUDED.user_id,
            metadata = EXCLUDED.metadata,
            updated_at = CURRENT_TIMESTAMP;
        RETURN NEW;
    END IF;
END;
$$ LANGUAGE plpgsql;

-- 4. Record migration
INSERT INTO rem_migrations (name, type, version)
VALUES ('004_fix_kv_store_triggers.sql', 'fix', '1.0.0')
ON CONFLICT (name) DO UPDATE
SET applied_at = CURRENT_TIMESTAMP;
