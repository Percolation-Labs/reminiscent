-- Migration: Update messages.session_id from session name to session UUID
-- This fixes the bug where messages were stored with session.name instead of session.id
--
-- Run this migration AFTER deploying the code fixes in remdb 0.3.204+
-- The code now correctly stores session.id (UUID), but existing data needs migration.

BEGIN;

-- First, count how many messages need to be updated
DO $$
DECLARE
    count_to_migrate INTEGER;
BEGIN
    SELECT COUNT(*) INTO count_to_migrate
    FROM messages m
    JOIN sessions s ON m.session_id = s.name
    WHERE m.session_id != s.id::text;

    RAISE NOTICE 'Messages needing migration: %', count_to_migrate;
END $$;

-- Update messages.session_id from session name to session UUID
UPDATE messages m
SET session_id = s.id::text
FROM sessions s
WHERE m.session_id = s.name
  AND m.session_id != s.id::text;

-- Report how many were updated
DO $$
DECLARE
    updated_count INTEGER;
BEGIN
    GET DIAGNOSTICS updated_count = ROW_COUNT;
    RAISE NOTICE 'Messages updated: %', updated_count;
END $$;

COMMIT;

-- Verify the fix - all messages should now join by UUID
SELECT
    'Messages matching sessions by UUID' as status,
    COUNT(*) as count
FROM messages m
JOIN sessions s ON m.session_id = s.id::text;
