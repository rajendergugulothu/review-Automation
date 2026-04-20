# Database Migrations

## 000_create_review_requests.sql
Creates the base `public.review_requests` table in Supabase with the columns the
backend expects for review routing, reminders, and admin analytics.

### How to apply
1. Open Supabase dashboard for your project.
2. Go to `SQL Editor`.
3. Paste and run:
   - `scripts/db/000_create_review_requests.sql`

## 001_review_requests_hardening.sql
Adds the optional tracking columns required by the current backend for:
- Static office QR support (`office_code`)
- Reminder scheduling metadata
- Delivery provider/message diagnostics
- Reliable ordering (`created_at`)

### How to apply
1. Open Supabase dashboard for your project.
2. Go to `SQL Editor`.
3. Paste and run:
   - `scripts/db/000_create_review_requests.sql` if the table does not exist yet
   - `scripts/db/001_review_requests_hardening.sql`
4. Confirm columns exist in `public.review_requests`.

### Notes
- The SQL is idempotent (`IF NOT EXISTS`), so re-running is safe.
- Existing rows are backfilled for `created_at`.
