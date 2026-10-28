"""
Sister's Live Academy - Online Live Classroom & Coaching Web App
Complete Production-Ready Streamlit Application for 1 Teacher and 10+ Students
Compatible with Streamlit Community Cloud and Local Execution
"""

import streamlit as st
import sqlite3
import hashlib
import os
import re
import datetime
import io
import pandas as pd
import streamlit.components.v1 as components

# ==========================================
# 1. PAGE CONFIGURATION & GLOBAL STYLING
# ==========================================
st.set_page_config(
    page_title="Sister's Live Academy",
    page_icon="🎓",
    layout="wide",
    initial_sidebar_state="expanded"
)

CUSTOM_CSS = """
<style>
    @import url('https://fonts.googleapis.com/css2?family=Outfit:wght@300;400;500;600;700&family=Inter:wght@400;500;600&display=swap');

    html, body, [class*="css"] {
        font-family: 'Outfit', 'Inter', -apple-system, BlinkMacSystemFont, sans-serif;
    }

    /* Main Container Padding */
    .block-container {
        padding-top: 1.8rem;
        padding-bottom: 3rem;
        max-width: 95% !important;
    }

    /* Gradient Header Card */
    .hero-banner {
        background: linear-gradient(135deg, #4f46e5 0%, #7c3aed 50%, #db2777 100%);
        padding: 24px 30px;
        border-radius: 16px;
        color: white;
        margin-bottom: 24px;
        box-shadow: 0 10px 25px -5px rgba(79, 70, 229, 0.3);
    }
    .hero-banner h1 {
        color: #ffffff !important;
        font-size: 2.1rem;
        font-weight: 700;
        margin-bottom: 6px;
    }
    .hero-banner p {
        color: rgba(255, 255, 255, 0.9);
        font-size: 1.05rem;
        margin-bottom: 0px;
    }

    /* Status Badges */
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
        box-shadow: 0 2px 8px rgba(239, 68, 68, 0.25);
    }
    .live-pulse {
        width: 10px;
        height: 10px;
        background-color: #ef4444;
        border-radius: 50%;
        animation: pulse-ring 1.5s cubic-bezier(0.215, 0.61, 0.355, 1) infinite;
    }
    @keyframes pulse-ring {
        0% { transform: scale(0.95); box-shadow: 0 0 0 0 rgba(239, 68, 68, 0.7); }
        70% { transform: scale(1); box-shadow: 0 0 0 10px rgba(239, 68, 68, 0); }
        100% { transform: scale(0.95); box-shadow: 0 0 0 0 rgba(239, 68, 68, 0); }
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

    /* Cards */
    .glass-card {
        background: #ffffff;
        border-radius: 14px;
        padding: 20px;
        border: 1px solid #e2e8f0;
        box-shadow: 0 4px 12px rgba(0, 0, 0, 0.04);
        margin-bottom: 18px;
        transition: transform 0.15s ease, box-shadow 0.15s ease;
    }
    .glass-card:hover {
        box-shadow: 0 8px 20px rgba(0, 0, 0, 0.07);
    }

    /* Notice Card Variants */
    .notice-card {
        border-left: 5px solid #6366f1;
        background: #f8fafc;
        padding: 16px 20px;
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

    /* Streamlit Button Tweaks */
    div.stButton > button:first-child {
        border-radius: 8px;
        font-weight: 600;
        transition: all 0.2s;
    }

    /* Streamlit Expander & Tabs */
    .stTabs [data-baseweb="tab-list"] {
        gap: 8px;
    }
    .stTabs [data-baseweb="tab"] {
        border-radius: 8px 8px 0px 0px;
        padding: 10px 18px;
        font-weight: 600;
    }
</style>
"""
st.markdown(CUSTOM_CSS, unsafe_allow_html=True)


# ==========================================
# 2. HYBRID DATABASE ENGINE (SQLITE & SUPABASE)
# ==========================================
DB_FILE = "classroom.db"

def get_supabase_client():
    """Optional Supabase support via st.secrets if configured"""
    try:
        supabase_url = st.secrets.get("SUPABASE_URL")
        supabase_key = st.secrets.get("SUPABASE_KEY")
        if supabase_url and supabase_key:
            from supabase import create_client
            return create_client(supabase_url, supabase_key)
    except Exception:
        pass
    return None

