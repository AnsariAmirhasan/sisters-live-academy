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
    st.session_state.jitsi_server = "meet.ffmuc.net"
if "live_joined" not in st.session_state:
    st.session_state.live_joined = False

# ==========================================
# 3. HYBRID DATABASE ENGINE (SQLITE & SUPABASE)
# ==========================================
DB_FILE = "classroom.db"

@st.cache_resource
def get_db():
    """
    Returns single persistent thread-safe SQLite connection.
    Cached globally so user actions are written immediately.
    """
    conn = sqlite3.connect(DB_FILE, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn

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

    return raw_link, raw_link

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
        server TEXT DEFAULT 'meet.ffmuc.net',
        started_at TEXT,
        ended_at TEXT,
        teacher_notes TEXT DEFAULT ''
    )
    """)

    # Automatic column migrations for existing databases
    try:
        c.execute("ALTER TABLE class_session ADD COLUMN server TEXT DEFAULT 'meet.ffmuc.net'")
    except Exception:
        pass
    try:
        c.execute("ALTER TABLE class_session ADD COLUMN teacher_notes TEXT DEFAULT ''")
    except Exception:
        pass

    # Ensure row 1 exists
    c.execute("SELECT COUNT(*) as cnt FROM class_session WHERE id = 1")
    if c.fetchone()['cnt'] == 0:
        c.execute("""
        INSERT INTO class_session (id, is_live, topic, room_name, server, teacher_notes)
        VALUES (1, 0, 'Mathematics & Science Live Coaching', 'SistersLiveClass_MasterRoom', 'meet.ffmuc.net', 'Welcome! Camera is OFF by default. Turn on mic when asked.')
        """)
    else:
        c.execute("UPDATE class_session SET server = 'meet.ffmuc.net' WHERE server IS NULL OR server = ''")

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
# 5. JITSI EMBED & SCREEN RECORDER
# ==========================================
def build_jitsi_url(server: str, room_name: str, display_name: str, is_teacher: bool) -> str:
    safe_name = urllib.parse.quote(display_name)
    audio_param = "false" if is_teacher else "true"
    server_clean = server.replace("https://", "").replace("http://", "").strip("/")
    
    jitsi_url = (
        f"https://{server_clean}/{room_name}"
        f"#userInfo.displayName=\"{safe_name}\""
        f"&config.prejoinPageEnabled=false"
        f"&config.startWithVideoMuted=true"
        f"&config.startWithAudioMuted={audio_param}"
        f"&config.disableDeepLinking=true"
    )
    return jitsi_url

def render_jitsi_embed(jitsi_url: str):
    iframe_html = f"""
    <div style="width: 100%; border-radius: 12px; overflow: hidden; box-shadow: 0 4px 20px rgba(0,0,0,0.12); margin-top: 10px;">
        <iframe 
            src="{jitsi_url}" 
            style="width: 100%; height: 680px; border: 0;"
            allow="microphone; camera; display-capture; fullscreen; autoplay; clipboard-write"
            allowfullscreen>
        </iframe>
    </div>
    """
    components.html(iframe_html, height=700, scrolling=False)

def render_html5_recorder():
    recorder_code = """
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="utf-8">
        <style>
            .recorder-container {
                background: linear-gradient(135deg, #1e293b, #0f172a);
                border: 1px solid #334155;
                border-radius: 10px;
                padding: 14px 18px;
                color: #f8fafc;
                display: flex;
                align-items: center;
                justify-content: space-between;
                flex-wrap: wrap;
                gap: 12px;
                font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
                margin-top: 12px;
            }
            .rec-left {
                display: flex;
                align-items: center;
                gap: 10px;
            }
            .pulse-dot {
                width: 12px;
                height: 12px;
                border-radius: 50%;
                background-color: #64748b;
            }
            .pulse-dot.recording {
                background-color: #ef4444;
                box-shadow: 0 0 10px #ef4444;
                animation: blink 1s infinite;
            }
            @keyframes blink { 50% { opacity: 0.3; } }
            .timer {
                font-family: monospace;
                font-size: 1.2rem;
                font-weight: bold;
                color: #38bdf8;
            }
            .btn-start {
                background-color: #ef4444;
                color: white;
                border: none;
                padding: 8px 16px;
                border-radius: 6px;
                font-weight: 600;
                cursor: pointer;
            }
            .btn-start:hover { background-color: #dc2626; }
            .btn-stop {
                background-color: #10b981;
                color: white;
                border: none;
                padding: 8px 16px;
                border-radius: 6px;
                font-weight: 600;
                cursor: pointer;
            }
            .btn-stop:hover { background-color: #059669; }
            .note {
                font-size: 0.82rem;
                color: #94a3b8;
                width: 100%;
            }
        </style>
    </head>
    <body>
        <div class="recorder-container">
            <div class="rec-left">
                <span id="dot" class="pulse-dot"></span>
                <span id="label" style="font-weight: 600;">Screen & Audio Recorder: Standby</span>
                <span id="timer" class="timer">00:00:00</span>
            </div>
            <div>
                <button id="startBtn" class="btn-start" onclick="startRec()">⏺️ Start Screen & Audio Recording</button>
                <button id="stopBtn" class="btn-stop" onclick="stopRec()" style="display: none;">💾 Stop & Download Video</button>
            </div>
            <div class="note">
                💡 <b>1-Click Class Recording:</b> Click Start, select your Live Class tab/screen with audio checked. When stopped, your class recording automatically downloads directly to your PC as a <code>.webm</code> file.
            </div>
        </div>

        <script>
            let mediaRecorder;
            let chunks = [];
            let timerTimer;
            let secCount = 0;

            function fmt(s) {
                const h = String(Math.floor(s / 3600)).padStart(2, '0');
                const m = String(Math.floor((s % 3600) / 60)).padStart(2, '0');
                const sc = String(s % 60).padStart(2, '0');
                return `${h}:${m}:${sc}`;
            }

            async function startRec() {
                try {
                    const stream = await navigator.mediaDevices.getDisplayMedia({
                        video: { cursor: "always" },
                        audio: true
                    });

                    chunks = [];
                    mediaRecorder = new MediaRecorder(stream, { mimeType: 'video/webm' });

                    mediaRecorder.ondataavailable = (e) => {
                        if (e.data.size > 0) chunks.push(e.data);
                    };

                    mediaRecorder.onstop = () => {
                        clearInterval(timerTimer);
                        document.getElementById('timer').innerText = "00:00:00";
                        document.getElementById('dot').classList.remove('recording');
                        document.getElementById('label').innerText = "Recording Saved & Downloaded!";
                        document.getElementById('startBtn').style.display = "inline-block";
                        document.getElementById('stopBtn').style.display = "none";

                        const blob = new Blob(chunks, { type: 'video/webm' });
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
                    document.getElementById('startBtn').style.display = "none";
                    document.getElementById('stopBtn').style.display = "inline-block";
                    document.getElementById('dot').classList.add('recording');
                    document.getElementById('label').innerText = "Recording Live Class in Progress...";

                    secCount = 0;
                    timerTimer = setInterval(() => {
                        secCount++;
                        document.getElementById('timer').innerText = fmt(secCount);
                    }, 1000);

                } catch (err) {
                    alert("Recording request cancelled or permission not granted: " + err.message);
                }
            }

            function stopRec() {
                if (mediaRecorder && mediaRecorder.state !== 'inactive') {
                    mediaRecorder.stop();
                }
            }
        </script>
    </body>
    </html>
    """
    components.html(recorder_code, height=125, scrolling=False)


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
        conn = get_db()
        c = conn.cursor()
        c.execute("SELECT * FROM users WHERE username = ? AND password_hash = ?", (username_val.strip().lower(), pwd_hash))
        raw_u = c.fetchone()
        if raw_u:
            user = dict(raw_u)

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
                    f_server = st.selectbox("Jitsi Server (Free & Login-Free)", ["meet.ffmuc.net", "jitsi.riot.im", "framatalk.org"], index=0)
                    f_room = st.text_input("Room Key", value=room_name or "SistersLiveClass_MasterRoom")
                    f_notes = st.text_input("Note for Students", value="Camera is OFF by default. Unmute mic to ask doubts.")
                    btn_start = st.form_submit_button("🚀 Start Live Broadcast", type="primary", use_container_width=True)

                    if btn_start:
                        now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                        c.execute("""
                        UPDATE class_session 
                        SET is_live = 1, topic = ?, room_name = ?, server = ?, teacher_notes = ?, started_at = ?
                        WHERE id = 1
                        """, (f_topic, f_room, f_server, f_notes, now_str))
                        conn.commit()

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
                        c.execute("UPDATE class_session SET is_live = 0, ended_at = ? WHERE id = 1", (now_str,))
                        conn.commit()

                        if is_supabase_active():
                            supabase_request("PATCH", "class_session", {"is_live": 0, "ended_at": now_str}, params="id=eq.1")

                        st.warning("Live class ended. Students are back to offline status.")
                        st.rerun()

        with col_st3:
            st.link_button("📂 Open My Google Drive", "https://drive.google.com/drive/my-drive", use_container_width=True)

        st.markdown("---")

        if is_live:
            teacher_jitsi_url = build_jitsi_url(server, room_name, f"{st.session_state.name} (Teacher)", is_teacher=True)

            st.link_button(
                "🚀 Open Live Class in Full Screen Tab (Best for Screen Share & Recording)",
                teacher_jitsi_url,
                type="primary",
                use_container_width=True
            )

            render_jitsi_embed(teacher_jitsi_url)
            render_html5_recorder()
        else:
            st.info("💡 To begin teaching, configure your topic and click **'Start Live Broadcast'** above.")

    # ---------------------------------------------
    # TEACHER TAB 2: RECORDED CLASSES (GOOGLE DRIVE)
    # ---------------------------------------------
    with tab_recordings:
        st.subheader("Google Drive Recorded Classes & Study Library")
        st.caption("Paste any Google Drive or YouTube sharing link. It is automatically converted into an embedded player and direct download button for students.")

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
                        c.execute("""
                        INSERT INTO recordings (title, subject, lecture_date, description, drive_link, embed_url, download_url, created_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                        """, (r_title, r_subject, str(r_date), r_desc, r_link, embed_url, download_url, now_str))
                        conn.commit()

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
                                    c.execute("DELETE FROM recordings WHERE id = ?", (rec['id'],))
                                    conn.commit()
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
                        c.execute("""
                        INSERT INTO announcements (title, message, priority, created_at)
                        VALUES (?, ?, ?, ?)
                        """, (n_title, n_msg, n_priority, now_str))
                        conn.commit()

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
                            c.execute("DELETE FROM announcements WHERE id = ?", (n['id'],))
                            conn.commit()
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
                                c.execute("""
                                UPDATE doubts SET reply = ?, status = 'Answered', replied_at = ? WHERE id = ?
                                """, (reply_val.strip(), now_str, d['id']))
                                conn.commit()
                                if is_supabase_active():
                                    supabase_request("PATCH", "doubts", {
                                        "reply": reply_val.strip(), "status": "Answered", "replied_at": now_str
                                    }, params=f"id=eq.{d['id']}")
                                st.success("Answer published to student!")
                                st.rerun()
                            else:
                                st.error("Response cannot be empty.")

                        if del_doubt:
                            c.execute("DELETE FROM doubts WHERE id = ?", (d['id'],))
                            conn.commit()
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
                                c.execute("""
                                INSERT INTO users (username, password_hash, role, full_name, is_active, created_at)
                                VALUES (?, ?, 'student', ?, 1, ?)
                                """, (n_un, pw_h, n_fn, now_str))
                                conn.commit()

                                if is_supabase_active():
                                    supabase_request("POST", "users", {
                                        "username": n_un, "password_hash": pw_h, "role": "student",
                                        "full_name": n_fn, "is_active": 1, "created_at": now_str
                                    })

                                st.success(f"Student {n_fn} (@{n_un}) registered successfully!")
                                st.rerun()
                            except sqlite3.IntegrityError:
                                st.error(f"Username '{n_un}' is already taken.")

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
                                        c.execute("UPDATE users SET is_active = 0 WHERE id = ?", (s['id'],))
                                        conn.commit()
                                        if is_supabase_active():
                                            supabase_request("PATCH", "users", {"is_active": 0}, params=f"id=eq.{s['id']}")
                                        st.warning(f"Blocked @{s['username']}.")
                                        st.rerun()
                                else:
                                    if st.form_submit_button("✅ Unblock Student", use_container_width=True):
                                        c.execute("UPDATE users SET is_active = 1 WHERE id = ?", (s['id'],))
                                        conn.commit()
                                        if is_supabase_active():
                                            supabase_request("PATCH", "users", {"is_active": 1}, params=f"id=eq.{s['id']}")
                                        st.success(f"Unblocked @{s['username']}.")
                                        st.rerun()

                        with c_b2:
                            with st.form(f"rst_form_{s['id']}"):
                                new_p = st.text_input("New Password", value="pass123")
                                if st.form_submit_button("🔑 Reset Pass", use_container_width=True):
                                    pwd_res = hash_password(new_p)
                                    c.execute("UPDATE users SET password_hash = ? WHERE id = ?", (pwd_res, s['id']))
                                    conn.commit()
                                    if is_supabase_active():
                                        supabase_request("PATCH", "users", {"password_hash": pwd_res}, params=f"id=eq.{s['id']}")
                                    st.success(f"Password reset for @{s['username']}.")
                                    st.rerun()

                        with c_b3:
                            with st.form(f"del_st_form_{s['id']}"):
                                if st.form_submit_button("🗑️ Delete Account", use_container_width=True):
                                    c.execute("DELETE FROM users WHERE id = ?", (s['id'],))
                                    conn.commit()
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

            student_jitsi_url = build_jitsi_url(server, room_name, f"{st.session_state.name} (Student)", is_teacher=False)

            if not st.session_state.live_joined:
                col_j1, col_j2, col_j3 = st.columns([1, 2, 1])
                with col_j2:
                    with st.form("join_live_form"):
                        btn_join = st.form_submit_button("🚀 Join Live Class Now (Logs Attendance)", type="primary", use_container_width=True)
                        if btn_join:
                            now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                            today_str = str(datetime.date.today())
                            c.execute("""
                            SELECT id FROM attendance WHERE student_username = ? AND date = ? AND room_name = ?
                            """, (st.session_state.username, today_str, room_name))
                            if not c.fetchone():
                                c.execute("""
                                INSERT INTO attendance (student_username, student_name, room_name, topic, join_timestamp, date)
                                VALUES (?, ?, ?, ?, ?, ?)
                                """, (st.session_state.username, st.session_state.name, room_name, session_topic, now_str, today_str))
                                conn.commit()

                                if is_supabase_active():
                                    supabase_request("POST", "attendance", {
                                        "student_username": st.session_state.username,
                                        "student_name": st.session_state.name,
                                        "room_name": room_name,
                                        "topic": session_topic,
                                        "join_timestamp": now_str,
                                        "date": today_str
                                    })

                            st.session_state.live_joined = True
                            st.rerun()
            else:
                st.success("✅ Attendance recorded! You are in the live room.")

                st.link_button(
                    "🚀 Open Live Class in Full Screen Tab (Best for Clean Audio/Video)",
                    student_jitsi_url,
                    type="primary",
                    use_container_width=True
                )

                render_jitsi_embed(student_jitsi_url)

                with st.form("leave_live_form"):
                    if st.form_submit_button("Leave Live Room"):
                        st.session_state.live_joined = False
                        st.rerun()

    # ---------------------------------------------
    # STUDENT TAB 2: RECORDED LECTURES
    # ---------------------------------------------
    with tab_library:
        st.subheader("📚 Study Library & Recorded Classes")

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
                        c.execute("""
                        INSERT INTO doubts (student_username, student_name, question, subject, created_at)
                        VALUES (?, ?, ?, ?, ?)
                        """, (st.session_state.username, st.session_state.name, d_q.strip(), d_sub, now_str))
                        conn.commit()

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

        st.caption(f"Jitsi Server: **{st.session_state.jitsi_server}**")

        st.markdown("---")
        with st.form("logout_form"):
            if st.form_submit_button("🚪 Sign Out", use_container_width=True):
                st.session_state.logged_in = False
                st.session_state.username = None
                st.session_state.role = None
                st.session_state.name = None
                st.session_state.live_joined = False
                st.rerun()

    if st.session_state.role == 'teacher':
        render_teacher_dashboard()
    else:
        render_student_dashboard()


if __name__ == "__main__":
    main()
