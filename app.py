"""
Sister's Live Academy - Online Live Classroom & Coaching Web App
Complete Production-Ready Streamlit Application for 1 Teacher and 10+ Students.
Hybrid Storage: Local Persistent SQLite with Automatic Supabase Cloud Sync.
"""

import streamlit as st
import sqlite3
import hashlib
import os
import re
import datetime
import urllib.parse
import urllib.request
import io
import csv
import ssl
import json
import streamlit.components.v1 as components

# ==========================================
# 1. PAGE CONFIGURATION
# ==========================================
st.set_page_config(
    page_title="Sister's Live Academy",
    page_icon="🎓",
    layout="wide",
    initial_sidebar_state="expanded"
)

# ==========================================
# GOOGLE DRIVE CONFIGURATION
# ==========================================
DEFAULT_DRIVE_FOLDER_URL = "https://drive.google.com/drive/folders/10g6bnUyJJXVA_ABy2xZtL_FxUfUB7Uzb?usp=sharing"

def get_drive_folder_id(url: str = DEFAULT_DRIVE_FOLDER_URL) -> str:
    """Extracts folder ID from Google Drive folder URL using regex"""
    if not url:
        return "10g6bnUyJJXVA_ABy2xZtL_FxUfUB7Uzb"
    match = re.search(r'folders/([a-zA-Z0-9_-]+)', url)
    if match:
        return match.group(1)
    param_match = re.search(r'[?&]id=([a-zA-Z0-9_-]+)', url)
    if param_match:
        return param_match.group(1)
    return "10g6bnUyJJXVA_ABy2xZtL_FxUfUB7Uzb"

DEFAULT_DRIVE_FOLDER_ID = get_drive_folder_id(DEFAULT_DRIVE_FOLDER_URL)

# ==========================================
# 2. SAFE SESSION STATE INITIALIZATION
# ==========================================
if "logged_in" not in st.session_state:
    st.session_state.logged_in = False
if "username" not in st.session_state:
    st.session_state.username = None
if "role" not in st.session_state:
    st.session_state.role = None
if "name" not in st.session_state:
    st.session_state.name = None
if "jitsi_server" not in st.session_state:
    st.session_state.jitsi_server = "jitsi.riot.im"
if "live_joined" not in st.session_state:
    st.session_state.live_joined = False
if "joined_live_class" not in st.session_state:
    st.session_state.joined_live_class = False

# ==========================================
# 3. HYBRID DATABASE ENGINE (SQLITE & SUPABASE)
# ==========================================
DB_FILE = "classroom.db"

