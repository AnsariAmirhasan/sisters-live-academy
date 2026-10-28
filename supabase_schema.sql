-- ========================================================
-- Sister's Live Academy - Supabase Database Schema
-- Run this in your Supabase SQL Editor:
-- https://supabase.com/dashboard/project/qxfuebpmspwixaylddby/sql/new
-- ========================================================

-- 1. Users Table
CREATE TABLE IF NOT EXISTS public.users (
    id BIGSERIAL PRIMARY KEY,
    username TEXT UNIQUE NOT NULL,
    password TEXT DEFAULT '',
    password_hash TEXT NOT NULL,
    role TEXT NOT NULL,
    full_name TEXT NOT NULL,
    is_active INTEGER DEFAULT 1,
    created_at TEXT NOT NULL
);

-- Safe migrations if table already exists
ALTER TABLE public.users ADD COLUMN IF NOT EXISTS password TEXT DEFAULT '';

-- 2. Class Session Table
CREATE TABLE IF NOT EXISTS public.class_session (
    id BIGINT PRIMARY KEY,
    is_live INTEGER DEFAULT 0,
    topic TEXT DEFAULT 'General Coaching Session',
    room_name TEXT DEFAULT 'SistersClass_Room101',
    server TEXT DEFAULT 'jitsi.riot.im',
    host_teacher TEXT DEFAULT 'Lead Teacher',
    started_at TEXT,
    ended_at TEXT,
    teacher_notes TEXT DEFAULT ''
);

-- Safe migration if column missing
ALTER TABLE public.class_session ADD COLUMN IF NOT EXISTS host_teacher TEXT DEFAULT 'Lead Teacher';

-- 3. Attendance Logs
CREATE TABLE IF NOT EXISTS public.attendance (
    id BIGSERIAL PRIMARY KEY,
    student_username TEXT NOT NULL,
    student_name TEXT NOT NULL,
    room_name TEXT NOT NULL,
    topic TEXT,
    join_timestamp TEXT NOT NULL,
    date TEXT NOT NULL
);

-- 4. Recordings & Notes Library
CREATE TABLE IF NOT EXISTS public.recordings (
    id BIGSERIAL PRIMARY KEY,
    title TEXT NOT NULL,
    subject TEXT NOT NULL,
    lecture_date TEXT NOT NULL,
    description TEXT,
    drive_link TEXT NOT NULL,
    embed_url TEXT NOT NULL,
    download_url TEXT NOT NULL,
    created_at TEXT NOT NULL
);

-- 5. Announcements / Notice Board
CREATE TABLE IF NOT EXISTS public.announcements (
    id BIGSERIAL PRIMARY KEY,
    title TEXT NOT NULL,
    message TEXT NOT NULL,
    priority TEXT DEFAULT 'Normal',
    created_at TEXT NOT NULL
);

-- 6. Doubts Board
CREATE TABLE IF NOT EXISTS public.doubts (
    id BIGSERIAL PRIMARY KEY,
    student_username TEXT NOT NULL,
    student_name TEXT NOT NULL,
    question TEXT NOT NULL,
    subject TEXT NOT NULL,
    reply TEXT DEFAULT NULL,
    status TEXT DEFAULT 'Pending',
    created_at TEXT NOT NULL,
    replied_at TEXT DEFAULT NULL
);

-- Insert Default Class Session Row
INSERT INTO public.class_session (id, is_live, topic, room_name, server, host_teacher, teacher_notes)
VALUES (1, 0, 'Urdu & Arabic Live Class', 'SistersLiveClass_MasterRoom', 'jitsi.riot.im', 'Lead Teacher', 'Welcome! Camera is OFF by default. Turn on mic when asked.')
ON CONFLICT (id) DO UPDATE SET server = EXCLUDED.server, host_teacher = EXCLUDED.host_teacher;

-- Enforce Super Admin Account (admin / Amir@7861)
-- Hash for Amir@7861 with salt sister_academy_salt_2026:
-- 3b40097a858567ee7452601da42e3bfd5cb8ebc27599026da6e6aa5c602a831e
INSERT INTO public.users (username, password, password_hash, role, full_name, is_active, created_at)
VALUES ('admin', 'Amir@7861', '3b40097a858567ee7452601da42e3bfd5cb8ebc27599026da6e6aa5c602a831e', 'admin', 'Super Admin', 1, NOW()::TEXT)
ON CONFLICT (username) DO UPDATE SET password = EXCLUDED.password, password_hash = EXCLUDED.password_hash, role = 'admin', full_name = 'Super Admin', is_active = 1;

-- Seed Teacher Accounts
INSERT INTO public.users (username, password, password_hash, role, full_name, is_active, created_at)
VALUES 
  ('teacher', 'teacher123', '3a7b9fc286b2e1e94cb02ff0b6d91f24d7764d8527a2fb0e8cb554030616aef7', 'teacher', 'Lead Teacher', 1, NOW()::TEXT),
  ('teacher1', 'teacher123', '3a7b9fc286b2e1e94cb02ff0b6d91f24d7764d8527a2fb0e8cb554030616aef7', 'teacher', 'Teacher 1', 1, NOW()::TEXT),
  ('teacher2', 'teacher456', '8ca9489ce47dfb2a472c6cf67f673f4eec9d8161726a41f6ca19ebc5740fcbca', 'teacher', 'Teacher 2', 1, NOW()::TEXT)
ON CONFLICT (username) DO NOTHING;

