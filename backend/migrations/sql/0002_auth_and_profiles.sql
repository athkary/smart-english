-- Phase 2: authentication & profiles

-- Refresh-token families for rotation + reuse detection
ALTER TABLE refresh_tokens ADD COLUMN family_id uuid NOT NULL DEFAULT gen_random_uuid();
CREATE INDEX ix_refresh_tokens_family ON refresh_tokens(family_id);

-- Parent-area PIN lockout
ALTER TABLE parents ADD COLUMN pin_failed_attempts smallint NOT NULL DEFAULT 0;
ALTER TABLE parents ADD COLUMN pin_locked_until timestamptz;

-- Deleting a student (directly or via parent cascade) also deletes the student's login identity.
CREATE OR REPLACE FUNCTION delete_student_user() RETURNS trigger AS $$
BEGIN
  DELETE FROM users WHERE id = OLD.user_id AND role = 'student';
  RETURN OLD;
END; $$ LANGUAGE plpgsql;

CREATE TRIGGER trg_students_delete_user AFTER DELETE ON students
  FOR EACH ROW EXECUTE FUNCTION delete_student_user();

-- We hard-delete for privacy; soft-delete columns are not used.
ALTER TABLE users DROP COLUMN deleted_at;
ALTER TABLE students DROP COLUMN deleted_at;
DROP INDEX IF EXISTS ix_students_parent;
CREATE INDEX ix_students_parent ON students(parent_id);

-- Phase 2 teacher codes are what clients send; enable Emma & Daniel, Alex later.
UPDATE teachers SET is_enabled = (code <> 'alex');
