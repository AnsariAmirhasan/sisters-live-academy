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
        password_hash TEXT NOT NULL,
        role TEXT NOT NULL,
        full_name TEXT NOT NULL,
        is_active INTEGER DEFAULT 1,
        created_at TEXT NOT NULL
    )
    """)

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
        teacher_notes TEXT DEFAULT ''
    )
    """)

    # Safe automatic column migrations for existing databases
    try:
        c.execute("PRAGMA table_info(class_session)")
        existing_cols = [r[1] for r in c.fetchall()]
        if 'server' not in existing_cols:
            c.execute("ALTER TABLE class_session ADD COLUMN server TEXT DEFAULT 'jitsi.riot.im'")
        if 'teacher_notes' not in existing_cols:
            c.execute("ALTER TABLE class_session ADD COLUMN teacher_notes TEXT DEFAULT ''")
        conn.commit()
    except Exception:
        pass

    # Ensure row 1 exists
    try:
        c.execute("SELECT COUNT(*) as cnt FROM class_session WHERE id = 1")
        if c.fetchone()['cnt'] == 0:
            c.execute("""
            INSERT INTO class_session (id, is_live, topic, room_name, server, teacher_notes)
            VALUES (1, 0, 'Mathematics & Science Live Coaching', 'SistersLiveClass_MasterRoom', 'jitsi.riot.im', 'Welcome! Camera is OFF by default. Turn on mic when asked.')
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

    # Pre-seed default users if table is empty
    c.execute("SELECT COUNT(*) as cnt FROM users")
    if c.fetchone()['cnt'] == 0:
        now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        teacher_pwd = hash_password("teacher123")
        c.execute("""
        INSERT INTO users (username, password_hash, role, full_name, is_active, created_at)
        VALUES (?, ?, 'teacher', 'Prof. Academy Teacher', 1, ?)
        """, ("teacher", teacher_pwd, now_str))

        student_pwd = hash_password("pass123")
        for i in range(1, 11):
            c.execute("""
            INSERT INTO users (username, password_hash, role, full_name, is_active, created_at)
            VALUES (?, ?, 'student', ?, 1, ?)
            """, (f"student{i}", student_pwd, f"Student {i}", now_str))

        c.execute("""
        INSERT INTO announcements (title, message, priority, created_at)
        VALUES ('Welcome to Sister''s Live Academy!', 
                'Live sessions are held Monday to Saturday at 6:00 PM. Camera is OFF by default.', 
                'Important', ?)
        """, (now_str,))

        demo_drive_url = "https://drive.google.com/file/d/1BxiMVs0XRA5nFMdKvBdBZjgmUUqptlbs/view?usp=sharing"
        embed_url, dl_url = process_google_drive_link(demo_drive_url)
        c.execute("""
        INSERT INTO recordings (title, subject, lecture_date, description, drive_link, embed_url, download_url, created_at)
        VALUES ('Foundation & Orientation Class 01', 'Orientation', '2026-10-25', 
                'Complete syllabus blueprint, exam strategy, and doubt-clearing structure.', 
                ?, ?, ?, ?)
        """, (demo_drive_url, embed_url, dl_url, now_str))

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

    pwd_hash = hash_password(password_val)
    user = None

    # Check Supabase first if active
    if is_supabase_active():
        ok, rows = supabase_request("GET", "users", params=f"username=eq.{username_val.strip().lower()}&password_hash=eq.{pwd_hash}&select=*")
        if ok and rows:
            user = rows[0]

    # Fallback to local SQLite
    if not user:
        conn = get_db_connection()
        try:
            c = conn.cursor()
            c.execute("SELECT * FROM users WHERE username = ? AND password_hash = ?", (username_val.strip().lower(), pwd_hash))
            raw_u = c.fetchone()
            if raw_u:
                user = dict(raw_u)
        finally:
            conn.close()


    if user:
        if user.get('is_active', 1) == 0:
            st.error("⛔ Your account has been suspended or blocked by the Teacher. Please contact your instructor.")
        else:
            st.session_state.logged_in = True
            st.session_state.username = user['username']
            st.session_state.role = user['role']
            st.session_state.name = user['full_name']
            st.success(f"Signed in as {user['full_name']}!")
            st.rerun()
    else:
        st.error("Invalid username or password. Check default test credentials below.")

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
            u_input = st.text_input("Username", placeholder="e.g. teacher or student1").strip().lower()
            p_input = st.text_input("Password", type="password", placeholder="Enter your password")
            submit = st.form_submit_button("Sign In to Portal", use_container_width=True, type="primary")

            if submit:
                handle_login(u_input, p_input)

        with st.expander("🔑 Default Test Credentials (Click to view)"):
            st.markdown("""
            - **Teacher / Admin:** Username: `teacher` | Password: `teacher123`
            - **Student Accounts:** Usernames: `student1` to `student10` | Password: `pass123`
            """)


# ==========================================
# 7. TEACHER DASHBOARD
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

    tab_live, tab_recordings, tab_notices, tab_doubts, tab_students, tab_cloud = st.tabs([
        "🔴 Live Studio & Screen Share",
        "📚 Recorded Classes (Google Drive)",
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
                st.markdown(f"""
                <div class="live-badge">
                    <span class="live-dot"></span>
                    <span>BROADCAST STATUS: LIVE NOW</span>
                </div>
                <div style="margin-top: 6px; color: #1e293b; font-size: 0.95rem;">
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
                        try:
                            with get_db_connection() as conn_w:
                                conn_w.execute("""
                                UPDATE class_session 
                                SET is_live = 1, topic = ?, room_name = ?, server = ?, teacher_notes = ?, started_at = ?
                                WHERE id = 1
                                """, (f_topic, f_room, f_server, f_notes, now_str))
                                conn_w.commit()
                        except Exception as e:
                            print(f"Error starting live class: {e}")

                        if is_supabase_active():
                            supabase_request("PATCH", "class_session", {
                                "is_live": 1, "topic": f_topic, "room_name": f_room,
                                "server": f_server, "teacher_notes": f_notes, "started_at": now_str
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
                                    INSERT INTO users (username, password_hash, role, full_name, is_active, created_at)
                                    VALUES (?, ?, 'student', ?, 1, ?)
                                    """, (n_un, pw_h, n_fn, now_str))
                                    conn_w.commit()

                                if is_supabase_active():
                                    supabase_request("POST", "users", {
                                        "username": n_un, "password_hash": pw_h, "role": "student",
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
                    c.execute("SELECT id, username, full_name, is_active, created_at FROM users WHERE role = 'student' ORDER BY id ASC")
                    st_list = [dict(r) for r in c.fetchall()]

                for s in st_list:
                    status_lbl = "🟢 Active" if s.get('is_active', 1) == 1 else "🔴 Blocked / Suspended"
                    with st.expander(f"{s['full_name']} (@{s['username']}) - {status_lbl}"):
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
                                new_p = st.text_input("New Password", value="pass123")
                                if st.form_submit_button("🔑 Reset Pass", use_container_width=True):
                                    pwd_res = hash_password(new_p)
                                    try:
                                        with get_db_connection() as conn_w:
                                            conn_w.execute("UPDATE users SET password_hash = ? WHERE id = ?", (pwd_res, s['id']))
                                            conn_w.commit()
                                    except Exception as e:
                                        print(f"Error resetting password: {e}")
                                    if is_supabase_active():
                                        supabase_request("PATCH", "users", {"password_hash": pwd_res}, params=f"id=eq.{s['id']}")
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

    tab_live, tab_library, tab_doubts, tab_att = st.tabs([
        "🎥 Live Classroom",
        "📖 Recorded Lectures & Notes",
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
            st.markdown("""
            <div class="glass-card" style="text-align: center; padding: 36px 20px;">
                <div class="offline-badge" style="font-size: 1.05rem; padding: 8px 24px; margin-bottom: 14px;">
                    ⚪ Live Class is Currently Offline
                </div>
                <h3 style="color: #334155; margin-bottom: 6px;">No broadcast active right now.</h3>
                <p style="color: #64748b; max-width: 520px; margin: 0 auto;">
                    Check announcements above for session schedules, or watch past lecture videos from the <b>Recorded Lectures & Notes</b> tab.
                </p>
            </div>
            """, unsafe_allow_html=True)
            st.session_state.live_joined = False
            st.session_state.joined_live_class = False
        else:
            st.markdown(f"""
            <div class="glass-card" style="border: 2px solid #f87171; background: #fff5f5;">
                <div class="live-badge">
                    <span class="live-dot"></span>
                    <span>TEACHER IS LIVE NOW!</span>
                </div>
                <h3 style="margin: 8px 0 4px 0; color: #1e293b;">{session_topic}</h3>
                <p style="margin: 0; color: #475569;"><b>Teacher's Instructions:</b> {teacher_notes}</p>
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

        st.markdown(f"""
        <div style="background:#f1f5f9; padding:12px; border-radius:10px; margin-bottom:15px;">
            <div style="font-size:0.75rem; color:#64748b; text-transform:uppercase; font-weight:700;">Active Account</div>
            <div style="font-weight:700; color:#1e293b; font-size:1rem;">{st.session_state.name}</div>
            <div style="font-size:0.85rem; color:#4f46e5; font-weight:600;">Role: {st.session_state.role.capitalize()} (@{st.session_state.username})</div>
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
        with st.form("logout_form"):
            if st.form_submit_button("🚪 Sign Out", use_container_width=True):
                st.session_state.logged_in = False
                st.session_state.username = None
                st.session_state.role = None
                st.session_state.name = None
                st.session_state.live_joined = False
                st.session_state.joined_live_class = False
                st.rerun()

    if st.session_state.role == 'teacher':
        render_teacher_dashboard()
    else:
        render_student_dashboard()


if __name__ == "__main__":
    main()