-- Seed 10 Default Student Accounts (student1 to student10 / pass123)
-- Hash for pass123 with salt sister_academy_salt_2026:
-- b915152a5c5313d3950ef80d287391ea6b6b77202352b2104332d91795b2875b
INSERT INTO public.users (username, password, password_hash, role, full_name, is_active, created_at)
VALUES 
  ('student1', 'pass123', 'b915152a5c5313d3950ef80d287391ea6b6b77202352b2104332d91795b2875b', 'student', 'Student 1', 1, NOW()::TEXT),
  ('student2', 'pass123', 'b915152a5c5313d3950ef80d287391ea6b6b77202352b2104332d91795b2875b', 'student', 'Student 2', 1, NOW()::TEXT),
  ('student3', 'pass123', 'b915152a5c5313d3950ef80d287391ea6b6b77202352b2104332d91795b2875b', 'student', 'Student 3', 1, NOW()::TEXT),
  ('student4', 'pass123', 'b915152a5c5313d3950ef80d287391ea6b6b77202352b2104332d91795b2875b', 'student', 'Student 4', 1, NOW()::TEXT),
  ('student5', 'pass123', 'b915152a5c5313d3950ef80d287391ea6b6b77202352b2104332d91795b2875b', 'student', 'Student 5', 1, NOW()::TEXT),
  ('student6', 'pass123', 'b915152a5c5313d3950ef80d287391ea6b6b77202352b2104332d91795b2875b', 'student', 'Student 6', 1, NOW()::TEXT),
  ('student7', 'pass123', 'b915152a5c5313d3950ef80d287391ea6b6b77202352b2104332d91795b2875b', 'student', 'Student 7', 1, NOW()::TEXT),
  ('student8', 'pass123', 'b915152a5c5313d3950ef80d287391ea6b6b77202352b2104332d91795b2875b', 'student', 'Student 8', 1, NOW()::TEXT),
  ('student9', 'pass123', 'b915152a5c5313d3950ef80d287391ea6b6b77202352b2104332d91795b2875b', 'student', 'Student 9', 1, NOW()::TEXT),
  ('student10', 'pass123', 'b915152a5c5313d3950ef80d287391ea6b6b77202352b2104332d91795b2875b', 'student', 'Student 10', 1, NOW()::TEXT)
ON CONFLICT (username) DO NOTHING;

-- Initial Announcement
INSERT INTO public.announcements (title, message, priority, created_at)
VALUES ('Welcome to Sister''s Live Academy!', 'Live sessions are held Monday to Saturday at 6:00 PM. Cloud sync is active via Supabase.', 'Important', NOW()::TEXT);

-- 7. Fees Table
CREATE TABLE IF NOT EXISTS public.fees (
    id BIGSERIAL PRIMARY KEY,
    student_username TEXT NOT NULL,
    student_name TEXT NOT NULL,
    month_title TEXT NOT NULL,
    amount TEXT NOT NULL,
    due_date TEXT NOT NULL,
    status TEXT DEFAULT 'Pending',
    paid_date TEXT DEFAULT '-',
    marked_by TEXT DEFAULT '-',
    note TEXT DEFAULT ''
);

-- 8. Future Scheduled Classes Table
CREATE TABLE IF NOT EXISTS public.scheduled_classes (
    id BIGSERIAL PRIMARY KEY,
    topic TEXT NOT NULL,
    subject TEXT NOT NULL,
    teacher_name TEXT NOT NULL,
    scheduled_date TEXT NOT NULL,
    scheduled_time TEXT NOT NULL,
    room_name TEXT NOT NULL,
    notes TEXT DEFAULT '',
    status TEXT DEFAULT 'Scheduled',
    allow_waiting_room INTEGER DEFAULT 1
);

-- 9. Payment Settings Table (Editable UPI, Number & Instructions)
CREATE TABLE IF NOT EXISTS public.payment_settings (
    id BIGSERIAL PRIMARY KEY,
    upi_id TEXT DEFAULT '',
    payment_number TEXT DEFAULT '',
    account_holder_name TEXT DEFAULT '',
    custom_instructions TEXT DEFAULT ''
);

INSERT INTO public.payment_settings (id, upi_id, payment_number, account_holder_name, custom_instructions)
VALUES (1, '', '', '', 'Please share payment screenshot with your teacher after completing the transfer.')
ON CONFLICT (id) DO NOTHING;

-- Enable Row Level Security (RLS) with open policy for service_role and authenticated users
ALTER TABLE public.users ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.class_session ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.attendance ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.recordings ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.announcements ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.doubts ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.fees ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.scheduled_classes ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.payment_settings ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Allow all operations on users" ON public.users FOR ALL USING (true) WITH CHECK (true);
CREATE POLICY "Allow all operations on class_session" ON public.class_session FOR ALL USING (true) WITH CHECK (true);
CREATE POLICY "Allow all operations on attendance" ON public.attendance FOR ALL USING (true) WITH CHECK (true);
CREATE POLICY "Allow all operations on recordings" ON public.recordings FOR ALL USING (true) WITH CHECK (true);
CREATE POLICY "Allow all operations on announcements" ON public.announcements FOR ALL USING (true) WITH CHECK (true);
CREATE POLICY "Allow all operations on doubts" ON public.doubts FOR ALL USING (true) WITH CHECK (true);
CREATE POLICY "Allow all operations on fees" ON public.fees FOR ALL USING (true) WITH CHECK (true);
CREATE POLICY "Allow all operations on scheduled_classes" ON public.scheduled_classes FOR ALL USING (true) WITH CHECK (true);
CREATE POLICY "Allow all operations on payment_settings" ON public.payment_settings FOR ALL USING (true) WITH CHECK (true);