def get_db_connection():
    """
    Opens a fresh, short-lived SQLite connection with 30s timeout and WAL journal mode.
    Allows concurrent reads and writes from multiple users (Teacher + Students)
    without database locking conflicts.
    """
    conn = sqlite3.connect(DB_FILE, timeout=30.0, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA busy_timeout = 30000;")
        conn.execute("PRAGMA synchronous = NORMAL;")
    except Exception:
        pass
    return conn

# Compatibility alias
get_db = get_db_connection


def hash_password(password: str, salt: str = "sister_academy_salt_2026") -> str:
    """Standard SHA-256 password hashing with salt"""
    return hashlib.sha256(f"{password}_{salt}".encode('utf-8')).hexdigest()

def get_supabase_config():
    """Returns (url, key) if configured in Streamlit secrets or env"""
    try:
        url = st.secrets.get("SUPABASE_URL", os.environ.get("SUPABASE_URL", ""))
        key = st.secrets.get("SUPABASE_KEY", os.environ.get("SUPABASE_KEY", ""))
        if url and key:
            return url.strip().rstrip("/"), key.strip()
    except Exception:
        pass
    return None, None

def supabase_request(method: str, endpoint: str, data: dict = None, params: str = "") -> tuple[bool, any]:
    """
    Makes a direct REST call to Supabase PostgREST API using standard library.
    Returns (success: bool, response_data: list|dict|str).
    """
    url, key = get_supabase_config()
    if not url or not key:
        return False, None
    try:
        ctx = ssl._create_unverified_context()
        full_url = f"{url}/rest/v1/{endpoint}"
        if params:
            full_url += f"?{params}"
        headers = {
            "apikey": key,
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
            "Prefer": "return=representation"
        }
        encoded_data = json.dumps(data).encode('utf-8') if data is not None else None
        req = urllib.request.Request(full_url, data=encoded_data, headers=headers, method=method)
        with urllib.request.urlopen(req, context=ctx, timeout=4) as resp:
            content = resp.read().decode('utf-8')
            return True, json.loads(content) if content else []
    except Exception as e:
        return False, str(e)

def is_supabase_active() -> bool:
    """Checks if Supabase credentials are present and tables are ready"""
    url, key = get_supabase_config()
    if not url or not key:
        return False
    ok, _ = supabase_request("GET", "users", params="select=id&limit=1")
    return bool(ok)

def process_google_drive_link(raw_link: str) -> tuple[str, str]:
    """
    Parses Google Drive sharing links into:
    1. Embeddable preview player link (https://drive.google.com/file/d/FILE_ID/preview)
    2. Direct file download link (https://drive.google.com/uc?export=download&id=FILE_ID)
    Also supports YouTube and standard URLs.
    """
    raw_link = raw_link.strip() if raw_link else ""
    if not raw_link:
        return "", ""

    drive_match = re.search(r'(?:drive\.google\.com\/(?:file\/d\/|open\?id=|uc\?id=))([a-zA-Z0-9_-]{20,})', raw_link)
    if drive_match:
        file_id = drive_match.group(1)
        embed_url = f"https://drive.google.com/file/d/{file_id}/preview"
        download_url = f"https://drive.google.com/uc?export=download&id={file_id}"
        return embed_url, download_url

    yt_match = re.search(r'(?:youtube\.com\/(?:watch\?v=|embed\/)|youtu\.be\/)([a-zA-Z0-9_-]{11})', raw_link)
    if yt_match:
        vid_id = yt_match.group(1)
        embed_url = f"https://www.youtube.com/embed/{vid_id}"
        return embed_url, raw_link

    folder_match = re.search(r'folders/([a-zA-Z0-9_-]+)', raw_link)
    if folder_match:
        f_id = folder_match.group(1)
        return f"https://drive.google.com/embeddedfolderview?id={f_id}#grid", raw_link

    return raw_link, raw_link

def upload_file_to_google_drive(file_obj, filename: str, folder_id: str = DEFAULT_DRIVE_FOLDER_ID) -> tuple[bool, str, str]:
    """
    Uploads a video directly to Google Drive folder using service account credentials if configured.
    Returns (success: bool, web_view_link: str, error_message: str).
    """
    try:
        from google.oauth2 import service_account
        from googleapiclient.discovery import build
        from googleapiclient.http import MediaIoBaseUpload

        sa_info = None
        if "gcp_service_account" in st.secrets:
            sa_info = dict(st.secrets["gcp_service_account"])
        elif "google_drive" in st.secrets and "service_account" in st.secrets["google_drive"]:
            sa_info = dict(st.secrets["google_drive"]["service_account"])
        elif "service_account" in st.secrets:
            sa_info = dict(st.secrets["service_account"])

        if not sa_info:
            return False, "", "Google Cloud Service Account credentials ('gcp_service_account') not found in st.secrets."

        creds = service_account.Credentials.from_service_account_info(
            sa_info,
            scopes=['https://www.googleapis.com/auth/drive']
        )
        service = build('drive', 'v3', credentials=creds)

        file_metadata = {
            'name': filename,
            'parents': [folder_id]
        }
        file_obj.seek(0)
        media = MediaIoBaseUpload(file_obj, mimetype='video/webm', resumable=True)
        uploaded = service.files().create(
            body=file_metadata,
            media_body=media,
            fields='id, webViewLink'
        ).execute()

        file_id = uploaded.get('id')
        web_link = uploaded.get('webViewLink') or f"https://drive.google.com/file/d/{file_id}/view?usp=sharing"

        try:
            service.permissions().create(
                fileId=file_id,
                body={'type': 'anyone', 'role': 'reader'}
            ).execute()
        except Exception:
            pass

        return True, web_link, ""
    except ImportError:
        return False, "", "The 'google-api-python-client' or 'google-auth' package is not installed."
    except Exception as e:
        return False, "", str(e)

def render_embedded_drive_folder(folder_id: str = DEFAULT_DRIVE_FOLDER_ID, folder_url: str = DEFAULT_DRIVE_FOLDER_URL, title: str = "Class Recordings Cloud Folder", key_suffix: str = "main"):
    """
    Renders an embedded, real-time Google Drive folder viewer inside Streamlit.
    Any video uploaded to this folder automatically appears here for all students & teacher.
    """
    st.markdown(f"""
    <div style="background: linear-gradient(135deg, #f0fdf4 0%, #eff6ff 100%); border: 1px solid #bbf7d0; border-radius: 12px; padding: 14px 18px; margin-bottom: 12px;">
        <div style="display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 8px;">
            <div>
                <h4 style="margin: 0; color: #166534; display: flex; align-items: center; gap: 8px;">
                    <span>📁</span> <span>{title}</span>
                    <span style="font-size: 0.72rem; background: #16a34a; color: white; padding: 2px 8px; border-radius: 9999px; font-weight: 700; letter-spacing: 0.5px;">LIVE AUTO-SYNC</span>
                </h4>
                <p style="margin: 4px 0 0 0; color: #374151; font-size: 0.88rem;">
                    Every lecture video dropped into this Google Drive folder updates automatically below in real time for all students.
                </p>
            </div>
        </div>
    </div>
    """, unsafe_allow_html=True)

    col_v1, col_v2 = st.columns([2.5, 1])
    with col_v1:
        view_mode = st.radio("Display Mode:", ["Grid View", "List View"], horizontal=True, key=f"drive_view_mode_{key_suffix}")
    with col_v2:
        st.link_button("↗️ Open Folder in Google Drive", folder_url, use_container_width=True)

    layout_suffix = "#grid" if view_mode == "Grid View" else "#list"
    embed_url = f"https://drive.google.com/embeddedfolderview?id={folder_id}{layout_suffix}"

    components.iframe(embed_url, height=450, scrolling=True)

def init_database():
    """Initializes SQLite schema and ensures columns exist"""
    conn = get_db()
    c = conn.cursor()

    # 1. Users
    c.execute("""
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE NOT NULL,
        password TEXT NOT NULL DEFAULT '',
        password_hash TEXT NOT NULL,
        role TEXT NOT NULL,
        full_name TEXT NOT NULL,
        is_active INTEGER DEFAULT 1,
        created_at TEXT NOT NULL
    )
    """)

    # Safe column migration for users table
    try:
        c.execute("PRAGMA table_info(users)")
        u_cols = [r[1] for r in c.fetchall()]
        if 'password' not in u_cols:
            c.execute("ALTER TABLE users ADD COLUMN password TEXT DEFAULT ''")
        conn.commit()
    except Exception:
        pass

    # 2. Live Session State
    c.execute("""
    CREATE TABLE IF NOT EXISTS class_session (
        id INTEGER PRIMARY KEY,
        is_live INTEGER DEFAULT 0,
        topic TEXT DEFAULT 'General Coaching Session',
        room_name TEXT DEFAULT 'SistersClass_Room101',
        server TEXT DEFAULT 'jitsi.riot.im',
        started_at TEXT,
        ended_at TEXT,
        teacher_notes TEXT DEFAULT '',
        host_teacher TEXT DEFAULT 'Lead Teacher'
    )
    """)

    # Safe automatic column migrations for class_session
    try:
        c.execute("PRAGMA table_info(class_session)")
        existing_cols = [r[1] for r in c.fetchall()]
        if 'server' not in existing_cols:
            c.execute("ALTER TABLE class_session ADD COLUMN server TEXT DEFAULT 'jitsi.riot.im'")
        if 'teacher_notes' not in existing_cols:
            c.execute("ALTER TABLE class_session ADD COLUMN teacher_notes TEXT DEFAULT ''")
        if 'host_teacher' not in existing_cols:
            c.execute("ALTER TABLE class_session ADD COLUMN host_teacher TEXT DEFAULT 'Lead Teacher'")
        conn.commit()
    except Exception:
        pass

    # Ensure compatibility view class_state exists
    try:
        c.execute("CREATE VIEW IF NOT EXISTS class_state AS SELECT * FROM class_session")
        conn.commit()
    except Exception:
        pass

    # Ensure row 1 exists
    try:
        c.execute("SELECT COUNT(*) as cnt FROM class_session WHERE id = 1")
        if c.fetchone()['cnt'] == 0:
            c.execute("""
            INSERT INTO class_session (id, is_live, topic, room_name, server, teacher_notes, host_teacher)
            VALUES (1, 0, 'Mathematics & Science Live Coaching', 'SistersLiveClass_MasterRoom', 'jitsi.riot.im', 'Welcome! Camera is OFF by default. Turn on mic when asked.', 'Lead Teacher')
            """)
            conn.commit()
        else:
            try:
                c.execute("UPDATE class_session SET server = 'jitsi.riot.im' WHERE server = 'meet.ffmuc.net' OR server IS NULL OR server = ''")
                conn.commit()
            except Exception:
                pass
    except Exception:
        pass


    # 3. Attendance
    c.execute("""
    CREATE TABLE IF NOT EXISTS attendance (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        student_username TEXT NOT NULL,
        student_name TEXT NOT NULL,
        room_name TEXT NOT NULL,
        topic TEXT,
        join_timestamp TEXT NOT NULL,
        date TEXT NOT NULL
    )
    """)

    # Safe column migration for attendance table
    try:
        c.execute("PRAGMA table_info(attendance)")
        att_cols = [r[1] for r in c.fetchall()]
        if 'student_username' not in att_cols:
            c.execute("ALTER TABLE attendance ADD COLUMN student_username TEXT DEFAULT ''")
        if 'student_name' not in att_cols:
            c.execute("ALTER TABLE attendance ADD COLUMN student_name TEXT DEFAULT ''")
        if 'room_name' not in att_cols:
            c.execute("ALTER TABLE attendance ADD COLUMN room_name TEXT DEFAULT ''")
        if 'topic' not in att_cols:
            c.execute("ALTER TABLE attendance ADD COLUMN topic TEXT DEFAULT ''")
        if 'join_timestamp' not in att_cols:
            c.execute("ALTER TABLE attendance ADD COLUMN join_timestamp TEXT DEFAULT ''")
        if 'date' not in att_cols:
            c.execute("ALTER TABLE attendance ADD COLUMN date TEXT DEFAULT ''")
        conn.commit()
    except Exception:
        pass

    # 4. Recordings
    c.execute("""
    CREATE TABLE IF NOT EXISTS recordings (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        title TEXT NOT NULL,
        subject TEXT NOT NULL,
        lecture_date TEXT NOT NULL,
        description TEXT,
        drive_link TEXT NOT NULL,
        embed_url TEXT NOT NULL,
        download_url TEXT NOT NULL,
        created_at TEXT NOT NULL
    )
    """)

    # 5. Announcements
    c.execute("""
    CREATE TABLE IF NOT EXISTS announcements (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        title TEXT NOT NULL,
        message TEXT NOT NULL,
        priority TEXT DEFAULT 'Normal',
        created_at TEXT NOT NULL
    )
    """)

    # 6. Doubts
    c.execute("""
    CREATE TABLE IF NOT EXISTS doubts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        student_username TEXT NOT NULL,
        student_name TEXT NOT NULL,
        question TEXT NOT NULL,
        subject TEXT NOT NULL,
        reply TEXT DEFAULT NULL,
        status TEXT DEFAULT 'Pending',
        created_at TEXT NOT NULL,
        replied_at TEXT DEFAULT NULL
    )
    """)

    # 7. Student Fees Table
    c.execute("""
    CREATE TABLE IF NOT EXISTS fees (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        student_username TEXT NOT NULL,
        student_name TEXT NOT NULL,
        month_title TEXT NOT NULL,
        amount TEXT NOT NULL,
        due_date TEXT NOT NULL,
        status TEXT DEFAULT 'Pending',
        paid_date TEXT DEFAULT '-',
        marked_by TEXT DEFAULT '-',
        note TEXT DEFAULT ''
    )
    """)

    # 8. Future Scheduled Classes Table
    c.execute("""
    CREATE TABLE IF NOT EXISTS scheduled_classes (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        topic TEXT NOT NULL,
        subject TEXT NOT NULL,
        teacher_name TEXT NOT NULL,
        scheduled_date TEXT NOT NULL,
        scheduled_time TEXT NOT NULL,
        room_name TEXT NOT NULL,
        notes TEXT DEFAULT '',
        status TEXT DEFAULT 'Scheduled',
        allow_waiting_room INTEGER DEFAULT 1
    )
    """)
    try:
        c.execute("ALTER TABLE scheduled_classes ADD COLUMN allow_waiting_room INTEGER DEFAULT 1")
    except Exception:
        pass

    # ---------------------------------------------
    # 9. ENFORCE 3-TIER DEFAULT ACCOUNTS
    # ---------------------------------------------
    now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # (a) Enforce Super Admin (Username: admin, Password: Amir@7861)
    admin_pwd = "Amir@7861"
    admin_hash = hash_password(admin_pwd)
    c.execute("SELECT id FROM users WHERE username = 'admin'")
    if c.fetchone():
        c.execute("""
        UPDATE users 
        SET password = ?, password_hash = ?, role = 'admin', full_name = 'Super Admin', is_active = 1
        WHERE username = 'admin'
        """, (admin_pwd, admin_hash))
    else:
        c.execute("""
        INSERT INTO users (username, password, password_hash, role, full_name, is_active, created_at)
        VALUES ('admin', ?, ?, 'admin', 'Super Admin', 1, ?)
        """, (admin_pwd, admin_hash, now_str))

    # (b) Pre-seed Default Teacher Accounts (INSERT OR IGNORE preserves custom passwords)
    t1_hash = hash_password("teacher123")
    t2_hash = hash_password("teacher456")

    c.execute("""
    INSERT OR IGNORE INTO users (username, password, password_hash, role, full_name, is_active, created_at)
    VALUES ('teacher', 'teacher123', ?, 'teacher', 'Lead Teacher', 1, ?)
    """, (t1_hash, now_str))

    c.execute("""
    INSERT OR IGNORE INTO users (username, password, password_hash, role, full_name, is_active, created_at)
    VALUES ('teacher1', 'teacher123', ?, 'teacher', 'Teacher 1', 1, ?)
    """, (t1_hash, now_str))

    c.execute("""
    INSERT OR IGNORE INTO users (username, password, password_hash, role, full_name, is_active, created_at)
    VALUES ('teacher2', 'teacher456', ?, 'teacher', 'Teacher 2', 1, ?)
    """, (t2_hash, now_str))

    c.execute("UPDATE users SET password = 'teacher123' WHERE username IN ('teacher', 'teacher1') AND (password IS NULL OR password = '')")
    c.execute("UPDATE users SET password = 'teacher456' WHERE username = 'teacher2' AND (password IS NULL OR password = '')")

    # (c) Pre-seed 10 Default Student Accounts (INSERT OR IGNORE preserves custom passwords)
    st_pwd_hash = hash_password("pass123")
    for i in range(1, 11):
        u_name = f"student{i}"
        c.execute("""
        INSERT OR IGNORE INTO users (username, password, password_hash, role, full_name, is_active, created_at)
        VALUES (?, 'pass123', ?, 'student', ?, 1, ?)
        """, (u_name, st_pwd_hash, f"Student {i}", now_str))
        c.execute("UPDATE users SET password = 'pass123' WHERE username = ? AND (password IS NULL OR password = '')", (u_name,))

    # Seed initial announcement if empty
    c.execute("SELECT COUNT(*) as cnt FROM announcements")
    if c.fetchone()['cnt'] == 0:
        c.execute("""
        INSERT INTO announcements (title, message, priority, created_at)
        VALUES ('Welcome to Sister''s Live Academy!', 
                'Live sessions are held Monday to Saturday at 6:00 PM. Camera is OFF by default.', 
                'Important', ?)
        """, (now_str,))

    # Seed initial recording if empty
    c.execute("SELECT COUNT(*) as cnt FROM recordings")
    if c.fetchone()['cnt'] == 0:
        demo_drive_url = "https://drive.google.com/file/d/1BxiMVs0XRA5nFMdKvBdBZjgmUUqptlbs/view?usp=sharing"
        embed_url, dl_url = process_google_drive_link(demo_drive_url)
        c.execute("""
        INSERT INTO recordings (title, subject, lecture_date, description, drive_link, embed_url, download_url, created_at)
        VALUES ('Foundation & Orientation Class 01', 'Orientation', '2026-10-25', 
                'Complete syllabus blueprint, exam strategy, and doubt-clearing structure.', 
                ?, ?, ?, ?)
        """, (demo_drive_url, embed_url, dl_url, now_str))

    # Seed initial demo fees if empty
    c.execute("SELECT COUNT(*) as cnt FROM fees")
    if c.fetchone()['cnt'] == 0:
        c.execute("""
        INSERT INTO fees (student_username, student_name, month_title, amount, due_date, status, paid_date, marked_by, note)
        VALUES 
            ('student1', 'Student 1', 'October 2026 Tuition', '1500', '2026-10-10', 'Paid', '2026-10-05', 'Lead Teacher', 'Paid via UPI ref #98721'),
            ('student2', 'Student 2', 'October 2026 Tuition', '1500', '2026-10-10', 'Pending', '-', '-', 'Dues reminder sent'),
            ('student3', 'Student 3', 'October 2026 Tuition', '1500', '2026-10-10', 'Paid', '2026-10-08', 'Teacher 1', 'Paid in Cash')
        """)

    # Seed initial scheduled class if empty
    c.execute("SELECT COUNT(*) as cnt FROM scheduled_classes")
    if c.fetchone()['cnt'] == 0:
        tomorrow_str = str(datetime.date.today() + datetime.timedelta(days=1))
        c.execute("""
        INSERT INTO scheduled_classes (topic, subject, teacher_name, scheduled_date, scheduled_time, room_name, notes, status, allow_waiting_room)
        VALUES 
            ('Trigonometry & Calculus Deep Dive', 'Mathematics', 'Teacher 1', ?, '18:00', 'SistersLiveClass_MasterRoom', 'Bring graph books. Waiting lounge is open for early discussion!', 'Scheduled', 1),
            ('Electromagnetism & Circuit Laws', 'Physics', 'Teacher 2', ?, '17:30', 'SistersLiveClass_MasterRoom', 'Revise chapter 4 formulas before entering.', 'Scheduled', 1)
        """, (tomorrow_str, str(datetime.date.today() + datetime.timedelta(days=2))))

    conn.commit()
    conn.close()

# Compatibility alias
init_db = init_database

# Run DB initialization once
init_database()


# ==========================================
# 4. CUSTOM CSS (MODERN EDTECH STYLING)
# ==========================================
st.markdown("""
<style>
    @import url('https://fonts.googleapis.com/css2?family=Outfit:wght@400;500;600;700&family=Inter:wght@400;500;600&display=swap');

    html, body, [class*="css"] {
        font-family: 'Outfit', 'Inter', -apple-system, BlinkMacSystemFont, sans-serif;
    }

    .block-container {
        padding-top: 1.5rem;
        padding-bottom: 2.5rem;
        max-width: 96% !important;
    }

    .hero-banner {
        background: linear-gradient(135deg, #4338ca 0%, #6366f1 50%, #a855f7 100%);
        padding: 22px 28px;
        border-radius: 14px;
        color: white;
        margin-bottom: 20px;
        box-shadow: 0 8px 24px -4px rgba(79, 70, 229, 0.25);
    }
    .hero-banner h1 {
        color: #ffffff !important;
        font-size: 2rem;
        font-weight: 700;
        margin-bottom: 4px;
    }
    .hero-banner p {
        color: rgba(255, 255, 255, 0.9);
        font-size: 1rem;
        margin-bottom: 0;
    }

    .live-badge {
        display: inline-flex;
        align-items: center;
        gap: 8px;
        background: #fee2e2;
        color: #b91c1c;
        border: 1px solid #f87171;
        padding: 6px 16px;
        border-radius: 9999px;
        font-weight: 700;
        font-size: 0.95rem;
    }
    .live-dot {
        width: 10px;
        height: 10px;
        background-color: #ef4444;
        border-radius: 50%;
        animation: pulse 1.4s infinite;
    }
    @keyframes pulse {
        0% { transform: scale(0.9); opacity: 1; }
        50% { transform: scale(1.2); opacity: 0.5; }
        100% { transform: scale(0.9); opacity: 1; }
    }

    .offline-badge {
        display: inline-flex;
        align-items: center;
        gap: 8px;
        background: #f1f5f9;
        color: #475569;
        border: 1px solid #cbd5e1;
        padding: 6px 16px;
        border-radius: 9999px;
        font-weight: 600;
        font-size: 0.95rem;
    }

    .glass-card {
        background: #ffffff;
        border-radius: 12px;
        padding: 18px 20px;
        border: 1px solid #e2e8f0;
        box-shadow: 0 4px 12px rgba(0, 0, 0, 0.04);
        margin-bottom: 16px;
    }

    .notice-card {
        border-left: 5px solid #6366f1;
        background: #f8fafc;
        padding: 14px 18px;
        border-radius: 8px 12px 12px 8px;
        margin-bottom: 12px;
    }
    .notice-important {
        border-left: 5px solid #ef4444;
        background: #fef2f2;
    }
    .notice-exam {
        border-left: 5px solid #f59e0b;
        background: #fffbeb;
    }
    .notice-holiday {
        border-left: 5px solid #10b981;
        background: #ecfdf5;
    }

    div.stButton > button:first-child {
        border-radius: 8px;
        font-weight: 600;
        transition: all 0.2s;
    }
</style>
""", unsafe_allow_html=True)


# ==========================================
# 5. JITSI MEET EXTERNAL API & IN-APP FULLSCREEN CLASSROOM
# ==========================================
def build_jitsi_url(server: str, room_name: str, display_name: str = "", is_teacher: bool = False) -> str:
    """Helper to construct direct Jitsi URL if needed anywhere"""
    safe_name = urllib.parse.quote(display_name) if display_name else "User"
    audio_param = "false" if is_teacher else "true"
    server_clean = server.replace("https://", "").replace("http://", "").strip("/") if server else "jitsi.riot.im"
    return (
        f"https://{server_clean}/{room_name}"
        f"#userInfo.displayName=\"{safe_name}\""
        f"&config.prejoinPageEnabled=false"
        f"&config.startWithVideoMuted=true"
        f"&config.startWithAudioMuted={audio_param}"
        f"&config.disableDeepLinking=true"
    )

def render_jitsi_classroom(domain: str, room_name: str, display_name: str, is_teacher: bool):
    """
    Renders Jitsi Meet using the official JitsiMeetExternalAPI (external_api.js) inside st.components.v1.html.
    Features:
    - Zero external redirects (no external tab buttons).
    - ⛶ In-app Fullscreen Toggle button via element.requestFullscreen().
    - ⏺️ HTML5 1-click Screen + Voice Recorder with live timer and direct .webm download for teacher.
    - Video camera OFF by default (startWithVideoMuted=true).
    - Pre-join check screen skipped (prejoinPageEnabled=false).
    - Proper permissions (camera, microphone, display-capture, fullscreen, autoplay).
    """
    domain_clean = domain.replace("https://", "").replace("http://", "").strip("/")
    if not domain_clean or "ffmuc.net" in domain_clean:
        domain_clean = "jitsi.riot.im"

    if is_teacher:
        tb_buttons = json.dumps([
            'microphone', 'camera', 'desktop', 'chat', 'raisehand',
            'videoquality', 'tileview', 'mute-everyone', 'security', 'whiteboard', 'hangup'
        ])
    else:
        tb_buttons = json.dumps([
            'microphone', 'camera', 'chat', 'raisehand', 'tileview', 'fullscreen', 'hangup'
        ])


    topbar_right = """
        <div style="display:flex; align-items:center; gap:8px;">
            <span id="rec-dot" style="width:10px; height:10px; border-radius:50%; background:#64748b; display:inline-block;"></span>
            <span id="rec-timer" style="font-family:monospace; color:#38bdf8; font-weight:bold; font-size:0.95rem;">00:00:00</span>
            <button id="start-rec-btn" onclick="startRecording()" style="background:#ef4444; color:white; border:none; padding:6px 14px; border-radius:6px; font-size:0.85rem; font-weight:600; cursor:pointer;">⏺️ Record Screen & Voice</button>
            <button id="stop-rec-btn" onclick="stopRecording()" style="display:none; background:#10b981; color:white; border:none; padding:6px 14px; border-radius:6px; font-size:0.85rem; font-weight:600; cursor:pointer;">💾 Stop & Download Video</button>
        </div>
    """ if is_teacher else """
        <span style="color:#94a3b8; font-size:0.85rem; font-weight:500;">🎥 Live Audio/Video Stream Active</span>
    """

    recorder_script = """
        let mediaRecorder;
        let recordedChunks = [];
        let timerInterval;
        let recSeconds = 0;

        function formatTimer(s) {
            const h = String(Math.floor(s / 3600)).padStart(2, '0');
            const m = String(Math.floor((s % 3600) / 60)).padStart(2, '0');
            const sc = String(s % 60).padStart(2, '0');
            return `${h}:${m}:${sc}`;
        }

        async function startRecording() {
            try {
                const stream = await navigator.mediaDevices.getDisplayMedia({
                    video: { cursor: "always" },
                    audio: true
                });

                recordedChunks = [];
                mediaRecorder = new MediaRecorder(stream, { mimeType: 'video/webm' });

                mediaRecorder.ondataavailable = (e) => {
                    if (e.data.size > 0) recordedChunks.push(e.data);
                };

                mediaRecorder.onstop = () => {
                    clearInterval(timerInterval);
                    document.getElementById('rec-timer').innerText = "00:00:00";
                    document.getElementById('rec-dot').style.background = "#64748b";
                    document.getElementById('rec-dot').style.boxShadow = "none";
                    document.getElementById('start-rec-btn').style.display = "inline-block";
                    document.getElementById('stop-rec-btn').style.display = "none";

                    const blob = new Blob(recordedChunks, { type: 'video/webm' });
                    const url = URL.createObjectURL(blob);
                    const a = document.createElement('a');
                    a.style.display = 'none';
                    a.href = url;
                    const d = new Date().toISOString().slice(0, 19).replace(/[:T]/g, '-');
                    a.download = `Sisters_Academy_Class_${d}.webm`;
                    document.body.appendChild(a);
                    a.click();
                    setTimeout(() => {
                        document.body.removeChild(a);
                        window.URL.revokeObjectURL(url);
                    }, 100);
                };

                stream.getVideoTracks()[0].onended = () => {
                    if (mediaRecorder.state !== 'inactive') mediaRecorder.stop();
                };

                mediaRecorder.start(1000);
                document.getElementById('start-rec-btn').style.display = "none";
                document.getElementById('stop-rec-btn').style.display = "inline-block";
                document.getElementById('rec-dot').style.background = "#ef4444";
                document.getElementById('rec-dot').style.boxShadow = "0 0 10px #ef4444";

                recSeconds = 0;
                timerInterval = setInterval(() => {
                    recSeconds++;
                    document.getElementById('rec-timer').innerText = formatTimer(recSeconds);
                }, 1000);

            } catch (err) {
                alert("Recording request cancelled or permission not granted: " + err.message);
            }
        }

        function stopRecording() {
            if (mediaRecorder && mediaRecorder.state !== 'inactive') {
                mediaRecorder.stop();
            }
        }
    """ if is_teacher else ""

    html_code = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="utf-8">
        <script src="https://{domain_clean}/external_api.js"></script>
        <style>
            * {{ box-sizing: border-box; }}
            body, html {{
                margin: 0;
                padding: 0;
                width: 100%;
                height: 100%;
                background: #0f172a;
                font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
                overflow: hidden;
            }}
            #classroom-wrapper {{
                width: 100%;
                height: 100%;
                display: flex;
                flex-direction: column;
                background: #0f172a;
                border-radius: 12px;
                overflow: hidden;
                border: 1px solid #334155;
            }}
            .classroom-topbar {{
                background: #1e293b;
                padding: 10px 16px;
                display: flex;
                justify-content: space-between;
                align-items: center;
                border-bottom: 1px solid #334155;
            }}
            .fs-btn {{
                background: #334155;
                color: #f8fafc;
                border: 1px solid #475569;
                padding: 6px 14px;
                border-radius: 6px;
                font-size: 0.85rem;
                font-weight: 600;
                cursor: pointer;
                transition: 0.2s;
            }}
            .fs-btn:hover {{ background: #475569; }}
            #jitsi-container {{
                flex: 1;
                width: 100%;
                height: 620px;
                background: #111827;
            }}
            #jitsi-container iframe {{
                width: 100% !important;
                height: 100% !important;
                border: none !important;
            }}
        </style>
    </head>
    <body>
        <div id="classroom-wrapper">
            <div class="classroom-topbar">
                <button class="fs-btn" onclick="toggleFullScreen()">⛶ Toggle Full Screen (In-App)</button>
                {topbar_right}
            </div>
            <div id="jitsi-container"></div>
        </div>

        <script>
            function toggleFullScreen() {{
                const el = document.getElementById('classroom-wrapper');
                if (!document.fullscreenElement && !document.webkitFullscreenElement) {{
                    if (el.requestFullscreen) {{
                        el.requestFullscreen();
                    }} else if (el.webkitRequestFullscreen) {{
                        el.webkitRequestFullscreen();
                    }}
                }} else {{
                    if (document.exitFullscreen) {{
                        document.exitFullscreen();
                    }} else if (document.webkitExitFullscreen) {{
                        document.webkitExitFullscreen();
                    }}
                }}
            }}

            {recorder_script}

            window.onload = function() {{
                try {{
                    const domain = "{domain_clean}";
                    const options = {{
                        roomName: "{room_name}",
                        width: "100%",
                        height: "100%",
                        parentNode: document.querySelector('#jitsi-container'),
                        userInfo: {{
                            displayName: "{display_name}"
                        }},
                        configOverwrite: {{
                            prejoinPageEnabled: false,
                            startWithVideoMuted: true,
                            startWithAudioMuted: {'false' if is_teacher else 'true'},
                            disableDeepLinking: true,
                            toolbarButtons: {tb_buttons}
                        }},
                        interfaceConfigOverwrite: {{
                            SHOW_JITSI_WATERMARK: false,
                            SHOW_WATERMARK_FOR_GUESTS: false,
                            TOOLBAR_ALWAYS_VISIBLE: true
                        }}
                    }};
                    const api = new JitsiMeetExternalAPI(domain, options);
                    
                    // Ensure iframe permissions are set
                    setTimeout(() => {{
                        const iframe = document.querySelector('#jitsi-container iframe');
                        if (iframe) {{
                            iframe.setAttribute('allow', 'camera; microphone; display-capture; fullscreen; autoplay; clipboard-write');
                        }}
                    }}, 400);
                }} catch (e) {{
                    console.error("Jitsi init error:", e);
                    document.getElementById('jitsi-container').innerHTML = 
                        '<div style="color:#ef4444; padding:40px; text-align:center;">Failed to connect to video room. Please change server in sidebar.</div>';
                }}
            }};
        </script>
    </body>
    </html>
    """
    components.html(html_code, height=680, scrolling=False)



# ==========================================
# 6. AUTHENTICATION & LOGIN SCREEN
# ==========================================
def handle_login(username_val: str, password_val: str):
    if not username_val or not password_val:
        st.error("Please enter both username and password.")
        return

    un = username_val.strip().lower()
    pwd = password_val.strip()
    pwd_hash = hash_password(pwd)
    user = None

    # Check Supabase first if active
    if is_supabase_active():
        ok, rows = supabase_request("GET", "users", params=f"username=eq.{un}&select=*")
        if ok and rows:
            for r in rows:
                if r.get('password') == pwd or r.get('password_hash') == pwd_hash:
                    user = r
                    break

    # Fallback to local SQLite
    if not user:
        conn = get_db_connection()
        try:
            c = conn.cursor()
            c.execute("SELECT * FROM users WHERE username = ?", (un,))
            raw_u = c.fetchone()
            if raw_u:
                u_dict = dict(raw_u)
                if u_dict.get('password') == pwd or u_dict.get('password_hash') == pwd_hash:
                    user = u_dict
        finally:
            conn.close()

    if user:
        if user.get('is_active', 1) == 0:
            st.error("⛔ Your account has been suspended or blocked. Please contact the administrator.")
        else:
            st.session_state.logged_in = True
            st.session_state.username = user['username']
            st.session_state.role = user['role']
            st.session_state.name = user['full_name']
            st.success(f"Signed in as {user['full_name']} ({user['role'].capitalize()})!")
            st.rerun()
    else:
        st.error("Invalid username or password. Please verify your credentials.")

def render_login_screen():
    st.markdown("""
    <div class="hero-banner" style="text-align: center; margin-top: 10px;">
        <h1>🎓 Sister's Live Academy</h1>
        <p>Online Live Coaching, Screen Sharing Studio & Recorded Notes Hub</p>
    </div>
    """, unsafe_allow_html=True)

    col1, col2, col3 = st.columns([1, 1.8, 1])
    with col2:
        st.markdown("""
        <div class="glass-card">
            <h3 style="margin-top:0; color:#1e293b;">🔐 Portal Sign In</h3>
            <p style="color:#64748b; font-size:0.9rem; margin-bottom: 12px;">Sign in with your Teacher or Student credentials to proceed.</p>
        </div>
        """, unsafe_allow_html=True)

        with st.form("login_form", clear_on_submit=False):
            u_input = st.text_input("Username", placeholder="e.g. teacher1 or student1").strip().lower()
            p_input = st.text_input("Password", type="password", placeholder="Enter your password")
            submit = st.form_submit_button("Sign In to Portal", use_container_width=True, type="primary")

            if submit:
                handle_login(u_input, p_input)

        with st.expander("🔑 Default Demo Accounts (Click to view)"):
            st.markdown("""
            - **Teacher Accounts:**
              - `teacher1` | Password: `teacher123` (Teacher 1)
              - `teacher2` | Password: `teacher456` (Teacher 2)
              - `teacher` | Password: `teacher123` (Lead Teacher)
            - **Student Accounts:** Usernames: `student1` to `student10` | Password: `pass123`
            """)


# ==========================================
# 6.5. STUDENT FEES MANAGEMENT & PORTAL
# ==========================================
def render_fees_management(is_admin: bool = True):
    st.subheader("💳 Student Fees & Invoices Management")
    st.caption("Manage student monthly fees, issue tuition invoices, record payments, and audit fee ledgers.")

    # 1. Fetch all fees
    fees_list = []
    if is_supabase_active():
        ok, rows = supabase_request("GET", "fees", params="order=id.desc&select=*")
        if ok and rows:
            fees_list = rows

    if not fees_list:
        with get_db_connection() as conn_r:
            c_r = conn_r.cursor()
            c_r.execute("SELECT * FROM fees ORDER BY id DESC")
            fees_list = [dict(r) for r in c_r.fetchall()]

    # Fetch all students for dropdown
    students_list = []
    with get_db_connection() as conn_s:
        c_s = conn_s.cursor()
        c_s.execute("SELECT username, full_name FROM users WHERE role = 'student' ORDER BY full_name ASC")
        students_list = [dict(r) for r in c_s.fetchall()]

    # Summary Metrics
    total_invoices = len(fees_list)
    paid_invoices = [f for f in fees_list if f.get('status') == 'Paid']
    pending_invoices = [f for f in fees_list if f.get('status') == 'Pending']

    total_collected = sum(int(str(f['amount']).replace(',', '')) for f in paid_invoices if str(f.get('amount', '')).replace(',', '').isdigit())
    total_outstanding = sum(int(str(f['amount']).replace(',', '')) for f in pending_invoices if str(f.get('amount', '')).replace(',', '').isdigit())

    col_m1, col_m2, col_m3, col_m4 = st.columns(4)
    with col_m1:
        st.metric("Total Invoices", total_invoices)
    with col_m2:
        st.metric("Total Collected", f"₹{total_collected:,}")
    with col_m3:
        st.metric("Pending Dues", f"₹{total_outstanding:,}")
    with col_m4:
        st.metric("Pending Invoices", len(pending_invoices))

    st.markdown("---")

    col_f1, col_f2 = st.columns([1.3, 1.7])

    with col_f1:
        st.markdown("### ➕ Issue New Fee Invoice")
        with st.form(f"issue_fee_form_{'adm' if is_admin else 'tch'}", clear_on_submit=True):
            target_type = st.radio("Issue To", ["Single Student", "All Registered Students (Batch)"], horizontal=True)

            sel_student = None
            if target_type == "Single Student":
                if students_list:
                    student_opts = {f"{s['full_name']} (@{s['username']})": s for s in students_list}
                    chosen_lbl = st.selectbox("Select Student", list(student_opts.keys()))
                    sel_student = student_opts[chosen_lbl]
                else:
                    st.warning("No students registered yet.")

            default_month = datetime.date.today().strftime("%B %Y") + " Monthly Tuition"
            f_month = st.text_input("Month / Invoice Title", value=default_month, placeholder="e.g. November 2026 Tuition")
            f_amt = st.text_input("Fee Amount (₹)", value="1500", placeholder="e.g. 1500")
            f_due = st.date_input("Due Date", value=datetime.date.today() + datetime.timedelta(days=10))
            f_note = st.text_input("Instructions / Payment Note", value="Pay via UPI or Cash to Academy Office", placeholder="e.g. UPI to academy@upi")

            btn_issue = st.form_submit_button("🚀 Issue Fee Invoice", type="primary", use_container_width=True)

            if btn_issue:
                if not f_month.strip() or not f_amt.strip():
                    st.error("Month/Title and Fee Amount are required.")
                elif not f_amt.strip().replace(",", "").isdigit():
                    st.error("Fee Amount must be a valid number.")
                else:
                    clean_amt = f_amt.strip().replace(",", "")
                    due_str = str(f_due)
                    targets = []
                    if target_type == "Single Student":
                        if sel_student:
                            targets.append(sel_student)
                    else:
                        targets = students_list

                    if not targets:
                        st.error("No target student found to issue invoice.")
                    else:
                        try:
                            with get_db_connection() as conn_w:
                                for t in targets:
                                    conn_w.execute("""
                                    INSERT INTO fees (student_username, student_name, month_title, amount, due_date, status, paid_date, marked_by, note)
                                    VALUES (?, ?, ?, ?, ?, 'Pending', '-', '-', ?)
                                    """, (t['username'], t['full_name'], f_month.strip(), clean_amt, due_str, f_note.strip()))
                                conn_w.commit()

                            if is_supabase_active():
                                for t in targets:
                                    supabase_request("POST", "fees", {
                                        "student_username": t['username'],
                                        "student_name": t['full_name'],
                                        "month_title": f_month.strip(),
                                        "amount": clean_amt,
                                        "due_date": due_str,
                                        "status": "Pending",
                                        "paid_date": "-",
                                        "marked_by": "-",
                                        "note": f_note.strip()
                                    })

                            st.success(f"Successfully issued {len(targets)} fee invoice(s) for '{f_month.strip()}' (₹{clean_amt})!")
                            st.rerun()
                        except Exception as e:
                            st.error(f"Error issuing fee invoices: {e}")

    with col_f2:
        st.markdown("### ✍️ Collect Payment / Update Status")
        if not fees_list:
            st.info("No fee invoices created yet.")
        else:
            fee_opts = {
                f"#{f['id']} | {f['student_name']} (@{f['student_username']}) - {f['month_title']} (₹{f['amount']}) [{f.get('status','Pending')}]": f 
                for f in fees_list
            }
            sel_fee_lbl = st.selectbox("Select Invoice to Update", list(fee_opts.keys()), key=f"fee_up_sel_{'adm' if is_admin else 'tch'}")
            target_fee = fee_opts[sel_fee_lbl]

            st.markdown(f"""
            <div style="background:#f8fafc; border:1px solid #e2e8f0; border-radius:10px; padding:12px; margin-bottom:12px;">
                <b>Student:</b> {target_fee['student_name']} (<code>@{target_fee['student_username']}</code>)<br>
                <b>Title:</b> {target_fee['month_title']} &nbsp;|&nbsp; <b>Amount:</b> <span style="color:#059669; font-weight:700;">₹{target_fee['amount']}</span><br>
                <b>Due Date:</b> {target_fee['due_date']} &nbsp;|&nbsp; <b>Status:</b> {'🟢 Paid' if target_fee['status'] == 'Paid' else '🔴 Pending Dues'}<br>
                <b>Payment Date:</b> {target_fee.get('paid_date', '-')} &nbsp;|&nbsp; <b>Marked By:</b> {target_fee.get('marked_by', '-')}
            </div>
            """, unsafe_allow_html=True)

            c_act1, c_act2, c_act3 = st.columns([1, 1, 1])

            with c_act1:
                with st.form(f"mark_paid_form_{target_fee['id']}_{'adm' if is_admin else 'tch'}"):
                    if st.form_submit_button("✅ Mark as PAID", type="primary", use_container_width=True):
                        today_str = str(datetime.date.today())
                        marker = st.session_state.name or ("Admin" if is_admin else "Teacher")
                        try:
                            with get_db_connection() as conn_w:
                                conn_w.execute("""
                                UPDATE fees SET status = 'Paid', paid_date = ?, marked_by = ? WHERE id = ?
                                """, (today_str, marker, target_fee['id']))
                                conn_w.commit()

                            if is_supabase_active():
                                supabase_request("PATCH", "fees", {
                                    "status": "Paid", "paid_date": today_str, "marked_by": marker
                                }, params=f"id=eq.{target_fee['id']}")

                            st.success(f"Invoice #{target_fee['id']} marked as PAID by {marker}!")
                            st.rerun()
                        except Exception as e:
                            st.error(f"Error marking as paid: {e}")

            with c_act2:
                with st.form(f"mark_pending_form_{target_fee['id']}_{'adm' if is_admin else 'tch'}"):
                    if st.form_submit_button("↩️ Mark as UNPAID", use_container_width=True):
                        try:
                            with get_db_connection() as conn_w:
                                conn_w.execute("""
                                UPDATE fees SET status = 'Pending', paid_date = '-', marked_by = '-' WHERE id = ?
                                """, (target_fee['id'],))
                                conn_w.commit()

                            if is_supabase_active():
                                supabase_request("PATCH", "fees", {
                                    "status": "Pending", "paid_date": "-", "marked_by": "-"
                                }, params=f"id=eq.{target_fee['id']}")

                            st.warning(f"Invoice #{target_fee['id']} reset to PENDING.")
                            st.rerun()
                        except Exception as e:
                            st.error(f"Error updating fee: {e}")

            with c_act3:
                with st.form(f"delete_fee_form_{target_fee['id']}_{'adm' if is_admin else 'tch'}"):
                    if st.form_submit_button("🗑️ Delete Invoice", use_container_width=True):
                        try:
                            with get_db_connection() as conn_w:
                                conn_w.execute("DELETE FROM fees WHERE id = ?", (target_fee['id'],))
                                conn_w.commit()

                            if is_supabase_active():
                                supabase_request("DELETE", "fees", params=f"id=eq.{target_fee['id']}")

                            st.success(f"Invoice #{target_fee['id']} removed.")
                            st.rerun()
                        except Exception as e:
                            st.error(f"Error deleting fee: {e}")

    st.markdown("---")

    # Invoices Ledger & Filter
    st.markdown("### 📋 Student Fees Master Ledger")
    col_flt1, col_flt2, col_flt3 = st.columns([1, 1, 1])
    with col_flt1:
        st_filter = st.selectbox("Filter by Student", ["All Students"] + [f"{s['full_name']} (@{s['username']})" for s in students_list], key=f"flt_st_{'adm' if is_admin else 'tch'}")
    with col_flt2:
        status_filter = st.selectbox("Filter by Status", ["All Invoices", "Pending Only", "Paid Only"], key=f"flt_status_{'adm' if is_admin else 'tch'}")
    with col_flt3:
        search_kw = st.text_input("Search Ledger", placeholder="e.g. October, 1500, Cash...", key=f"flt_srch_{'adm' if is_admin else 'tch'}").strip().lower()

    filtered_fees = fees_list
    if st_filter != "All Students":
        u_extracted = st_filter.split("(@")[-1].replace(")", "")
        filtered_fees = [f for f in filtered_fees if f['student_username'] == u_extracted]

    if status_filter == "Pending Only":
        filtered_fees = [f for f in filtered_fees if f.get('status') == 'Pending']
    elif status_filter == "Paid Only":
        filtered_fees = [f for f in filtered_fees if f.get('status') == 'Paid']

    if search_kw:
        filtered_fees = [
            f for f in filtered_fees
            if search_kw in f['student_name'].lower() or search_kw in f['student_username'].lower()
            or search_kw in f['month_title'].lower() or search_kw in str(f.get('amount', '')).lower()
            or search_kw in str(f.get('note', '')).lower()
        ]

    table_data = []
    for f in filtered_fees:
        st_badge = "🟢 Paid" if f.get('status') == 'Paid' else "🔴 Pending"
        table_data.append({
            "Invoice #": f['id'],
            "Student Name": f['student_name'],
            "Username": f['student_username'],
            "Month / Title": f['month_title'],
            "Amount": f"₹{f['amount']}",
            "Due Date": f['due_date'],
            "Status": st_badge,
            "Paid Date": f.get('paid_date', '-'),
            "Marked By": f.get('marked_by', '-'),
            "Note": f.get('note', '')
        })

    if not table_data:
        st.info("No fee invoices match the selected filter.")
    else:
        st.dataframe(table_data, use_container_width=True, hide_index=True)

        # Export CSV
        csv_out = io.StringIO()
        csv_writer = csv.DictWriter(csv_out, fieldnames=[
            "Invoice #", "Student Name", "Username", "Month / Title", "Amount", "Due Date", "Status", "Paid Date", "Marked By", "Note"
        ])
        csv_writer.writeheader()
        csv_writer.writerows(table_data)

        st.download_button(
            label="📥 Export Fee Ledger (CSV)",
            data=csv_out.getvalue(),
            file_name=f"Sisters_Academy_Fees_{datetime.date.today()}.csv",
            mime="text/csv",
            type="primary",
            key=f"dl_fees_csv_{'adm' if is_admin else 'tch'}"
        )


def render_student_fees_portal():
    st.subheader("💳 My Tuition Fee & Receipt Portal")
    st.caption("Review your monthly fee dues, payment history, payment instructions, and official receipts.")

    # 1. Fetch fees for this student
    my_fees = []
    if is_supabase_active():
        ok, rows = supabase_request("GET", "fees", params=f"student_username=eq.{st.session_state.username}&order=id.desc&select=*")
        if ok and rows:
            my_fees = rows

    if not my_fees:
        with get_db_connection() as conn_r:
            c_r = conn_r.cursor()
            c_r.execute("SELECT * FROM fees WHERE student_username = ? ORDER BY id DESC", (st.session_state.username,))
            my_fees = [dict(r) for r in c_r.fetchall()]

    # Summary metrics
    paid_items = [f for f in my_fees if f.get('status') == 'Paid']
    pending_items = [f for f in my_fees if f.get('status') == 'Pending']
    total_paid = sum(int(str(f['amount']).replace(',', '')) for f in paid_items if str(f.get('amount', '')).replace(',', '').isdigit())
    total_due = sum(int(str(f['amount']).replace(',', '')) for f in pending_items if str(f.get('amount', '')).replace(',', '').isdigit())

    col_s1, col_s2, col_s3 = st.columns(3)
    with col_s1:
        st.metric("Total Invoices", len(my_fees))
    with col_s2:
        st.metric("Total Paid", f"₹{total_paid:,}")
    with col_s3:
        st.metric("Pending Dues", f"₹{total_due:,}")

    st.markdown("---")

    col_p1, col_p2 = st.columns([1.8, 1.2])

    with col_p1:
        st.markdown("### 📋 Fee Invoices & Payment Receipts")
        if not my_fees:
            st.info("No fee invoices issued for your account yet.")
        else:
            for f in my_fees:
                is_p = f.get('status') == 'Paid'
                card_border = "#10b981" if is_p else "#ef4444"
                card_bg = "#f0fdf4" if is_p else "#fff1f2"
                status_tag = '<span style="background:#10b981; color:white; padding:3px 10px; border-radius:12px; font-weight:700; font-size:0.8rem;">PAID</span>' if is_p else '<span style="background:#ef4444; color:white; padding:3px 10px; border-radius:12px; font-weight:700; font-size:0.8rem;">DUE PENDING</span>'

                st.markdown(f"""
                <div style="background:{card_bg}; border:1px solid {card_border}; border-radius:12px; padding:16px; margin-bottom:12px;">
                    <div style="display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:8px;">
                        <div>
                            <h4 style="margin:0; color:#1e293b;">{f['month_title']}</h4>
                            <span style="font-size:1.15rem; font-weight:700; color:{'#059669' if is_p else '#dc2626'};">₹{f['amount']}</span>
                        </div>
                        {status_tag}
                    </div>
                    <div style="margin-top:8px; font-size:0.9rem; color:#475569;">
                        <b>Due Date:</b> {f['due_date']} &nbsp;|&nbsp; 
                        <b>Paid Date:</b> {f.get('paid_date', '-')} &nbsp;|&nbsp; 
                        <b>Verified By:</b> {f.get('marked_by', '-')}
                    </div>
                    {f'<div style="margin-top:4px; font-size:0.85rem; color:#64748b;"><b>Note:</b> {f["note"]}</div>' if f.get('note') else ''}
                </div>
                """, unsafe_allow_html=True)

    with col_p2:
        st.markdown("### 💳 How to Pay Your Tuition Fees")
        st.markdown("""
        <div class="glass-card" style="padding:18px;">
            <h4 style="margin-top:0; color:#1e293b;">📌 Payment Instructions</h4>
            <ul style="color:#475569; font-size:0.9rem; padding-left:18px; margin-bottom:12px;">
                <li><b>UPI ID:</b> <code>sistersacademy@upi</code></li>
                <li><b>Google Pay / PhonePe / Paytm:</b> Scan the Academy QR Code at the office or send to <code>9876543210</code></li>
                <li><b>Cash Payment:</b> Pay in person at the Academy Reception Desk.</li>
            </ul>
            <div style="background:#e0f2fe; border-left:4px solid #0284c7; padding:10px; border-radius:6px; font-size:0.85rem; color:#0369a1;">
                ℹ️ <b>Important:</b> After completing your UPI payment, share your payment reference number / screenshot with your Teacher or Administrator to have your fee receipt marked as <b>Paid</b>.
            </div>
        </div>
        """, unsafe_allow_html=True)


# ==========================================
# 6.6. FUTURE CLASS SCHEDULER & WAITING LOUNGE CONTROLLER
# ==========================================
def render_class_scheduler_widget(is_admin: bool = False):
    st.markdown("#### 📅 Future Class Scheduler & Waiting Lounge Controller")
    st.caption("Plan and schedule upcoming live classes. Enable the pre-class waiting lounge so students can join early to test audio, meet, and discuss.")

    # 1. Fetch scheduled classes
    scheduled_list = []
    if is_supabase_active():
        ok, rows = supabase_request("GET", "scheduled_classes", params="order=scheduled_date.asc,scheduled_time.asc&select=*")
        if ok and rows:
            scheduled_list = rows

    if not scheduled_list:
        with get_db_connection() as conn_r:
            c_r = conn_r.cursor()
            c_r.execute("SELECT * FROM scheduled_classes ORDER BY scheduled_date ASC, scheduled_time ASC")
            scheduled_list = [dict(r) for r in c_r.fetchall()]

    col_sc1, col_sc2 = st.columns([1.4, 1.6])

    with col_sc1:
        st.markdown("##### ➕ Schedule a Future Class")
        with st.form(f"schedule_class_form_{'adm' if is_admin else 'tch'}", clear_on_submit=True):
            sc_topic = st.text_input("Class Topic", placeholder="e.g. Calculus & Derivatives Masterclass")
            sc_sub = st.selectbox("Subject", ["Mathematics", "Physics", "Chemistry", "Biology", "English", "General Coaching"])
            sc_teacher = st.text_input("Teacher / Host Name", value=st.session_state.name or "Teacher")
            
            c_d1, c_d2 = st.columns(2)
            with c_d1:
                sc_date = st.date_input("Scheduled Date", value=datetime.date.today())
            with c_d2:
                sc_time = st.text_input("Time (HH:MM)", value="18:00", placeholder="18:00")

            sc_room = st.text_input("Room Key", value="SistersLiveClass_MasterRoom")
            sc_notes = st.text_input("Instructions for Students", value="Camera is OFF by default. Waiting lounge is open for discussion.")
            sc_wait = st.checkbox("Allow Students to Join Waiting Lounge Early", value=True)

            btn_sched = st.form_submit_button("🗓️ Schedule Class", type="primary", use_container_width=True)

            if btn_sched:
                if not sc_topic.strip():
                    st.error("Please enter a class topic.")
                else:
                    date_str = str(sc_date)
                    wait_val = 1 if sc_wait else 0
                    try:
                        with get_db_connection() as conn_w:
                            conn_w.execute("""
                            INSERT INTO scheduled_classes (topic, subject, teacher_name, scheduled_date, scheduled_time, room_name, notes, status, allow_waiting_room)
                            VALUES (?, ?, ?, ?, ?, ?, ?, 'Scheduled', ?)
                            """, (sc_topic.strip(), sc_sub, sc_teacher.strip(), date_str, sc_time.strip(), sc_room.strip(), sc_notes.strip(), wait_val))
                            conn_w.commit()

                        if is_supabase_active():
                            supabase_request("POST", "scheduled_classes", {
                                "topic": sc_topic.strip(),
                                "subject": sc_sub,
                                "teacher_name": sc_teacher.strip(),
                                "scheduled_date": date_str,
                                "scheduled_time": sc_time.strip(),
                                "room_name": sc_room.strip(),
                                "notes": sc_notes.strip(),
                                "status": "Scheduled",
                                "allow_waiting_room": wait_val
                            })

                        st.success(f"Class '{sc_topic.strip()}' scheduled for {date_str} at {sc_time.strip()}!")
                        st.rerun()
                    except Exception as e:
                        st.error(f"Error scheduling class: {e}")

    with col_sc2:
        st.markdown("##### 📋 Scheduled Classes Queue")
        active_scheduled = [c for c in scheduled_list if c.get('status') in ('Scheduled', 'Live')]
        if not active_scheduled:
            st.info("No upcoming classes scheduled. Fill the form on the left to schedule a class.")
        else:
            for sc in active_scheduled:
                is_sc_live = sc.get('status') == 'Live'
                st_color = "#059669" if is_sc_live else "#0284c7"
                st_bg = "#f0fdf4" if is_sc_live else "#f0f9ff"
                status_badge = "🔴 LIVE NOW" if is_sc_live else "🗓️ SCHEDULED"
                wl_badge = "🛋️ Waiting Lounge: OPEN" if sc.get('allow_waiting_room', 1) == 1 else "🔒 Waiting Lounge: Closed"

                with st.container():
                    st.markdown(f"""
                    <div style="background:{st_bg}; border:1px solid {st_color}; border-radius:10px; padding:12px; margin-bottom:10px;">
                        <div style="display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:6px;">
                            <b style="color:#1e293b; font-size:1rem;">[{sc.get('subject')}] {sc.get('topic')}</b>
                            <span style="background:{st_color}; color:white; padding:2px 8px; border-radius:12px; font-weight:700; font-size:0.75rem;">{status_badge}</span>
                        </div>
                        <div style="margin-top:6px; font-size:0.88rem; color:#475569;">
                            <b>Teacher:</b> {sc.get('teacher_name')} &nbsp;|&nbsp; 
                            <b>Date:</b> {sc.get('scheduled_date')} at {sc.get('scheduled_time')}<br>
                            <b>Room:</b> <code>{sc.get('room_name')}</code> &nbsp;|&nbsp; 
                            <span style="color:#0284c7; font-weight:600;">{wl_badge}</span>
                        </div>
                        {f'<div style="font-size:0.82rem; color:#64748b; margin-top:4px;"><b>Note:</b> {sc.get("notes")}</div>' if sc.get('notes') else ''}
                    </div>
                    """, unsafe_allow_html=True)

                    btn_c1, btn_c2, btn_c3 = st.columns([1.5, 1, 1])

                    with btn_c1:
                        with st.form(f"launch_sc_form_{sc['id']}_{'adm' if is_admin else 'tch'}"):
                            if st.form_submit_button("🚀 Launch Live Now", type="primary", use_container_width=True):
                                now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                                host_name = sc.get('teacher_name') or st.session_state.name or "Teacher"
                                try:
                                    with get_db_connection() as conn_w:
                                        conn_w.execute("""
                                        UPDATE class_session 
                                        SET is_live = 1, topic = ?, room_name = ?, teacher_notes = ?, started_at = ?, host_teacher = ?
                                        WHERE id = 1
                                        """, (sc['topic'], sc['room_name'], sc.get('notes', ''), now_str, host_name))
                                        conn_w.execute("UPDATE scheduled_classes SET status = 'Live' WHERE id = ?", (sc['id'],))
                                        conn_w.commit()

                                    if is_supabase_active():
                                        supabase_request("PATCH", "class_session", {
                                            "is_live": 1, "topic": sc['topic'], "room_name": sc['room_name'],
                                            "teacher_notes": sc.get('notes', ''), "started_at": now_str, "host_teacher": host_name
                                        }, params="id=eq.1")
                                        supabase_request("PATCH", "scheduled_classes", {"status": "Live"}, params=f"id=eq.{sc['id']}")

                                    st.success(f"Broadcast started for '{sc['topic']}'! Students in waiting lounge are now live.")
                                    st.rerun()
                                except Exception as e:
                                    st.error(f"Error launching live broadcast: {e}")

                    with btn_c2:
                        with st.form(f"done_sc_form_{sc['id']}_{'adm' if is_admin else 'tch'}"):
                            if st.form_submit_button("✅ Done", use_container_width=True):
                                try:
                                    with get_db_connection() as conn_w:
                                        conn_w.execute("UPDATE scheduled_classes SET status = 'Completed' WHERE id = ?", (sc['id'],))
                                        conn_w.commit()

                                    if is_supabase_active():
                                        supabase_request("PATCH", "scheduled_classes", {"status": "Completed"}, params=f"id=eq.{sc['id']}")

                                    st.success("Marked as Completed.")
                                    st.rerun()
                                except Exception as e:
                                    st.error(f"Error completing class: {e}")

                    with btn_c3:
                        with st.form(f"del_sc_form_{sc['id']}_{'adm' if is_admin else 'tch'}"):
                            if st.form_submit_button("🗑️ Cancel", use_container_width=True):
                                try:
                                    with get_db_connection() as conn_w:
                                        conn_w.execute("DELETE FROM scheduled_classes WHERE id = ?", (sc['id'],))
                                        conn_w.commit()

                                    if is_supabase_active():
                                        supabase_request("DELETE", "scheduled_classes", params=f"id=eq.{sc['id']}")

                                    st.warning("Scheduled class removed.")
                                    st.rerun()
                                except Exception as e:
                                    st.error(f"Error deleting class: {e}")


# ==========================================
# 7. SUPER ADMIN DASHBOARD
# ==========================================
def render_admin_dashboard():
    conn = get_db()
    c = conn.cursor()

    # Get live session status safely
    sess = {}
    if is_supabase_active():
        ok, rows = supabase_request("GET", "class_session", params="id=eq.1&select=*")
        if ok and rows:
            sess = rows[0]

    if not sess:
        c.execute("SELECT * FROM class_session WHERE id = 1")
        raw_sess = c.fetchone()
        sess = dict(raw_sess) if raw_sess else {}

    is_live = bool(sess.get('is_live', 0))
    room_name = sess.get('room_name') or 'SistersLiveClass_MasterRoom'
    session_topic = sess.get('topic') or 'General Coaching Session'
    server = sess.get('server') or st.session_state.jitsi_server or "jitsi.riot.im"
    started_at = sess.get('started_at') or "Recently"
    teacher_notes = sess.get('teacher_notes') or ""
    host_teacher = sess.get('host_teacher') or "Super Admin"

    st.markdown("""
    <div style="background: linear-gradient(135deg, #1e1b4b 0%, #312e81 100%); color: white; padding: 22px 26px; border-radius: 14px; margin-bottom: 20px; box-shadow: 0 10px 25px -5px rgba(49, 46, 129, 0.3);">
        <div style="display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 10px;">
            <div>
                <h2 style="margin: 0; color: #ffffff; font-weight: 700; display: flex; align-items: center; gap: 10px;">
                    <span>👑 Super Admin Master Dashboard</span>
                    <span style="font-size: 0.75rem; background: #f59e0b; color: #1e1b4b; padding: 3px 10px; border-radius: 9999px; font-weight: 800;">MASTER ROOT</span>
                </h2>
                <p style="margin: 6px 0 0 0; color: #c7d2fe; font-size: 0.92rem;">
                    Full central control: View all user credentials (passwords), provision Teacher/Student accounts, monitor live classes, manage recordings, and audit attendance.
                </p>
            </div>
        </div>
    </div>
    """, unsafe_allow_html=True)

    tab_cred, tab_fees, tab_live, tab_recordings, tab_notices, tab_doubts, tab_att, tab_cloud = st.tabs([
        "👑 Master Credentials & Accounts",
        "💳 Student Fees & Invoices",
        "🎥 Live Classroom Broadcast",
        "📚 Study Library & Drive Folder",
        "📢 Announcements Board",
        "❓ Doubts & Discussion Moderation",
        "📊 Master Attendance Logs",
        "☁️ Cloud Sync Status"
    ])

    # ---------------------------------------------
    # ADMIN TAB 1: MASTER CREDENTIALS DIRECTORY
    # ---------------------------------------------
    with tab_cred:
        st.subheader("👑 Master User Credentials & Account Administration")
        st.caption("Central directory for all Administrator, Teacher, and Student accounts. Plain-text passwords are saved and visible specifically for administrative management.")

        c.execute("SELECT id, username, password, password_hash, role, full_name, is_active, created_at FROM users ORDER BY role ASC, id ASC")
        all_users = [dict(r) for r in c.fetchall()]

        # Metrics Overview
        col_m1, col_m2, col_m3, col_m4 = st.columns(4)
        with col_m1:
            st.metric("Total Accounts", len(all_users))
        with col_m2:
            st.metric("Teachers", len([u for u in all_users if u['role'] == 'teacher']))
        with col_m3:
            st.metric("Students", len([u for u in all_users if u['role'] == 'student']))
        with col_m4:
            st.metric("Super Admins", len([u for u in all_users if u['role'] == 'admin']))

        st.markdown("---")

        q_user = st.text_input("🔍 Search Directory (by name, username, or role)", placeholder="e.g. teacher1, student5, admin, Sara...").strip().lower()
        filtered_users = all_users
        if q_user:
            filtered_users = [
                u for u in all_users 
                if q_user in u['username'].lower() or q_user in u['full_name'].lower() or q_user in u['role'].lower()
            ]

        display_data = []
        for u in filtered_users:
            role_icon = "👑 Admin" if u['role'] == 'admin' else ("👩‍🏫 Teacher" if u['role'] == 'teacher' else "🎓 Student")
            status_str = "🟢 Active" if u.get('is_active', 1) == 1 else "🔴 Blocked"
            display_data.append({
                "ID": u['id'],
                "Role": role_icon,
                "Full Name": u['full_name'],
                "Username": u['username'],
                "Password (Plain-Text)": u.get('password') or "(hash stored)",
                "Account Status": status_str,
                "Joined Date": u['created_at']
            })

        st.dataframe(display_data, use_container_width=True, hide_index=True)

        st.markdown("---")

        col_adm1, col_adm2 = st.columns([1.2, 1.8])

        with col_adm1:
            st.markdown("### ➕ Provision New Account")
            with st.form("admin_create_user_form", clear_on_submit=True):
                new_role = st.selectbox("Account Role", ["Teacher", "Student", "Admin"])
                new_fn = st.text_input("Full Name", placeholder="e.g. Teacher 3 or Aisha Siddiq")
                new_un = st.text_input("Username", placeholder="e.g. teacher3 or student11").strip().lower()
                new_pw = st.text_input("Password (Plain-Text)", placeholder="e.g. teach789 or pass123")
                btn_create = st.form_submit_button("Provision Account", type="primary", use_container_width=True)

                if btn_create:
                    if not new_un or not new_fn or not new_pw:
                        st.error("All fields (Role, Full Name, Username, Password) are required.")
                    else:
                        role_val = new_role.lower()
                        pw_hash = hash_password(new_pw)
                        now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                        try:
                            with get_db_connection() as conn_w:
                                conn_w.execute("""
                                INSERT INTO users (username, password, password_hash, role, full_name, is_active, created_at)
                                VALUES (?, ?, ?, ?, ?, 1, ?)
                                """, (new_un, new_pw, pw_hash, role_val, new_fn, now_str))
                                conn_w.commit()

                            if is_supabase_active():
                                supabase_request("POST", "users", {
                                    "username": new_un, "password": new_pw, "password_hash": pw_hash,
                                    "role": role_val, "full_name": new_fn, "is_active": 1, "created_at": now_str
                                })

                            st.success(f"{new_role} account '{new_fn}' (@{new_un}) created successfully!")
                            st.rerun()
                        except sqlite3.IntegrityError:
                            st.error(f"Username '{new_un}' is already in use.")
                        except Exception as e:
                            st.error(f"Error provisioning account: {e}")

        with col_adm2:
            st.markdown("### 🔑 Password Recovery & Reset Tool")
            user_options = {f"{u['full_name']} (@{u['username']}) — {u['role'].upper()}": u for u in all_users}
            if user_options:
                sel_label = st.selectbox("Select Account to Inspect / Reset Password", list(user_options.keys()))
                sel_user = user_options[sel_label]

                curr_pwd = sel_user.get('password') or "(no plain-text stored)"
                st.info(f"👤 Selected User: **{sel_user['full_name']}** (`@{sel_user['username']}`) | Role: **{sel_user['role'].capitalize()}**\n\n🔑 **Current Plain-Text Password:** `{curr_pwd}`")

                with st.form(f"admin_rst_pw_form_{sel_user['id']}"):
                    col_p1, col_p2 = st.columns([2, 1])
                    with col_p1:
                        new_password_val = st.text_input("Set New Password", value=curr_pwd if curr_pwd != "(no plain-text stored)" else "newPass123")
                    with col_p2:
                        st.write("")
                        st.write("")
                        btn_rst_pw = st.form_submit_button("Update Password", type="primary", use_container_width=True)

                    if btn_rst_pw:
                        if not new_password_val.strip():
                            st.error("Password cannot be blank.")
                        else:
                            pw_new_hash = hash_password(new_password_val.strip())
                            try:
                                with get_db_connection() as conn_w:
                                    conn_w.execute("UPDATE users SET password = ?, password_hash = ? WHERE id = ?", (new_password_val.strip(), pw_new_hash, sel_user['id']))
                                    conn_w.commit()
                            except Exception as e:
                                print(f"Error updating user password: {e}")

                            if is_supabase_active():
                                supabase_request("PATCH", "users", {"password": new_password_val.strip(), "password_hash": pw_new_hash}, params=f"id=eq.{sel_user['id']}")

                            st.success(f"Password updated for @{sel_user['username']}! New Password: {new_password_val.strip()}")
                            st.rerun()

                st.markdown("#### 🚫 Account Status & Deletion")
                col_st1, col_st2 = st.columns([1, 1])
                with col_st1:
                    is_act = sel_user.get('is_active', 1) == 1
                    btn_status_label = "🚫 Suspend / Block Account" if is_act else "✅ Reactivate Account"
                    with st.form(f"status_toggle_form_{sel_user['id']}"):
                        if st.form_submit_button(btn_status_label, use_container_width=True):
                            if sel_user['username'] == 'admin':
                                st.error("Cannot suspend the master Super Admin account.")
                            else:
                                new_act = 0 if is_act else 1
                                try:
                                    with get_db_connection() as conn_w:
                                        conn_w.execute("UPDATE users SET is_active = ? WHERE id = ?", (new_act, sel_user['id']))
                                        conn_w.commit()
                                except Exception as e:
                                    print(f"Error toggling user status: {e}")

                                if is_supabase_active():
                                    supabase_request("PATCH", "users", {"is_active": new_act}, params=f"id=eq.{sel_user['id']}")

                                st.success(f"Account @{sel_user['username']} status updated.")
                                st.rerun()

                with col_st2:
                    with st.form(f"delete_user_form_{sel_user['id']}"):
                        if st.form_submit_button("🗑️ Delete Account Permanently", use_container_width=True):
                            if sel_user['username'] == 'admin':
                                st.error("Cannot delete the master Super Admin account.")
                            else:
                                try:
                                    with get_db_connection() as conn_w:
                                        conn_w.execute("DELETE FROM users WHERE id = ?", (sel_user['id'],))
                                        conn_w.commit()
                                except Exception as e:
                                    print(f"Error deleting user: {e}")

                                if is_supabase_active():
                                    supabase_request("DELETE", "users", params=f"id=eq.{sel_user['id']}")

                                st.success(f"Account @{sel_user['username']} deleted.")
                                st.rerun()

    # ---------------------------------------------
    # ADMIN TAB 1.5: FEES MANAGEMENT
    # ---------------------------------------------
    with tab_fees:
        render_fees_management(is_admin=True)

    # ---------------------------------------------
    # ADMIN TAB 2: LIVE BROADCAST STUDIO
    # ---------------------------------------------
    with tab_live:
        st.subheader("Live Class Broadcast & Monitoring Engine")

        col_st1, col_st2, col_st3 = st.columns([1.8, 1.2, 1])

        with col_st1:
            if is_live:
                st.markdown(f"""
                <div class="live-badge">
                    <span class="live-dot"></span>
                    <span>BROADCAST STATUS: LIVE NOW</span>
                </div>
                <div style="margin-top: 6px; color: #1e293b; font-size: 0.95rem;">
                    <b>Host:</b> {host_teacher}<br>
                    <b>Topic:</b> {session_topic}<br>
                    <b>Started at:</b> {started_at}
                </div>
                """, unsafe_allow_html=True)
            else:
                st.markdown("""
                <div class="offline-badge">
                    <span>⚪ BROADCAST STATUS: OFFLINE</span>
                </div>
                <div style="margin-top: 6px; color: #64748b; font-size: 0.95rem;">
                    Class is offline. Students see an offline banner until a broadcast is started.
                </div>
                """, unsafe_allow_html=True)

        with col_st2:
            if not is_live:
                with st.form("admin_start_class_form"):
                    st.write("<b>Configure Session</b>", unsafe_allow_html=True)
                    f_topic = st.text_input("Topic", value=session_topic or "Mathematics & Science Coaching", key="adm_topic")
                    f_server = st.selectbox("Jitsi Server (Embed-Friendly)", ["jitsi.riot.im", "meet.jit.si", "framatalk.org"], index=0, key="adm_server")
                    f_room = st.text_input("Room Key", value=room_name or "SistersLiveClass_MasterRoom", key="adm_room")
                    f_notes = st.text_input("Note for Students", value="Camera is OFF by default. Unmute mic to ask doubts.", key="adm_notes")
                    btn_start = st.form_submit_button("🚀 Start Live Broadcast", type="primary", use_container_width=True)

                    if btn_start:
                        now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                        h_name = st.session_state.name or "Super Admin"
                        try:
                            with get_db_connection() as conn_w:
                                conn_w.execute("""
                                UPDATE class_session 
                                SET is_live = 1, topic = ?, room_name = ?, server = ?, teacher_notes = ?, host_teacher = ?, started_at = ?
                                WHERE id = 1
                                """, (f_topic, f_room, f_server, f_notes, h_name, now_str))
                                conn_w.commit()
                        except Exception as e:
                            print(f"Error starting live class: {e}")

                        if is_supabase_active():
                            supabase_request("PATCH", "class_session", {
                                "is_live": 1, "topic": f_topic, "room_name": f_room,
                                "server": f_server, "teacher_notes": f_notes, "host_teacher": h_name, "started_at": now_str
                            }, params="id=eq.1")

                        st.session_state.jitsi_server = f_server
                        st.success("Live broadcast started!")
                        st.rerun()
            else:
                with st.form("admin_stop_class_form"):
                    btn_stop = st.form_submit_button("🛑 End Live Class for All", type="primary", use_container_width=True)
                    if btn_stop:
                        now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                        try:
                            with get_db_connection() as conn_w:
                                conn_w.execute("UPDATE class_session SET is_live = 0, ended_at = ? WHERE id = 1", (now_str,))
                                conn_w.commit()
                        except Exception as e:
                            print(f"Error ending live class: {e}")

                        if is_supabase_active():
                            supabase_request("PATCH", "class_session", {"is_live": 0, "ended_at": now_str}, params="id=eq.1")

                        st.warning("Live class ended. Students are back to offline status.")
                        st.rerun()

        with col_st3:
            st.link_button("📂 Open Class Recordings Drive Folder (Upload Here)", DEFAULT_DRIVE_FOLDER_URL, use_container_width=True)

        st.markdown("---")

        if is_live:
            render_jitsi_classroom(
                domain=server,
                room_name=room_name,
                display_name=f"{st.session_state.name} (Super Admin)",
                is_teacher=True
            )
        else:
            st.info("💡 To begin teaching or broadcasting, configure your topic and click **'Start Live Broadcast'** above.")

        st.markdown("---")
        with st.expander("📅 Class Scheduler & Pre-Class Waiting Lounge Queue", expanded=not is_live):
            render_class_scheduler_widget(is_admin=True)

    # ---------------------------------------------
    # ADMIN TAB 3: RECORDED CLASSES (GOOGLE DRIVE)
    # ---------------------------------------------
    with tab_recordings:
        st.subheader("Google Drive Recorded Classes & Study Library")
        st.caption("All class recordings dropped into your Google Drive folder automatically appear below for all users in real time.")

        render_embedded_drive_folder(
            folder_id=DEFAULT_DRIVE_FOLDER_ID,
            folder_url=DEFAULT_DRIVE_FOLDER_URL,
            title="Class Recordings Google Drive Folder",
            key_suffix="admin"
        )
        st.markdown("---")

        col_up_btn1, col_up_btn2 = st.columns([1.5, 1])
        with col_up_btn1:
            st.link_button("📂 Open Class Recordings Drive Folder (Upload Here)", DEFAULT_DRIVE_FOLDER_URL, type="primary", use_container_width=True)
        with col_up_btn2:
            st.info(f"📁 Folder ID: `{DEFAULT_DRIVE_FOLDER_ID}`")

        with st.expander("☁️ Direct Google Drive Video Auto-Uploader (Service Account)", expanded=False):
            st.write("Upload a recorded `.webm`, `.mp4`, or `.mkv` file directly into your Google Drive folder from here:")
            uploaded_file = st.file_uploader("Upload Recording Directly to Google Drive Folder", type=["webm", "mp4", "mkv"], key="admin_drive_uploader")
            if uploaded_file is not None:
                up_col1, up_col2 = st.columns([1.5, 1])
                with up_col1:
                    up_title = st.text_input("Recording Title", value=uploaded_file.name.rsplit(".", 1)[0], key="admin_up_title")
                with up_col2:
                    up_sub = st.selectbox("Subject", ["Mathematics", "Physics", "Chemistry", "Biology", "English", "General Coaching"], key="admin_up_sub")

                if st.button("🚀 Upload File to Google Drive Folder", type="primary", use_container_width=True, key="btn_admin_up"):
                    with st.spinner("Uploading video to Google Drive folder..."):
                        ok, web_link, err_msg = upload_file_to_google_drive(uploaded_file, uploaded_file.name, DEFAULT_DRIVE_FOLDER_ID)
                        if ok:
                            embed_url, download_url = process_google_drive_link(web_link)
                            now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                            today_str = str(datetime.date.today())
                            try:
                                with get_db_connection() as conn_w:
                                    conn_w.execute("""
                                    INSERT INTO recordings (title, subject, lecture_date, description, drive_link, embed_url, download_url, created_at)
                                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                                    """, (up_title, up_sub, today_str, f"Auto-uploaded: {uploaded_file.name}", web_link, embed_url, download_url, now_str))
                                    conn_w.commit()
                            except Exception as e:
                                print(f"Error saving auto-uploaded recording: {e}")

                            if is_supabase_active():
                                supabase_request("POST", "recordings", {
                                    "title": up_title, "subject": up_sub, "lecture_date": today_str,
                                    "description": f"Auto-uploaded: {uploaded_file.name}", "drive_link": web_link,
                                    "embed_url": embed_url, "download_url": download_url, "created_at": now_str
                                })

                            st.success(f"Video uploaded to Google Drive! Link: {web_link}")
                            st.rerun()
                        else:
                            st.warning(f"Notice: {err_msg}")
                            st.markdown(f"💡 **Quick Alternative:** Click **[📂 Open Class Recordings Drive Folder (Upload Here)]({DEFAULT_DRIVE_FOLDER_URL})** to drag & drop your video directly into the folder.")

        st.markdown("---")
        st.markdown("#### 🎬 Spotlight Individual Video Player")
        col_r1, col_r2 = st.columns([1.2, 1.8])

        with col_r1:
            with st.form("admin_add_rec_form", clear_on_submit=True):
                r_title = st.text_input("Lecture Title", placeholder="e.g. Chapter 4: Chemical Bonding")
                r_subject = st.selectbox("Subject", ["Mathematics", "Physics", "Chemistry", "Biology", "English", "General Coaching"], key="admin_rec_sub")
                r_date = st.date_input("Class Date", datetime.date.today(), key="admin_rec_date")
                r_link = st.text_input("Google Drive / YouTube Link", placeholder="https://drive.google.com/file/d/FILE_ID/view?usp=sharing")
                r_desc = st.text_area("Notes / Summary", placeholder="Topics covered, homework exercises, formulas...")
                submit_rec = st.form_submit_button("Publish Recording", type="primary", use_container_width=True)

                if submit_rec:
                    if not r_title or not r_link:
                        st.error("Title and Video link are required.")
                    else:
                        embed_url, download_url = process_google_drive_link(r_link)
                        now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                        try:
                            with get_db_connection() as conn_w:
                                conn_w.execute("""
                                INSERT INTO recordings (title, subject, lecture_date, description, drive_link, embed_url, download_url, created_at)
                                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                                """, (r_title, r_subject, str(r_date), r_desc, r_link, embed_url, download_url, now_str))
                                conn_w.commit()
                        except Exception as e:
                            print(f"Error publishing recording: {e}")

                        if is_supabase_active():
                            supabase_request("POST", "recordings", {
                                "title": r_title, "subject": r_subject, "lecture_date": str(r_date),
                                "description": r_desc, "drive_link": r_link, "embed_url": embed_url,
                                "download_url": download_url, "created_at": now_str
                            })

                        st.success("Recording published successfully!")
                        st.rerun()

        with col_r2:
            st.markdown("### 📋 Published Library")
            all_recs = []
            if is_supabase_active():
                ok, rows = supabase_request("GET", "recordings", params="order=id.desc&select=*")
                if ok:
                    all_recs = rows

            if not all_recs:
                c.execute("SELECT * FROM recordings ORDER BY id DESC")
                all_recs = [dict(r) for r in c.fetchall()]

            if not all_recs:
                st.info("No recordings added yet.")
            else:
                for rec in all_recs:
                    with st.expander(f"🎬 {rec['title']} ({rec['subject']} - {rec['lecture_date']})"):
                        st.write(f"**Notes:** {rec.get('description') or 'No notes added.'}")
                        col_l1, col_l2 = st.columns([1.5, 1])
                        with col_l1:
                            st.link_button("📥 Direct Download Link", rec['download_url'], use_container_width=True)
                        with col_l2:
                            with st.form(f"del_rec_admin_{rec['id']}"):
                                if st.form_submit_button("🗑️ Delete Recording", use_container_width=True):
                                    try:
                                        with get_db_connection() as conn_w:
                                            conn_w.execute("DELETE FROM recordings WHERE id = ?", (rec['id'],))
                                            conn_w.commit()
                                    except Exception as e:
                                        print(f"Error deleting recording: {e}")
                                    if is_supabase_active():
                                        supabase_request("DELETE", "recordings", params=f"id=eq.{rec['id']}")
                                    st.success("Deleted recording.")
                                    st.rerun()

                        if "drive.google.com" in rec['embed_url'] or "youtube.com" in rec['embed_url']:
                            st.markdown(f"""
                            <iframe src="{rec['embed_url']}" width="100%" height="320" frameborder="0" allow="autoplay; fullscreen" allowfullscreen style="border-radius:8px; border:1px solid #cbd5e1; margin-top:8px;"></iframe>
                            """, unsafe_allow_html=True)

    # ---------------------------------------------
    # ADMIN TAB 4: NOTICE BOARD
    # ---------------------------------------------
    with tab_notices:
        st.subheader("Notice Board & Announcement Alerts")
        col_n1, col_n2 = st.columns([1.2, 1.8])

        with col_n1:
            st.markdown("### 📢 Post New Announcement")
            with st.form("admin_post_notice_form", clear_on_submit=True):
                n_title = st.text_input("Notice Title", placeholder="e.g. Science Test on Saturday")
                n_priority = st.selectbox("Priority / Category", ["Important", "Exam", "Holiday", "Normal"])
                n_msg = st.text_area("Notice Message", placeholder="Please revise chapter 3 formulas...")
                btn_n = st.form_submit_button("Publish Notice", type="primary", use_container_width=True)

                if btn_n:
                    if not n_title or not n_msg:
                        st.error("Title and message are required.")
                    else:
                        now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                        try:
                            with get_db_connection() as conn_w:
                                conn_w.execute("""
                                INSERT INTO announcements (title, message, priority, created_at)
                                VALUES (?, ?, ?, ?)
                                """, (n_title, n_msg, n_priority, now_str))
                                conn_w.commit()
                        except Exception as e:
                            print(f"Error publishing announcement: {e}")

                        if is_supabase_active():
                            supabase_request("POST", "announcements", {
                                "title": n_title, "message": n_msg, "priority": n_priority, "created_at": now_str
                            })

                        st.success("Notice posted!")
                        st.rerun()

        with col_n2:
            st.markdown("### 📌 Active Notices")
            notices = []
            if is_supabase_active():
                ok, rows = supabase_request("GET", "announcements", params="order=id.desc&select=*")
                if ok:
                    notices = rows

            if not notices:
                c.execute("SELECT * FROM announcements ORDER BY id DESC")
                notices = [dict(r) for r in c.fetchall()]

            if not notices:
                st.info("No active notices.")
            else:
                for n in notices:
                    badge_cls = "notice-card"
                    if n.get('priority') == 'Important': badge_cls += " notice-important"
                    elif n.get('priority') == 'Exam': badge_cls += " notice-exam"
                    elif n.get('priority') == 'Holiday': badge_cls += " notice-holiday"

                    st.markdown(f"""
                    <div class="{badge_cls}">
                        <div style="display:flex; justify-content:space-between; align-items:center;">
                            <h4 style="margin:0; color:#1e293b;">{n['title']}</h4>
                            <span style="font-size:0.8rem; background:#cbd5e1; padding:2px 8px; border-radius:12px; font-weight:600;">{n.get('priority', 'Normal')}</span>
                        </div>
                        <p style="margin:6px 0 2px 0; color:#475569;">{n['message']}</p>
                        <small style="color:#94a3b8;">Posted: {n['created_at']}</small>
                    </div>
                    """, unsafe_allow_html=True)

                    with st.form(f"del_not_admin_{n['id']}"):
                        if st.form_submit_button("Delete Notice", use_container_width=False):
                            try:
                                with get_db_connection() as conn_w:
                                    conn_w.execute("DELETE FROM announcements WHERE id = ?", (n['id'],))
                                    conn_w.commit()
                            except Exception as e:
                                print(f"Error deleting announcement: {e}")
                            if is_supabase_active():
                                supabase_request("DELETE", "announcements", params=f"id=eq.{n['id']}")
                            st.rerun()

    # ---------------------------------------------
    # ADMIN TAB 5: DOUBTS & DISCUSSION MODERATION
    # ---------------------------------------------
    with tab_doubts:
        st.subheader("Student Doubts & Questions Moderation")
        doubts = []
        if is_supabase_active():
            ok, rows = supabase_request("GET", "doubts", params="order=id.desc&select=*")
            if ok:
                doubts = rows

        if not doubts:
            c.execute("SELECT * FROM doubts ORDER BY id DESC")
            doubts = [dict(r) for r in c.fetchall()]

        if not doubts:
            st.info("No doubts submitted by students yet.")
        else:
            for d in doubts:
                with st.expander(f"❓ [{d.get('subject')}] {d.get('student_name')} (@{d.get('student_username')}) - {d.get('status')}"):
                    st.write(f"**Question:** {d['question']}")
                    st.caption(f"Submitted on: {d['created_at']}")

                    if d.get('reply'):
                        st.markdown(f"""
                        <div style="background:#f0fdf4; border-left:4px solid #10b981; padding:10px 14px; border-radius:6px; margin:8px 0;">
                            <b>Explanation:</b> {d['reply']}<br>
                            <small style="color:#64748b;">Answered at: {d.get('replied_at')}</small>
                        </div>
                        """, unsafe_allow_html=True)

                    with st.form(f"rep_form_admin_{d['id']}"):
                        reply_val = st.text_area("Explanation / Answer", value=d.get('reply') or "")
                        col_rb1, col_rb2 = st.columns([1, 1])
                        with col_rb1:
                            sub_ans = st.form_submit_button("Save & Send Answer", type="primary", use_container_width=True)
                        with col_rb2:
                            del_doubt = st.form_submit_button("Remove Doubt", use_container_width=True)

                        if sub_ans:
                            if reply_val.strip():
                                now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                                try:
                                    with get_db_connection() as conn_w:
                                        conn_w.execute("""
                                        UPDATE doubts SET reply = ?, status = 'Answered', replied_at = ? WHERE id = ?
                                        """, (reply_val.strip(), now_str, d['id']))
                                        conn_w.commit()
                                except Exception as e:
                                    print(f"Error answering doubt: {e}")
                                if is_supabase_active():
                                    supabase_request("PATCH", "doubts", {
                                        "reply": reply_val.strip(), "status": "Answered", "replied_at": now_str
                                    }, params=f"id=eq.{d['id']}")
                                st.success("Answer published to student!")
                                st.rerun()
                            else:
                                st.error("Response cannot be empty.")

                        if del_doubt:
                            try:
                                with get_db_connection() as conn_w:
                                    conn_w.execute("DELETE FROM doubts WHERE id = ?", (d['id'],))
                                    conn_w.commit()
                            except Exception as e:
                                print(f"Error deleting doubt: {e}")
                            if is_supabase_active():
                                supabase_request("DELETE", "doubts", params=f"id=eq.{d['id']}")
                            st.warning("Doubt removed.")
                            st.rerun()

    # ---------------------------------------------
    # ADMIN TAB 6: MASTER ATTENDANCE LOGS
    # ---------------------------------------------
    with tab_att:
        st.subheader("📊 Master Attendance Logs & CSV Audit")
        records_data = []
        if is_supabase_active():
            ok, rows = supabase_request("GET", "attendance", params="order=id.desc&select=*")
            if ok:
                records_data = rows

        if not records_data:
            c.execute("SELECT id, student_name, student_username, room_name, topic, join_timestamp, date FROM attendance ORDER BY id DESC")
            records_data = [dict(r) for r in c.fetchall()]

        if not records_data:
            st.info("No attendance entries logged yet.")
        else:
            st.dataframe(records_data, use_container_width=True, hide_index=True)

            csv_output = io.StringIO()
            csv_writer = csv.DictWriter(csv_output, fieldnames=['id', 'student_name', 'student_username', 'room_name', 'topic', 'join_timestamp', 'date'])
            csv_writer.writeheader()
            csv_writer.writerows(records_data)

            st.download_button(
                label="📥 Export Master Attendance as CSV",
                data=csv_output.getvalue(),
                file_name=f"Master_Attendance_{datetime.date.today()}.csv",
                mime="text/csv",
                type="primary"
            )

    # ---------------------------------------------
    # ADMIN TAB 7: CLOUD STORAGE STATUS
    # ---------------------------------------------
    with tab_cloud:
        st.subheader("☁️ Supabase Cloud Storage Status")
        supabase_on = is_supabase_active()
        url_cfg, key_cfg = get_supabase_config()

        if supabase_on:
            st.success("🟢 Supabase Cloud Storage is fully CONNECTED and ACTIVE!")
        else:
            st.warning("🟡 Supabase credentials not found or database tables not yet initialized.")
            if url_cfg:
                st.info(f"Target Project URL: `{url_cfg}`")

    try:
        conn.close()
    except Exception:
        pass


# ==========================================
# 8. TEACHER DASHBOARD
# ==========================================
def render_teacher_dashboard():
    conn = get_db()
    c = conn.cursor()

    # Get live session status safely (from Supabase or SQLite)
    sess = {}
    if is_supabase_active():
        ok, rows = supabase_request("GET", "class_session", params="id=eq.1&select=*")
        if ok and rows:
            sess = rows[0]

    if not sess:
        c.execute("SELECT * FROM class_session WHERE id = 1")
        raw_sess = c.fetchone()
        sess = dict(raw_sess) if raw_sess else {}

    is_live = bool(sess.get('is_live', 0))
    room_name = sess.get('room_name') or 'SistersLiveClass_MasterRoom'
    session_topic = sess.get('topic') or 'General Coaching Session'
    server = sess.get('server') or "meet.ffmuc.net"
    teacher_notes = sess.get('teacher_notes') or ""
    started_at = sess.get('started_at') or "Recently"

    st.markdown(f"""
    <div class="hero-banner">
        <div style="display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap;">
            <div>
                <h1>👩‍🏫 Teacher Control Center</h1>
                <p>Welcome, <b>{st.session_state.name}</b> | Server: <code>{server}</code> | Room: <code>{room_name}</code></p>
            </div>
        </div>
    </div>
    """, unsafe_allow_html=True)

    tab_live, tab_recordings, tab_fees, tab_notices, tab_doubts, tab_students, tab_cloud = st.tabs([
        "🔴 Live Studio & Screen Share",
        "📚 Recorded Classes (Google Drive)",
        "💳 Student Fees & Invoices",
        "📢 Notice Board",
        "❓ Doubt Box & Chat",
        "👥 Attendance & Student Accounts",
        "☁️ Supabase Cloud Setup"
    ])

    # ---------------------------------------------
    # TEACHER TAB 1: LIVE STUDIO
    # ---------------------------------------------
    with tab_live:
        st.subheader("Live Class Broadcast Engine")

        col_st1, col_st2, col_st3 = st.columns([1.8, 1.2, 1])

        with col_st1:
            if is_live:
                live_host = sess.get('host_teacher') or "Teacher"
                st.markdown(f"""
                <div class="live-badge">
                    <span class="live-dot"></span>
                    <span>BROADCAST STATUS: LIVE NOW</span>
                </div>
                <div style="margin-top: 6px; color: #1e293b; font-size: 0.95rem;">
                    <b>Topic:</b> {session_topic}<br>
                    <b>Host Teacher:</b> {live_host}<br>
                    <b>Started at:</b> {started_at}
                </div>
                """, unsafe_allow_html=True)
            else:
                st.markdown("""
                <div class="offline-badge">
                    <span>⚪ BROADCAST STATUS: OFFLINE</span>
                </div>
                <div style="margin-top: 6px; color: #64748b; font-size: 0.95rem;">
                    Class is offline. Students see an offline banner until you start the broadcast.
                </div>
                """, unsafe_allow_html=True)

        with col_st2:
            if not is_live:
                with st.form("start_class_form"):
                    st.write("<b>Configure Session</b>", unsafe_allow_html=True)
                    f_topic = st.text_input("Topic", value=session_topic or "Mathematics & Science Coaching")
                    f_server = st.selectbox("Jitsi Server (Embed-Friendly)", ["jitsi.riot.im", "meet.jit.si", "framatalk.org"], index=0)
                    f_room = st.text_input("Room Key", value=room_name or "SistersLiveClass_MasterRoom")

                    f_notes = st.text_input("Note for Students", value="Camera is OFF by default. Unmute mic to ask doubts.")
                    btn_start = st.form_submit_button("🚀 Start Live Broadcast", type="primary", use_container_width=True)

                    if btn_start:
                        now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                        host_name = st.session_state.name or "Teacher"
                        try:
                            with get_db_connection() as conn_w:
                                conn_w.execute("""
                                UPDATE class_session 
                                SET is_live = 1, topic = ?, room_name = ?, server = ?, teacher_notes = ?, started_at = ?, host_teacher = ?
                                WHERE id = 1
                                """, (f_topic, f_room, f_server, f_notes, now_str, host_name))
                                conn_w.commit()
                        except Exception as e:
                            print(f"Error starting live class: {e}")

                        if is_supabase_active():
                            supabase_request("PATCH", "class_session", {
                                "is_live": 1, "topic": f_topic, "room_name": f_room,
                                "server": f_server, "teacher_notes": f_notes, "started_at": now_str,
                                "host_teacher": host_name
                            }, params="id=eq.1")

                        st.session_state.jitsi_server = f_server
                        st.success("Live broadcast started!")
                        st.rerun()
            else:
                with st.form("stop_class_form"):
                    btn_stop = st.form_submit_button("🛑 End Live Class for All", type="primary", use_container_width=True)
                    if btn_stop:
                        now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                        try:
                            with get_db_connection() as conn_w:
                                conn_w.execute("UPDATE class_session SET is_live = 0, ended_at = ? WHERE id = 1", (now_str,))
                                conn_w.commit()
                        except Exception as e:
                            print(f"Error ending live class: {e}")

                        if is_supabase_active():
                            supabase_request("PATCH", "class_session", {"is_live": 0, "ended_at": now_str}, params="id=eq.1")

                        st.warning("Live class ended. Students are back to offline status.")
                        st.rerun()

        with col_st3:
            st.link_button("📂 Open Class Recordings Drive Folder (Upload Here)", DEFAULT_DRIVE_FOLDER_URL, use_container_width=True)

        st.markdown("---")

        if is_live:
            # Active in-app classroom embed with fullscreen and screen recorder buttons
            render_jitsi_classroom(
                domain=server,
                room_name=room_name,
                display_name=f"{st.session_state.name} (Teacher)",
                is_teacher=True
            )
        else:
            st.info("💡 To begin teaching, configure your topic and click **'Start Live Broadcast'** above.")

        st.markdown("---")
        with st.expander("📅 Class Scheduler & Pre-Class Waiting Lounge Queue", expanded=not is_live):
            render_class_scheduler_widget(is_admin=False)

    # ---------------------------------------------
    # TEACHER TAB 2: RECORDED CLASSES (GOOGLE DRIVE)
    # ---------------------------------------------
    with tab_recordings:
        st.subheader("Google Drive Recorded Classes & Study Library")
        st.caption("All class recordings dropped into your Google Drive folder automatically appear below for you and all students in real time.")

        # Embedded Google Drive Folder Viewer: real-time auto-sync
        render_embedded_drive_folder(
            folder_id=DEFAULT_DRIVE_FOLDER_ID,
            folder_url=DEFAULT_DRIVE_FOLDER_URL,
            title="Class Recordings Google Drive Folder",
            key_suffix="teacher"
        )
        st.markdown("---")

        # Quick Actions & Direct Auto-Uploader
        col_up_btn1, col_up_btn2 = st.columns([1.5, 1])
        with col_up_btn1:
            st.link_button("📂 Open Class Recordings Drive Folder (Upload Here)", DEFAULT_DRIVE_FOLDER_URL, type="primary", use_container_width=True)
            st.caption("Click to open the Google Drive folder in a new tab and drop your downloaded recording files directly.")
        with col_up_btn2:
            st.info(f"📁 Folder ID: `{DEFAULT_DRIVE_FOLDER_ID}`")

        with st.expander("☁️ Direct Google Drive Video Auto-Uploader (Service Account)", expanded=False):
            st.write("Upload a recorded `.webm`, `.mp4`, or `.mkv` file directly into your Google Drive folder from here:")
            uploaded_file = st.file_uploader("Upload Recording Directly to Google Drive Folder", type=["webm", "mp4", "mkv"], key="teacher_drive_uploader")
            if uploaded_file is not None:
                up_col1, up_col2 = st.columns([1.5, 1])
                with up_col1:
                    up_title = st.text_input("Recording Title", value=uploaded_file.name.rsplit(".", 1)[0], key="auto_up_title")
                with up_col2:
                    up_sub = st.selectbox("Subject", ["Mathematics", "Physics", "Chemistry", "Biology", "English", "General Coaching"], key="auto_up_sub")

                if st.button("🚀 Upload File to Google Drive Folder", type="primary", use_container_width=True, key="btn_auto_up"):
                    with st.spinner("Uploading video to Google Drive folder..."):
                        ok, web_link, err_msg = upload_file_to_google_drive(uploaded_file, uploaded_file.name, DEFAULT_DRIVE_FOLDER_ID)
                        if ok:
                            embed_url, download_url = process_google_drive_link(web_link)
                            now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                            today_str = str(datetime.date.today())
                            try:
                                with get_db_connection() as conn_w:
                                    conn_w.execute("""
                                    INSERT INTO recordings (title, subject, lecture_date, description, drive_link, embed_url, download_url, created_at)
                                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                                    """, (up_title, up_sub, today_str, f"Auto-uploaded: {uploaded_file.name}", web_link, embed_url, download_url, now_str))
                                    conn_w.commit()
                            except Exception as e:
                                print(f"Error saving auto-uploaded recording: {e}")

                            if is_supabase_active():
                                supabase_request("POST", "recordings", {
                                    "title": up_title, "subject": up_sub, "lecture_date": today_str,
                                    "description": f"Auto-uploaded: {uploaded_file.name}", "drive_link": web_link,
                                    "embed_url": embed_url, "download_url": download_url, "created_at": now_str
                                })

                            st.success(f"Video uploaded to Google Drive! Link: {web_link}")
                            st.rerun()
                        else:
                            st.warning(f"Notice: {err_msg}")
                            st.markdown(f"""
                            💡 **Quick Alternative:** Click **[📂 Open Class Recordings Drive Folder (Upload Here)]({DEFAULT_DRIVE_FOLDER_URL})** to drag & drop your video directly into the folder. Once uploaded, it instantly appears in the embedded viewer above!
                            """)

        st.markdown("---")
        st.markdown("#### 🎬 Spotlight Individual Video Player")
        st.caption("You can also add an individual Google Drive or YouTube sharing link below to highlight specific lessons in the student player.")

        col_r1, col_r2 = st.columns([1.2, 1.8])

        with col_r1:
            st.markdown("### ➕ Publish Recorded Lecture")
            with st.form("add_rec_form", clear_on_submit=True):
                r_title = st.text_input("Lecture Title", placeholder="e.g. Chapter 4: Chemical Bonding")
                r_subject = st.selectbox("Subject", ["Mathematics", "Physics", "Chemistry", "Biology", "English", "General Coaching"])
                r_date = st.date_input("Class Date", datetime.date.today())
                r_link = st.text_input("Google Drive / YouTube Link", placeholder="https://drive.google.com/file/d/FILE_ID/view?usp=sharing")
                r_desc = st.text_area("Notes / Summary", placeholder="Topics covered, homework exercises, formulas...")
                submit_rec = st.form_submit_button("Publish Recording", type="primary", use_container_width=True)

                if submit_rec:
                    if not r_title or not r_link:
                        st.error("Title and Video link are required.")
                    else:
                        embed_url, download_url = process_google_drive_link(r_link)
                        now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                        try:
                            with get_db_connection() as conn_w:
                                conn_w.execute("""
                                INSERT INTO recordings (title, subject, lecture_date, description, drive_link, embed_url, download_url, created_at)
                                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                                """, (r_title, r_subject, str(r_date), r_desc, r_link, embed_url, download_url, now_str))
                                conn_w.commit()
                        except Exception as e:
                            print(f"Error publishing recording: {e}")

                        if is_supabase_active():
                            supabase_request("POST", "recordings", {
                                "title": r_title, "subject": r_subject, "lecture_date": str(r_date),
                                "description": r_desc, "drive_link": r_link, "embed_url": embed_url,
                                "download_url": download_url, "created_at": now_str
                            })

                        st.success("Recording published successfully!")
                        st.rerun()

        with col_r2:
            st.markdown("### 📋 Published Library")
            all_recs = []
            if is_supabase_active():
                ok, rows = supabase_request("GET", "recordings", params="order=id.desc&select=*")
                if ok:
                    all_recs = rows

            if not all_recs:
                c.execute("SELECT * FROM recordings ORDER BY id DESC")
                all_recs = [dict(r) for r in c.fetchall()]

            if not all_recs:
                st.info("No recordings added yet.")
            else:
                for rec in all_recs:
                    with st.expander(f"🎬 {rec['title']} ({rec['subject']} - {rec['lecture_date']})"):
                        st.write(f"**Notes:** {rec.get('description') or 'No notes added.'}")
                        
                        col_l1, col_l2 = st.columns([1.5, 1])
                        with col_l1:
                            st.link_button("📥 Direct Download Link", rec['download_url'], use_container_width=True)
                        with col_l2:
                            with st.form(f"del_rec_form_{rec['id']}"):
                                if st.form_submit_button("🗑️ Delete Recording", use_container_width=True):
                                    try:
                                        with get_db_connection() as conn_w:
                                            conn_w.execute("DELETE FROM recordings WHERE id = ?", (rec['id'],))
                                            conn_w.commit()
                                    except Exception as e:
                                        print(f"Error deleting recording: {e}")
                                    if is_supabase_active():
                                        supabase_request("DELETE", "recordings", params=f"id=eq.{rec['id']}")
                                    st.success("Deleted recording.")
                                    st.rerun()

                        if "drive.google.com" in rec['embed_url'] or "youtube.com" in rec['embed_url']:
                            st.markdown(f"""
                            <iframe src="{rec['embed_url']}" width="100%" height="320" frameborder="0" allow="autoplay; fullscreen" allowfullscreen style="border-radius:8px; border:1px solid #cbd5e1; margin-top:8px;"></iframe>
                            """, unsafe_allow_html=True)

    # ---------------------------------------------
    # TEACHER TAB 2.5: FEES MANAGEMENT
    # ---------------------------------------------
    with tab_fees:
        render_fees_management(is_admin=False)

    # ---------------------------------------------
    # TEACHER TAB 3: NOTICE BOARD
    # ---------------------------------------------
    with tab_notices:
        st.subheader("Notice Board & Announcement Alerts")

        col_n1, col_n2 = st.columns([1.2, 1.8])

        with col_n1:
            st.markdown("### 📢 Post New Announcement")
            with st.form("post_notice_form", clear_on_submit=True):
                n_title = st.text_input("Notice Title", placeholder="e.g. Science Test on Saturday")
                n_priority = st.selectbox("Priority / Category", ["Important", "Exam", "Holiday", "Normal"])
                n_msg = st.text_area("Notice Message", placeholder="Please revise chapter 3 formulas...")
                btn_n = st.form_submit_button("Publish Notice", type="primary", use_container_width=True)

                if btn_n:
                    if not n_title or not n_msg:
                        st.error("Title and message are required.")
                    else:
                        now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                        try:
                            with get_db_connection() as conn_w:
                                conn_w.execute("""
                                INSERT INTO announcements (title, message, priority, created_at)
                                VALUES (?, ?, ?, ?)
                                """, (n_title, n_msg, n_priority, now_str))
                                conn_w.commit()
                        except Exception as e:
                            print(f"Error publishing announcement: {e}")

                        if is_supabase_active():
                            supabase_request("POST", "announcements", {
                                "title": n_title, "message": n_msg, "priority": n_priority, "created_at": now_str
                            })

                        st.success("Notice posted!")
                        st.rerun()

        with col_n2:
            st.markdown("### 📌 Active Notices")
            notices = []
            if is_supabase_active():
                ok, rows = supabase_request("GET", "announcements", params="order=id.desc&select=*")
                if ok:
                    notices = rows

            if not notices:
                c.execute("SELECT * FROM announcements ORDER BY id DESC")
                notices = [dict(r) for r in c.fetchall()]

            if not notices:
                st.info("No active notices.")
            else:
                for n in notices:
                    badge_cls = "notice-card"
                    if n.get('priority') == 'Important': badge_cls += " notice-important"
                    elif n.get('priority') == 'Exam': badge_cls += " notice-exam"
                    elif n.get('priority') == 'Holiday': badge_cls += " notice-holiday"

                    st.markdown(f"""
                    <div class="{badge_cls}">
                        <div style="display:flex; justify-content:space-between; align-items:center;">
                            <h4 style="margin:0; color:#1e293b;">{n['title']}</h4>
                            <span style="font-size:0.8rem; background:#cbd5e1; padding:2px 8px; border-radius:12px; font-weight:600;">{n.get('priority', 'Normal')}</span>
                        </div>
                        <p style="margin:6px 0 2px 0; color:#475569;">{n['message']}</p>
                        <small style="color:#94a3b8;">Posted: {n['created_at']}</small>
                    </div>
                    """, unsafe_allow_html=True)

                    with st.form(f"del_not_{n['id']}"):
                        if st.form_submit_button("Delete Notice", use_container_width=False):
                            try:
                                with get_db_connection() as conn_w:
                                    conn_w.execute("DELETE FROM announcements WHERE id = ?", (n['id'],))
                                    conn_w.commit()
                            except Exception as e:
                                print(f"Error deleting announcement: {e}")
                            if is_supabase_active():
                                supabase_request("DELETE", "announcements", params=f"id=eq.{n['id']}")
                            st.rerun()

    # ---------------------------------------------
    # TEACHER TAB 4: DOUBTS & CHAT
    # ---------------------------------------------
    with tab_doubts:
        st.subheader("Student Doubts & Questions")
        doubts = []
        if is_supabase_active():
            ok, rows = supabase_request("GET", "doubts", params="order=id.desc&select=*")
            if ok:
                doubts = rows

        if not doubts:
            c.execute("SELECT * FROM doubts ORDER BY id DESC")
            doubts = [dict(r) for r in c.fetchall()]

        if not doubts:
            st.info("No doubts submitted by students yet.")
        else:
            for d in doubts:
                with st.expander(f"❓ [{d.get('subject')}] {d.get('student_name')} (@{d.get('student_username')}) - {d.get('status')}"):
                    st.write(f"**Question:** {d['question']}")
                    st.caption(f"Submitted on: {d['created_at']}")

                    if d.get('reply'):
                        st.markdown(f"""
                        <div style="background:#f0fdf4; border-left:4px solid #10b981; padding:10px 14px; border-radius:6px; margin:8px 0;">
                            <b>Your Answer:</b> {d['reply']}<br>
                            <small style="color:#64748b;">Answered at: {d.get('replied_at')}</small>
                        </div>
                        """, unsafe_allow_html=True)

                    with st.form(f"rep_form_{d['id']}"):
                        reply_val = st.text_area("Your Explanation / Answer", value=d.get('reply') or "")
                        col_rb1, col_rb2 = st.columns([1, 1])
                        with col_rb1:
                            sub_ans = st.form_submit_button("Save & Send Answer", type="primary", use_container_width=True)
                        with col_rb2:
                            del_doubt = st.form_submit_button("Remove Doubt", use_container_width=True)

                        if sub_ans:
                            if reply_val.strip():
                                now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                                try:
                                    with get_db_connection() as conn_w:
                                        conn_w.execute("""
                                        UPDATE doubts SET reply = ?, status = 'Answered', replied_at = ? WHERE id = ?
                                        """, (reply_val.strip(), now_str, d['id']))
                                        conn_w.commit()
                                except Exception as e:
                                    print(f"Error answering doubt: {e}")
                                if is_supabase_active():
                                    supabase_request("PATCH", "doubts", {
                                        "reply": reply_val.strip(), "status": "Answered", "replied_at": now_str
                                    }, params=f"id=eq.{d['id']}")
                                st.success("Answer published to student!")
                                st.rerun()
                            else:
                                st.error("Response cannot be empty.")

                        if del_doubt:
                            try:
                                with get_db_connection() as conn_w:
                                    conn_w.execute("DELETE FROM doubts WHERE id = ?", (d['id'],))
                                    conn_w.commit()
                            except Exception as e:
                                print(f"Error deleting doubt: {e}")
                            if is_supabase_active():
                                supabase_request("DELETE", "doubts", params=f"id=eq.{d['id']}")
                            st.warning("Doubt removed.")
                            st.rerun()

    # ---------------------------------------------
    # TEACHER TAB 5: ATTENDANCE & STUDENT ACCOUNTS
    # ---------------------------------------------
    with tab_students:
        st.subheader("Attendance Records & Student Account Administration")

        sub_att, sub_acc = st.tabs(["📊 Live Attendance Logs", "👤 Student Accounts & Access Control"])

        with sub_att:
            st.markdown("### 📋 Attendance Records")
            records_data = []
            if is_supabase_active():
                ok, rows = supabase_request("GET", "attendance", params="order=id.desc&select=*")
                if ok:
                    records_data = rows

            if not records_data:
                c.execute("SELECT id, student_name, student_username, room_name, topic, join_timestamp, date FROM attendance ORDER BY id DESC")
                records_data = [dict(r) for r in c.fetchall()]

            if not records_data:
                st.info("No attendance entries logged yet. Students are logged automatically when clicking 'Join Live Class'.")
            else:
                st.dataframe(records_data, use_container_width=True, hide_index=True)

                csv_output = io.StringIO()
                csv_writer = csv.DictWriter(csv_output, fieldnames=['id', 'student_name', 'student_username', 'room_name', 'topic', 'join_timestamp', 'date'])
                csv_writer.writeheader()
                csv_writer.writerows(records_data)

                st.download_button(
                    label="📥 Export Attendance as CSV",
                    data=csv_output.getvalue(),
                    file_name=f"Sisters_Academy_Attendance_{datetime.date.today()}.csv",
                    mime="text/csv",
                    type="primary"
                )

        with sub_acc:
            col_u1, col_u2 = st.columns([1.2, 1.8])

            with col_u1:
                st.markdown("#### ➕ Add New Student")
                st.caption("ℹ️ *Note: Teacher and Admin accounts can only be created and managed by the Super Admin.*")
                with st.form("new_st_form", clear_on_submit=True):
                    n_un = st.text_input("Username", placeholder="e.g. student11").strip().lower()
                    n_fn = st.text_input("Full Name", placeholder="e.g. Sara Ahmed")
                    n_pw = st.text_input("Initial Password", value="pass123")
                    btn_add = st.form_submit_button("Register Student", type="primary", use_container_width=True)

                    if btn_add:
                        if not n_un or not n_fn or not n_pw:
                            st.error("All fields are required.")
                        else:
                            pw_h = hash_password(n_pw)
                            now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                            try:
                                with get_db_connection() as conn_w:
                                    conn_w.execute("""
                                    INSERT INTO users (username, password, password_hash, role, full_name, is_active, created_at)
                                    VALUES (?, ?, ?, 'student', ?, 1, ?)
                                    """, (n_un, n_pw, pw_h, n_fn, now_str))
                                    conn_w.commit()

                                if is_supabase_active():
                                    supabase_request("POST", "users", {
                                        "username": n_un, "password": n_pw, "password_hash": pw_h, "role": "student",
                                        "full_name": n_fn, "is_active": 1, "created_at": now_str
                                    })

                                st.success(f"Student {n_fn} (@{n_un}) registered successfully!")
                                st.rerun()
                            except sqlite3.IntegrityError:
                                st.error(f"Username '{n_un}' is already taken.")
                            except Exception as e:
                                st.error(f"Error registering student: {e}")

            with col_u2:
                st.markdown("#### 🔒 Student List & Access Controls")
                st_list = []
                if is_supabase_active():
                    ok, rows = supabase_request("GET", "users", params="role=eq.student&order=id.asc&select=*")
                    if ok:
                        st_list = rows

                if not st_list:
                    c.execute("SELECT id, username, password, full_name, is_active, created_at FROM users WHERE role = 'student' ORDER BY id ASC")
                    st_list = [dict(r) for r in c.fetchall()]

                for s in st_list:
                    status_lbl = "🟢 Active" if s.get('is_active', 1) == 1 else "🔴 Blocked / Suspended"
                    cur_pwd = s.get('password') or "pass123"
                    with st.expander(f"{s['full_name']} (@{s['username']}) - {status_lbl}"):
                        st.caption(f"🔑 **Current Password:** `{cur_pwd}`")
                        c_b1, c_b2, c_b3 = st.columns([1, 1, 1])

                        with c_b1:
                            with st.form(f"blk_form_{s['id']}"):
                                if s.get('is_active', 1) == 1:
                                    if st.form_submit_button("🚫 Block Student", use_container_width=True):
                                        try:
                                            with get_db_connection() as conn_w:
                                                conn_w.execute("UPDATE users SET is_active = 0 WHERE id = ?", (s['id'],))
                                                conn_w.commit()
                                        except Exception as e:
                                            print(f"Error blocking user: {e}")
                                        if is_supabase_active():
                                            supabase_request("PATCH", "users", {"is_active": 0}, params=f"id=eq.{s['id']}")
                                        st.warning(f"Blocked @{s['username']}.")
                                        st.rerun()
                                else:
                                    if st.form_submit_button("✅ Unblock Student", use_container_width=True):
                                        try:
                                            with get_db_connection() as conn_w:
                                                conn_w.execute("UPDATE users SET is_active = 1 WHERE id = ?", (s['id'],))
                                                conn_w.commit()
                                        except Exception as e:
                                            print(f"Error unblocking user: {e}")
                                        if is_supabase_active():
                                            supabase_request("PATCH", "users", {"is_active": 1}, params=f"id=eq.{s['id']}")
                                        st.success(f"Unblocked @{s['username']}.")
                                        st.rerun()

                        with c_b2:
                            with st.form(f"rst_form_{s['id']}"):
                                new_p = st.text_input("New Password", value=cur_pwd)
                                if st.form_submit_button("🔑 Reset Pass", use_container_width=True):
                                    pwd_res = hash_password(new_p)
                                    try:
                                        with get_db_connection() as conn_w:
                                            conn_w.execute("UPDATE users SET password = ?, password_hash = ? WHERE id = ?", (new_p, pwd_res, s['id']))
                                            conn_w.commit()
                                    except Exception as e:
                                        print(f"Error resetting password: {e}")
                                    if is_supabase_active():
                                        supabase_request("PATCH", "users", {"password": new_p, "password_hash": pwd_res}, params=f"id=eq.{s['id']}")
                                    st.success(f"Password reset for @{s['username']}.")
                                    st.rerun()

                        with c_b3:
                            with st.form(f"del_st_form_{s['id']}"):
                                if st.form_submit_button("🗑️ Delete Account", use_container_width=True):
                                    try:
                                        with get_db_connection() as conn_w:
                                            conn_w.execute("DELETE FROM users WHERE id = ?", (s['id'],))
                                            conn_w.commit()
                                    except Exception as e:
                                        print(f"Error deleting user: {e}")
                                    if is_supabase_active():
                                        supabase_request("DELETE", "users", params=f"id=eq.{s['id']}")
                                    st.success("Student removed.")
                                    st.rerun()

    # ---------------------------------------------
    # TEACHER TAB 6: SUPABASE CLOUD STATUS
    # ---------------------------------------------
    with tab_cloud:
        st.subheader("☁️ Supabase Cloud Storage Status")
        supabase_on = is_supabase_active()
        url_cfg, key_cfg = get_supabase_config()

        if supabase_on:
            st.success("🎉 Supabase Cloud Database is CONNECTED & ACTIVE! All students, attendance, doubts, and recordings are permanently saved in the cloud.")
            st.write(f"**Connected Supabase Project URL:** `{url_cfg}`")
        else:
            st.warning("⚠️ Currently using local SQLite database. To enable permanent Cloud storage across all device restarts:")
            st.markdown("""
            1. Open your Supabase SQL Editor:
            """)
            st.link_button("👉 Open Supabase SQL Editor", "https://supabase.com/dashboard/project/qxfuebpmspwixaylddby/sql/new", type="primary")
            st.markdown("""
            2. Copy the SQL script below, paste it into the editor, and click **RUN**:
            """)
            
            try:
                with open("supabase_schema.sql", "r") as f:
                    sql_content = f.read()
            except Exception:
                sql_content = "-- Run supabase_schema.sql from your repository"

            st.code(sql_content, language="sql")
            st.info("Once you click RUN in Supabase, refresh this page. Cloud Storage will automatically turn GREEN!")

    # Close connection cleanly
    try:
        conn.close()
    except Exception:
        pass


# ==========================================
# 8. STUDENT DASHBOARD

# ==========================================
def render_student_dashboard():
    conn = get_db()
    c = conn.cursor()

    st.markdown(f"""
    <div class="hero-banner">
        <h1>👋 Welcome, {st.session_state.name}!</h1>
        <p>Sister's Live Academy Student Portal | Roll No: @{st.session_state.username}</p>
    </div>
    """, unsafe_allow_html=True)

    # 1. Top Notice Board
    notices = []
    if is_supabase_active():
        ok, rows = supabase_request("GET", "announcements", params="order=id.desc&limit=2&select=*")
        if ok:
            notices = rows

    if not notices:
        c.execute("SELECT * FROM announcements ORDER BY id DESC LIMIT 2")
        notices = [dict(r) for r in c.fetchall()]

    if notices:
        for n in notices:
            badge_cls = "notice-card"
            icon = "📢"
            if n.get('priority') == 'Important': badge_cls += " notice-important"; icon = "🚨"
            elif n.get('priority') == 'Exam': badge_cls += " notice-exam"; icon = "📝"
            elif n.get('priority') == 'Holiday': badge_cls += " notice-holiday"; icon = "🏖️"

            st.markdown(f"""
            <div class="{badge_cls}">
                <div style="display:flex; justify-content:space-between;">
                    <b style="color:#1e293b;">{icon} {n['title']}</b>
                    <span style="font-size:0.8rem; background:#cbd5e1; padding:2px 8px; border-radius:12px; font-weight:600;">{n.get('priority', 'Normal')}</span>
                </div>
                <p style="margin:4px 0 0 0; color:#475569; font-size:0.95rem;">{n['message']}</p>
            </div>
            """, unsafe_allow_html=True)

    # 2. Fee Dues Notification Banner
    c.execute("SELECT * FROM fees WHERE student_username = ? AND status = 'Pending' ORDER BY due_date ASC", (st.session_state.username,))
    pending_fees = [dict(r) for r in c.fetchall()]
    if pending_fees:
        total_due_amt = sum(int(str(f['amount']).replace(',', '')) for f in pending_fees if str(f.get('amount', '')).replace(',', '').isdigit())
        due_items = ", ".join([f"{f['month_title']} (₹{f['amount']})" for f in pending_fees[:2]])
        st.markdown(f"""
        <div style="background: linear-gradient(135deg, #fff1f2 0%, #fee2e2 100%); border-left: 5px solid #ef4444; padding: 14px 18px; border-radius: 10px; margin-bottom: 16px; box-shadow: 0 4px 12px rgba(239, 68, 68, 0.12);">
            <div style="display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: 8px;">
                <div>
                    <b style="color: #991b1b; font-size: 1.05rem;">🔔 Pending Tuition Fee Reminder:</b>
                    <span style="color: #7f1d1d; font-size: 0.95rem; margin-left: 6px;">
                        You have <b>{len(pending_fees)} pending invoice(s)</b> totaling <b style="color:#b91c1c; font-size:1.05rem;">₹{total_due_amt:,}</b> ({due_items}).
                    </span>
                </div>
                <span style="font-size: 0.8rem; background: #ef4444; color: white; padding: 4px 12px; border-radius: 9999px; font-weight: 700; letter-spacing: 0.5px;">ACTION REQUIRED</span>
            </div>
            <div style="color: #b91c1c; font-size: 0.88rem; margin-top: 6px;">
                Please clear your monthly tuition dues on time via UPI/Cash to maintain continuous access to all academy features. Click the <b>💳 My Fee Portal</b> tab below to view your full fee receipt and payment instructions.
            </div>
        </div>
        """, unsafe_allow_html=True)

    tab_live, tab_library, tab_fees, tab_doubts, tab_att = st.tabs([
        "🎥 Live Classroom",
        "📖 Recorded Lectures & Notes",
        "💳 My Fee Portal",
        "❓ Ask Doubts & Discussion",
        "📊 My Attendance"
    ])

    # ---------------------------------------------
    # STUDENT TAB 1: LIVE CLASSROOM
    # ---------------------------------------------
    with tab_live:
        sess = {}
        if is_supabase_active():
            ok, rows = supabase_request("GET", "class_session", params="id=eq.1&select=*")
            if ok and rows:
                sess = rows[0]

        if not sess:
            c.execute("SELECT * FROM class_session WHERE id = 1")
            raw_sess = c.fetchone()
            sess = dict(raw_sess) if raw_sess else {}

        is_live = bool(sess.get('is_live', 0))
        room_name = sess.get('room_name') or 'SistersLiveClass_MasterRoom'
        session_topic = sess.get('topic') or 'General Coaching Session'
        server = sess.get('server') or "meet.ffmuc.net"
        teacher_notes = sess.get('teacher_notes') or ""

        if not is_live:
            # Query upcoming scheduled classes
            sched_classes = []
            if is_supabase_active():
                ok, rows = supabase_request("GET", "scheduled_classes", params="status=eq.Scheduled&order=scheduled_date.asc,scheduled_time.asc&limit=3&select=*")
                if ok and rows:
                    sched_classes = rows

            if not sched_classes:
                c.execute("SELECT * FROM scheduled_classes WHERE status = 'Scheduled' ORDER BY scheduled_date ASC, scheduled_time ASC LIMIT 3")
                sched_classes = [dict(r) for r in c.fetchall()]

            next_class = sched_classes[0] if sched_classes else None
            is_in_waiting_lounge = st.session_state.get('in_waiting_lounge', False)

            if is_in_waiting_lounge and next_class:
                # Student is inside the pre-class waiting lounge!
                st.markdown(f"""
                <div class="glass-card" style="border: 2px solid #0284c7; background: #f0f9ff; margin-bottom: 14px;">
                    <div style="display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 8px;">
                        <div class="live-badge" style="background: #0284c7;">
                            <span class="live-dot" style="background: #38bdf8;"></span>
                            <span>🛋️ PRE-CLASS WAITING LOUNGE ACTIVE</span>
                        </div>
                        <span style="font-size: 0.85rem; color: #0369a1; font-weight: 600;">
                            ⏰ Scheduled for {next_class['scheduled_date']} at {next_class['scheduled_time']}
                        </span>
                    </div>
                    <h3 style="margin: 8px 0 4px 0; color: #0c4a6e;">{next_class['topic']}</h3>
                    <p style="margin: 0; color: #0369a1; font-size: 0.92rem;">
                        <b>Conducted by:</b> {next_class['teacher_name']} &nbsp;|&nbsp; 
                        <b>Instructions:</b> {next_class.get('notes') or 'Waiting lounge is open. Test your audio and chat with classmates!'}
                    </p>
                </div>
                """, unsafe_allow_html=True)

                col_w1, col_w2 = st.columns([3, 1])
                with col_w2:
                    with st.form("leave_waiting_lounge_form"):
                        if st.form_submit_button("🚪 Leave Waiting Lounge", use_container_width=True):
                            st.session_state.in_waiting_lounge = False
                            st.rerun()

                # Render embedded room for pre-class student discussion
                wl_room = next_class.get('room_name') or room_name
                render_jitsi_classroom(
                    domain=server,
                    room_name=wl_room,
                    display_name=f"{st.session_state.name} (Student - Waiting Lounge)",
                    is_teacher=False
                )

            else:
                st.markdown("""
                <div class="glass-card" style="text-align: center; padding: 24px 20px 18px 20px; margin-bottom: 15px;">
                    <div class="offline-badge" style="font-size: 0.95rem; padding: 6px 18px; margin-bottom: 8px;">
                        ⚪ Live Broadcast is Currently Offline
                    </div>
                    <h3 style="color: #334155; margin-bottom: 4px;">No live broadcast active right now.</h3>
                    <p style="color: #64748b; max-width: 520px; margin: 0 auto; font-size: 0.92rem;">
                        Classes start according to the schedule below. When the waiting lounge is open, enter early to discuss with your classmates!
                    </p>
                </div>
                """, unsafe_allow_html=True)

                if next_class:
                    allow_wl = next_class.get('allow_waiting_room', 1) == 1
                    wl_status_pill = '<span style="background: #10b981; color: white; padding: 3px 10px; border-radius: 9999px; font-weight: 700; font-size: 0.78rem;">🛋️ WAITING LOUNGE OPEN</span>' if allow_wl else '<span style="background: #64748b; color: white; padding: 3px 10px; border-radius: 9999px; font-weight: 700; font-size: 0.78rem;">WAITING LOUNGE CLOSED</span>'

                    st.markdown(f"""
                    <div style="background: linear-gradient(135deg, #f0f9ff 0%, #e0f2fe 100%); border: 1.5px solid #38bdf8; border-radius: 14px; padding: 18px 22px; margin-bottom: 14px; box-shadow: 0 4px 15px rgba(2, 132, 199, 0.08);">
                        <div style="display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 8px;">
                            <div>
                                <span style="font-size: 0.8rem; background: #0284c7; color: white; padding: 3px 10px; border-radius: 6px; font-weight: 700;">UPCOMING NEXT CLASS</span>
                                <span style="margin-left: 8px; font-size: 0.9rem; color: #0369a1; font-weight: 600;">📅 {next_class['scheduled_date']} at {next_class['scheduled_time']}</span>
                            </div>
                            {wl_status_pill}
                        </div>
                        <h3 style="margin: 10px 0 4px 0; color: #0c4a6e;">{next_class['topic']}</h3>
                        <p style="margin: 0; color: #0369a1; font-size: 0.92rem;">
                            <b>Subject:</b> {next_class['subject']} &nbsp;|&nbsp; 
                            <b>Teacher:</b> {next_class['teacher_name']} &nbsp;|&nbsp; 
                            <b>Note:</b> {next_class.get('notes') or 'No special instructions.'}
                        </p>
                    </div>
                    """, unsafe_allow_html=True)

                    if allow_wl:
                        col_wl1, col_wl2, col_wl3 = st.columns([1, 2, 1])
                        with col_wl2:
                            with st.form("enter_waiting_lounge_form"):
                                btn_enter_wl = st.form_submit_button("🛋️ Enter Student Waiting Lounge Early (Discuss & Wait)", type="primary", use_container_width=True)
                                if btn_enter_wl:
                                    st.session_state.in_waiting_lounge = True
                                    st.rerun()

                if len(sched_classes) > 1:
                    with st.expander("📅 View More Upcoming Scheduled Classes"):
                        for sc_item in sched_classes[1:]:
                            st.markdown(f"""
                            - **[{sc_item['subject']}] {sc_item['topic']}** — Conducted by *{sc_item['teacher_name']}*  
                              📅 **Date & Time:** {sc_item['scheduled_date']} at {sc_item['scheduled_time']} | Note: {sc_item.get('notes', 'None')}
                            """)

            st.session_state.live_joined = False
            st.session_state.joined_live_class = False
        else:
            host_teacher = sess.get('host_teacher') or "Teacher"
            st.markdown(f"""
            <div class="glass-card" style="border: 2px solid #f87171; background: #fff5f5;">
                <div class="live-badge">
                    <span class="live-dot"></span>
                    <span>🔴 LIVE NOW with {host_teacher}!</span>
                </div>
                <h3 style="margin: 8px 0 4px 0; color: #1e293b;">{session_topic}</h3>
                <p style="margin: 0; color: #475569;"><b>Conducted By:</b> {host_teacher} &nbsp;|&nbsp; <b>Instructions:</b> {teacher_notes}</p>
            </div>
            """, unsafe_allow_html=True)

            is_already_joined = st.session_state.get("live_joined", False) or st.session_state.get("joined_live_class", False)
            if not is_already_joined:
                col_j1, col_j2, col_j3 = st.columns([1, 2, 1])
                with col_j2:
                    with st.form("join_live_form"):
                        btn_join = st.form_submit_button("🚀 Join Live Class Now (Logs Attendance)", type="primary", use_container_width=True)
                        if btn_join:
                            # Fail-safe attendance logging: even if DB encounters locks/delays,
                            # NEVER block the student from joining!
                            try:
                                now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                                today_str = str(datetime.date.today())
                                with get_db_connection() as att_conn:
                                    att_c = att_conn.cursor()
                                    att_c.execute("""
                                    SELECT id FROM attendance WHERE student_username = ? AND date = ? AND room_name = ?
                                    """, (st.session_state.username, today_str, room_name))
                                    if not att_c.fetchone():
                                        att_c.execute("""
                                        INSERT INTO attendance (student_username, student_name, room_name, topic, join_timestamp, date)
                                        VALUES (?, ?, ?, ?, ?, ?)
                                        """, (st.session_state.username, st.session_state.name, room_name, session_topic, now_str, today_str))
                                        att_conn.commit()

                                if is_supabase_active():
                                    supabase_request("POST", "attendance", {
                                        "student_username": st.session_state.username,
                                        "student_name": st.session_state.name,
                                        "room_name": room_name,
                                        "topic": session_topic,
                                        "join_timestamp": now_str,
                                        "date": today_str
                                    })
                            except Exception as att_err:
                                print(f"Non-critical attendance log error: {att_err}")

                            st.session_state.live_joined = True
                            st.session_state.joined_live_class = True
                            st.rerun()
            else:

                st.success("✅ Attendance recorded! You are in the live room.")

                # Active in-app classroom embed with fullscreen button (no external redirects)
                render_jitsi_classroom(
                    domain=server,
                    room_name=room_name,
                    display_name=f"{st.session_state.name} (Student)",
                    is_teacher=False
                )


                with st.form("leave_live_form"):
                    if st.form_submit_button("Leave Live Room"):
                        st.session_state.live_joined = False
                        st.session_state.joined_live_class = False
                        st.rerun()

    # ---------------------------------------------
    # STUDENT TAB 2: RECORDED LECTURES
    # ---------------------------------------------
    with tab_library:
        st.subheader("📚 Study Library & Recorded Classes")

        # Embedded Google Drive Folder Viewer: real-time auto-sync for all students
        render_embedded_drive_folder(
            folder_id=DEFAULT_DRIVE_FOLDER_ID,
            folder_url=DEFAULT_DRIVE_FOLDER_URL,
            title="📚 Class Recordings & Notes Google Drive Folder",
            key_suffix="student"
        )
        st.markdown("---")
        st.markdown("#### 🔍 Spotlight Lectures & In-App Player")

        col_s1, col_s2 = st.columns([2, 1])
        with col_s1:
            q = st.text_input("🔍 Search Lectures", placeholder="Search by topic or title...")
        with col_s2:
            sub_filter = st.selectbox("Subject Filter", ["All Subjects", "Mathematics", "Physics", "Chemistry", "Biology", "English", "General Coaching"])

        recs = []
        if is_supabase_active():
            params = "order=id.desc&select=*"
            if sub_filter != "All Subjects":
                params += f"&subject=eq.{sub_filter}"
            ok, rows = supabase_request("GET", "recordings", params=params)
            if ok:
                if q:
                    recs = [r for r in rows if q.lower() in r.get('title', '').lower() or q.lower() in r.get('description', '').lower()]
                else:
                    recs = rows

        if not recs:
            sql = "SELECT * FROM recordings WHERE 1=1"
            sql_params = []
            if q:
                sql += " AND (title LIKE ? OR description LIKE ?)"
                sql_params.extend([f"%{q}%", f"%{q}%"])
            if sub_filter != "All Subjects":
                sql += " AND subject = ?"
                sql_params.append(sub_filter)
            sql += " ORDER BY id DESC"

            c.execute(sql, sql_params)
            recs = [dict(r) for r in c.fetchall()]

        if not recs:
            st.info("No recorded classes found matching your search.")
        else:
            for r in recs:
                st.markdown(f"""
                <div class="glass-card">
                    <div style="display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap;">
                        <h3 style="margin:0; color:#1e293b;">📖 {r['title']}</h3>
                        <span style="background:#e0e7ff; color:#3730a3; padding:2px 10px; border-radius:9999px; font-weight:600; font-size:0.85rem;">
                            {r.get('subject')} | {r.get('lecture_date')}
                        </span>
                    </div>
                    <p style="margin:8px 0; color:#475569;">{r.get('description') or 'No description provided.'}</p>
                </div>
                """, unsafe_allow_html=True)

                col_v, col_d = st.columns([2.5, 1])
                with col_v:
                    if "drive.google.com" in r['embed_url'] or "youtube.com" in r['embed_url']:
                        st.markdown(f"""
                        <iframe src="{r['embed_url']}" width="100%" height="340" frameborder="0" allow="autoplay; fullscreen" allowfullscreen style="border-radius:10px; border:1px solid #cbd5e1;"></iframe>
                        """, unsafe_allow_html=True)
                with col_d:
                    st.link_button("📥 Direct Download Video", r['download_url'], type="primary", use_container_width=True)
                    st.link_button("🔗 Open in Google Drive", r['drive_link'], use_container_width=True)
                    st.caption("Tip: Download to your phone or laptop for offline revision without buffering.")
                st.markdown("---")

    # ---------------------------------------------
    # STUDENT TAB 2.5: MY FEE PORTAL
    # ---------------------------------------------
    with tab_fees:
        render_student_fees_portal()

    # ---------------------------------------------
    # STUDENT TAB 3: ASK DOUBTS
    # ---------------------------------------------
    with tab_doubts:
        st.subheader("❓ Ask Doubts & Discussion Board")

        col_d1, col_d2 = st.columns([1.2, 1.8])

        with col_d1:
            st.markdown("### ✍️ Ask a Question")
            with st.form("ask_doubt_form", clear_on_submit=True):
                d_sub = st.selectbox("Subject", ["Mathematics", "Physics", "Chemistry", "Biology", "English", "General Coaching"])
                d_q = st.text_area("Your Doubt / Question", placeholder="Explain your question in detail...")
                btn_d = st.form_submit_button("Submit Question", type="primary", use_container_width=True)

                if btn_d:
                    if not d_q.strip():
                        st.error("Question cannot be empty.")
                    else:
                        now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                        try:
                            with get_db_connection() as conn_w:
                                conn_w.execute("""
                                INSERT INTO doubts (student_username, student_name, question, subject, created_at)
                                VALUES (?, ?, ?, ?, ?)
                                """, (st.session_state.username, st.session_state.name, d_q.strip(), d_sub, now_str))
                                conn_w.commit()
                        except Exception as e:
                            print(f"Error submitting doubt: {e}")

                        if is_supabase_active():
                            supabase_request("POST", "doubts", {
                                "student_username": st.session_state.username,
                                "student_name": st.session_state.name,
                                "question": d_q.strip(),
                                "subject": d_sub,
                                "created_at": now_str
                            })

                        st.success("Question submitted to Teacher!")
                        st.rerun()

        with col_d2:
            st.markdown("### 💬 Your Questions & Answers")
            my_doubts = []
            if is_supabase_active():
                ok, rows = supabase_request("GET", "doubts", params=f"student_username=eq.{st.session_state.username}&order=id.desc&select=*")
                if ok:
                    my_doubts = rows

            if not my_doubts:
                c.execute("SELECT * FROM doubts WHERE student_username = ? ORDER BY id DESC", (st.session_state.username,))
                my_doubts = [dict(r) for r in c.fetchall()]

            if not my_doubts:
                st.info("You haven't posted any doubts yet.")
            else:
                for md in my_doubts:
                    is_ans = md.get('status') == 'Answered'
                    st_badge = "🟢 Answered" if is_ans else "🟠 Awaiting Reply"

                    st.markdown(f"""
                    <div class="glass-card">
                        <div style="display:flex; justify-content:space-between;">
                            <b style="color:#1e293b;">[{md.get('subject')}]</b>
                            <span style="font-size:0.85rem; font-weight:600;">{st_badge}</span>
                        </div>
                        <p style="margin:6px 0; color:#334155;"><b>Question:</b> {md['question']}</p>
                        <small style="color:#94a3b8;">Posted: {md['created_at']}</small>
                    </div>
                    """, unsafe_allow_html=True)

                    if md.get('reply'):
                        st.markdown(f"""
                        <div style="background:#f0fdf4; border-left:4px solid #10b981; padding:10px 14px; border-radius:6px; margin-bottom:14px;">
                            <b style="color:#166534;">👩‍🏫 Teacher's Explanation:</b>
                            <p style="margin:4px 0; color:#14532d;">{md['reply']}</p>
                            <small style="color:#64748b;">Answered at: {md.get('replied_at')}</small>
                        </div>
                        """, unsafe_allow_html=True)

    # ---------------------------------------------
    # STUDENT TAB 4: MY ATTENDANCE
    # ---------------------------------------------
    with tab_att:
        st.subheader("📊 My Class Attendance")
        my_logs = []
        if is_supabase_active():
            ok, rows = supabase_request("GET", "attendance", params=f"student_username=eq.{st.session_state.username}&order=id.desc&select=*")
            if ok:
                my_logs = rows

        if not my_logs:
            c.execute("SELECT date, join_timestamp, topic, room_name FROM attendance WHERE student_username = ? ORDER BY id DESC", (st.session_state.username,))
            my_logs = [dict(r) for r in c.fetchall()]

        if not my_logs:
            st.info("No attendance recorded yet. Click 'Join Live Class' when the teacher is live to log your attendance.")
        else:
            st.write(f"**Total Live Classes Attended:** {len(my_logs)}")
            st.dataframe(my_logs, use_container_width=True, hide_index=True)

    # Close connection cleanly
    try:
        conn.close()
    except Exception:
        pass


# ==========================================
# 9. MAIN ROUTER & SIDEBAR

# ==========================================
def main():
    if not st.session_state.logged_in or not st.session_state.username:
        render_login_screen()
        return

    with st.sidebar:
        st.markdown("""
        <div style="text-align: center; padding: 10px 0;">
            <div style="font-size: 2.8rem; margin-bottom: 2px;">🎓</div>
            <h2 style="margin:0; font-size:1.25rem;">Sister's Live Academy</h2>
            <p style="color:#64748b; font-size:0.85rem; margin-top:2px;">Live Coaching Portal</p>
        </div>
        """, unsafe_allow_html=True)

        role_label = {
            'admin': '👑 Super Admin',
            'teacher': '👩‍🏫 Teacher',
            'student': '🎓 Student'
        }.get(st.session_state.role, str(st.session_state.role).capitalize())

        st.markdown(f"""
        <div style="background:#f1f5f9; padding:12px; border-radius:10px; margin-bottom:15px;">
            <div style="font-size:0.75rem; color:#64748b; text-transform:uppercase; font-weight:700;">Active Account</div>
            <div style="font-weight:700; color:#1e293b; font-size:1rem;">{st.session_state.name}</div>
            <div style="font-size:0.85rem; color:#4f46e5; font-weight:600;">{role_label} (@{st.session_state.username})</div>
        </div>
        """, unsafe_allow_html=True)

        # Storage indicator
        if is_supabase_active():
            st.success("🟢 Storage: Supabase Cloud Active")
        else:
            url_cfg, _ = get_supabase_config()
            if url_cfg:
                st.warning("🟡 Storage: Local SQLite (Run SQL schema to activate Supabase)")
            else:
                st.caption("Storage: **Local SQLite (classroom.db)**")

        # Server Selector
        server_options = ["jitsi.riot.im", "meet.jit.si", "framatalk.org"]
        curr_srv = st.session_state.jitsi_server if st.session_state.jitsi_server in server_options else "jitsi.riot.im"
        sel_srv = st.selectbox(
            "🌐 Video Server Selector",
            server_options,
            index=server_options.index(curr_srv),
            help="Select embed-friendly server if one is congested."
        )
        if sel_srv != st.session_state.jitsi_server:
            st.session_state.jitsi_server = sel_srv
            st.rerun()

        st.caption(f"Active Server: **{st.session_state.jitsi_server}**")


        st.markdown("---")

        # Self-Service Password Change for Teachers, Students & Admins
        with st.sidebar.expander("🔑 Change My Password"):
            with st.form("change_own_password_form", clear_on_submit=True):
                current_pwd = st.text_input("Current Password", type="password")
                new_pwd = st.text_input("New Password", type="password")
                confirm_pwd = st.text_input("Confirm New Password", type="password")
                btn_up_pwd = st.form_submit_button("Update Password", type="primary", use_container_width=True)

                if btn_up_pwd:
                    if not current_pwd or not new_pwd or not confirm_pwd:
                        st.error("All fields are required.")
                    elif len(new_pwd) < 4:
                        st.error("New password must be at least 4 characters long.")
                    elif new_pwd != confirm_pwd:
                        st.error("New password and confirm password do not match.")
                    else:
                        try:
                            with get_db_connection() as conn_chk:
                                c_chk = conn_chk.cursor()
                                c_chk.execute("SELECT password, password_hash FROM users WHERE username = ?", (st.session_state.username,))
                                u_row = c_chk.fetchone()

                            if not u_row:
                                st.error("User record not found.")
                            else:
                                raw_p = u_row['password'] if 'password' in u_row.keys() else ''
                                h_p = u_row['password_hash']
                                curr_h = hash_password(current_pwd)

                                is_match = (raw_p and current_pwd == raw_p) or (curr_h == h_p)
                                if not is_match:
                                    st.error("Incorrect current password.")
                                else:
                                    new_h = hash_password(new_pwd)
                                    with get_db_connection() as conn_w:
                                        conn_w.execute("""
                                        UPDATE users SET password = ?, password_hash = ? WHERE username = ?
                                        """, (new_pwd, new_h, st.session_state.username))
                                        conn_w.commit()

                                    if is_supabase_active():
                                        supabase_request("PATCH", "users", {
                                            "password": new_pwd,
                                            "password_hash": new_h
                                        }, params=f"username=eq.{st.session_state.username}")

                                    st.success("✅ Password updated successfully!")
                        except Exception as e:
                            st.error(f"Error updating password: {e}")

        st.markdown("<div style='height: 8px;'></div>", unsafe_allow_html=True)
        with st.form("logout_form"):
            if st.form_submit_button("🚪 Sign Out", use_container_width=True):
                st.session_state.logged_in = False
                st.session_state.username = None
                st.session_state.role = None
                st.session_state.name = None
                st.session_state.live_joined = False
                st.session_state.joined_live_class = False
                st.rerun()

    if st.session_state.role == 'admin':
        render_admin_dashboard()
    elif st.session_state.role == 'teacher':
        render_teacher_dashboard()
    else:
        render_student_dashboard()


if __name__ == "__main__":
    main()
