-- ========================================================
-- Sister's Live Academy - Supabase Database Schema
-- Run this in your Supabase SQL Editor:
-- https://supabase.com/dashboard/project/qxfuebpmspwixaylddby/sql/new
-- ========================================================

-- 1. Users Table
CREATE TABLE IF NOT EXISTS public.users (
    id BIGSERIAL PRIMARY KEY,
    username TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    role TEXT NOT NULL,
    full_name TEXT NOT NULL,
    is_active INTEGER DEFAULT 1,
    created_at TEXT NOT NULL
);

-- 2. Class Session Table
CREATE TABLE IF NOT EXISTS public.class_session (
    id BIGINT PRIMARY KEY,
    is_live INTEGER DEFAULT 0,
    topic TEXT DEFAULT 'General Coaching Session',
    room_name TEXT DEFAULT 'SistersClass_Room101',
    server TEXT DEFAULT 'meet.ffmuc.net',
    started_at TEXT,
    ended_at TEXT,
    teacher_notes TEXT DEFAULT ''
);

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
INSERT INTO public.class_session (id, is_live, topic, room_name, server, teacher_notes)
VALUES (1, 0, 'Mathematics & Science Live Coaching', 'SistersLiveClass_MasterRoom', 'meet.ffmuc.net', 'Welcome! Camera is OFF by default. Turn on mic when asked.')
ON CONFLICT (id) DO NOTHING;

-- Seed Teacher Account (teacher / teacher123)
-- Hash for teacher123 with salt sister_academy_salt_2026:
-- 3a7b9fc286b2e1e94cb02ff0b6d91f24d7764d8527a2fb0e8cb554030616aef7
INSERT INTO public.users (username, password_hash, role, full_name, is_active, created_at)
VALUES ('teacher', '3a7b9fc286b2e1e94cb02ff0b6d91f24d7764d8527a2fb0e8cb554030616aef7', 'teacher', 'Prof. Academy Teacher', 1, NOW()::TEXT)
ON CONFLICT (username) DO NOTHING;

-- Seed 10 Default Student Accounts (student1 to student10 / pass123)
-- Hash for pass123 with salt sister_academy_salt_2026:
-- b915152a5c5313d3950ef80d287391ea6b6b77202352b2104332d91795b2875b
INSERT INTO public.users (username, password_hash, role, full_name, is_active, created_at)
VALUES 
  ('student1', 'b915152a5c5313d3950ef80d287391ea6b6b77202352b2104332d91795b2875b', 'student', 'Student 1', 1, NOW()::TEXT),
  ('student2', 'b915152a5c5313d3950ef80d287391ea6b6b77202352b2104332d91795b2875b', 'student', 'Student 2', 1, NOW()::TEXT),
  ('student3', 'b915152a5c5313d3950ef80d287391ea6b6b77202352b2104332d91795b2875b', 'student', 'Student 3', 1, NOW()::TEXT),
  ('student4', 'b915152a5c5313d3950ef80d287391ea6b6b77202352b2104332d91795b2875b', 'student', 'Student 4', 1, NOW()::TEXT),
  ('student5', 'b915152a5c5313d3950ef80d287391ea6b6b77202352b2104332d91795b2875b', 'student', 'Student 5', 1, NOW()::TEXT),
  ('student6', 'b915152a5c5313d3950ef80d287391ea6b6b77202352b2104332d91795b2875b', 'student', 'Student 6', 1, NOW()::TEXT),
  ('student7', 'b915152a5c5313d3950ef80d287391ea6b6b77202352b2104332d91795b2875b', 'student', 'Student 7', 1, NOW()::TEXT),
  ('student8', 'b915152a5c5313d3950ef80d287391ea6b6b77202352b2104332d91795b2875b', 'student', 'Student 8', 1, NOW()::TEXT),
  ('student9', 'b915152a5c5313d3950ef80d287391ea6b6b77202352b2104332d91795b2875b', 'student', 'Student 9', 1, NOW()::TEXT),
  ('student10', 'b915152a5c5313d3950ef80d287391ea6b6b77202352b2104332d91795b2875b', 'student', 'Student 10', 1, NOW()::TEXT)
ON CONFLICT (username) DO NOTHING;

-- Initial Announcement
INSERT INTO public.announcements (title, message, priority, created_at)
VALUES ('Welcome to Sister''s Live Academy!', 'Live sessions are held Monday to Saturday at 6:00 PM. Cloud sync is active via Supabase.', 'Important', NOW()::TEXT);

-- Enable Row Level Security (RLS) with open policy for service_role and authenticated users
ALTER TABLE public.users ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.class_session ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.attendance ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.recordings ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.announcements ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.doubts ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Allow all operations on users" ON public.users FOR ALL USING (true) WITH CHECK (true);
CREATE POLICY "Allow all operations on class_session" ON public.class_session FOR ALL USING (true) WITH CHECK (true);
CREATE POLICY "Allow all operations on attendance" ON public.attendance FOR ALL USING (true) WITH CHECK (true);
CREATE POLICY "Allow all operations on recordings" ON public.recordings FOR ALL USING (true) WITH CHECK (true);
CREATE POLICY "Allow all operations on announcements" ON public.announcements FOR ALL USING (true) WITH CHECK (true);
CREATE POLICY "Allow all operations on doubts" ON public.doubts FOR ALL USING (true) WITH CHECK (true);
