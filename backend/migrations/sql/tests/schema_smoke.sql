-- Run after 0001. Each block must behave as commented; ON_ERROR_STOP applies to non-guarded statements.
\set ON_ERROR_STOP 1
BEGIN;
INSERT INTO users(id, role, email, password_hash) VALUES ('00000000-0000-0000-0000-000000000001','parent','Mom@Example.com','x');
INSERT INTO parents(id, user_id, display_name) VALUES ('00000000-0000-0000-0000-0000000000a1','00000000-0000-0000-0000-000000000001','أم أحمد');
INSERT INTO users(id, role) VALUES ('00000000-0000-0000-0000-000000000002','student');
INSERT INTO students(id, user_id, parent_id, nickname, birth_year, preferred_teacher_id)
  SELECT '00000000-0000-0000-0000-0000000000b1','00000000-0000-0000-0000-000000000002','00000000-0000-0000-0000-0000000000a1','Ahmed',2017,id FROM teachers WHERE code='emma';
-- citext uniqueness: same email different case must fail
DO $$ BEGIN
  INSERT INTO users(role,email,password_hash) VALUES ('parent','mom@example.com','y');
  RAISE EXCEPTION 'citext uniqueness NOT enforced';
EXCEPTION WHEN unique_violation THEN RAISE NOTICE 'ok: email unique (case-insensitive)'; END $$;
-- parent without password must fail
DO $$ BEGIN
  INSERT INTO users(role,email) VALUES ('parent','dad@example.com');
  RAISE EXCEPTION 'parent credential check NOT enforced';
EXCEPTION WHEN check_violation THEN RAISE NOTICE 'ok: parent needs credentials'; END $$;
-- accuracy score without phoneme assessment must fail
DO $$ BEGIN
  INSERT INTO pronunciation_results(student_id,target_text,recognized_text,method,accuracy_score,provider)
  VALUES ('00000000-0000-0000-0000-0000000000b1','I like apples','I like apple','transcript_match',80,'stt');
  RAISE EXCEPTION 'accuracy guard NOT enforced';
EXCEPTION WHEN check_violation THEN RAISE NOTICE 'ok: no accuracy score from transcript alone'; END $$;
-- updated_at trigger
UPDATE students SET nickname='Ahmad' WHERE id='00000000-0000-0000-0000-0000000000b1';
-- cascade delete: deleting parent user removes parent, students' rows via parent
INSERT INTO conversation_sessions(student_id, teacher_id, mode) SELECT '00000000-0000-0000-0000-0000000000b1', id, 'beginner' FROM teachers WHERE code='emma';
INSERT INTO conversation_messages(session_id, seq, speaker, text_en, text_ar) SELECT id,1,'teacher','Hello! What is your name?','مرحباً! ما اسمك؟' FROM conversation_sessions;
DELETE FROM users WHERE id='00000000-0000-0000-0000-000000000001';
DO $$ BEGIN
  IF (SELECT count(*) FROM students) <> 0 OR (SELECT count(*) FROM conversation_messages) <> 0 THEN
    RAISE EXCEPTION 'parent deletion did not cascade to child data';
  END IF;
  RAISE NOTICE 'ok: parent-controlled deletion cascades';
END $$;
DO $$ BEGIN IF (SELECT count(*) FROM teachers) <> 3 THEN RAISE EXCEPTION 'teacher seed missing'; END IF; RAISE NOTICE 'ok: 3 teachers seeded'; END $$;
ROLLBACK;
