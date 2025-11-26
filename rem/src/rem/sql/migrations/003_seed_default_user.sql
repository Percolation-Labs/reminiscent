-- ============================================================================
-- Migration: 003_seed_default_user.sql
-- Description: Seed the default system user for CLI and API operations
--
-- The default user is derived from settings.test.user_email (test@rem.ai)
-- using deterministic UUID v5 generation. This ensures consistent user ID
-- across all environments and test runs.
--
-- Default user:
--   email: test@rem.ai
--   user_id: 9e7dc22b-13bb-5cea-8aee-f6b8e6dc962f (UUID v5 from DNS namespace)
--
-- This user is used when:
--   - CLI commands run without --user-id flag
--   - API requests come without X-User-Id header
--   - Tests run without explicit user context
-- ============================================================================

-- Insert default user (idempotent - skip if exists)
INSERT INTO users (
    id,
    user_id,
    tenant_id,
    name,
    email,
    role,
    tags,
    metadata,
    created_at,
    updated_at
) VALUES (
    '9e7dc22b-13bb-5cea-8aee-f6b8e6dc962f'::uuid,
    '9e7dc22b-13bb-5cea-8aee-f6b8e6dc962f',
    '9e7dc22b-13bb-5cea-8aee-f6b8e6dc962f',
    'Default User',
    'test@rem.ai',
    'system',
    ARRAY['system', 'default'],
    '{"description": "Default system user for CLI and API operations without explicit user context"}'::jsonb,
    NOW(),
    NOW()
) ON CONFLICT (id) DO NOTHING;

-- Log migration
DO $$
BEGIN
    RAISE NOTICE 'Seeded default user: test@rem.ai (id: 9e7dc22b-13bb-5cea-8aee-f6b8e6dc962f)';
END $$;