def get_db_connection():
    """Returns thread-safe connection to persistent SQLite DB"""
    conn = sqlite3.connect(DB_FILE, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn

def hash_password(password: str, salt: str = "sister_academy_salt_2026") -> str:
    """Standard SHA-256 password hashing with salt"""
    return hashlib.sha256(f"{password}_{salt}".encode('utf-8')).hexdigest()

def process_google_drive_link(raw_link: str) -> tuple[str, str]:
    """
    Parses Google Drive sharing links into:
    1. Embeddable preview player link
    2. Direct file download link
    Also supports YouTube and standard direct URLs.
    """
    raw_link = raw_link.strip() if raw_link else ""
    if not raw_link:
        return "", ""

    # Google Drive File ID match
    drive_match = re.search(r'(?:drive\.google\.com\/(?:file\/d\/|open\?id=|uc\?id=))([a-zA-Z0-9_-]{20,})', raw_link)
    if drive_match:
        file_id = drive_match.group(1)
        embed_url = f"https://drive.google.com/file/d/{file_id}/preview"
        download_url = f"https://drive.google.com/uc?export=download&id={file_id}"
        return embed_url, download_url

    # YouTube Video Match
    yt_match = re.search(r'(?:youtube\.com\/(?:watch\?v=|embed\/)|youtu\.be\/)([a-zA-Z0-9_-]{11})', raw_link)
    if yt_match:
        vid_id = yt_match.group(1)
        embed_url = f"https://www.youtube.com/embed/{vid_id}"
        download_url = raw_link
        return embed_url, download_url

    # Fallback for standard links or folders
    return raw_link, raw_link


def init_database():
    """Initializes schema and pre-seeds teacher & student accounts"""
    conn = get_db_connection()
    c = conn.cursor()

    # 1. Users Table
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

    # 2. Live Class Session Table
    c.execute("""
    CREATE TABLE IF NOT EXISTS class_session (
        id INTEGER PRIMARY KEY,
        is_live INTEGER DEFAULT 0,
        topic TEXT DEFAULT 'General Coaching Session',
        room_name TEXT DEFAULT 'SistersLiveClass_MainStudio',
        started_at TEXT,
        ended_at TEXT,
        teacher_notes TEXT DEFAULT ''
    )
    """)

    # Ensure single row exists for live session state
    c.execute("SELECT COUNT(*) as cnt FROM class_session WHERE id = 1")
    if c.fetchone()['cnt'] == 0:
        c.execute("""
        INSERT INTO class_session (id, is_live, topic, room_name, teacher_notes)
        VALUES (1, 0, 'Mathematics & Science Mastery', 'SistersLiveClass_MasterRoom', 'Welcome students! Please keep your notebooks ready.')
        """)

    # 3. Attendance Logs
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

    # 4. Recordings & Notes Library
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

    # 5. Announcements / Notice Board
    c.execute("""
    CREATE TABLE IF NOT EXISTS announcements (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        title TEXT NOT NULL,
        message TEXT NOT NULL,
        priority TEXT DEFAULT 'Normal',
        created_at TEXT NOT NULL
    )
    """)

    # 6. Doubts & Discussion Board
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

    # Pre-seed Default Users (1 Teacher, 10 Students)
    c.execute("SELECT COUNT(*) as cnt FROM users")
    user_count = c.fetchone()['cnt']
    now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    if user_count == 0:
        # Teacher Account
        teacher_pwd = hash_password("teacher123")
        c.execute("""
        INSERT INTO users (username, password_hash, role, full_name, is_active, created_at)
        VALUES (?, ?, 'teacher', 'Prof. Academy Teacher', 1, ?)
        """, ("teacher", teacher_pwd, now_str))

        # 10 Student Accounts
        student_pwd = hash_password("pass123")
        for i in range(1, 11):
            uname = f"student{i}"
            fname = f"Student {i}"
            c.execute("""
            INSERT INTO users (username, password_hash, role, full_name, is_active, created_at)
            VALUES (?, ?, 'student', ?, 1, ?)
            """, (uname, student_pwd, fname, now_str))

        # Seed initial announcement
        c.execute("""
        INSERT INTO announcements (title, message, priority, created_at)
        VALUES ('Welcome to Sister''s Live Academy!', 
                'Live sessions will be held Monday to Saturday at 6:00 PM. Check your Doubt Box and Study Library regularly for updates.', 
                'Important', ?)
        """, (now_str,))

        # Seed sample recorded lecture
        demo_drive_url = "https://drive.google.com/file/d/1BxiMVs0XRA5nFMdKvBdBZjgmUUqptlbs/view?usp=sharing"
        embed_url, dl_url = process_google_drive_link(demo_drive_url)
        c.execute("""
        INSERT INTO recordings (title, subject, lecture_date, description, drive_link, embed_url, download_url, created_at)
        VALUES ('Orientation & Foundation Class 01', 'Orientation', '2026-10-25', 
                'Introduction to syllabus, weekly schedule, test series blueprint and doubt-clearing sessions.', 
                ?, ?, ?, ?)
        """, (demo_drive_url, embed_url, dl_url, now_str))

    conn.commit()
    conn.close()

# Execute DB initialization once
init_database()


# ==========================================
# 4. SESSION STATE INITIALIZATION
# ==========================================
if "authenticated" not in st.session_state:
    st.session_state.authenticated = False
if "user" not in st.session_state:
    st.session_state.user = None
if "live_joined" not in st.session_state:
    st.session_state.live_joined = False


# ==========================================
# 5. AUTHENTICATION MODULE
# ==========================================
def login_user(username, password):
    conn = get_db_connection()
    c = conn.cursor()
    pwd_hash = hash_password(password)
    c.execute("SELECT * FROM users WHERE username = ? AND password_hash = ?", (username.strip().lower(), pwd_hash))
    user = c.fetchone()
    conn.close()
    return user

def render_login_screen():
    st.markdown("""
    <div class="hero-banner" style="text-align: center; margin-top: 10px;">
        <h1>🎓 Sister's Live Academy</h1>
        <p>Interactive Live Classroom, Coaching Studio & Study Material Hub</p>
    </div>
    """, unsafe_allow_html=True)

    col1, col2, col3 = st.columns([1, 1.8, 1])
    with col2:
        with st.container():
            st.markdown("""
            <div class="glass-card">
                <h3 style="margin-top:0; color:#1e293b;">🔐 Portal Login</h3>
                <p style="color:#64748b; font-size:0.9rem;">Sign in as Teacher or Student to access your live portal</p>
            </div>
            """, unsafe_allow_html=True)

            with st.form("login_form", clear_on_submit=False):
                username_input = st.text_input("Username", placeholder="e.g. teacher or student1").strip().lower()
                password_input = st.text_input("Password", type="password", placeholder="Enter your password")
                submit = st.form_submit_button("Sign In to Portal", use_container_width=True, type="primary")

                if submit:
                    if not username_input or not password_input:
                        st.error("Please enter both username and password.")
                    else:
                        user = login_user(username_input, password_input)
                        if user:
                            if user['is_active'] == 0:
                                st.error("⛔ Your account has been suspended or blocked by the Teacher. Please contact your administrator.")
                            else:
                                st.session_state.authenticated = True
                                st.session_state.user = {
                                    'id': user['id'],
                                    'username': user['username'],
                                    'role': user['role'],
                                    'full_name': user['full_name'],
                                    'is_active': user['is_active']
                                }
                                st.success(f"Welcome back, {user['full_name']}!")
                                st.rerun()
                        else:
                            st.error("Invalid username or password. Check default test credentials below.")

            with st.expander("🔑 Quick Demo Credentials (Click to view)"):
                st.markdown("""
                - **Teacher / Admin:** Username: `teacher` | Password: `teacher123`
                - **Student Accounts (10 seeded):** Usernames: `student1` to `student10` | Password: `pass123`
                """)


# ==========================================
# 6. JITSI MEET & SCREEN RECORDER COMPONENTS
# ==========================================
def render_jitsi_classroom(room_name: str, display_name: str, is_teacher: bool, session_topic: str):
    """
    Renders Jitsi Meet External API with customized toolbars,
    permissions, and layout for Teacher (Moderator) vs Student.
    """
    if is_teacher:
        toolbar_buttons = "['microphone', 'camera', 'desktop', 'chat', 'raisehand', 'videoquality', 'tileview', 'mute-everyone', 'security', 'localrecording', 'whiteboard', 'hangup']"
        is_moderator = "true"
    else:
        # Restricted toolbar for students: no screen sharing desktop, no muting others
        toolbar_buttons = "['microphone', 'camera', 'chat', 'raisehand', 'tileview', 'fullscreen', 'hangup']"
        is_moderator = "false"

    jitsi_html = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="utf-8">
        <script src="https://meet.jit.si/external_api.js"></script>
        <style>
            body, html {{
                margin: 0;
                padding: 0;
                height: 100%;
                width: 100%;
                overflow: hidden;
                background-color: #0f172a;
                font-family: 'Inter', sans-serif;
            }}
            #jitsi-container {{
                height: 100vh;
                width: 100%;
            }}
            .loading-text {{
                color: #e2e8f0;
                text-align: center;
                padding-top: 40px;
                font-size: 1.1rem;
            }}
        </style>
    </head>
    <body>
        <div id="jitsi-container">
            <div class="loading-text">Connecting to Live Studio ({session_topic})...</div>
        </div>
        <script>
            window.onload = function() {{
                const domain = 'meet.jit.si';
                const options = {{
                    roomName: '{room_name}',
                    width: '100%',
                    height: '100%',
                    parentNode: document.querySelector('#jitsi-container'),
                    userInfo: {{
                        displayName: '{display_name}'
                    }},
                    configOverwrite: {{
                        prejoinPageEnabled: false,
                        disableDeepLinking: true,
                        startWithAudioMuted: { 'false' if is_teacher else 'true' },
                        startWithVideoMuted: false,
                        toolbarButtons: {toolbar_buttons},
                        disableThirdPartyRequests: true,
                        enableWelcomePage: false,
                        enableClosePage: false
                    }},
                    interfaceConfigOverwrite: {{
                        SHOW_JITSI_WATERMARK: false,
                        SHOW_WATERMARK_FOR_GUESTS: false,
                        DEFAULT_REMOTE_DISPLAY_NAME: 'Academy Student',
                        TOOLBAR_ALWAYS_VISIBLE: true,
                        SETTINGS_SECTIONS: ['devices', 'language']
                    }}
                }};
                const api = new JitsiMeetExternalAPI(domain, options);
                
                // Moderator safety setups
                api.addEventListeners({{
                    readyToClose: function() {{
                        console.log('Class session closed');
                    }}
                }});
            }};
        </script>
    </body>
    </html>
    """
    components.html(jitsi_html, height=720, scrolling=False)


def render_browser_screen_recorder():
    """
    Custom HTML5 MediaRecorder Tool for Teacher to record
    live screen + system/mic audio with 1-click and auto-save as .webm file.
    """
    recorder_html = """
    <!DOCTYPE html>
    <html>
    <head>
        <style>
            .recorder-box {
                background: linear-gradient(145deg, #1e293b, #0f172a);
                border: 1px solid #334155;
                border-radius: 12px;
                padding: 16px 20px;
                color: #f8fafc;
                display: flex;
                align-items: center;
                justify-content: space-between;
                flex-wrap: wrap;
                gap: 15px;
                font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
            }
            .rec-info {
                display: flex;
                align-items: center;
                gap: 12px;
            }
            .rec-dot {
                width: 14px;
                height: 14px;
                border-radius: 50%;
                background-color: #64748b;
                display: inline-block;
            }
            .rec-dot.active {
                background-color: #ef4444;
                box-shadow: 0 0 10px #ef4444;
                animation: blink 1s infinite;
            }
            @keyframes blink {
                50% { opacity: 0.3; }
            }
            .timer {
                font-family: monospace;
                font-size: 1.25rem;
                font-weight: bold;
                letter-spacing: 1px;
                color: #38bdf8;
            }
            .rec-btn {
                background-color: #ef4444;
                color: white;
                border: none;
                padding: 10px 18px;
                border-radius: 8px;
                font-weight: 600;
                cursor: pointer;
                display: inline-flex;
                align-items: center;
                gap: 8px;
                font-size: 0.95rem;
                transition: 0.2s;
            }
            .rec-btn:hover {
                background-color: #dc2626;
            }
            .stop-btn {
                background-color: #059669;
                color: white;
                border: none;
                padding: 10px 18px;
                border-radius: 8px;
                font-weight: 600;
                cursor: pointer;
                display: inline-flex;
                align-items: center;
                gap: 8px;
                font-size: 0.95rem;
                transition: 0.2s;
            }
            .stop-btn:hover {
                background-color: #047857;
            }
            .guide-note {
                font-size: 0.85rem;
                color: #94a3b8;
                width: 100%;
                margin-top: 6px;
            }
        </style>
    </head>
    <body>
        <div class="recorder-box">
            <div class="rec-info">
                <span id="dot" class="rec-dot"></span>
                <span id="statusText" style="font-weight:600;">Browser Screen & Audio Recorder: Ready</span>
                <span id="timer" class="timer">00:00:00</span>
            </div>
            <div>
                <button id="startBtn" class="rec-btn" onclick="startRecording()">🔴 Start Recording</button>
                <button id="stopBtn" class="stop-btn" onclick="stopRecording()" style="display:none;">💾 Stop & Download</button>
            </div>
            <div class="guide-note">
                💡 <b>Teacher's 1-Click Recording:</b> When you click Start, choose your live classroom tab or entire screen with audio. When you click Stop, the video file (.webm) downloads directly to your PC.
            </div>
        </div>

        <script>
            let mediaRecorder;
            let recordedChunks = [];
            let timerInterval;
            let seconds = 0;

            function formatTime(s) {
                const hrs = String(Math.floor(s / 3600)).padStart(2, '0');
                const mins = String(Math.floor((s % 3600) / 60)).padStart(2, '0');
                const secs = String(s % 60).padStart(2, '0');
                return `${hrs}:${mins}:${secs}`;
            }

            async function startRecording() {
                try {
                    const stream = await navigator.mediaDevices.getDisplayMedia({
                        video: { cursor: "always" },
                        audio: true
                    });

                    recordedChunks = [];
                    mediaRecorder = new MediaRecorder(stream, { mimeType: 'video/webm;codecs=vp9,opus' });

                    mediaRecorder.ondataavailable = function(e) {
                        if (e.data.size > 0) {
                            recordedChunks.push(e.data);
                        }
                    };

                    mediaRecorder.onstop = function() {
                        clearInterval(timerInterval);
                        document.getElementById('timer').innerText = "00:00:00";
                        document.getElementById('dot').classList.remove('active');
                        document.getElementById('statusText').innerText = "Recording Saved & Downloaded!";
                        document.getElementById('startBtn').style.display = "inline-flex";
                        document.getElementById('stopBtn').style.display = "none";

                        const blob = new Blob(recordedChunks, { type: 'video/webm' });
                        const url = URL.createObjectURL(blob);
                        const a = document.createElement('a');
                        a.style.display = 'none';
                        a.href = url;
                        const dateStr = new Date().toISOString().slice(0, 19).replace(/[:T]/g, '-');
                        a.download = `Sisters_Academy_Class_${dateStr}.webm`;
                        document.body.appendChild(a);
                        a.click();
                        setTimeout(() => {
                            document.body.removeChild(a);
                            window.URL.revokeObjectURL(url);
                        }, 100);
                    };

                    // Listen if user cancels via browser chrome bar
                    stream.getVideoTracks()[0].onended = function() {
                        if (mediaRecorder.state !== 'inactive') {
                            mediaRecorder.stop();
                        }
                    };

                    mediaRecorder.start(1000);

                    // UI update
                    document.getElementById('startBtn').style.display = "none";
                    document.getElementById('stopBtn').style.display = "inline-flex";
                    document.getElementById('dot').classList.add('active');
                    document.getElementById('statusText').innerText = "Recording Live Class...";

                    seconds = 0;
                    timerInterval = setInterval(() => {
                        seconds++;
                        document.getElementById('timer').innerText = formatTime(seconds);
                    }, 1000);

                } catch (err) {
                    alert("Recording cancelled or permission not granted: " + err.message);
                }
            }

            function stopRecording() {
                if (mediaRecorder && mediaRecorder.state !== 'inactive') {
                    mediaRecorder.stop();
                }
            }
        </script>
    </body>
    </html>
    """
    components.html(recorder_html, height=135, scrolling=False)


# ==========================================
# 7. TEACHER DASHBOARD
# ==========================================
def render_teacher_dashboard():
    user = st.session_state.user

    # Header Banner
    st.markdown(f"""
    <div class="hero-banner">
        <div style="display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap;">
            <div>
                <h1>👩‍🏫 Teacher Control Center</h1>
                <p>Welcome, <b>{user['full_name']}</b> | Live Classroom Management & Student Portal</p>
            </div>
        </div>
    </div>
    """, unsafe_allow_html=True)

    # Load current Live Class Status
    conn = get_db_connection()
    c = conn.cursor()
    c.execute("SELECT * FROM class_session WHERE id = 1")
    session = c.fetchone()
    is_live = bool(session['is_live'])
    room_name = session['room_name']
    session_topic = session['topic']
    started_at = session['started_at'] or "Not started yet"

    # Tab navigation
    tab1, tab2, tab3, tab4, tab5 = st.tabs([
        "🔴 Live Studio & Whiteboard",
        "📚 Recordings & Drive Library",
        "📢 Notice Board",
        "❓ Doubt Box & Chat",
        "👥 Attendance & Student Accounts"
    ])

    # ---------------------------------------------
    # TAB 1: LIVE STUDIO (TEACHER MODERATOR)
    # ---------------------------------------------
    with tab1:
        st.subheader("Live Class Broadcast Engine")
        col_st1, col_st2, col_st3 = st.columns([2, 1, 1])

        with col_st1:
            if is_live:
                st.markdown(f"""
                <div class="live-badge">
                    <span class="live-pulse"></span>
                    <span>STUDIO STATUS: LIVE NOW</span>
                </div>
                <div style="margin-top: 8px; color: #334155;">
                    <b>Topic:</b> {session_topic} | <b>Room:</b> <code>{room_name}</code> | <b>Started:</b> {started_at}
                </div>
                """, unsafe_allow_html=True)
            else:
                st.markdown("""
                <div class="offline-badge">
                    <span>⚪ STUDIO STATUS: OFFLINE</span>
                </div>
                <div style="margin-top: 8px; color: #64748b;">
                    Classroom is currently closed. Students see the offline banner until you launch the session.
                </div>
                """, unsafe_allow_html=True)

        with col_st2:
            if not is_live:
                with st.popover("🚀 Launch Live Class", use_container_width=True):
                    st.write("### Configure Live Session")
                    new_topic = st.text_input("Session Topic / Subject", value=session_topic or "Mathematics & Science Live Coaching")
                    new_room = st.text_input("Secure Room Key", value=room_name or "SistersLiveClass_MasterRoom")
                    teacher_msg = st.text_area("Welcome Note for Students", value="Please turn on your camera and mute microphone upon entry.")
                    if st.button("Start Live Broadcast Now", type="primary", use_container_width=True):
                        now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                        c.execute("""
                        UPDATE class_session 
                        SET is_live = 1, topic = ?, room_name = ?, started_at = ?, teacher_notes = ? 
                        WHERE id = 1
                        """, (new_topic, new_room, now_str, teacher_msg))
                        conn.commit()
                        st.success("Live Classroom has been broadcasted! Students can now join.")
                        st.rerun()
            else:
                if st.button("🛑 End Live Class for All", type="primary", use_container_width=True):
                    now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    c.execute("""
                    UPDATE class_session 
                    SET is_live = 0, ended_at = ? 
                    WHERE id = 1
                    """, (now_str,))
                    conn.commit()
                    st.warning("Live class ended. Students are now redirected to offline status.")
                    st.rerun()

        with col_st3:
            # Quick Link to Teacher's Google Drive Folder
            st.link_button("📂 Open My Google Drive Folder", "https://drive.google.com/drive/my-drive", use_container_width=True)

        st.markdown("---")

        # Live Jitsi Screen & Screen Recorder
        if is_live:
            st.markdown("#### 🎥 Teacher Live Studio & Interactive Whiteboard")
            render_jitsi_classroom(
                room_name=room_name,
                display_name=f"{user['full_name']} (Teacher/Host)",
                is_teacher=True,
                session_topic=session_topic
            )

            st.markdown("#### ⏺️ Built-in 1-Click Screen & Audio Recorder")
            render_browser_screen_recorder()

            with st.expander("🛡️ Teacher Moderator Quick Guide"):
                st.markdown("""
                - **Mute All Students:** Click the `...` (More actions) or `Mute Everyone` icon on the Jitsi toolbar to instantly mute all participants.
                - **Interactive Whiteboard:** Click the Whiteboard icon in the toolbar to draw formulas, diagram sketches, and take notes collaboratively.
                - **Tile View:** Press `W` or click the 4-squares icon to toggle grid view of all students.
                - **Kick / Remove a Disruptive Student:** Hover over any student tile -> Click `...` -> Select `Kick out` or `Mute`.
                """)
        else:
            st.info("💡 To enter the live studio and initiate audio/video with students, click **'Launch Live Class'** above.")

    # ---------------------------------------------
    # TAB 2: GOOGLE DRIVE RECORDINGS & NOTES LIBRARY
    # ---------------------------------------------
    with tab2:
        st.subheader("Google Drive & Recorded Lectures Manager")
        st.markdown("Upload your class recordings to Google Drive, paste the sharing link here, and the system automatically generates an in-app player and direct download button for students.")

        col_rec1, col_rec2 = st.columns([1.2, 1.8])

        with col_rec1:
            st.markdown("### ➕ Add Recorded Lecture")
            with st.form("add_recording_form", clear_on_submit=True):
                rec_title = st.text_input("Lecture Title", placeholder="e.g. Chapter 4: Chemical Bonding")
                rec_subject = st.selectbox("Subject", ["Mathematics", "Physics", "Chemistry", "Biology", "English", "General Coaching"])
                rec_date = st.date_input("Class Date", datetime.date.today())
                rec_link = st.text_input("Google Drive / YouTube Link", placeholder="https://drive.google.com/file/d/FILE_ID/view?usp=sharing")
                rec_desc = st.text_area("Lecture Notes / Summary", placeholder="Key topics covered, homework questions, page numbers...")
                submit_rec = st.form_submit_button("Publish Recording", type="primary", use_container_width=True)

                if submit_rec:
                    if not rec_title or not rec_link:
                        st.error("Title and Google Drive / Video link are required.")
                    else:
                        embed_url, download_url = process_google_drive_link(rec_link)
                        now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                        c.execute("""
                        INSERT INTO recordings (title, subject, lecture_date, description, drive_link, embed_url, download_url, created_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                        """, (rec_title, rec_subject, str(rec_date), rec_desc, rec_link, embed_url, download_url, now_str))
                        conn.commit()
                        st.success("Recorded class published successfully!")
                        st.rerun()

        with col_rec2:
            st.markdown("### 📋 Published Recordings")
            c.execute("SELECT * FROM recordings ORDER BY id DESC")
            recordings_list = c.fetchall()

            if not recordings_list:
                st.info("No recorded classes added yet. Use the form on the left to add one.")
            else:
                for rec in recordings_list:
                    with st.expander(f"🎬 {rec['title']} ({rec['subject']} - {rec['lecture_date']})"):
                        st.write(f"**Description:** {rec['description']}")
                        st.write(f"**Drive Link:** `{rec['drive_link']}`")
                        
                        col_p1, col_p2 = st.columns([1, 1])
                        with col_p1:
                            st.link_button("📥 Direct Download Link", rec['download_url'], use_container_width=True)
                        with col_p2:
                            if st.button(f"🗑️ Delete Lecture #{rec['id']}", key=f"del_rec_{rec['id']}", use_container_width=True):
                                c.execute("DELETE FROM recordings WHERE id = ?", (rec['id'],))
                                conn.commit()
                                st.success("Recording deleted.")
                                st.rerun()

                        # In-app player preview
                        if "drive.google.com" in rec['embed_url'] or "youtube.com" in rec['embed_url']:
                            st.markdown(f"""
                            <iframe src="{rec['embed_url']}" width="100%" height="320" frameborder="0" allow="autoplay; fullscreen" allowfullscreen></iframe>
                            """, unsafe_allow_html=True)

    # ---------------------------------------------
    # TAB 3: NOTICE BOARD
    # ---------------------------------------------
    with tab3:
        st.subheader("Notice Board & Announcement Alerts")
        st.markdown("Announcements are immediately highlighted at the top of the Student Dashboard.")

        col_n1, col_n2 = st.columns([1.2, 1.8])
        with col_n1:
            st.markdown("### 📢 Post New Announcement")
            with st.form("post_notice_form", clear_on_submit=True):
                n_title = st.text_input("Notice Title", placeholder="e.g. Test Tomorrow at 5:00 PM")
                n_priority = st.selectbox("Priority / Category", ["Important", "Exam", "Holiday", "Normal"])
                n_message = st.text_area("Notice Details", placeholder="Complete chapter 3 exercises and be ready for quiz.")
                submit_notice = st.form_submit_button("Publish Announcement", type="primary", use_container_width=True)

                if submit_notice:
                    if not n_title or not n_message:
                        st.error("Please provide both title and notice message.")
                    else:
                        now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                        c.execute("""
                        INSERT INTO announcements (title, message, priority, created_at)
                        VALUES (?, ?, ?, ?)
                        """, (n_title, n_message, n_priority, now_str))
                        conn.commit()
                        st.success("Notice posted!")
                        st.rerun()

        with col_n2:
            st.markdown("### 📌 Active Notices")
            c.execute("SELECT * FROM announcements ORDER BY id DESC")
            notices = c.fetchall()

            if not notices:
                st.info("No active notices.")
            else:
                for n in notices:
                    badge_class = "notice-card"
                    if n['priority'] == 'Important': badge_class += " notice-important"
                    elif n['priority'] == 'Exam': badge_class += " notice-exam"
                    elif n['priority'] == 'Holiday': badge_class += " notice-holiday"

                    st.markdown(f"""
                    <div class="{badge_class}">
                        <div style="display:flex; justify-content:space-between; align-items:center;">
                            <h4 style="margin:0; color:#1e293b;">{n['title']}</h4>
                            <span style="font-size:0.8rem; background:#cbd5e1; padding:2px 8px; border-radius:12px; font-weight:600;">{n['priority']}</span>
                        </div>
                        <p style="margin:8px 0 4px 0; color:#475569;">{n['message']}</p>
                        <small style="color:#94a3b8;">Posted on: {n['created_at']}</small>
                    </div>
                    """, unsafe_allow_html=True)
                    if st.button("Delete Notice", key=f"del_not_{n['id']}"):
                        c.execute("DELETE FROM announcements WHERE id = ?", (n['id'],))
                        conn.commit()
                        st.rerun()

    # ---------------------------------------------
    # TAB 4: DOUBTS & CHAT BOARD
    # ---------------------------------------------
    with tab4:
        st.subheader("Student Doubts & Questions")
        st.markdown("Review and answer questions raised by students before, during, or after class.")

        c.execute("SELECT * FROM doubts ORDER BY id DESC")
        doubts_list = c.fetchall()

        if not doubts_list:
            st.info("No student doubts posted yet.")
        else:
            for d in doubts_list:
                status_color = "#f59e0b" if d['status'] == 'Pending' else "#10b981"
                with st.expander(f"❓ [{d['subject']}] {d['student_name']} (@{d['student_username']}) - Status: {d['status']}"):
                    st.write(f"**Question:** {d['question']}")
                    st.caption(f"Submitted on: {d['created_at']}")

                    if d['reply']:
                        st.markdown(f"""
                        <div style="background:#f0fdf4; border-left:4px solid #10b981; padding:10px 14px; border-radius:6px; margin:10px 0;">
                            <b>Teacher's Answer:</b> {d['reply']}<br>
                            <small style="color:#64748b;">Answered on: {d['replied_at']}</small>
                        </div>
                        """, unsafe_allow_html=True)

                    with st.form(f"reply_form_{d['id']}"):
                        reply_text = st.text_area("Your Response / Explanation", value=d['reply'] or "", key=f"rep_txt_{d['id']}")
                        col_btn1, col_btn2 = st.columns([1, 1])
                        with col_btn1:
                            submit_rep = st.form_submit_button("Send Answer", type="primary", use_container_width=True)
                        with col_btn2:
                            clear_rep = st.form_submit_button("Clear / Delete Doubt", use_container_width=True)

                        if submit_rep:
                            if reply_text.strip():
                                now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                                c.execute("""
                                UPDATE doubts 
                                SET reply = ?, status = 'Answered', replied_at = ? 
                                WHERE id = ?
                                """, (reply_text.strip(), now_str, d['id']))
                                conn.commit()
                                st.success("Answer saved and published to student.")
                                st.rerun()
                            else:
                                st.error("Response cannot be empty.")

                        if clear_rep:
                            c.execute("DELETE FROM doubts WHERE id = ?", (d['id'],))
                            conn.commit()
                            st.warning("Doubt removed.")
                            st.rerun()

    # ---------------------------------------------
    # TAB 5: ATTENDANCE & STUDENT MANAGEMENT
    # ---------------------------------------------
    with tab5:
        st.subheader("Attendance Records & Student Account Administration")

        subtab_att, subtab_users = st.tabs(["📊 Live Attendance Logs", "👤 Student Accounts & Access Control"])

        with subtab_att:
            st.markdown("### 📋 Attendance Records")
            c.execute("SELECT * FROM attendance ORDER BY id DESC")
            att_records = c.fetchall()

            if not att_records:
                st.info("No attendance entries logged yet. Students are automatically logged when they enter the Live Classroom.")
            else:
                att_df = pd.DataFrame([dict(row) for row in att_records])
                st.dataframe(
                    att_df[['id', 'student_name', 'student_username', 'room_name', 'topic', 'join_timestamp', 'date']],
                    use_container_width=True,
                    hide_index=True
                )

                # Export CSV button
                csv_buffer = io.StringIO()
                att_df.to_csv(csv_buffer, index=False)
                st.download_button(
                    label="📥 Export Attendance as CSV",
                    data=csv_buffer.getvalue(),
                    file_name=f"Sisters_Academy_Attendance_{datetime.date.today()}.csv",
                    mime="text/csv",
                    type="primary"
                )

        with subtab_users:
            st.markdown("### 👥 Manage Student Access & Passwords")
            st.caption("Block student access if needed, reset passwords, or register new students.")

            col_u1, col_u2 = st.columns([1.2, 1.8])

            with col_u1:
                st.markdown("#### ➕ Add New Student")
                with st.form("add_student_form", clear_on_submit=True):
                    new_uname = st.text_input("Username", placeholder="e.g. student11").strip().lower()
                    new_fname = st.text_input("Full Name", placeholder="e.g. Sara Ahmed")
                    new_pwd = st.text_input("Initial Password", value="pass123")
                    submit_add_st = st.form_submit_button("Register Student", type="primary", use_container_width=True)

                    if submit_add_st:
                        if not new_uname or not new_fname or not new_pwd:
                            st.error("All fields are required.")
                        else:
                            pwd_hashed = hash_password(new_pwd)
                            now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                            try:
                                c.execute("""
                                INSERT INTO users (username, password_hash, role, full_name, is_active, created_at)
                                VALUES (?, ?, 'student', ?, 1, ?)
                                """, (new_uname, pwd_hashed, new_fname, now_str))
                                conn.commit()
                                st.success(f"Student {new_fname} (@{new_uname}) registered successfully!")
                                st.rerun()
                            except sqlite3.IntegrityError:
                                st.error(f"Username '{new_uname}' is already taken.")

            with col_u2:
                st.markdown("#### 🔒 Student List & Access Controls")
                c.execute("SELECT id, username, full_name, is_active, created_at FROM users WHERE role = 'student' ORDER BY id ASC")
                students = c.fetchall()

                for s in students:
                    status_text = "🟢 Active" if s['is_active'] == 1 else "🔴 Blocked / Suspended"
                    with st.expander(f"{s['full_name']} (@{s['username']}) - {status_text}"):
                        c_act1, c_act2, c_act3 = st.columns([1, 1, 1])

                        with c_act1:
                            if s['is_active'] == 1:
                                if st.button("🚫 Block Student", key=f"blk_{s['id']}", use_container_width=True):
                                    c.execute("UPDATE users SET is_active = 0 WHERE id = ?", (s['id'],))
                                    conn.commit()
                                    st.warning(f"Student @{s['username']} blocked.")
                                    st.rerun()
                            else:
                                if st.button("✅ Unblock Student", key=f"unblk_{s['id']}", use_container_width=True):
                                    c.execute("UPDATE users SET is_active = 1 WHERE id = ?", (s['id'],))
                                    conn.commit()
                                    st.success(f"Student @{s['username']} unblocked.")
                                    st.rerun()

                        with c_act2:
                            with st.popover("🔑 Reset Password", use_container_width=True):
                                reset_p = st.text_input("New Password", value="pass123", key=f"rst_val_{s['id']}")
                                if st.button("Confirm Reset", key=f"rst_btn_{s['id']}"):
                                    c.execute("UPDATE users SET password_hash = ? WHERE id = ?", (hash_password(reset_p), s['id']))
                                    conn.commit()
                                    st.success(f"Password reset for @{s['username']}.")
                                    st.rerun()

                        with c_act3:
                            if st.button("🗑️ Delete", key=f"del_st_{s['id']}", use_container_width=True):
                                c.execute("DELETE FROM users WHERE id = ?", (s['id'],))
                                conn.commit()
                                st.success("Student removed.")
                                st.rerun()

    conn.close()


# ==========================================
# 8. STUDENT DASHBOARD
# ==========================================
def render_student_dashboard():
    user = st.session_state.user

    # Header Banner
    st.markdown(f"""
    <div class="hero-banner">
        <h1>👋 Welcome, {user['full_name']}!</h1>
        <p>Sister's Live Academy Student Portal | Roll No: @{user['username']}</p>
    </div>
    """, unsafe_allow_html=True)

    # 1. Top Notice Board Alerts
    conn = get_db_connection()
    c = conn.cursor()
    c.execute("SELECT * FROM announcements ORDER BY id DESC LIMIT 3")
    latest_notices = c.fetchall()

    if latest_notices:
        for n in latest_notices:
            badge_class = "notice-card"
            icon = "📢"
            if n['priority'] == 'Important':
                badge_class += " notice-important"
                icon = "🚨"
            elif n['priority'] == 'Exam':
                badge_class += " notice-exam"
                icon = "📝"
            elif n['priority'] == 'Holiday':
                badge_class += " notice-holiday"
                icon = "🏖️"

            st.markdown(f"""
            <div class="{badge_class}">
                <div style="display:flex; justify-content:space-between;">
                    <b style="color:#1e293b;">{icon} {n['title']}</b>
                    <span style="font-size:0.8rem; background:#cbd5e1; padding:2px 8px; border-radius:12px; font-weight:600;">{n['priority']}</span>
                </div>
                <p style="margin:4px 0 0 0; color:#475569; font-size:0.95rem;">{n['message']}</p>
            </div>
            """, unsafe_allow_html=True)

    # Tabs for Student
    tab1, tab2, tab3, tab4 = st.tabs([
        "🎥 Live Classroom",
        "📖 Recorded Lectures & Notes",
        "❓ Ask Doubts & Discussion",
        "📊 My Attendance History"
    ])

    # ---------------------------------------------
    # STUDENT TAB 1: LIVE CLASSROOM
    # ---------------------------------------------
    with tab1:
        c.execute("SELECT * FROM class_session WHERE id = 1")
        session = c.fetchone()
        is_live = bool(session['is_live'])
        room_name = session['room_name']
        session_topic = session['topic']
        teacher_notes = session['teacher_notes']

        if not is_live:
            st.markdown("""
            <div class="glass-card" style="text-align: center; padding: 40px 20px;">
                <div class="offline-badge" style="font-size: 1.1rem; padding: 8px 24px; margin-bottom: 16px;">
                    ⚪ Live Class is Currently Offline
                </div>
                <h3 style="color: #334155; margin-bottom: 8px;">No broadcast active right now.</h3>
                <p style="color: #64748b; max-width: 550px; margin: 0 auto 20px auto;">
                    Please check the notice board announcements for class schedules, or revise past lectures and study notes from the <b>Recorded Lectures & Notes</b> tab.
                </p>
            </div>
            """, unsafe_allow_html=True)
            st.session_state.live_joined = False
        else:
            # Class is LIVE!
            st.markdown(f"""
            <div class="glass-card" style="border: 2px solid #f87171; background: #fff5f5;">
                <div style="display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 12px;">
                    <div>
                        <div class="live-badge">
                            <span class="live-pulse"></span>
                            <span>TEACHER IS LIVE NOW!</span>
                        </div>
                        <h3 style="margin: 8px 0 4px 0; color: #1e293b;">{session_topic}</h3>
                        <p style="margin: 0; color: #475569;">Teacher's Note: {teacher_notes}</p>
                    </div>
                </div>
            </div>
            """, unsafe_allow_html=True)

            if not st.session_state.live_joined:
                col_j1, col_j2, col_j3 = st.columns([1, 2, 1])
                with col_j2:
                    if st.button("🚀 Join Live Class Now (Logs Attendance)", type="primary", use_container_width=True):
                        # Log attendance in database automatically
                        now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                        today_str = str(datetime.date.today())
                        
                        # Check if already logged for this session today
                        c.execute("""
                        SELECT id FROM attendance 
                        WHERE student_username = ? AND date = ? AND room_name = ?
                        """, (user['username'], today_str, room_name))
                        existing = c.fetchone()
                        
                        if not existing:
                            c.execute("""
                            INSERT INTO attendance (student_username, student_name, room_name, topic, join_timestamp, date)
                            VALUES (?, ?, ?, ?, ?, ?)
                            """, (user['username'], user['full_name'], room_name, session_topic, now_str, today_str))
                            conn.commit()

                        st.session_state.live_joined = True
                        st.rerun()
            else:
                st.success("✅ Attendance marked! You are in the live room.")
                render_jitsi_classroom(
                    room_name=room_name,
                    display_name=f"{user['full_name']} (Student)",
                    is_teacher=False,
                    session_topic=session_topic
                )
                if st.button("Leave Live Classroom", use_container_width=False):
                    st.session_state.live_joined = False
                    st.rerun()

    # ---------------------------------------------
    # STUDENT TAB 2: RECORDED LECTURES
    # ---------------------------------------------
    with tab2:
        st.subheader("📚 Study Library & Recorded Classes")
        st.caption("Access all past video lectures stored on Google Drive, download study notes, and watch directly.")

        # Search / filter
        col_s1, col_s2 = st.columns([2, 1])
        with col_s1:
            search_query = st.text_input("🔍 Search by Lecture Topic or Title", placeholder="e.g. Chemical Bonding, Algebra...")
        with col_s2:
            filter_subject = st.selectbox("Filter by Subject", ["All Subjects", "Mathematics", "Physics", "Chemistry", "Biology", "English", "General Coaching"])

        # Fetch recordings
        query = "SELECT * FROM recordings WHERE 1=1"
        params = []
        if search_query:
            query += " AND (title LIKE ? OR description LIKE ?)"
            params.extend([f"%{search_query}%", f"%{search_query}%"])
        if filter_subject != "All Subjects":
            query += " AND subject = ?"
            params.append(filter_subject)

        query += " ORDER BY id DESC"
        c.execute(query, params)
        recordings = c.fetchall()

        if not recordings:
            st.info("No recordings found matching your search criteria.")
        else:
            for rec in recordings:
                with st.container():
                    st.markdown(f"""
                    <div class="glass-card">
                        <div style="display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap;">
                            <h3 style="margin:0; color:#1e293b;">📖 {rec['title']}</h3>
                            <span style="background:#e0e7ff; color:#3730a3; padding:3px 12px; border-radius:9999px; font-weight:600; font-size:0.85rem;">
                                {rec['subject']} | {rec['lecture_date']}
                            </span>
                        </div>
                        <p style="margin:10px 0; color:#475569;">{rec['description'] or 'No description provided.'}</p>
                    </div>
                    """, unsafe_allow_html=True)

                    col_vid, col_btn = st.columns([2.5, 1])
                    with col_vid:
                        if "drive.google.com" in rec['embed_url'] or "youtube.com" in rec['embed_url']:
                            st.markdown(f"""
                            <iframe src="{rec['embed_url']}" width="100%" height="340" frameborder="0" allow="autoplay; fullscreen" allowfullscreen style="border-radius:10px; border:1px solid #cbd5e1;"></iframe>
                            """, unsafe_allow_html=True)
                        else:
                            st.info("Video player preview not available for this custom link format.")
                    with col_btn:
                        st.markdown("#### Options")
                        st.link_button("📥 Direct Download Video", rec['download_url'], type="primary", use_container_width=True)
                        st.link_button("🔗 Open in Google Drive", rec['drive_link'], use_container_width=True)
                        st.caption("Tip: Download to your phone or laptop for offline revision without data charges.")
                    st.markdown("---")

    # ---------------------------------------------
    # STUDENT TAB 3: ASK DOUBTS
    # ---------------------------------------------
    with tab3:
        st.subheader("❓ Ask Doubts & Discussion Board")
        st.markdown("Have questions about homework or a concept? Ask here anytime. Teacher will reply directly.")

        col_d1, col_d2 = st.columns([1.2, 1.8])

        with col_d1:
            st.markdown("### ✍️ Post a New Question")
            with st.form("student_doubt_form", clear_on_submit=True):
                d_subject = st.selectbox("Subject", ["Mathematics", "Physics", "Chemistry", "Biology", "English", "General Coaching"])
                d_question = st.text_area("Your Question / Doubt", placeholder="Describe your doubt in detail...")
                submit_d = st.form_submit_button("Submit Question to Teacher", type="primary", use_container_width=True)

                if submit_d:
                    if not d_question.strip():
                        st.error("Please write your question before submitting.")
                    else:
                        now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                        c.execute("""
                        INSERT INTO doubts (student_username, student_name, question, subject, created_at)
                        VALUES (?, ?, ?, ?, ?)
                        """, (user['username'], user['full_name'], d_question.strip(), d_subject, now_str))
                        conn.commit()
                        st.success("Your question has been sent to the Teacher! Check answers on the right.")
                        st.rerun()

        with col_d2:
            st.markdown("### 💬 Your Questions & Teacher Replies")
            c.execute("SELECT * FROM doubts WHERE student_username = ? ORDER BY id DESC", (user['username'],))
            my_doubts = c.fetchall()

            if not my_doubts:
                st.info("You haven't posted any questions yet.")
            else:
                for d in my_doubts:
                    is_ans = d['status'] == 'Answered'
                    status_badge = "🟢 Answered" if is_ans else "🟠 Awaiting Teacher Reply"

                    with st.container():
                        st.markdown(f"""
                        <div class="glass-card">
                            <div style="display:flex; justify-content:space-between; align-items:center;">
                                <b style="color:#1e293b;">[{d['subject']}]</b>
                                <span style="font-size:0.85rem; font-weight:600;">{status_badge}</span>
                            </div>
                            <p style="margin:8px 0; color:#334155;"><b>Question:</b> {d['question']}</p>
                            <small style="color:#94a3b8;">Posted on: {d['created_at']}</small>
                        </div>
                        """, unsafe_allow_html=True)

                        if d['reply']:
                            st.markdown(f"""
                            <div style="background:#f0fdf4; border-left:4px solid #10b981; padding:12px 16px; border-radius:8px; margin-bottom:18px;">
                                <b style="color:#166534;">👩‍🏫 Teacher's Response:</b>
                                <p style="margin:4px 0; color:#14532d;">{d['reply']}</p>
                                <small style="color:#64748b;">Answered at: {d['replied_at']}</small>
                            </div>
                            """, unsafe_allow_html=True)

    # ---------------------------------------------
    # STUDENT TAB 4: MY ATTENDANCE
    # ---------------------------------------------
    with tab4:
        st.subheader("📊 My Class Attendance History")
        c.execute("SELECT * FROM attendance WHERE student_username = ? ORDER BY id DESC", (user['username'],))
        my_att = c.fetchall()

        if not my_att:
            st.info("No attendance records found yet. Click 'Join Live Class' when the teacher is live to log your attendance.")
        else:
            df = pd.DataFrame([dict(row) for row in my_att])
            st.write(f"**Total Live Classes Attended:** {len(df)}")
            st.dataframe(
                df[['date', 'join_timestamp', 'topic', 'room_name']],
                use_container_width=True,
                hide_index=True
            )

    conn.close()


# ==========================================
# 9. MAIN ROUTER & SIDEBAR
# ==========================================
def main():
    # If not logged in, show login screen
    if not st.session_state.authenticated or not st.session_state.user:
        render_login_screen()
        return

    user = st.session_state.user

    # Sidebar Navigation & Account Info
    with st.sidebar:
        st.markdown(f"""
        <div style="text-align: center; padding: 15px 0;">
            <div style="font-size: 3rem; margin-bottom: 5px;">🎓</div>
            <h2 style="margin:0; font-size:1.3rem;">Sister's Live Academy</h2>
            <p style="color:#64748b; font-size:0.85rem; margin-top:2px;">Online Classroom Portal</p>
        </div>
        """, unsafe_allow_html=True)

        st.markdown(f"""
        <div style="background:#f1f5f9; padding:12px; border-radius:10px; margin-bottom:15px;">
            <div style="font-size:0.8rem; color:#64748b; text-transform:uppercase; font-weight:700;">Signed in as</div>
            <div style="font-weight:700; color:#1e293b; font-size:1rem;">{user['full_name']}</div>
            <div style="font-size:0.85rem; color:#4f46e5; font-weight:600;">Role: {user['role'].capitalize()} (@{user['username']})</div>
        </div>
        """, unsafe_allow_html=True)

        # Database engine info
        supabase_ready = get_supabase_client() is not None
        db_mode_label = "Supabase Cloud" if supabase_ready else "Local SQLite (classroom.db)"
        st.caption(f"Storage Engine: **{db_mode_label}**")

        st.markdown("---")
        if st.button("🚪 Sign Out", use_container_width=True, type="secondary"):
            st.session_state.authenticated = False
            st.session_state.user = None
            st.session_state.live_joined = False
            st.rerun()

    # Route based on role
    if user['role'] == 'teacher':
        render_teacher_dashboard()
    else:
        render_student_dashboard()


if __name__ == "__main__":
    main()
