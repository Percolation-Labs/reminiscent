-- Fix resources KV Store trigger to use URI as key
-- Date: 2025-11-22
-- Description: Updates trigger for resources to use 'uri' as entity_key, matching test expectations

CREATE OR REPLACE FUNCTION fn_resources_kv_store_upsert()
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
            NEW.uri, -- Use URI as key for resources
            'resources',
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

INSERT INTO rem_migrations (name, type, version)
VALUES ('005_fix_resources_trigger.sql', 'fix', '1.0.0')
ON CONFLICT (name) DO UPDATE
SET applied_at = CURRENT_TIMESTAMP;
