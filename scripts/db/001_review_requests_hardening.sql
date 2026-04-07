-- Urban Review System - Review Requests Schema Hardening
-- Safe to run multiple times (idempotent).
-- Run in Supabase SQL Editor against your project database.

DO $$
BEGIN
  IF to_regclass('public.review_requests') IS NULL THEN
    RAISE EXCEPTION 'Table public.review_requests does not exist. Create it first.';
  END IF;
END $$;

ALTER TABLE public.review_requests
  ADD COLUMN IF NOT EXISTS created_at timestamptz DEFAULT timezone('utc', now()),
  ADD COLUMN IF NOT EXISTS office_code text,
  ADD COLUMN IF NOT EXISTS external_source text,
  ADD COLUMN IF NOT EXISTS external_event_id text,
  ADD COLUMN IF NOT EXISTS request_sent_at timestamptz,
  ADD COLUMN IF NOT EXISTS first_reminder_sent_at timestamptz,
  ADD COLUMN IF NOT EXISTS second_reminder_sent_at timestamptz,
  ADD COLUMN IF NOT EXISTS last_reminder_at timestamptz,
  ADD COLUMN IF NOT EXISTS review_submitted_at timestamptz,
  ADD COLUMN IF NOT EXISTS feedback_submitted_at timestamptz,
  ADD COLUMN IF NOT EXISTS last_channel_status text,
  ADD COLUMN IF NOT EXISTS last_channel_detail text,
  ADD COLUMN IF NOT EXISTS last_channel_provider text,
  ADD COLUMN IF NOT EXISTS last_channel_message_id text;

-- Backfill timestamps for older rows.
UPDATE public.review_requests
SET created_at = timezone('utc', now())
WHERE created_at IS NULL;

-- Helpful defaults for new rows.
ALTER TABLE public.review_requests
  ALTER COLUMN status SET DEFAULT 'request_pending';

ALTER TABLE public.review_requests
  ALTER COLUMN channel SET DEFAULT 'email';

-- Performance indexes used by APIs and reminder processor.
CREATE INDEX IF NOT EXISTS idx_review_requests_unique_token
  ON public.review_requests (unique_token);

CREATE INDEX IF NOT EXISTS idx_review_requests_status
  ON public.review_requests (status);

CREATE INDEX IF NOT EXISTS idx_review_requests_created_at
  ON public.review_requests (created_at DESC);

CREATE INDEX IF NOT EXISTS idx_review_requests_office_code
  ON public.review_requests (office_code);

CREATE INDEX IF NOT EXISTS idx_review_requests_external_event
  ON public.review_requests (external_source, external_event_id);

CREATE INDEX IF NOT EXISTS idx_review_requests_status_created_at
  ON public.review_requests (status, created_at DESC);
