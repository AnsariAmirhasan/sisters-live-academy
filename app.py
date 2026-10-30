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
import base64
import threading
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
# 3. HYBRID DATABASE ENGINE & CLOUD PERSISTENCE (SQLITE + GITHUB AUTO-SYNC)
# ==========================================
DB_FILE = "classroom.db"

class CheckpointingConnection(sqlite3.Connection):
    """
    Subclass of sqlite3.Connection that automatically truncates and flushes the
    Write-Ahead Log (WAL) into classroom.db every time a write transaction commits.
    This guarantees that the main classroom.db file on disk is always completely current.
    """
    def __exit__(self, exc_type, exc_val, exc_tb):
        res = super().__exit__(exc_type, exc_val, exc_tb)
        if exc_type is None:
            try:
                self.execute("PRAGMA wal_checkpoint(TRUNCATE);")
            except Exception:
                pass
        return res

def flush_db_wal():
    """Flushes all pending SQLite WAL pages directly into classroom.db so the main file is always 100% up-to-date."""
    try:
        conn = sqlite3.connect(DB_FILE, timeout=10.0)
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE);")
        conn.close()
    except Exception as e:
        print(f"WAL checkpoint error: {e}")

def get_db_connection():
    """
    Opens a fresh, short-lived SQLite connection with 30s timeout, WAL journal mode,
    and automatic checkpointing upon transaction exit.
    """
    conn = sqlite3.connect(DB_FILE, timeout=30.0, check_same_thread=False, factory=CheckpointingConnection)
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


def get_github_config() -> tuple:
    """
    Returns (github_token, github_repo) from:
    1. st.secrets ('GITHUB_TOKEN', 'GITHUB_REPO')
    2. os.environ ('GITHUB_TOKEN', 'GITHUB_REPO')
    3. SQLite table app_meta (key='github_token', key='github_repo')
    Defaults repository to 'AnsariAmirhasan/sisters-live-academy'
    """
    token = ""
    repo = "AnsariAmirhasan/sisters-live-academy"

    try:
        token = st.secrets.get("GITHUB_TOKEN", os.environ.get("GITHUB_TOKEN", ""))
        repo = st.secrets.get("GITHUB_REPO", os.environ.get("GITHUB_REPO", repo))
    except Exception:
        token = os.environ.get("GITHUB_TOKEN", "")
        repo = os.environ.get("GITHUB_REPO", repo)

    if not token:
        try:
            if os.path.exists(DB_FILE):
                conn_tmp = sqlite3.connect(DB_FILE, timeout=4.0)
                c_tmp = conn_tmp.cursor()
                c_tmp.execute("CREATE TABLE IF NOT EXISTS app_meta (key TEXT PRIMARY KEY, value TEXT)")
                c_tmp.execute("SELECT value FROM app_meta WHERE key = 'github_token'")
                row_t = c_tmp.fetchone()
                if row_t and row_t[0]:
                    token = row_t[0]
                c_tmp.execute("SELECT value FROM app_meta WHERE key = 'github_repo'")
                row_r = c_tmp.fetchone()
                if row_r and row_r[0]:
                    repo = row_r[0]
                conn_tmp.close()
        except Exception:
            pass

    return (token.strip() if token else "", repo.strip() if repo else "AnsariAmirhasan/sisters-live-academy")


def sync_db_to_cloud(commit_message: str = "Auto-sync database") -> tuple:
    """
    Flushes SQLite WAL to classroom.db and commits the updated database
    directly to GitHub repository via GitHub Contents API.
    """
    flush_db_wal()
    token, repo = get_github_config()
    if not token:
        return False, "GITHUB_TOKEN is not configured. Add it in Streamlit Cloud Secrets or Super Admin settings."

    if not os.path.exists(DB_FILE):
        return False, f"{DB_FILE} not found on disk."

    try:
        with open(DB_FILE, "rb") as f:
            db_bytes = f.read()

        if not db_bytes.startswith(b"SQLite format 3\x00"):
            return False, "Local database file is not a valid SQLite database."

        content_b64 = base64.b64encode(db_bytes).decode('utf-8')

        headers = {
            "Authorization": f"token {token}",
            "Accept": "application/vnd.github.v3+json",
            "User-Agent": "SistersLiveAcademy-Sync",
            "Content-Type": "application/json"
        }
        api_url = f"https://api.github.com/repos/{repo}/contents/{DB_FILE}"

        # 1. Get current file SHA on main branch
        sha = None
        try:
            req_get = urllib.request.Request(f"{api_url}?ref=main", headers=headers)
            with urllib.request.urlopen(req_get, timeout=4) as resp:
                if resp.status == 200:
                    info = json.loads(resp.read().decode('utf-8'))
                    sha = info.get("sha")
        except urllib.error.HTTPError as he:
            if he.code != 404:
                return False, f"GitHub check failed (HTTP {he.code}): {he.reason}"
        except Exception as e:
            return False, f"GitHub connect error: {e}"

        # 2. PUT updated classroom.db
        payload = {
            "message": f"☁️ [Auto-Sync] {commit_message}",
            "content": content_b64,
            "branch": "main"
        }
        if sha:
            payload["sha"] = sha

        req_put = urllib.request.Request(
            api_url,
            data=json.dumps(payload).encode('utf-8'),
            headers=headers,
            method="PUT"
        )
        with urllib.request.urlopen(req_put, timeout=4) as resp:
            if resp.status in (200, 201):
                return True, "Database synced to GitHub successfully!"
            return False, f"Unexpected response status: {resp.status}"

    except urllib.error.HTTPError as he:
        err_msg = he.read().decode('utf-8', errors='ignore')
        return False, f"GitHub API error ({he.code}): {err_msg}"
    except Exception as e:
        return False, f"Cloud sync failed: {e}"


def trigger_cloud_sync(commit_message: str = "Auto-sync database", blocking: bool = False):
    """
    Flushes WAL and triggers cloud sync.
    If blocking=True, waits for result and returns (success: bool, msg: str).
    If blocking=False, launches in daemon background thread to keep UI snappy.
    """
    flush_db_wal()
    if blocking:
        return sync_db_to_cloud(commit_message)
    else:
        t = threading.Thread(target=sync_db_to_cloud, args=(commit_message,), daemon=True)
        t.start()
        return True, "Sync queued in background"


_CLOUD_PULL_DONE = False

def pull_db_from_cloud() -> tuple:
    """
    Fetches the latest classroom.db from GitHub repository on startup.
    Ensures that waking / redeploying Streamlit Community Cloud instances
    immediately restore all teacher and student accounts without data loss.
    """
    token, repo = get_github_config()
    if not token:
        return False, "GITHUB_TOKEN not configured."

    headers = {
        "Authorization": f"token {token}",
        "User-Agent": "SistersLiveAcademy-Sync"
    }

    try:
        # First attempt: request raw bytes directly
        raw_headers = dict(headers)
        raw_headers["Accept"] = "application/vnd.github.v3.raw"
        req_raw = urllib.request.Request(f"https://api.github.com/repos/{repo}/contents/{DB_FILE}?ref=main", headers=raw_headers)
        
        db_bytes = None
        try:
            with urllib.request.urlopen(req_raw, timeout=12) as resp:
                if resp.status == 200:
                    content = resp.read()
                    if content.startswith(b"SQLite format 3\x00"):
                        db_bytes = content
        except Exception:
            pass

        # Second attempt if raw didn't work: standard json request to get download_url or content
        if not db_bytes:
            json_headers = dict(headers)
            json_headers["Accept"] = "application/vnd.github.v3+json"
            req_json = urllib.request.Request(f"https://api.github.com/repos/{repo}/contents/{DB_FILE}?ref=main", headers=json_headers)
            with urllib.request.urlopen(req_json, timeout=12) as resp:
                if resp.status == 200:
                    meta = json.loads(resp.read().decode('utf-8'))
                    dl_url = meta.get("download_url")
                    if dl_url:
                        dl_req = urllib.request.Request(dl_url, headers=headers)
                        with urllib.request.urlopen(dl_req, timeout=12) as dl_resp:
                            dl_data = dl_resp.read()
                            if dl_data.startswith(b"SQLite format 3\x00"):
                                db_bytes = dl_data
                    elif meta.get("content"):
                        decoded = base64.b64decode(meta["content"])
                        if decoded.startswith(b"SQLite format 3\x00"):
                            db_bytes = decoded

        if db_bytes and db_bytes.startswith(b"SQLite format 3\x00"):
            tmp_path = DB_FILE + ".cloud_pull"
            with open(tmp_path, "wb") as f:
                f.write(db_bytes)
            os.replace(tmp_path, DB_FILE)
            return True, f"Successfully pulled {len(db_bytes)} bytes from GitHub repository ({repo})."
        return False, "Could not retrieve valid SQLite database from GitHub."

    except Exception as e:
        return False, f"Startup pull error: {e}"


def ensure_cloud_db_pulled():
    global _CLOUD_PULL_DONE
    if _CLOUD_PULL_DONE:
        return
    _CLOUD_PULL_DONE = True
    ok, msg = pull_db_from_cloud()
    if ok:
        print(f"[Cloud Sync] {msg}")
    else:
        print(f"[Cloud Sync] Startup pull notice: {msg}")


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

UPLOAD_DIR = "uploaded_recordings"
os.makedirs(UPLOAD_DIR, exist_ok=True)

def save_recording_file(file_obj, original_filename: str) -> str:
    """Saves an uploaded video file locally in uploaded_recordings/ and returns safe relative filename."""
    os.makedirs(UPLOAD_DIR, exist_ok=True)
    clean_name = re.sub(r'[^a-zA-Z0-9_\-\.]', '_', original_filename)
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    safe_filename = f"{timestamp}_{clean_name}"
    target_path = os.path.join(UPLOAD_DIR, safe_filename)
    file_obj.seek(0)
    with open(target_path, "wb") as f:
        f.write(file_obj.read())
    file_obj.seek(0)
    return safe_filename

def process_and_save_recording(uploaded_file, title: str, subject: str, notes: str = "") -> tuple[bool, str, bool, str]:
    """
    Saves recording locally on disk first (guaranteed 100% working without any external APIs),
    then attempts optional Google Drive sync if service account credentials exist in st.secrets.
    Inserts a row into recordings SQLite table and syncs with Supabase.
    Returns (success: bool, safe_filename: str, gdrive_synced: bool, final_link: str).
    """
    safe_fn = save_recording_file(uploaded_file, uploaded_file.name)
    local_uri = f"local://{safe_fn}"
    final_drive_link = local_uri
    final_embed_url = local_uri
    final_download_url = local_uri
    gdrive_synced = False

    # Optional Google Drive sync if service account is configured
    try:
        ok_drive, g_link, _ = upload_file_to_google_drive(uploaded_file, safe_fn, DEFAULT_DRIVE_FOLDER_ID)
        if ok_drive and g_link:
            final_drive_link = g_link
            final_embed_url, final_download_url = process_google_drive_link(g_link)
            gdrive_synced = True
    except Exception as e:
        print(f"Optional Google Drive sync skipped: {e}")

    now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    today_str = str(datetime.date.today())
    desc = notes.strip() if notes.strip() else f"Uploaded class recording ({uploaded_file.name})"

    try:
        with get_db_connection() as conn_w:
            conn_w.execute("""
            INSERT INTO recordings (title, subject, lecture_date, description, drive_link, embed_url, download_url, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (title.strip(), subject.strip(), today_str, desc, final_drive_link, final_embed_url, final_download_url, now_str))
            conn_w.commit()
            trigger_cloud_sync(f"Added recording '{title.strip()}'")
    except Exception as e:
        print(f"Error saving recording row: {e}")

    if is_supabase_active():
        supabase_request("POST", "recordings", {
            "title": title.strip(),
            "subject": subject.strip(),
            "lecture_date": today_str,
            "description": desc,
            "drive_link": final_drive_link,
            "embed_url": final_embed_url,
            "download_url": final_download_url,
            "created_at": now_str
        })

    return True, safe_fn, gdrive_synced, final_drive_link

def render_recording_player(rec: dict, is_student: bool = False, key_suffix: str = ""):
    """Renders either local audio/video player or embedded Google Drive / YouTube player"""
    drive_link = rec.get('drive_link') or ''
    embed_url = rec.get('embed_url') or ''
    is_local = drive_link.startswith("local://") or embed_url.startswith("local://")

    if is_local:
        safe_fn = drive_link.replace("local://", "") if drive_link.startswith("local://") else embed_url.replace("local://", "")
        file_path = os.path.join(UPLOAD_DIR, safe_fn)
        if os.path.exists(file_path):
            ext = safe_fn.rsplit('.', 1)[-1].lower() if '.' in safe_fn else ''
            # Play saved local audio recordings using Streamlit's native audio player
            # so students can easily listen to recorded lessons on mobile with minimal data
            is_video = ext in ['mp4', 'mkv', 'avi', 'mov']
            if is_video:
                st.video(file_path)
            else:
                st.audio(file_path)

            try:
                with open(file_path, "rb") as vf:
                    file_bytes = vf.read()
                mime_map = {
                    'webm': 'audio/webm',
                    'mp3': 'audio/mpeg',
                    'wav': 'audio/wav',
                    'm4a': 'audio/mp4',
                    'ogg': 'audio/ogg',
                    'mp4': 'video/mp4'
                }
                st.download_button(
                    "⬇️ Download Audio Lecture" if not is_video else "📥 Direct Download Video",
                    data=file_bytes,
                    file_name=safe_fn,
                    mime=mime_map.get(ext, "application/octet-stream"),
                    type="primary" if is_student else "secondary",
                    use_container_width=True,
                    key=f"dl_loc_{rec.get('id', 0)}_{key_suffix}"
                )
            except Exception as e:
                print(f"Error reading local recording bytes: {e}")
        else:
            st.warning(f"⚠️ Recording file `{safe_fn}` not found on server storage.")
    else:
        if "drive.google.com" in embed_url or "youtube.com" in embed_url:
            st.markdown(f"""
            <iframe src="{embed_url}" width="100%" height="340" frameborder="0" allow="autoplay; fullscreen" allowfullscreen style="border-radius:10px; border:1px solid #cbd5e1;"></iframe>
            """, unsafe_allow_html=True)
        if is_student:
            c1, c2 = st.columns(2)
            with c1:
                st.link_button("⬇️ Download Audio Lecture", rec.get('download_url') or drive_link, type="primary", use_container_width=True)
            with c2:
                st.link_button("🔗 Open in Google Drive", drive_link, use_container_width=True)
        else:
            dl = rec.get('download_url') or drive_link
            if dl:
                st.link_button("📥 Direct Download Link", dl, use_container_width=True)

def render_quick_recording_uploader(key_suffix: str = "main", title: str = "Publish Audio Lecture / Recording"):
    """Reusable widget to upload and publish audio lecture recordings immediately to all students"""
    with st.expander(f"🎙️ {title}", expanded=False):
        st.write("Upload a recorded `.webm`, `.mp3`, `.wav`, `.m4a`, `.ogg`, or `.mp4` audio lecture to immediately save and publish it to all Students:")
        uploaded_file = st.file_uploader(
            "Select or drop audio lecture recording file",
            type=["webm", "mp3", "wav", "m4a", "ogg", "mp4"],
            key=f"file_up_{key_suffix}"
        )
        if uploaded_file is not None:
            up_col1, up_col2 = st.columns([1.5, 1])
            with up_col1:
                up_title = st.text_input("Recording Title", value=uploaded_file.name.rsplit(".", 1)[0], key=f"title_{key_suffix}")
            with up_col2:
                up_sub = st.text_input("Subject", value="Urdu / Arabic", placeholder="Type any subject e.g. Urdu, Arabic, Tajweed, Grammar...", key=f"sub_{key_suffix}")
            up_notes = st.text_input("Notes / Summary (Optional)", placeholder="e.g. Chapter 1 voice lecture, grammar pronunciation exercises", key=f"notes_{key_suffix}")

            if st.button("🚀 Upload & Publish Audio Lecture to Students", type="primary", use_container_width=True, key=f"btn_save_{key_suffix}"):
                with st.spinner("Saving audio lecture locally and publishing to students..."):
                    ok, safe_fn, gdrive_synced, drive_link = process_and_save_recording(uploaded_file, up_title, up_sub, up_notes)
                    if ok:
                        if gdrive_synced:
                            st.success(f"✅ Audio lecture published locally & synced to Google Drive folder! ({safe_fn})")
                        else:
                            st.success(f"✅ Audio lecture uploaded and published to all students successfully! ({safe_fn})")
                        st.rerun()

def ensure_class_state_table(conn=None):
    """
    100% fail-safe initialization and schema migration for class_state and class_session.
    Ensures class_state is a REAL SQLite table (not a view) with all required columns:
    id, is_live, topic, subject, jitsi_server, room_name, teacher_note, host_teacher, started_at, ended_at.
    """
    if conn is None:
        conn = get_db()

    try:
        # 1. If class_state exists as a view, drop it so it can be a real writable table
        c_check = conn.cursor()
        c_check.execute("SELECT type FROM sqlite_master WHERE name = 'class_state'")
        row_type = c_check.fetchone()
        if row_type and row_type[0] == 'view':
            conn.execute("DROP VIEW IF EXISTS class_state")
            conn.commit()
    except Exception:
        pass

    # 2. Create class_state as a real table
    conn.execute("""
    CREATE TABLE IF NOT EXISTS class_state (
        id INTEGER PRIMARY KEY,
        is_live INTEGER DEFAULT 0,
        topic TEXT DEFAULT 'Urdu & Arabic Live Class',
        subject TEXT DEFAULT 'Urdu / Arabic',
        jitsi_server TEXT DEFAULT 'jitsi.riot.im',
        room_name TEXT DEFAULT 'SistersLiveClass_MasterRoom',
        teacher_note TEXT DEFAULT '',
        host_teacher TEXT DEFAULT 'Lead Teacher',
        started_at TEXT,
        ended_at TEXT
    )
    """)

    # 3. Ensure all required columns exist via ALTER TABLE checks
    cols_to_check = {
        'is_live': "INTEGER DEFAULT 0",
        'topic': "TEXT DEFAULT 'Urdu & Arabic Live Class'",
        'subject': "TEXT DEFAULT 'Urdu / Arabic'",
        'jitsi_server': "TEXT DEFAULT 'jitsi.riot.im'",
        'room_name': "TEXT DEFAULT 'SistersLiveClass_MasterRoom'",
        'teacher_note': "TEXT DEFAULT ''",
        'host_teacher': "TEXT DEFAULT 'Lead Teacher'",
        'started_at': "TEXT",
        'ended_at': "TEXT"
    }
    try:
        c_cur = conn.cursor()
        c_cur.execute("PRAGMA table_info(class_state)")
        existing_cols = {r[1] for r in c_cur.fetchall()}
        for col_name, col_def in cols_to_check.items():
            if col_name not in existing_cols:
                try:
                    conn.execute(f"ALTER TABLE class_state ADD COLUMN {col_name} {col_def}")
                except Exception:
                    pass
        conn.commit()
    except Exception:
        pass

    # 4. Ensure row 1 exists in class_state
    try:
        c_cur = conn.cursor()
        c_cur.execute("SELECT COUNT(*) as cnt FROM class_state WHERE id = 1")
        if c_cur.fetchone()['cnt'] == 0:
            conn.execute("""
            INSERT OR REPLACE INTO class_state (id, is_live, topic, subject, jitsi_server, room_name, teacher_note, host_teacher)
            VALUES (1, 0, 'Urdu & Arabic Live Class', 'Urdu / Arabic', 'jitsi.riot.im', 'SistersLiveClass_MasterRoom', 'Welcome! Camera is OFF by default. Unmute mic to ask doubts.', 'Lead Teacher')
            """)
            conn.commit()
    except Exception:
        pass

    # 5. Maintain compatibility table class_session
    try:
        conn.execute("""
        CREATE TABLE IF NOT EXISTS class_session (
            id INTEGER PRIMARY KEY,
            is_live INTEGER DEFAULT 0,
            topic TEXT DEFAULT 'Urdu & Arabic Live Class',
            room_name TEXT DEFAULT 'SistersLiveClass_MasterRoom',
            server TEXT DEFAULT 'jitsi.riot.im',
            started_at TEXT,
            ended_at TEXT,
            teacher_notes TEXT DEFAULT '',
            host_teacher TEXT DEFAULT 'Lead Teacher'
        )
        """)
        c_cur = conn.cursor()
        c_cur.execute("PRAGMA table_info(class_session)")
        s_cols = {r[1] for r in c_cur.fetchall()}
        if 'server' not in s_cols:
            conn.execute("ALTER TABLE class_session ADD COLUMN server TEXT DEFAULT 'jitsi.riot.im'")
        if 'teacher_notes' not in s_cols:
            conn.execute("ALTER TABLE class_session ADD COLUMN teacher_notes TEXT DEFAULT ''")
        if 'host_teacher' not in s_cols:
            conn.execute("ALTER TABLE class_session ADD COLUMN host_teacher TEXT DEFAULT 'Lead Teacher'")
        c_cur.execute("SELECT COUNT(*) as cnt FROM class_session WHERE id = 1")
        if c_cur.fetchone()['cnt'] == 0:
            conn.execute("""
            INSERT OR REPLACE INTO class_session (id, is_live, topic, room_name, server, teacher_notes, host_teacher)
            VALUES (1, 0, 'Urdu & Arabic Live Class', 'SistersLiveClass_MasterRoom', 'jitsi.riot.im', 'Welcome! Camera is OFF by default. Unmute mic to ask doubts.', 'Lead Teacher')
            """)
        conn.commit()
    except Exception:
        pass


def get_live_class_state() -> dict:
    """
    Directly reads live broadcast state from SQLite without stale cache.
    Reconciles class_state, class_session, and st.session_state.is_live_local.
    """
    conn = get_db()
    ensure_class_state_table(conn)
    c = conn.cursor()

    row = None
    try:
        c.execute("SELECT * FROM class_state WHERE id = 1")
        row = c.fetchone()
    except Exception:
        pass

    if not row:
        try:
            c.execute("SELECT * FROM class_session WHERE id = 1")
            row = c.fetchone()
        except Exception:
            pass

    sess = dict(row) if row else {
        'id': 1, 'is_live': 0, 'topic': 'Urdu & Arabic Live Class',
        'subject': 'Urdu / Arabic', 'jitsi_server': 'jitsi.riot.im', 'server': 'jitsi.riot.im',
        'room_name': 'SistersLiveClass_MasterRoom', 'teacher_note': '', 'teacher_notes': '',
        'host_teacher': 'Lead Teacher', 'started_at': 'Recently'
    }

    # Normalize fields across schemas
    sess['jitsi_server'] = sess.get('jitsi_server') or sess.get('server') or 'jitsi.riot.im'
    sess['server'] = sess['jitsi_server']
    sess['teacher_note'] = sess.get('teacher_note') or sess.get('teacher_notes') or ''
    sess['teacher_notes'] = sess['teacher_note']
    sess['topic'] = sess.get('topic') or 'Urdu & Arabic Live Class'
    sess['room_name'] = sess.get('room_name') or 'SistersLiveClass_MasterRoom'
    sess['started_at'] = sess.get('started_at') or 'Recently'
    sess['host_teacher'] = sess.get('host_teacher') or 'Lead Teacher'

    # Honor immediate local live toggle for instantaneous reactivity
    if st.session_state.get('is_live_local') is True:
        sess['is_live'] = 1

    return sess


def start_live_class(topic: str, subject: str = "Urdu / Arabic", jitsi_server: str = "jitsi.riot.im", room_name: str = "SistersLiveClass_MasterRoom", teacher_notes: str = "", host_teacher: str = "") -> bool:
    """
    100% fail-safe live broadcast starter.
    Explicitly runs INSERT OR REPLACE on class_state and class_session,
    immediately flushes WAL, updates session state, and initiates non-blocking background sync.
    """
    now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    h_name = host_teacher.strip() if host_teacher.strip() else (st.session_state.get('name') or "Teacher")
    t_topic = topic.strip() if topic.strip() else "Urdu & Arabic Live Class"
    t_server = jitsi_server.strip() if jitsi_server.strip() else "jitsi.riot.im"
    t_room = room_name.strip() if room_name.strip() else "SistersLiveClass_MasterRoom"
    t_notes = teacher_notes.strip() if teacher_notes.strip() else "Camera is OFF by default. Unmute mic to ask doubts."
    t_subject = subject.strip() if subject.strip() else "Urdu / Arabic"

    try:
        with get_db_connection() as conn:
            ensure_class_state_table(conn)
            conn.execute("""
            INSERT OR REPLACE INTO class_state (id, is_live, topic, subject, jitsi_server, room_name, teacher_note, host_teacher, started_at)
            VALUES (1, 1, ?, ?, ?, ?, ?, ?, ?)
            """, (t_topic, t_subject, t_server, t_room, t_notes, h_name, now_str))
            conn.execute("""
            INSERT OR REPLACE INTO class_session (id, is_live, topic, room_name, server, teacher_notes, host_teacher, started_at)
            VALUES (1, 1, ?, ?, ?, ?, ?, ?)
            """, (t_topic, t_room, t_server, t_notes, h_name, now_str))
            conn.commit()
            conn.execute("PRAGMA wal_checkpoint(TRUNCATE);")
    except Exception as e:
        print(f"Error starting live class in SQLite: {e}")

    st.session_state.is_live_local = True
    st.session_state.jitsi_server = t_server

    # Non-blocking Supabase sync
    if is_supabase_active():
        try:
            supabase_request("PATCH", "class_session", {
                "is_live": 1, "topic": t_topic, "room_name": t_room,
                "server": t_server, "teacher_notes": t_notes, "host_teacher": h_name, "started_at": now_str
            }, params="id=eq.1")
        except Exception:
            pass

    # Non-blocking background GitHub sync
    try:
        trigger_cloud_sync(f"Started live class '{t_topic}'", blocking=False)
    except Exception:
        pass

    return True


def end_live_class() -> bool:
    """100% fail-safe live broadcast terminator"""
    now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    try:
        with get_db_connection() as conn:
            ensure_class_state_table(conn)
            conn.execute("UPDATE class_state SET is_live = 0, ended_at = ? WHERE id = 1", (now_str,))
            conn.execute("UPDATE class_session SET is_live = 0, ended_at = ? WHERE id = 1", (now_str,))
            conn.commit()
            conn.execute("PRAGMA wal_checkpoint(TRUNCATE);")
    except Exception as e:
        print(f"Error ending live class in SQLite: {e}")

    st.session_state.is_live_local = False

    if is_supabase_active():
        try:
            supabase_request("PATCH", "class_session", {"is_live": 0, "ended_at": now_str}, params="id=eq.1")
        except Exception:
            pass

    try:
        trigger_cloud_sync("Ended live class broadcast", blocking=False)
    except Exception:
        pass

    return True


def reset_studio_state():
    """Forces cache clear, resets class_state cleanly to offline, and updates session state"""
    try:
        if hasattr(st, "cache_data"):
            st.cache_data.clear()
        if hasattr(st, "cache_resource"):
            st.cache_resource.clear()
        st.session_state.is_live_local = False
        with get_db_connection() as conn:
            ensure_class_state_table(conn)
            conn.execute("UPDATE class_state SET is_live = 0 WHERE id = 1")
            conn.execute("UPDATE class_session SET is_live = 0 WHERE id = 1")
            conn.commit()
            conn.execute("PRAGMA wal_checkpoint(TRUNCATE);")
    except Exception as e:
        print(f"Error resetting studio state: {e}")


def init_database():
    """Initializes SQLite schema and ensures columns exist"""
    conn = get_db()
    c = conn.cursor()

    # 0. App Metadata table — used for one-time seed flag so deleted accounts
    #    do NOT reappear after st.rerun() re-triggers init_database()
    c.execute("""
    CREATE TABLE IF NOT EXISTS app_meta (
        key TEXT PRIMARY KEY,
        value TEXT NOT NULL
    )
    """)

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
    ensure_class_state_table(conn)


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

    # 8.5. Payment Settings Table (Editable UPI, GPay number & instructions)
    c.execute("""
    CREATE TABLE IF NOT EXISTS payment_settings (
        id INTEGER PRIMARY KEY,
        upi_id TEXT DEFAULT '',
        payment_number TEXT DEFAULT '',
        account_holder_name TEXT DEFAULT '',
        custom_instructions TEXT DEFAULT ''
    )
    """)
    try:
        c.execute("SELECT COUNT(*) as cnt FROM payment_settings WHERE id = 1")
        if c.fetchone()['cnt'] == 0:
            c.execute("""
            INSERT INTO payment_settings (id, upi_id, payment_number, account_holder_name, custom_instructions)
            VALUES (1, '', '', '', 'Please share your payment reference screenshot with the Teacher after paying.')
            """)
    except Exception:
        pass

    # ---------------------------------------------
    # 9. ENFORCE 3-TIER DEFAULT ACCOUNTS
    # ---------------------------------------------
    now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # (a) ALWAYS enforce Super Admin — admin can never be deleted/locked out
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

    # (b) One-time purge of all old demo/default accounts.
    #     Only the Super Admin (admin) can create real Teacher & Student accounts going forward.
    #     Demo accounts (teacher, teacher1, teacher2, student1..student10) must not appear.
    c.execute("SELECT value FROM app_meta WHERE key = 'demo_accounts_purged_v1'")
    purge_done = c.fetchone()

    if not purge_done:
        demo_usernames = (
            'teacher', 'teacher1', 'teacher2',
            'student1', 'student2', 'student3', 'student4', 'student5',
            'student6', 'student7', 'student8', 'student9', 'student10'
        )
        placeholders = ','.join('?' * len(demo_usernames))
        # Delete their fees first (no orphan records)
        c.execute(f"DELETE FROM fees WHERE student_username IN ({placeholders})", demo_usernames)
        # Delete the demo user accounts
        c.execute(f"DELETE FROM users WHERE username IN ({placeholders})", demo_usernames)
        # Mark purge as done — never runs again
        c.execute("INSERT OR IGNORE INTO app_meta (key, value) VALUES ('demo_accounts_purged_v1', '1')")

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

    # 8.6. Live Board Table (High Clarity Book & Whiteboard Sync)
    c.execute("""
    CREATE TABLE IF NOT EXISTS live_board (
        id INTEGER PRIMARY KEY,
        image_data TEXT,
        mime_type TEXT,
        updated_at TEXT
    )
    """)

    # One-time cleanup of legacy demo Math/Physics entries
    c.execute("SELECT value FROM app_meta WHERE key = 'legacy_cleanup_done_v1'")
    if not c.fetchone():
        try:
            c.execute("DELETE FROM scheduled_classes WHERE topic LIKE '%Trigonometry%' OR topic LIKE '%Electromagnetism%' OR subject LIKE '%Mathematics%' OR subject LIKE '%Physics%'")
            c.execute("UPDATE class_session SET topic = 'Urdu & Arabic Live Class' WHERE topic LIKE '%Mathematics%' OR topic LIKE '%Science%'")
            c.execute("UPDATE recordings SET subject = 'Urdu / Arabic', title = 'Urdu & Arabic Foundation Class 01' WHERE title LIKE '%Foundation & Orientation Class 01%'")
            c.execute("DELETE FROM fees WHERE note LIKE '%#98721%'")
            c.execute("INSERT OR IGNORE INTO app_meta (key, value) VALUES ('legacy_cleanup_done_v1', '1')")
        except Exception as e:
            print(f"Cleanup error: {e}")

    # One-time permanent cleanup of auto-seeded sample classes (never re-seeded)
    c.execute("SELECT value FROM app_meta WHERE key = 'purge_auto_schedules_v2'")
    if not c.fetchone():
        try:
            c.execute("DELETE FROM scheduled_classes WHERE topic LIKE '%Urdu Grammar & Nazm Reading Lesson 1%' OR topic LIKE '%Arabic Grammar (Nahw & Sarf) Essentials%' OR notes LIKE '%Bring notebooks%' OR notes LIKE '%Review previous vocabulary%'")
            c.execute("INSERT OR IGNORE INTO app_meta (key, value) VALUES ('purge_auto_schedules_v2', '1')")
        except Exception as e:
            print(f"Purge auto schedules error: {e}")

    conn.commit()
    try:
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE);")
    except Exception:
        pass
    conn.close()

# Compatibility alias
init_db = init_database

# Run Startup Pull from Cloud (if configured) then initialize DB schema
ensure_cloud_db_pulled()
init_database()


def delete_user_account(target_username: str, caller_role: str, caller_username: str) -> tuple:
    """
    Shared helper: safely deletes a user account and their associated fee records.
    Flushes WAL and triggers cloud sync so the deleted state persists in GitHub.
    Returns (success: bool, message: str)
    """
    # Guard: never delete admin
    if target_username == 'admin':
        return False, "Cannot delete the Super Admin account."

    # Guard: never delete yourself
    if target_username == caller_username:
        return False, "You cannot delete your own account."

    # Role-based permission check
    with get_db_connection() as conn_w:
        row = conn_w.execute("SELECT id, role FROM users WHERE username = ?", (target_username,)).fetchone()
        if not row:
            return False, f"Account '@{target_username}' not found."

        target_id = row['id']
        target_role = row['role']

        # Teachers can only delete students
        if caller_role == 'teacher' and target_role != 'student':
            return False, "Teachers can only delete student accounts."

        # Admins can delete students and teachers
        if caller_role == 'admin' and target_role == 'admin':
            return False, "Cannot delete another admin account."

        try:
            # Remove associated fee records first (no orphan rows)
            conn_w.execute("DELETE FROM fees WHERE student_username = ?", (target_username,))
            # Delete the user account
            conn_w.execute("DELETE FROM users WHERE id = ?", (target_id,))
            conn_w.commit()

            # Mirror delete to Supabase if active
            if is_supabase_active():
                supabase_request("DELETE", "users", params=f"username=eq.{target_username}")
                supabase_request("DELETE", "fees", params=f"student_username=eq.{target_username}")

            # Persist to cloud GitHub
            trigger_cloud_sync(f"Deleted user account @{target_username}")

            return True, f"Account '@{target_username}' permanently deleted."
        except Exception as e:
            return False, f"Delete failed: {e}"

def get_payment_settings():
    """Fetches payment settings (UPI, Number, Instructions) from Supabase or SQLite"""
    if is_supabase_active():
        ok, rows = supabase_request("GET", "payment_settings", params="id=eq.1&select=*")
        if ok and rows:
            return rows[0]
    try:
        with get_db_connection() as conn:
            c = conn.cursor()
            c.execute("SELECT * FROM payment_settings WHERE id = 1")
            row = c.fetchone()
            if row:
                return dict(row)
    except Exception as e:
        print(f"Error fetching payment settings: {e}")
    return {
        "id": 1,
        "upi_id": "",
        "payment_number": "",
        "account_holder_name": "",
        "custom_instructions": ""
    }

def update_payment_settings(upi_id: str, payment_number: str, account_holder_name: str, custom_instructions: str):
    """Updates payment settings in SQLite and Supabase"""
    try:
        with get_db_connection() as conn:
            conn.execute("""
            INSERT INTO payment_settings (id, upi_id, payment_number, account_holder_name, custom_instructions)
            VALUES (1, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                upi_id = excluded.upi_id,
                payment_number = excluded.payment_number,
                account_holder_name = excluded.account_holder_name,
                custom_instructions = excluded.custom_instructions
            """, (upi_id.strip(), payment_number.strip(), account_holder_name.strip(), custom_instructions.strip()))
            conn.commit()
    except Exception as e:
        print(f"Error updating payment settings locally: {e}")
        return False, str(e)

    if is_supabase_active():
        supabase_request("POST", "payment_settings", {
            "id": 1,
            "upi_id": upi_id.strip(),
            "payment_number": payment_number.strip(),
            "account_holder_name": account_holder_name.strip(),
            "custom_instructions": custom_instructions.strip()
        })
    return True, "Payment settings saved successfully!"


# ==========================================
# ==========================================
# 4. CUSTOM CSS (MODERN EDTECH APP STYLING)
# ==========================================
st.markdown("""
<style>
    @import url('https://fonts.googleapis.com/css2?family=Outfit:wght@400;500;600;700;800&family=Inter:wght@400;500;600;700&display=swap');

    html, body, [class*="css"] {
        font-family: 'Outfit', 'Inter', -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
    }

    /* --------------------------------------------------------
       1. MOBILE-COMPATIBLE STREAMLIT HEADER & EXPAND BUTTON
       -------------------------------------------------------- */
    header[data-testid="stHeader"] {
        background: transparent !important;
    }
    [data-testid="stToolbar"], [data-testid="stDecoration"], #MainMenu, .stAppDeployButton, footer, div[data-testid="stStatusWidget"] {
        display: none !important;
        visibility: hidden !important;
    }
    [data-testid="stExpandSidebarButton"], [data-testid="collapsedControl"] {
        display: flex !important;
        visibility: visible !important;
        z-index: 999999 !important;
        background-color: #6366f1 !important;
        color: white !important;
        border-radius: 8px !important;
        margin: 6px !important;
    }
    [data-testid="stExpandSidebarButton"] svg, [data-testid="collapsedControl"] svg {
        color: white !important;
        fill: white !important;
    }

    /* Hide heading anchor link icons (🔗) */
    .stMarkdown h1 a, .stMarkdown h2 a, .stMarkdown h3 a, .stMarkdown h4 a,
    [data-testid="stHeaderActionElements"],
    a.anchorjs-link,
    a[href^="#"] {
        display: none !important;
    }

    /* Full-width native app container */
    div.block-container {
        padding-top: 1.5rem !important;
        padding-bottom: 2.5rem !important;
        max-width: 96% !important;
    }

    /* Mobile Responsive Optimizations */
    @media (max-width: 768px) {
        div.block-container {
            padding-top: 0.9rem !important;
            padding-bottom: 2.5rem !important;
            padding-left: 0.5rem !important;
            padding-right: 0.5rem !important;
            max-width: 100% !important;
        }
        div[data-testid="stButton"] > button,
        div[data-testid="stFormSubmitButton"] > button,
        div[data-testid="stLinkButton"] > a,
        div[data-testid="stPopover"] > button {
            width: 100% !important;
            min-height: 44px !important;
            font-size: 14px !important;
            font-weight: 700 !important;
        }
        iframe[data-testid="stCustomComponentV1"] {
            width: 100% !important;
            border: none !important;
        }
    }

    /* --------------------------------------------------------
       2. MODERN PILL-SHAPED APP NAVIGATION (TABS)
       -------------------------------------------------------- */
    div[data-testid="stTabs"] {
        gap: 10px;
        margin-bottom: 22px;
    }
    div[data-baseweb="tab-list"] {
        background: #f1f5f9;
        padding: 6px 8px;
        border-radius: 9999px;
        gap: 8px;
        border: 1px solid #e2e8f0;
        display: flex;
        flex-wrap: wrap;
        box-shadow: inset 0 2px 4px rgba(0, 0, 0, 0.04);
    }
    button[data-baseweb="tab"] {
        border-radius: 9999px !important;
        padding: 8px 20px !important;
        font-weight: 600 !important;
        font-size: 0.95rem !important;
        color: #475569 !important;
        border: none !important;
        background: transparent !important;
        transition: all 0.25s cubic-bezier(0.4, 0, 0.2, 1) !important;
        white-space: nowrap !important;
    }
    button[data-baseweb="tab"]:hover {
        color: #1e293b !important;
        background: rgba(255, 255, 255, 0.8) !important;
        box-shadow: 0 2px 6px rgba(0, 0, 0, 0.05) !important;
    }
    button[data-baseweb="tab"][aria-selected="true"] {
        background: linear-gradient(135deg, #6366f1 0%, #8b5cf6 100%) !important;
        color: #ffffff !important;
        box-shadow: 0 4px 14px rgba(99, 102, 241, 0.35) !important;
        font-weight: 700 !important;
    }
    div[data-baseweb="tab-highlight"], div[data-baseweb="tab-border"] {
        display: none !important;
    }

    /* --------------------------------------------------------
       3. MODERN BUTTONS & FORM INPUTS (EDTECH PWA AESTHETIC)
       -------------------------------------------------------- */
    div.stButton > button, div.stDownloadButton > button, div[data-testid="stLinkButton"] > a {
        border-radius: 10px !important;
        font-weight: 600 !important;
        font-size: 0.92rem !important;
        font-family: 'Outfit', 'Inter', system-ui, sans-serif !important;
        transition: all 0.2s cubic-bezier(0.4, 0, 0.2, 1) !important;
        box-shadow: 0 2px 5px rgba(0, 0, 0, 0.04) !important;
    }
    div.stButton > button:hover, div.stDownloadButton > button:hover, div[data-testid="stLinkButton"] > a:hover {
        transform: translateY(-1px);
        box-shadow: 0 6px 16px rgba(99, 102, 241, 0.22) !important;
    }
    button[kind="primary"], button[data-testid="baseButton-primary"] {
        background: linear-gradient(135deg, #4f46e5 0%, #6366f1 100%) !important;
        border: none !important;
        color: #ffffff !important;
        box-shadow: 0 4px 14px rgba(79, 70, 229, 0.3) !important;
    }
    button[kind="primary"]:hover, button[data-testid="baseButton-primary"]:hover {
        background: linear-gradient(135deg, #4338ca 0%, #4f46e5 100%) !important;
    }

    /* Inputs */
    div[data-baseweb="input"] input, div[data-baseweb="textarea"] textarea {
        border-radius: 8px !important;
        font-size: 0.92rem !important;
    }
    div[data-baseweb="select"] {
        border-radius: 8px !important;
    }

    /* --------------------------------------------------------
       4. HERO BANNER & GLASSMORPHISM CARDS
       -------------------------------------------------------- */
    .hero-banner {
        background: linear-gradient(135deg, #3730a3 0%, #4f46e5 50%, #7c3aed 100%);
        padding: 22px 28px;
        border-radius: 16px;
        color: white;
        margin-bottom: 22px;
        box-shadow: 0 10px 28px -4px rgba(79, 70, 229, 0.3);
    }
    .hero-banner h1 {
        color: #ffffff !important;
        font-size: 1.85rem;
        font-weight: 700;
        margin-bottom: 4px;
    }
    .hero-banner p {
        color: rgba(255, 255, 255, 0.9);
        font-size: 0.95rem;
        margin-bottom: 0;
    }

    .glass-card {
        background: #ffffff;
        border-radius: 14px;
        padding: 20px 22px;
        border: 1px solid #e2e8f0;
        box-shadow: 0 4px 16px rgba(0, 0, 0, 0.04);
        margin-bottom: 16px;
        transition: all 0.2s ease;
    }
    .glass-card:hover {
        box-shadow: 0 6px 20px rgba(0, 0, 0, 0.06);
    }

    .live-badge {
        display: inline-flex;
        align-items: center;
        gap: 8px;
        background: #dcfce7;
        color: #15803d;
        border: 1px solid #86efac;
        padding: 6px 16px;
        border-radius: 9999px;
        font-weight: 700;
        font-size: 0.9rem;
    }
    .live-dot {
        width: 10px;
        height: 10px;
        background-color: #22c55e;
        border-radius: 50%;
        box-shadow: 0 0 10px #22c55e;
        animation: pulse-green 1.4s infinite;
    }
    @keyframes pulse-green {
        0% { transform: scale(0.9); opacity: 1; box-shadow: 0 0 4px #22c55e; }
        50% { transform: scale(1.3); opacity: 0.6; box-shadow: 0 0 12px #22c55e; }
        100% { transform: scale(0.9); opacity: 1; box-shadow: 0 0 4px #22c55e; }
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
        font-size: 0.9rem;
    }

    .notice-card {
        border-left: 5px solid #6366f1;
        background: #f8fafc;
        padding: 14px 18px;
        border-radius: 8px 14px 14px 8px;
        margin-bottom: 12px;
        box-shadow: 0 2px 8px rgba(0, 0, 0, 0.03);
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

    /* Left Sidebar Native Drawer Styling */
    section[data-testid="stSidebar"] {
        background-color: #0f172a !important;
        border-right: 1px solid #1e293b !important;
    }
    section[data-testid="stSidebar"] div.stMarkdown,
    section[data-testid="stSidebar"] p,
    section[data-testid="stSidebar"] span,
    section[data-testid="stSidebar"] label {
        color: #e2e8f0;
    }
    section[data-testid="stSidebar"] div.stExpander {
        border-color: #334155 !important;
        background: #1e293b !important;
        border-radius: 10px !important;
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
            'microphone', 'camera', 'desktop', 'whiteboard', 'chat', 'raisehand', 'tileview', 'hangup'
        ])
        student_restrictions_js = ""
    else:
        # Strict student security: No hangup button (prevents 'End meeting for all' popup),
        # no security/mute-everyone/livestreaming/desktop
        tb_buttons = json.dumps([
            'microphone', 'camera', 'whiteboard', 'chat', 'raisehand', 'tileview'
        ])
        student_restrictions_js = """,
                            disableRemoteMute: true,
                            remoteVideoMenu: {
                                disableKick: true,
                                disableGrantModerator: true,
                                disablePrivateChat: false
                            }"""

    if is_teacher:
        topbar_html = """
        <div class="classroom-topbar">
            <button id="fs-toggle-btn" class="topbar-btn fs-btn" onclick="toggleFullScreen()">⛶ Full Screen</button>
            <button id="whiteboard-btn" class="topbar-btn wb-btn" onclick="toggleWhiteboard()">✏️ Live Whiteboard</button>
            <button id="cam-toggle-btn" class="topbar-btn cam-btn" onclick="switchCamera()">📷 Camera Flip</button>
            <button id="share-screen-btn" class="topbar-btn share-btn" onclick="handleScreenShare()">🖥️ Share Screen / Book</button>
            <button id="rec-toggle-btn" class="topbar-btn rec-btn topbar-full-width" onclick="toggleRecording()">🎙️ Record Audio Lecture</button>
        </div>
        <div id="classroom-notice-toast" style="display:none; padding:6px 10px; margin:4px 8px; border-radius:6px; font-size:0.8rem; color:white; font-weight:600; text-align:center;"></div>
        <div id="rec-status-bar" style="display:none; padding:5px 8px; background:#0f172a; border-bottom:1px solid #334155; justify-content:center; align-items:center; gap:8px;">
            <span style="width:9px; height:9px; border-radius:50%; background:#ef4444; display:inline-block;"></span>
            <span id="rec-timer" style="font-family:monospace; color:#38bdf8; font-weight:bold; font-size:0.88rem;">00:00:00</span>
            <span style="color:#94a3b8; font-size:0.78rem; font-weight:500;">Recording Voice Lecture Active (Click 'Stop' to save)</span>
        </div>
        """
    else:
        topbar_html = """
        <div class="classroom-topbar" style="display:flex; justify-content:space-between; align-items:center; gap:6px;">
            <button id="fs-toggle-btn" class="topbar-btn fs-btn" onclick="toggleFullScreen()">⛶ Full Screen</button>
            <button id="student-wb-btn" class="topbar-btn wb-btn" onclick="toggleWhiteboard()">✏️ Teacher's Board <span id="wb-status-tag" style="background:#059669; color:white; border-radius:4px; padding:1px 5px; font-size:11px; margin-left:4px;">LIVE</span></button>
            <button id="raise-hand-btn" class="topbar-btn" style="background:#0284c7; color:white;" onclick="toggleRaiseHand()">✋ Raise Hand</button>
        </div>
        <div id="classroom-notice-toast" style="display:none; padding:6px 10px; margin:4px 8px; border-radius:6px; font-size:0.8rem; color:white; font-weight:600; text-align:center;"></div>
        """

    if is_teacher:
        whiteboard_html = """
        <!-- Built-in HTML5 Interactive Teaching Whiteboard & Lesson Presenter (Teacher Mode) -->
        <input type="file" id="board-image-loader" accept="image/*" style="display:none;" onchange="loadBookImageToCanvas(event)">
        <div id="whiteboard-panel" style="display:none;">
            <div class="wb-toolbar">
                <div class="wb-group">
                    <span style="font-size:0.75rem; font-weight:700; color:#94a3b8;">Pen:</span>
                    <button type="button" class="wb-color-btn active" style="background:#ffffff;" onclick="setPenColor('#ffffff', this)"></button>
                    <button type="button" class="wb-color-btn" style="background:#facc15;" onclick="setPenColor('#facc15', this)"></button>
                    <button type="button" class="wb-color-btn" style="background:#ef4444;" onclick="setPenColor('#ef4444', this)"></button>
                    <button type="button" class="wb-color-btn" style="background:#22c55e;" onclick="setPenColor('#22c55e', this)"></button>
                    <button type="button" class="wb-color-btn" style="background:#38bdf8;" onclick="setPenColor('#38bdf8', this)"></button>
                    <button type="button" id="eraser-btn" class="wb-tool-btn" onclick="toggleEraser()">🧹 Eraser</button>
                </div>
                <div class="wb-group">
                    <span style="font-size:0.75rem; font-weight:700; color:#94a3b8;">Size:</span>
                    <button type="button" class="wb-tool-btn" onclick="setLineWidth(3, this)">Thin</button>
                    <button type="button" class="wb-tool-btn active" onclick="setLineWidth(6, this)">Med</button>
                    <button type="button" class="wb-tool-btn" onclick="setLineWidth(14, this)">Thick</button>
                </div>
                <div class="wb-group">
                    <button type="button" class="wb-tool-btn" onclick="zoomCanvas(0.25)">🔍+ Zoom</button>
                    <button type="button" class="wb-tool-btn" onclick="zoomCanvas(-0.25)">🔍- Out</button>
                    <button type="button" class="wb-tool-btn" onclick="resetCanvasZoom()">🔄 Reset Fit</button>
                </div>
                <div class="wb-group">
                    <button type="button" class="wb-tool-btn" style="background:#2563eb; color:white;" onclick="triggerBookImagePicker()">📖 Load Book Page</button>
                    <button type="button" class="wb-tool-btn" style="background:#475569; color:white;" onclick="clearCanvasDrawing()">🗑️ Clear</button>
                    <button type="button" class="wb-tool-btn" style="background:#059669; color:white;" onclick="forceSyncCanvasToAll()">📤 Sync to Students</button>
                    <button type="button" class="wb-tool-btn" id="toggle-video-tiles-btn" style="background:#334155; color:white;" onclick="toggleStudentTiles()">👥 Show Video Tiles</button>
                    <button type="button" class="wb-tool-btn" style="background:#dc2626; color:white;" onclick="toggleWhiteboard()">✖️ Close</button>
                </div>
                <div class="wb-group wb-layout-group">
                    <span style="font-size:0.72rem; color:#94a3b8;">View:</span>
                    <button type="button" class="wb-tool-btn active" onclick="setLayoutMode('board', this)">📐 Board</button>
                    <button type="button" class="wb-tool-btn" onclick="setLayoutMode('split', this)">🌓 Split</button>
                    <button type="button" class="wb-tool-btn" onclick="setLayoutMode('video', this)">📹 Video</button>
                </div>
            </div>
            <div class="wb-canvas-container" id="wb-canvas-box">
                <canvas id="teaching-canvas"></canvas>
            </div>
        </div>
        """
    else:
        whiteboard_html = """
        <!-- Built-in HTML5 Interactive Teaching Whiteboard & Lesson Presenter (Student Live Viewer Mode) -->
        <div id="whiteboard-panel" style="display:none;">
            <div class="wb-toolbar" style="justify-content:space-between;">
                <div class="wb-group">
                    <span style="color:#38bdf8; font-weight:700; font-size:0.82rem;">🔴 Teacher's Live Whiteboard & Book Page</span>
                    <span id="student-wb-status" style="background:#059669; color:white; border-radius:4px; padding:2px 6px; font-size:0.72rem; font-weight:600;">● Live Synced</span>
                </div>
                <div class="wb-group">
                    <button type="button" class="wb-tool-btn" onclick="zoomCanvas(0.25)">🔍+ Zoom</button>
                    <button type="button" class="wb-tool-btn" onclick="zoomCanvas(-0.25)">🔍- Out</button>
                    <button type="button" class="wb-tool-btn" onclick="resetCanvasZoom()">🔄 Reset Fit</button>
                    <button type="button" class="wb-tool-btn" style="background:#0284c7; color:white;" onclick="requestWbSync()">🔄 Re-Sync</button>
                    <button type="button" class="wb-tool-btn" id="toggle-video-tiles-btn" style="background:#334155; color:white;" onclick="toggleStudentTiles()">👥 Show Video Tiles</button>
                    <button type="button" class="wb-tool-btn" style="background:#dc2626; color:white;" onclick="toggleWhiteboard()">✖️ Hide</button>
                </div>
                <div class="wb-group wb-layout-group">
                    <button type="button" class="wb-tool-btn active" onclick="setLayoutMode('board', this)">📐 Board</button>
                    <button type="button" class="wb-tool-btn" onclick="setLayoutMode('split', this)">🌓 Split</button>
                    <button type="button" class="wb-tool-btn" onclick="setLayoutMode('video', this)">📹 Video</button>
                </div>
            </div>
            <div class="wb-canvas-container" id="wb-canvas-box">
                <canvas id="teaching-canvas"></canvas>
            </div>
        </div>
        """

    component_height = 760 if is_teacher else 700

    html_code = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="utf-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
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
                overflow-x: hidden;
            }}
            #classroom-master-wrapper {{
                position: relative;
                width: 100%;
                min-height: 100%;
                display: flex;
                flex-direction: column;
                background: #0f172a;
                border-radius: 12px;
                overflow: hidden;
                border: 1px solid #334155;
                transition: all 0.25s ease;
            }}
            #classroom-master-wrapper.is-fullscreen {{
                position: fixed !important;
                top: 0 !important;
                left: 0 !important;
                width: 100vw !important;
                height: 100vh !important;
                max-width: 100vw !important;
                max-height: 100vh !important;
                border-radius: 0 !important;
                z-index: 999999 !important;
                border: none !important;
                overflow-y: auto !important;
            }}
            .classroom-topbar {{
                background: #1e293b;
                padding: 6px 8px;
                border-bottom: 1px solid #334155;
                display: grid;
                grid-template-columns: repeat(2, 1fr);
                gap: 6px;
                width: 100%;
                box-sizing: border-box;
                z-index: 20;
            }}
            .topbar-full-width {{
                grid-column: span 2;
            }}
            @media (min-width: 680px) {{
                .classroom-topbar {{
                    display: flex;
                    flex-direction: row;
                    justify-content: space-between;
                    align-items: center;
                    gap: 6px;
                    flex-wrap: wrap;
                }}
                .topbar-full-width {{
                    grid-column: auto;
                }}
            }}
            .topbar-btn {{
                border: none;
                padding: 7px 10px;
                border-radius: 7px;
                font-size: 13px;
                font-weight: 600;
                cursor: pointer;
                transition: 0.15s ease;
                display: inline-flex;
                align-items: center;
                justify-content: center;
                gap: 5px;
                white-space: nowrap;
                text-align: center;
                user-select: none;
                min-height: 36px;
                box-sizing: border-box;
            }}
            .fs-btn {{
                background: #334155;
                color: #f8fafc;
                border: 1px solid #475569;
            }}
            .fs-btn:hover {{ background: #475569; }}
            .fs-btn.fs-active {{
                background: #dc2626 !important;
                color: #ffffff !important;
                border: 1px solid #ef4444 !important;
            }}
            .share-btn {{
                background: #2563eb;
                color: white;
            }}
            .share-btn:hover {{ background: #1d4ed8; }}
            .wb-btn {{
                background: #0d9488;
                color: white;
            }}
            .wb-btn:hover {{ background: #0f766e; }}
            .cam-btn {{
                background: #6366f1;
                color: white;
            }}
            .cam-btn:hover {{ background: #4f46e5; }}
            .rec-btn {{
                background: #ef4444;
                color: white;
            }}
            .rec-btn:hover {{ background: #dc2626; }}
            .rec-btn-stop {{
                background: #10b981;
                color: white;
            }}
            .rec-btn-stop:hover {{ background: #059669; }}

            /* Whiteboard Panel Styling */
            #whiteboard-panel {{
                background: #020617;
                border-bottom: 2px solid #334155;
                display: none;
                flex-direction: column;
                width: 100%;
                z-index: 15;
            }}
            .wb-toolbar {{
                background: #0f172a;
                padding: 8px 10px;
                display: flex;
                align-items: center;
                gap: 8px;
                flex-wrap: wrap;
                border-bottom: 1px solid #1e293b;
            }}
            .wb-group {{
                display: inline-flex;
                align-items: center;
                gap: 5px;
            }}
            .wb-color-btn {{
                width: 22px;
                height: 22px;
                border-radius: 50%;
                border: 2px solid #64748b;
                cursor: pointer;
                padding: 0;
                outline: none;
            }}
            .wb-color-btn.active {{
                border-color: #38bdf8;
                box-shadow: 0 0 0 2px #0284c7;
                transform: scale(1.15);
            }}
            .wb-tool-btn {{
                background: #1e293b;
                color: #e2e8f0;
                border: 1px solid #334155;
                padding: 5px 9px;
                border-radius: 6px;
                font-size: 0.76rem;
                font-weight: 600;
                cursor: pointer;
            }}
            .wb-tool-btn.active {{
                background: #0284c7;
                color: white;
                border-color: #38bdf8;
            }}
            .wb-canvas-container {{
                width: 100%;
                height: 540px;
                position: relative;
                background: #020617;
                overflow-x: auto;
                overflow-y: auto;
                -webkit-overflow-scrolling: touch;
                touch-action: pan-x pan-y;
                transition: height 0.25s ease;
                display: flex;
                flex-direction: column;
                align-items: center;
            }}
            #classroom-master-wrapper.is-fullscreen .wb-canvas-container {{
                height: calc(100vh - 140px) !important;
            }}
            #teaching-canvas {{
                display: block;
                max-width: none;
                touch-action: none;
                cursor: crosshair;
                margin: 0 auto;
                background: #020617;
                box-shadow: 0 4px 20px rgba(0,0,0,0.5);
            }}

            /* Jitsi Video Container - Responsive docking */
            #jitsi-container {{
                width: 100% !important;
                height: 520px !important;
                min-height: 76px !important;
                flex: 1 1 auto !important;
                background: #111827;
                transition: height 0.25s ease;
                display: block;
            }}
            #classroom-master-wrapper.is-fullscreen #jitsi-container {{
                height: calc(100vh - 60px) !important;
                min-height: 76px !important;
            }}
            #jitsi-container iframe {{
                width: 100% !important;
                height: 100% !important;
                min-height: 100% !important;
                border: none !important;
                display: block !important;
            }}
        </style>
    </head>
    <body>
        <div id="classroom-master-wrapper">
            {topbar_html}
            {whiteboard_html}
            <div id="jitsi-container"></div>
        </div>

        <script>
            let api = null;
            let isFullscreenMode = false;
            const isTeacherRole = {'true' if is_teacher else 'false'};

            // Canvas & Whiteboard state
            let canvas = null;
            let ctx = null;
            let isDrawing = false;
            let currentPenColor = '#ffffff';
            let currentLineWidth = 6;
            let isEraser = false;
            let loadedBookImage = null;
            let lastPos = {{ x: 0, y: 0 }};
            let snapDebounceTimer = null;
            let currentLayout = 'board';
            let currentZoom = 1.0;
            let showingVideoTiles = false;

            // MediaRecorder state
            let mediaRecorder = null;
            let recordedChunks = [];
            let recTimerInterval = null;
            let recSeconds = 0;

            function isMobileDevice() {{
                return /Android|webOS|iPhone|iPad|iPod|BlackBerry|IEMobile|Opera Mini/i.test(navigator.userAgent) || (window.innerWidth <= 768);
            }}

            function showClassroomNotice(msg, isWarning = false) {{
                const banner = document.getElementById('classroom-notice-toast');
                if (banner) {{
                    banner.innerText = msg;
                    banner.style.display = 'block';
                    banner.style.background = isWarning ? '#b45309' : '#059669';
                    setTimeout(() => {{
                        banner.style.display = 'none';
                    }}, 8000);
                }} else {{
                    alert(msg);
                }}
            }}

            function toggleRaiseHand() {{
                if (api) {{
                    try {{
                        api.executeCommand('toggleRaiseHand');
                        showClassroomNotice("✋ Hand Raised / Lowered", false);
                    }} catch (e) {{
                        console.log("toggleRaiseHand error:", e);
                    }}
                }}
            }}

            // Clean Fullscreen Toggle
            function toggleFullScreen() {{
                const master = document.getElementById('classroom-master-wrapper');
                const topFsBtn = document.getElementById('fs-toggle-btn');
                const wbBox = document.getElementById('wb-canvas-box');

                isFullscreenMode = !isFullscreenMode;

                if (isFullscreenMode) {{
                    try {{
                        if (master.requestFullscreen) {{
                            master.requestFullscreen().catch(() => {{}});
                        }} else if (master.webkitRequestFullscreen) {{
                            master.webkitRequestFullscreen();
                        }}
                    }} catch (e) {{
                        console.log("Native FS error:", e);
                    }}

                    master.classList.add('is-fullscreen');
                    if (topFsBtn) {{
                        topFsBtn.innerHTML = '❌ Exit Full Screen';
                        topFsBtn.classList.add('fs-active');
                    }}
                    if (window.frameElement) {{
                        window.frameElement.style.height = "100vh";
                        window.frameElement.style.maxHeight = "100vh";
                        try {{
                            window.frameElement.scrollIntoView({{ behavior: 'smooth', block: 'start' }});
                        }} catch (err) {{}}
                    }}
                    if (wbBox) wbBox.style.height = "calc(100vh - 140px)";
                }} else {{
                    try {{
                        if (document.fullscreenElement || document.webkitFullscreenElement) {{
                            if (document.exitFullscreen) {{
                                document.exitFullscreen().catch(() => {{}});
                            }} else if (document.webkitExitFullscreen) {{
                                document.webkitExitFullscreen();
                            }}
                        }}
                    }} catch (e) {{
                        console.log("Exit FS error:", e);
                    }}

                    master.classList.remove('is-fullscreen');
                    if (topFsBtn) {{
                        topFsBtn.innerHTML = '⛶ Full Screen';
                        topFsBtn.classList.remove('fs-active');
                    }}
                    if (window.frameElement) {{
                        window.frameElement.style.height = "{component_height}px";
                    }}
                    if (wbBox) wbBox.style.height = (currentLayout === 'board') ? "540px" : "320px";
                }}
            }}

            document.addEventListener('fullscreenchange', () => {{
                if (!document.fullscreenElement && !document.webkitFullscreenElement && isFullscreenMode) {{
                    toggleFullScreen();
                }}
            }});
            document.addEventListener('webkitfullscreenchange', () => {{
                if (!document.webkitFullscreenElement && isFullscreenMode) {{
                    toggleFullScreen();
                }}
            }});

            // Camera Flip (Front ⇄ Back for showing book to students)
            function switchCamera() {{
                if (api) {{
                    try {{
                        api.executeCommand('toggleCamera');
                        showClassroomNotice("📷 Camera Flipped (Front ⇄ Back) to display Book / Notes to students!", false);
                    }} catch (e) {{
                        console.error("Camera switch error:", e);
                        try {{ api.executeCommand('toggleVideo'); }} catch(err) {{}}
                        showClassroomNotice("Toggled camera state.", false);
                    }}
                }}
            }}

            // Zoom & Pan System for Crisp Full-Width Book Pages
            function zoomCanvas(delta) {{
                currentZoom = Math.min(3.5, Math.max(0.5, currentZoom + delta));
                applyCanvasZoom();
                showClassroomNotice("🔍 Zoom: " + Math.round(currentZoom * 100) + "%", false);
            }}

            function resetCanvasZoom() {{
                currentZoom = 1.0;
                applyCanvasZoom();
                showClassroomNotice("🔄 Zoom Reset (Fit Width)", false);
            }}

            function applyCanvasZoom() {{
                if (!canvas) return;
                canvas.style.width = (currentZoom * 100) + '%';
                canvas.style.height = 'auto';
            }}

            // Toggle Participant Video Tiles (Shows / Hides SS avatar circle)
            function toggleStudentTiles() {{
                const jitsiCont = document.getElementById('jitsi-container');
                const btn = document.getElementById('toggle-video-tiles-btn');
                if (!jitsiCont) return;
                showingVideoTiles = !showingVideoTiles;
                if (showingVideoTiles) {{
                    jitsiCont.style.setProperty('height', '260px', 'important');
                    jitsiCont.style.setProperty('min-height', '260px', 'important');
                    jitsiCont.style.setProperty('max-height', 'none', 'important');
                    jitsiCont.style.setProperty('flex', '0 0 260px', 'important');
                    jitsiCont.style.setProperty('overflow', 'visible', 'important');
                    if (btn) btn.innerText = "👥 Hide Video Tiles";
                }} else {{
                    jitsiCont.style.setProperty('height', '76px', 'important');
                    jitsiCont.style.setProperty('min-height', '76px', 'important');
                    jitsiCont.style.setProperty('max-height', '76px', 'important');
                    jitsiCont.style.setProperty('flex', '0 0 76px', 'important');
                    jitsiCont.style.setProperty('overflow', 'hidden', 'important');
                    if (btn) btn.innerText = "👥 Show Video Tiles";
                }}
            }}

            // Whiteboard Layout Switcher (Board Focus 76px / Split / Video Focus)
            function setLayoutMode(mode, btn) {{
                currentLayout = mode;
                const wbBox = document.getElementById('wb-canvas-box');
                const jitsiCont = document.getElementById('jitsi-container');
                const panel = document.getElementById('whiteboard-panel');
                const tilesBtn = document.getElementById('toggle-video-tiles-btn');

                document.querySelectorAll('.wb-layout-group .wb-tool-btn').forEach(b => b.classList.remove('active'));
                if (btn) btn.classList.add('active');

                if (mode === 'board') {{
                    if (panel) panel.style.display = 'flex';
                    if (wbBox) wbBox.style.height = isFullscreenMode ? 'calc(100vh - 140px)' : '540px';
                    if (jitsiCont) {{
                        jitsiCont.style.setProperty('height', '76px', 'important');
                        jitsiCont.style.setProperty('min-height', '76px', 'important');
                        jitsiCont.style.setProperty('max-height', '76px', 'important');
                        jitsiCont.style.setProperty('flex', '0 0 76px', 'important');
                        jitsiCont.style.setProperty('overflow', 'hidden', 'important');
                    }}
                    showingVideoTiles = false;
                    if (tilesBtn) tilesBtn.innerText = "👥 Show Video Tiles";
                }} else if (mode === 'split') {{
                    if (panel) panel.style.display = 'flex';
                    if (wbBox) wbBox.style.height = '320px';
                    if (jitsiCont) {{
                        jitsiCont.style.setProperty('height', '260px', 'important');
                        jitsiCont.style.setProperty('min-height', '260px', 'important');
                        jitsiCont.style.setProperty('max-height', 'none', 'important');
                        jitsiCont.style.setProperty('flex', '0 0 260px', 'important');
                        jitsiCont.style.setProperty('overflow', 'visible', 'important');
                    }}
                    showingVideoTiles = true;
                    if (tilesBtn) tilesBtn.innerText = "👥 Hide Video Tiles";
                }} else if (mode === 'video') {{
                    if (wbBox) wbBox.style.height = '0px';
                    if (panel) panel.style.display = 'none';
                    if (jitsiCont) {{
                        jitsiCont.style.setProperty('height', '520px', 'important');
                        jitsiCont.style.setProperty('min-height', '520px', 'important');
                        jitsiCont.style.setProperty('max-height', 'none', 'important');
                        jitsiCont.style.setProperty('flex', '1 1 auto', 'important');
                        jitsiCont.style.setProperty('overflow', 'visible', 'important');
                    }}
                    showingVideoTiles = true;
                }}
                if (canvas && ctx) redrawCanvas();
            }}

            // Real-Time Whiteboard Broadcast & Messaging System
            const wbChannel = ('BroadcastChannel' in window) ? new BroadcastChannel('sisters_wb_sync_ch') : null;
            if (wbChannel) {{
                wbChannel.onmessage = function(e) {{
                    if (e && e.data) handleIncomingWbMessage(e.data);
                }};
            }}

            function broadcastWbMessage(payload) {{
                if (wbChannel) {{
                    try {{ wbChannel.postMessage(payload); }} catch(err) {{}}
                }}
                if (api) {{
                    try {{
                        api.executeCommand('sendEndpointTextMessage', '', JSON.stringify(payload));
                    }} catch (err) {{
                        console.log("Jitsi broadcast error:", err);
                    }}
                }}
            }}

            function handleIncomingWbMessage(msg) {{
                if (!msg || !msg.t) return;

                const panel = document.getElementById('whiteboard-panel');
                const statusTag = document.getElementById('wb-status-tag');
                const studentStatus = document.getElementById('student-wb-status');

                if (!isTeacherRole) {{
                    if (statusTag) {{
                        statusTag.innerText = "🔴 LIVE";
                        statusTag.style.background = "#ef4444";
                    }}
                    if (studentStatus) {{
                        studentStatus.innerText = "● Teacher Drawing";
                        studentStatus.style.background = "#ef4444";
                    }}

                    // Auto-open whiteboard in full board mode if teacher starts drawing or loads a book
                    if ((msg.t === 'm' || msg.t === 'snap' || msg.t === 'book_img' || (msg.t === 'toggle' && msg.open)) && panel) {{
                        if (panel.style.display === 'none') {{
                            panel.style.display = 'flex';
                            setLayoutMode('board', null);
                            initCanvas();
                        }}
                    }}
                }}

                if (msg.t === 'book_img') {{
                    if (msg.img) {{
                        const img = new Image();
                        img.onload = function() {{
                            loadedBookImage = img;
                            canvas = document.getElementById('teaching-canvas');
                            if (!canvas) initCanvas();
                            if (canvas) {{
                                canvas.width = msg.w || 1080;
                                canvas.height = msg.h || Math.round(1080 * (img.height / img.width));
                                currentZoom = 1.0;
                                canvas.style.width = '100%';
                                canvas.style.height = 'auto';
                                ctx = canvas.getContext('2d');
                                ctx.drawImage(img, 0, 0, canvas.width, canvas.height);
                            }}
                            if (panel && panel.style.display === 'none') {{
                                panel.style.display = 'flex';
                            }}
                            setLayoutMode('board', null);
                            if (studentStatus) {{
                                studentStatus.innerText = "● Book Page Synced";
                                studentStatus.style.background = "#059669";
                            }}
                        }};
                        img.src = msg.img;
                    }}
                }} else if (msg.t === 'toggle') {{
                    if (!isTeacherRole && panel) {{
                        if (msg.open) {{
                            panel.style.display = 'flex';
                            setLayoutMode('board', null);
                            initCanvas();
                        }} else {{
                            panel.style.display = 'none';
                            setLayoutMode('video', null);
                        }}
                    }}
                }} else if (msg.t === 'm') {{
                    if (!ctx) initCanvas();
                    if (ctx) {{
                        ctx.beginPath();
                        ctx.moveTo(msg.x0, msg.y0);
                        ctx.lineTo(msg.x1, msg.y1);
                        ctx.strokeStyle = msg.c;
                        ctx.lineWidth = msg.w;
                        ctx.lineCap = 'round';
                        ctx.lineJoin = 'round';
                        ctx.stroke();
                    }}
                }} else if (msg.t === 'clear') {{
                    loadedBookImage = null;
                    redrawCanvas();
                    if (studentStatus) {{
                        studentStatus.innerText = "● Board Cleared";
                        studentStatus.style.background = "#64748b";
                    }}
                }} else if (msg.t === 'snap') {{
                    if (msg.img) {{
                        const img = new Image();
                        img.onload = function() {{
                            canvas = document.getElementById('teaching-canvas');
                            if (!ctx || !canvas) initCanvas();
                            if (ctx && canvas) {{
                                if (msg.w && msg.h) {{
                                    canvas.width = msg.w;
                                    canvas.height = msg.h;
                                    canvas.style.width = (currentZoom * 100) + '%';
                                    canvas.style.height = 'auto';
                                }}
                                ctx.drawImage(img, 0, 0, canvas.width, canvas.height);
                            }}
                            if (studentStatus) {{
                                studentStatus.innerText = "● Live Synced";
                                studentStatus.style.background = "#059669";
                            }}
                        }};
                        img.src = msg.img;
                    }}
                }} else if (msg.t === 'req_sync') {{
                    if (isTeacherRole && canvas) {{
                        try {{
                            const snap = canvas.toDataURL('image/jpeg', 0.82);
                            broadcastWbMessage({{
                                t: 'snap',
                                img: snap,
                                w: canvas.width,
                                h: canvas.height
                            }});
                        }} catch(e) {{}}
                    }}
                }}
            }}

            function forceSyncCanvasToAll() {{
                if (!canvas) return;
                try {{
                    const snap = canvas.toDataURL('image/jpeg', 0.82);
                    broadcastWbMessage({{
                        t: 'snap',
                        img: snap,
                        w: canvas.width,
                        h: canvas.height
                    }});
                    showClassroomNotice("📤 High-resolution board synced to all students!", false);
                }} catch (e) {{
                    console.error("Sync error:", e);
                }}
            }}

            function requestWbSync() {{
                broadcastWbMessage({{ t: 'req_sync' }});
                showClassroomNotice("🔄 Requesting latest whiteboard from teacher...", false);
            }}

            // Whiteboard Canvas Interaction
            function initCanvas() {{
                canvas = document.getElementById('teaching-canvas');
                if (!canvas) return;
                ctx = canvas.getContext('2d');
                
                if (!loadedBookImage) {{
                    if (canvas.width !== 1080) canvas.width = 1080;
                    if (canvas.height !== 720) canvas.height = 720;
                    canvas.style.width = (currentZoom * 100) + '%';
                    canvas.style.height = 'auto';
                }}
                
                redrawCanvas();

                if (isTeacherRole) {{
                    // Mouse events
                    canvas.onmousedown = (e) => startDrawing(e);
                    canvas.onmousemove = (e) => drawMove(e);
                    canvas.onmouseup = () => stopDrawing();
                    canvas.onmouseleave = () => stopDrawing();

                    // Touch events (Mobile drawing)
                    canvas.addEventListener('touchstart', (e) => {{
                        e.preventDefault();
                        startDrawing(getTouchPos(e));
                    }}, {{ passive: false }});

                    canvas.addEventListener('touchmove', (e) => {{
                        e.preventDefault();
                        drawMove(getTouchPos(e));
                    }}, {{ passive: false }});

                    canvas.addEventListener('touchend', (e) => {{
                        e.preventDefault();
                        stopDrawing();
                    }}, {{ passive: false }});
                }}
            }}

            function getCanvasPos(evt) {{
                const rect = canvas.getBoundingClientRect();
                const scaleX = canvas.width / rect.width;
                const scaleY = canvas.height / rect.height;
                return {{
                    x: (evt.clientX - rect.left) * scaleX,
                    y: (evt.clientY - rect.top) * scaleY
                }};
            }}

            function getTouchPos(touchEvent) {{
                if (touchEvent.touches && touchEvent.touches.length > 0) {{
                    return touchEvent.touches[0];
                }}
                return touchEvent;
            }}

            function startDrawing(e) {{
                if (!isTeacherRole) return;
                isDrawing = true;
                lastPos = getCanvasPos(e);
                ctx.beginPath();
                ctx.moveTo(lastPos.x, lastPos.y);
                ctx.lineCap = 'round';
                ctx.lineJoin = 'round';
                ctx.strokeStyle = isEraser ? '#020617' : currentPenColor;
                ctx.lineWidth = isEraser ? (currentLineWidth * 3) : currentLineWidth;
            }}

            function drawMove(e) {{
                if (!isTeacherRole || !isDrawing) return;
                const pos = getCanvasPos(e);
                ctx.lineTo(pos.x, pos.y);
                ctx.stroke();

                const color = isEraser ? '#020617' : currentPenColor;
                const width = isEraser ? (currentLineWidth * 3) : currentLineWidth;

                broadcastWbMessage({{
                    t: 'm',
                    x0: Math.round(lastPos.x),
                    y0: Math.round(lastPos.y),
                    x1: Math.round(pos.x),
                    y1: Math.round(pos.y),
                    c: color,
                    w: width
                }});

                lastPos = pos;
            }}

            function stopDrawing() {{
                if (!isTeacherRole) return;
                if (isDrawing) {{
                    ctx.closePath();
                    isDrawing = false;
                    if (snapDebounceTimer) clearTimeout(snapDebounceTimer);
                    snapDebounceTimer = setTimeout(() => {{
                        if (canvas) {{
                            try {{
                                const snap = canvas.toDataURL('image/jpeg', 0.82);
                                broadcastWbMessage({{
                                    t: 'snap',
                                    img: snap,
                                    w: canvas.width,
                                    h: canvas.height
                                }});
                            }} catch(e) {{}}
                        }}
                    }}, 350);
                }}
            }}

            function setPenColor(color, btn) {{
                isEraser = false;
                currentPenColor = color;
                document.querySelectorAll('.wb-color-btn').forEach(b => b.classList.remove('active'));
                if (btn) btn.classList.add('active');
                const eraserBtn = document.getElementById('eraser-btn');
                if (eraserBtn) eraserBtn.classList.remove('active');
            }}

            function setLineWidth(width, btn) {{
                currentLineWidth = width;
                document.querySelectorAll('.wb-group .wb-tool-btn').forEach(b => {{
                    if (b.innerText === 'Thin' || b.innerText === 'Med' || b.innerText === 'Thick') {{
                        b.classList.remove('active');
                    }}
                }});
                if (btn) btn.classList.add('active');
            }}

            function toggleEraser() {{
                isEraser = !isEraser;
                const eraserBtn = document.getElementById('eraser-btn');
                if (eraserBtn) {{
                    if (isEraser) {{
                        eraserBtn.classList.add('active');
                        document.querySelectorAll('.wb-color-btn').forEach(b => b.classList.remove('active'));
                    }} else {{
                        eraserBtn.classList.remove('active');
                        setPenColor(currentPenColor, null);
                    }}
                }}
            }}

            function redrawCanvas() {{
                if (!ctx || !canvas) return;
                if (loadedBookImage) {{
                    ctx.fillStyle = '#020617';
                    ctx.fillRect(0, 0, canvas.width, canvas.height);
                    ctx.drawImage(loadedBookImage, 0, 0, canvas.width, canvas.height);
                }} else {{
                    ctx.fillStyle = '#020617';
                    ctx.fillRect(0, 0, canvas.width, canvas.height);
                    ctx.fillStyle = '#1e293b';
                    ctx.fillRect(0, 0, canvas.width, 42);
                    ctx.fillStyle = '#38bdf8';
                    ctx.font = 'bold 22px sans-serif';
                    ctx.fillText("✨ Sisters Academy Live Whiteboard & Lesson Presenter", 24, 28);
                }}
            }}

            function clearCanvasDrawing() {{
                loadedBookImage = null;
                redrawCanvas();
                if (isTeacherRole) {{
                    broadcastWbMessage({{ t: 'clear' }});
                }}
                showClassroomNotice("Whiteboard cleared.", false);
            }}

            function triggerBookImagePicker() {{
                const input = document.getElementById('board-image-loader');
                if (input) input.click();
            }}

            function loadBookImageToCanvas(event) {{
                const file = event.target.files && event.target.files[0];
                if (!file) return;
                const reader = new FileReader();
                reader.onload = function(e) {{
                    const img = new Image();
                    img.onload = function() {{
                        loadedBookImage = img;
                        
                        const naturalW = img.naturalWidth || img.width || 1080;
                        const naturalH = img.naturalHeight || img.height || 1920;
                        
                        canvas = document.getElementById('teaching-canvas');
                        if (canvas) {{
                            canvas.width = 1080;
                            canvas.height = Math.round(1080 * (naturalH / naturalW));
                            currentZoom = 1.0;
                            canvas.style.width = '100%';
                            canvas.style.height = 'auto';
                        }}
                        
                        const panel = document.getElementById('whiteboard-panel');
                        if (panel && panel.style.display === 'none') {{
                            panel.style.display = 'flex';
                        }}
                        
                        // Automatically switch to Board Focus (shrinks Jitsi to 76px audio bar)
                        setLayoutMode('board', null);
                        initCanvas();
                        redrawCanvas();

                        if (isTeacherRole) {{
                            setTimeout(() => {{
                                try {{
                                    const snap = canvas.toDataURL('image/jpeg', 0.82);
                                    broadcastWbMessage({{
                                        t: 'book_img',
                                        img: snap,
                                        w: canvas.width,
                                        h: canvas.height
                                    }});
                                }} catch(err) {{
                                    console.error("Book broadcast error:", err);
                                }}
                            }}, 150);
                        }}
                        showClassroomNotice("📖 Book page loaded in full width! Synced to all students.", false);
                    }};
                    img.src = e.target.result;
                }};
                reader.readAsDataURL(file);
            }}

            function toggleWhiteboard() {{
                const panel = document.getElementById('whiteboard-panel');
                if (!panel) return;
                const isHidden = panel.style.display === 'none';
                if (isHidden) {{
                    panel.style.display = 'flex';
                    // Auto-focus Board Mode (audio bar only, hiding big avatars)
                    setLayoutMode('board', null);
                    initCanvas();
                    if (isTeacherRole) {{
                        broadcastWbMessage({{ t: 'toggle', open: true }});
                        forceSyncCanvasToAll();
                    }} else {{
                        requestWbSync();
                    }}
                }} else {{
                    panel.style.display = 'none';
                    setLayoutMode('video', null);
                    if (isTeacherRole) {{
                        broadcastWbMessage({{ t: 'toggle', open: false }});
                    }}
                }}
            }}

            // Desktop Screen Share & Mobile Presentation Helper
            function handleScreenShare() {{
                if (isMobileDevice()) {{
                    showClassroomNotice("📱 Mobile Tip: Phone browsers cannot capture full screen due to Android/iOS security. Use ✏️ 'Live Whiteboard' (draw & share book pages) or 📷 'Camera Flip' (point at book)!", false);
                    const panel = document.getElementById('whiteboard-panel');
                    if (panel && panel.style.display === 'none') {{
                        toggleWhiteboard();
                    }}
                }} else {{
                    if (api) {{
                        try {{
                            api.executeCommand('toggleShareScreen');
                            showClassroomNotice("🖥️ Toggled Desktop Screen Share. Visible on all students' screens in stage view.", false);
                        }} catch (e) {{
                            showClassroomNotice("Screen share error: " + e.message, true);
                        }}
                    }}
                }}
            }}

            // 100% Strictly Audio-Only Voice Lecture Recorder
            let audioStream = null;

            async function toggleRecording() {{
                const btn = document.getElementById('rec-toggle-btn');
                const statusBar = document.getElementById('rec-status-bar');
                const timerElem = document.getElementById('rec-timer');

                if (mediaRecorder && mediaRecorder.state === 'recording') {{
                    mediaRecorder.stop();
                    if (recTimerInterval) clearInterval(recTimerInterval);
                    btn.innerHTML = "🎙️ Record Audio Lecture";
                    btn.className = "topbar-btn rec-btn topbar-full-width";
                    if (statusBar) statusBar.style.display = "none";
                    showClassroomNotice("Saving Audio Lecture...", false);
                    return;
                }}

                try {{
                    audioStream = await navigator.mediaDevices.getUserMedia({{
                        audio: {{
                            echoCancellation: true,
                            noiseSuppression: true,
                            autoGainControl: true
                        }},
                        video: false
                    }});

                    if (!audioStream || audioStream.getAudioTracks().length === 0) {{
                        alert("Could not access microphone to record audio lecture.");
                        return;
                    }}

                    let mimeType = 'audio/webm;codecs=opus';
                    if (!MediaRecorder.isTypeSupported(mimeType)) {{
                        if (MediaRecorder.isTypeSupported('audio/webm')) {{
                            mimeType = 'audio/webm';
                        }} else if (MediaRecorder.isTypeSupported('audio/mp4')) {{
                            mimeType = 'audio/mp4';
                        }} else if (MediaRecorder.isTypeSupported('audio/ogg')) {{
                            mimeType = 'audio/ogg';
                        }} else {{
                            mimeType = '';
                        }}
                    }}

                    recordedChunks = [];
                    const options = mimeType ? {{ mimeType }} : {{}};
                    mediaRecorder = new MediaRecorder(audioStream, options);

                    mediaRecorder.ondataavailable = function(e) {{
                        if (e.data && e.data.size > 0) {{
                            recordedChunks.push(e.data);
                        }}
                    }};

                    mediaRecorder.onstop = function() {{
                        if (audioStream) {{
                            audioStream.getTracks().forEach(t => t.stop());
                            audioStream = null;
                        }}

                        const blob = new Blob(recordedChunks, {{ type: mimeType || 'audio/webm' }});
                        const url = URL.createObjectURL(blob);
                        const a = document.createElement('a');
                        a.style.display = 'none';
                        a.href = url;
                        const now = new Date();
                        const dateStr = now.toISOString().slice(0,10) + "_" + String(now.getHours()).padStart(2, '0') + "-" + String(now.getMinutes()).padStart(2, '0');
                        a.download = "Sisters_Academy_Audio_Lecture_" + dateStr + ".webm";
                        document.body.appendChild(a);
                        a.click();
                        setTimeout(() => {{
                            document.body.removeChild(a);
                            window.URL.revokeObjectURL(url);
                        }}, 100);

                        showClassroomNotice("✅ Audio Lecture Saved! Upload it below to share with all students.", false);
                    }};

                    mediaRecorder.start(1000);

                    btn.innerHTML = "⏹️ Stop & Save Audio";
                    btn.className = "topbar-btn rec-btn-stop topbar-full-width";
                    if (statusBar) statusBar.style.display = "flex";

                    recSeconds = 0;
                    if (timerElem) timerElem.innerText = "00:00:00";
                    recTimerInterval = setInterval(() => {{
                        recSeconds++;
                        const hrs = String(Math.floor(recSeconds / 3600)).padStart(2, '0');
                        const mins = String(Math.floor((recSeconds % 3600) / 60)).padStart(2, '0');
                        const secs = String(recSeconds % 60).padStart(2, '0');
                        if (timerElem) timerElem.innerText = hrs + ":" + mins + ":" + secs;
                    }}, 1000);

                    showClassroomNotice("🎙️ Audio Lecture Recording Active...", false);
                }} catch (err) {{
                    console.error("Audio recording start error:", err);
                    alert("Could not start audio recording: " + err.message);
                }}
            }}

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
                            disableReactions: true,
                            disableReactionsModeration: true,
                            toolbarButtons: {tb_buttons},
                            MAIN_TOOLBAR_BUTTONS: {tb_buttons}{student_restrictions_js}
                        }},
                        interfaceConfigOverwrite: {{
                            SHOW_JITSI_WATERMARK: false,
                            SHOW_WATERMARK_FOR_GUESTS: false,
                            TOOLBAR_ALWAYS_VISIBLE: true,
                            TOOLBAR_BUTTONS: {tb_buttons},
                            MAIN_TOOLBAR_BUTTONS: {tb_buttons}
                        }}
                    }};
                    api = new JitsiMeetExternalAPI(domain, options);

                    // WebRTC Data Channel Listener for Real-Time Whiteboard Synchronization
                    api.addListener('endpointTextMessageReceived', function(event) {{
                        let raw = "";
                        if (event && event.data && event.data.eventData && event.data.eventData.text) {{
                            raw = event.data.eventData.text;
                        }} else if (event && event.eventData && event.eventData.text) {{
                            raw = event.eventData.text;
                        }} else if (event && event.data && event.data.text) {{
                            raw = event.data.text;
                        }} else if (event && event.text) {{
                            raw = event.text;
                        }}
                        if (!raw) return;
                        try {{
                            const payload = JSON.parse(raw);
                            handleIncomingWbMessage(payload);
                        }} catch(err) {{}}
                    }});

                    // Screen share pin to large view
                    api.addListener('screenSharingStatusChanged', function(event) {{
                        if (event && event.on) {{
                            showClassroomNotice("🖥️ Screen Sharing is LIVE! Pinned to main video stage.", false);
                            try {{ api.executeCommand('setTileView', false); }} catch(e) {{}}
                        }} else {{
                            showClassroomNotice("Screen sharing stopped.", false);
                        }}
                    }});

                    // If student, request initial whiteboard sync after joining
                    if (!isTeacherRole) {{
                        setTimeout(() => {{
                            requestWbSync();
                        }}, 2500);
                    }}
                    
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
    components.html(html_code, height=component_height, scrolling=True)



# ==========================================
# 6. AUTHENTICATION & LOGIN SCREEN
# ==========================================
def make_session_token(username: str, pwd_value: str = "") -> str:
    """Generates a secure token to keep the user logged in across mobile/browser tab reloads."""
    secret_salt = "sisters_live_academy_persistent_auth_key_v2"
    payload = f"{username.lower().strip()}:{pwd_value}:{secret_salt}"
    return hashlib.sha256(payload.encode()).hexdigest()[:24]

def verify_session_token(username_val: str, token_val: str):
    """
    Validates persistent session credentials from st.query_params across browser refreshes.
    Returns user dict if active (is_active != 0) and credentials match token, otherwise None.
    """
    if not username_val or not token_val:
        return None
    un = username_val.lower().strip()
    user = None

    if is_supabase_active():
        ok, rows = supabase_request("GET", "users", params=f"username=eq.{un}&select=*")
        if ok and rows:
            user = rows[0]

    if not user:
        try:
            with get_db_connection() as conn:
                c = conn.cursor()
                c.execute("SELECT * FROM users WHERE username = ?", (un,))
                r = c.fetchone()
                if r:
                    user = dict(r)
        except Exception as e:
            logger.warning(f"Failed persistent session verification query: {e}")

    if user and user.get('is_active', 1) != 0:
        pwd_val = user.get('password_hash') or user.get('password') or ''
        expected = make_session_token(un, pwd_val)
        if token_val == expected:
            return user
    return None

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
            st.session_state.user_id = user.get('id')
            # Persistent login in browser query params (mobile pull-down refresh safe)
            try:
                pwd_val = user.get('password_hash') or user.get('password') or ''
                st.query_params["u"] = user['username']
                st.query_params["t"] = make_session_token(user['username'], pwd_val)
            except Exception as e:
                logger.warning(f"Failed setting persistent query params: {e}")
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
            u_input = st.text_input("Username", placeholder="Enter your username").strip().lower()
            p_input = st.text_input("Password", type="password", placeholder="Enter your password")
            submit = st.form_submit_button("Sign In to Portal", use_container_width=True, type="primary")

            if submit:
                handle_login(u_input, p_input)


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

    # Editable Payment Instructions & UPI Settings for Teachers & Admins
    with st.expander("⚙️ Payment Instructions & UPI Settings (Visible to Students)", expanded=False):
        st.markdown("Configure the official UPI ID, mobile payment number, and instructions displayed on every student's fee payment portal:")
        pay_cfg = get_payment_settings()
        with st.form(f"payment_settings_form_{'adm' if is_admin else 'tch'}"):
            c_ps1, c_ps2 = st.columns(2)
            with c_ps1:
                p_upi = st.text_input("UPI ID", value=pay_cfg.get('upi_id', ''), placeholder="e.g. yourname@okaxis or sisterfatima@upi")
                p_num = st.text_input("GPay / PhonePe / Paytm Mobile Number", value=pay_cfg.get('payment_number', ''), placeholder="e.g. 98XXXXXXXX")
            with c_ps2:
                p_name = st.text_input("Beneficiary / Account Holder Name", value=pay_cfg.get('account_holder_name', ''), placeholder="e.g. Sister Fatima")
                p_inst = st.text_area("Custom Instructions / Notes for Students", value=pay_cfg.get('custom_instructions', ''), placeholder="e.g. Please share payment screenshot on WhatsApp after paying.")

            btn_save_pay = st.form_submit_button("💾 Save Payment Settings", type="primary", use_container_width=True)
            if btn_save_pay:
                ok, msg = update_payment_settings(p_upi, p_num, p_name, p_inst)
                if ok:
                    st.success(msg)
                    st.rerun()
                else:
                    st.error(f"Error: {msg}")

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
            f_amt = st.text_input("Fee Amount (₹)", value="", placeholder="e.g. 1000 or 1500")
            f_due = st.date_input("Due Date", value=datetime.date.today() + datetime.timedelta(days=10))
            f_note = st.text_input("Instructions / Payment Note", value="Pay via UPI or direct transfer", placeholder="e.g. Send screenshot on WhatsApp")

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
                                trigger_cloud_sync("Issued fee invoice(s)")

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
                                trigger_cloud_sync(f"Marked invoice #{target_fee['id']} as Paid")

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
                                trigger_cloud_sync(f"Reset invoice #{target_fee['id']} to Pending")

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
                                trigger_cloud_sync(f"Deleted invoice #{target_fee['id']}")

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
        pay_cfg = get_payment_settings()
        has_upi = bool(pay_cfg.get('upi_id', '').strip())
        has_num = bool(pay_cfg.get('payment_number', '').strip())
        has_name = bool(pay_cfg.get('account_holder_name', '').strip())
        custom_inst = pay_cfg.get('custom_instructions', '').strip()

        if not has_upi and not has_num and not custom_inst:
            st.markdown("""
            <div class="glass-card" style="padding:18px;">
                <h4 style="margin-top:0; color:#1e293b;">📌 Payment Instructions</h4>
                <p style="color:#64748b; font-size:0.9rem; margin-bottom:0;">
                    Payment details have not been configured yet. Please contact your Teacher or Academy Administrator directly for fee payment instructions.
                </p>
            </div>
            """, unsafe_allow_html=True)
        else:
            upi_li = f"<li><b>UPI ID:</b> <code>{pay_cfg['upi_id']}</code></li>" if has_upi else ""
            num_li = f"<li><b>Google Pay / PhonePe / Paytm:</b> Send to <code>{pay_cfg['payment_number']}</code></li>" if has_num else ""
            name_li = f"<li><b>Account / Beneficiary Name:</b> <b>{pay_cfg['account_holder_name']}</b></li>" if has_name else ""
            notes_div = f"""
            <div style="background:#e0f2fe; border-left:4px solid #0284c7; padding:10px; border-radius:6px; font-size:0.85rem; color:#0369a1; margin-top:12px;">
                ℹ️ <b>Important:</b> {custom_inst}
            </div>
            """ if custom_inst else ""

            st.markdown(f"""
            <div class="glass-card" style="padding:18px;">
                <h4 style="margin-top:0; color:#1e293b;">📌 Payment Instructions</h4>
                <ul style="color:#475569; font-size:0.9rem; padding-left:18px; margin-bottom:12px;">
                    {upi_li}
                    {num_li}
                    {name_li}
                </ul>
                {notes_div}
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
            sc_topic = st.text_input("Class Topic", placeholder="e.g. Urdu Grammar / Arabic Reading Lesson 1")
            sc_sub = st.text_input("Subject", value="Urdu / Arabic", placeholder="Type any subject e.g. Urdu, Arabic, Tajweed, Grammar...", key=f"sc_sub_{'adm' if is_admin else 'tch'}")
            sc_teacher = st.text_input("Teacher / Host Name", value=st.session_state.name or "Teacher")
            
            c_d1, c_d2 = st.columns(2)
            with c_d1:
                sc_date = st.date_input("Scheduled Date", value=datetime.date.today())
            with c_d2:
                sc_time = st.text_input("Time (HH:MM)", value="18:00", placeholder="18:00")

            # Room key is handled automatically in the background
            sc_room = "SistersLiveClass_MasterRoom"
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
                            trigger_cloud_sync(f"Scheduled class '{sc_topic.strip()}'")

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
                status_badge_bg = "#10b981" if is_sc_live else "#3b82f6"
                status_badge_text = "🔴 LIVE NOW" if is_sc_live else "🗓️ SCHEDULED"
                wl_open = sc.get('allow_waiting_room', 1) == 1
                wl_badge = '<span style="color:#34d399; font-weight:600;">🛋️ Waiting Lounge: OPEN</span>' if wl_open else '<span style="color:#94a3b8; font-weight:500;">🔒 Waiting Lounge: Closed</span>'

                with st.container():
                    st.markdown(f"""
                    <div style="background: linear-gradient(145deg, #1e293b 0%, #0f172a 100%); border: 1px solid #334155; color: #f8fafc; border-radius: 16px; padding: 18px; margin-bottom: 12px; box-shadow: 0 10px 25px -5px rgba(0, 0, 0, 0.35);">
                        <div style="display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:8px;">
                            <div style="display:flex; align-items:center; gap:8px;">
                                <span style="background: linear-gradient(135deg, #6366f1 0%, #8b5cf6 100%); color: white; padding: 3px 10px; border-radius: 9999px; font-weight: 700; font-size: 0.78rem;">
                                    {sc.get('subject') or 'Urdu / Arabic'}
                                </span>
                                <b style="color:#ffffff; font-size:1.05rem;">{sc.get('topic')}</b>
                            </div>
                            <span style="background:{status_badge_bg}; color:white; padding:3px 10px; border-radius:9999px; font-weight:700; font-size:0.75rem;">
                                {status_badge_text}
                            </span>
                        </div>
                        <div style="margin-top:10px; display:flex; flex-wrap:wrap; gap:12px; font-size:0.86rem; color:#94a3b8;">
                            <div>📅 <b>Date:</b> <span style="color:#f1f5f9;">{sc.get('scheduled_date')}</span></div>
                            <div>⏰ <b>Time:</b> <span style="color:#f1f5f9;">{sc.get('scheduled_time')}</span></div>
                            <div>👩‍🏫 <b>Teacher:</b> <span style="color:#f1f5f9;">{sc.get('teacher_name')}</span></div>
                            <div>{wl_badge}</div>
                        </div>
                        {f'<div style="font-size:0.82rem; color:#cbd5e1; margin-top:8px; padding-top:6px; border-top:1px solid #334155;">💬 <b>Note:</b> {sc.get("notes")}</div>' if sc.get('notes') else ''}
                    </div>
                    """, unsafe_allow_html=True)

                    btn_c1, btn_c2, btn_c3 = st.columns([1.5, 1, 1])

                    with btn_c1:
                        with st.form(f"launch_sc_form_{sc['id']}_{'adm' if is_admin else 'tch'}"):
                            if st.form_submit_button("🚀 Launch Live Now", type="primary", use_container_width=True):
                                host_name = sc.get('teacher_name') or st.session_state.name or "Teacher"
                                start_live_class(
                                    topic=sc.get('topic', 'Urdu & Arabic Live Class'),
                                    subject=sc.get('subject', 'Urdu / Arabic'),
                                    jitsi_server="jitsi.riot.im",
                                    room_name=sc.get('room_name', 'SistersLiveClass_MasterRoom'),
                                    teacher_notes=sc.get('notes', ''),
                                    host_teacher=host_name
                                )
                                try:
                                    with get_db_connection() as conn_w:
                                        conn_w.execute("UPDATE scheduled_classes SET status = 'Live' WHERE id = ?", (sc['id'],))
                                        conn_w.commit()
                                        conn_w.execute("PRAGMA wal_checkpoint(TRUNCATE);")
                                except Exception:
                                    pass
                                if is_supabase_active():
                                    try:
                                        supabase_request("PATCH", "scheduled_classes", {"status": "Live"}, params=f"id=eq.{sc['id']}")
                                    except Exception:
                                        pass
                                st.session_state.is_live_local = True
                                st.success(f"Broadcast started for '{sc['topic']}'! Students in waiting lounge are now live.")
                                st.rerun()

                    with btn_c2:
                        with st.form(f"done_sc_form_{sc['id']}_{'adm' if is_admin else 'tch'}"):
                            if st.form_submit_button("✅ Done", use_container_width=True):
                                try:
                                    with get_db_connection() as conn_w:
                                        conn_w.execute("DELETE FROM scheduled_classes WHERE id = ?", (sc['id'],))
                                        conn_w.commit()
                                        conn_w.execute("PRAGMA wal_checkpoint(TRUNCATE);")
                                    trigger_cloud_sync(f"Marked scheduled class #{sc['id']} completed and removed")

                                    if is_supabase_active():
                                        supabase_request("DELETE", "scheduled_classes", params=f"id=eq.{sc['id']}")

                                    st.success("Marked as Completed & Removed.")
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
                                        conn_w.execute("PRAGMA wal_checkpoint(TRUNCATE);")
                                    trigger_cloud_sync(f"Permanently cancelled scheduled class #{sc['id']}")

                                    if is_supabase_active():
                                        supabase_request("DELETE", "scheduled_classes", params=f"id=eq.{sc['id']}")

                                    st.warning("Scheduled class cancelled & permanently removed.")
                                    st.rerun()
                                except Exception as e:
                                    st.error(f"Error deleting class: {e}")

def render_live_studio_hero_card(is_admin: bool = False, show_stop_form: bool = True):
    """
    Renders the modern 2-column Live Class Broadcast Studio top Hero Card:
    - Left side: Live Status Badge (pulsing green dot when live / slate badge when offline),
      quick topic input, and full-width action button (Start Live / End Live).
    - Right side: Quick Stats mini-cards (Students, Upcoming Classes, Recordings, Pending Fees)
      + full-width 'Open Google Drive Folder' button.
    Technical server and room parameters are handled seamlessly in the background.
    """
    conn = get_db()
    c = conn.cursor()

    # Session state - fetched fresh without stale cache
    sess = get_live_class_state()

    is_live = bool(sess.get('is_live', 0))
    session_topic = sess.get('topic') or "Urdu & Arabic Live Class"
    room_name = sess.get('room_name') or "SistersLiveClass_MasterRoom"
    server = sess.get('server') or "jitsi.riot.im"
    teacher_notes = sess.get('teacher_notes') or ""
    host_teacher = sess.get('host_teacher') or (st.session_state.name or "Teacher")
    started_at = sess.get('started_at') or "Recently"

    # Query Quick Stats
    student_count = 0
    upcoming_count = 0
    recording_count = 0
    pending_fee_count = 0
    try:
        c.execute("SELECT COUNT(*) as cnt FROM users WHERE role = 'student' AND is_active = 1")
        r_u = c.fetchone()
        student_count = r_u['cnt'] if r_u else 0

        c.execute("SELECT COUNT(*) as cnt FROM scheduled_classes WHERE status = 'Scheduled'")
        r_sc = c.fetchone()
        upcoming_count = r_sc['cnt'] if r_sc else 0

        c.execute("SELECT COUNT(*) as cnt FROM recordings")
        r_rc = c.fetchone()
        recording_count = r_rc['cnt'] if r_rc else 0

        c.execute("SELECT COUNT(*) as cnt FROM fees WHERE status = 'Pending'")
        r_fe = c.fetchone()
        pending_fee_count = r_fe['cnt'] if r_fe else 0
    except Exception as e:
        print(f"Error fetching quick stats: {e}")

    col_hero_left, col_hero_right = st.columns([1.35, 1.15], gap="medium")

    with col_hero_left:
        # Header / Status row with Reset Studio State recovery button
        col_badge_head, col_badge_reset = st.columns([2.8, 1.2])

        if is_live:
            with col_badge_head:
                st.markdown(f"""
                <div class="glass-card" style="border: 2px solid #22c55e; background: linear-gradient(145deg, #f0fdf4 0%, #dcfce7 100%); margin-bottom: 8px; padding: 14px 18px;">
                    <div style="display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:8px;">
                        <div class="live-badge">
                            <span class="live-dot"></span>
                            <span>🔴 BROADCAST STATUS: LIVE NOW</span>
                        </div>
                        <span style="font-size: 0.85rem; color: #166534; font-weight: 700;">Started: {started_at}</span>
                    </div>
                    <h3 style="margin: 8px 0 2px 0; color: #14532d; font-size: 1.2rem;">{session_topic}</h3>
                    <p style="margin: 0; color: #166534; font-size: 0.85rem;">
                        <b>Host:</b> {host_teacher} &nbsp;|&nbsp; <b>Note:</b> {teacher_notes or 'Microphones active for student questions'}
                    </p>
                </div>
                """, unsafe_allow_html=True)
            with col_badge_reset:
                if st.button("🔄 Reset Studio State", key=f"reset_studio_live_{'adm' if is_admin else 'tch'}", help="Force reset studio state if stuck"):
                    reset_studio_state()
                    st.success("Studio state reset.")
                    st.rerun()

            if show_stop_form:
                with st.form(f"hero_stop_form_{'adm' if is_admin else 'tch'}"):
                    btn_stop = st.form_submit_button("🛑 End Live Class for All", type="primary", use_container_width=True)
                    if btn_stop:
                        end_live_class()
                        st.warning("Live class ended. Students returned to offline waiting status.")
                        st.rerun()

        else:
            with col_badge_head:
                st.markdown("""
                <div class="glass-card" style="border: 1px solid #e2e8f0; background: #ffffff; margin-bottom: 8px; padding: 12px 18px;">
                    <div style="display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:8px;">
                        <div class="offline-badge">
                            <span style="width:9px; height:9px; border-radius:50%; background:#94a3b8; display:inline-block;"></span>
                            <span>⚪ STUDIO READY — OFFLINE</span>
                        </div>
                        <span style="font-size: 0.82rem; color: #64748b; font-weight: 500;">Students waiting will join automatically</span>
                    </div>
                </div>
                """, unsafe_allow_html=True)
            with col_badge_reset:
                if st.button("🔄 Reset Studio State", key=f"reset_studio_off_{'adm' if is_admin else 'tch'}", help="Clear cached studio state"):
                    reset_studio_state()
                    st.success("Studio state reset.")
                    st.rerun()

            with st.form(f"hero_start_form_{'adm' if is_admin else 'tch'}"):
                f_topic = st.text_input("Class Topic", value=session_topic or "Urdu Grammar / Arabic Reading Lesson 1", placeholder="e.g. Urdu Grammar Lesson 1")
                f_notes = st.text_input("Instructions / Notes for Students", value="Camera is OFF by default. Unmute mic to ask doubts.", placeholder="e.g. Keep Tajweed book open...")
                btn_start = st.form_submit_button("🚀 Start Live Class Now", type="primary", use_container_width=True)

                if btn_start:
                    h_name = st.session_state.name or ("Super Admin" if is_admin else "Teacher")
                    target_server = "jitsi.riot.im"
                    target_room = room_name or "SistersLiveClass_MasterRoom"
                    start_live_class(
                        topic=f_topic,
                        subject="Urdu / Arabic",
                        jitsi_server=target_server,
                        room_name=target_room,
                        teacher_notes=f_notes,
                        host_teacher=h_name
                    )
                    st.success("Live broadcast started! Connected to all students.")
                    st.rerun()

    with col_hero_right:
        st.markdown(f"""
        <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 10px; margin-bottom: 12px;">
            <div style="background: linear-gradient(135deg, #eff6ff 0%, #dbeafe 100%); border: 1px solid #bfdbfe; border-radius: 12px; padding: 12px 14px; text-align: center;">
                <div style="font-size: 1.4rem; font-weight: 800; color: #1e40af;">{student_count}</div>
                <div style="font-size: 0.75rem; font-weight: 700; color: #3b82f6; text-transform: uppercase; margin-top: 2px;">👥 Students</div>
            </div>
            <div style="background: linear-gradient(135deg, #f5f3ff 0%, #ede9fe 100%); border: 1px solid #ddd6fe; border-radius: 12px; padding: 12px 14px; text-align: center;">
                <div style="font-size: 1.4rem; font-weight: 800; color: #5b21b6;">{upcoming_count}</div>
                <div style="font-size: 0.75rem; font-weight: 700; color: #8b5cf6; text-transform: uppercase; margin-top: 2px;">📅 Upcoming</div>
            </div>
            <div style="background: linear-gradient(135deg, #ecfdf5 0%, #d1fae5 100%); border: 1px solid #a7f3d0; border-radius: 12px; padding: 12px 14px; text-align: center;">
                <div style="font-size: 1.4rem; font-weight: 800; color: #065f46;">{recording_count}</div>
                <div style="font-size: 0.75rem; font-weight: 700; color: #10b981; text-transform: uppercase; margin-top: 2px;">🎥 Recordings</div>
            </div>
            <div style="background: linear-gradient(135deg, #fff1f2 0%, #ffe4e6 100%); border: 1px solid #fecdd3; border-radius: 12px; padding: 12px 14px; text-align: center;">
                <div style="font-size: 1.4rem; font-weight: 800; color: #9f1239;">{pending_fee_count}</div>
                <div style="font-size: 0.75rem; font-weight: 700; color: #f43f5e; text-transform: uppercase; margin-top: 2px;">💰 Pending Fees</div>
            </div>
        </div>
        """, unsafe_allow_html=True)

        st.link_button("📂 Open Google Drive Folder", DEFAULT_DRIVE_FOLDER_URL, use_container_width=True)

    return is_live, room_name, server

LIVE_BOARD_IMAGE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "live_board_image.png")

def render_live_board_manager(is_teacher: bool = False):
    """
    In-Browser Mobile Lesson & Book Sharing:
    Allows Teacher to upload or photo-capture an Urdu/Arabic book page or notes during live class,
    saving it to live_board_image.png which automatically renders above the video player for all students.
    """
    if is_teacher:
        with st.expander("📖 Share Urdu/Arabic Book Page or Image to All Students (Mobile Friendly)", expanded=False):
            st.caption("📱 **Mobile Teaching Tip:** Tap below to capture a live photo of your Qaida, Quran, or book with your phone camera. It displays live above the video for all students!")
            board_img_file = st.file_uploader(
                "Upload or Capture Book Page (Photo)",
                type=["png", "jpg", "jpeg", "webp"],
                key="live_board_uploader_file",
                help="Camera photo or scanned book page"
            )
            if board_img_file is not None:
                try:
                    raw_bytes = board_img_file.getbuffer()
                    with open(LIVE_BOARD_IMAGE_PATH, "wb") as f_board:
                        f_board.write(raw_bytes)
                    b64_str = base64.b64encode(raw_bytes).decode("utf-8")
                    mime = getattr(board_img_file, "type", "image/jpeg")
                    now_ts = datetime.datetime.now().isoformat()
                    with get_db_connection() as conn_b:
                        conn_b.execute("INSERT OR REPLACE INTO live_board (id, image_data, mime_type, updated_at) VALUES (1, ?, ?, ?)", (b64_str, mime, now_ts))
                        conn_b.commit()
                        conn_b.execute("PRAGMA wal_checkpoint(TRUNCATE);")
                    trigger_cloud_sync("Saved shared book page to cloud")
                    st.success("✅ Book page shared to all students' screens live!")
                except Exception as e:
                    st.error(f"Error saving book page: {e}")

            if os.path.exists(LIVE_BOARD_IMAGE_PATH):
                col_b1, col_b2 = st.columns([3, 1], gap="small")
                with col_b1:
                    st.image(LIVE_BOARD_IMAGE_PATH, caption="📖 Currently Shared Lesson Page (Visible to All Students)", use_container_width=True)
                with col_b2:
                    if st.button("🗑️ Remove Shared Book Page", key="clear_live_board_btn", type="secondary", use_container_width=True):
                        try:
                            if os.path.exists(LIVE_BOARD_IMAGE_PATH):
                                os.remove(LIVE_BOARD_IMAGE_PATH)
                            with get_db_connection() as conn_b:
                                conn_b.execute("DELETE FROM live_board WHERE id = 1")
                                conn_b.commit()
                                conn_b.execute("PRAGMA wal_checkpoint(TRUNCATE);")
                            trigger_cloud_sync("Cleared shared book page")
                            st.success("Page cleared.")
                            st.rerun()
                        except Exception as e:
                            st.error(f"Error removing: {e}")
    else:
        # Student Live Screen View - auto restore from DB if disk reset
        if not os.path.exists(LIVE_BOARD_IMAGE_PATH):
            try:
                with get_db_connection() as conn_b:
                    row_b = conn_b.execute("SELECT image_data FROM live_board WHERE id = 1").fetchone()
                    if row_b and row_b['image_data']:
                        with open(LIVE_BOARD_IMAGE_PATH, "wb") as f_out:
                            f_out.write(base64.b64decode(row_b['image_data']))
            except Exception:
                pass

        if os.path.exists(LIVE_BOARD_IMAGE_PATH):
            st.markdown("""
            <div style="background: #f8fafc; border: 2px solid #6366f1; border-radius: 12px; padding: 10px 14px; margin-bottom: 8px; text-align: center;">
                <b style="color: #4338ca; font-size: 0.95rem;">📖 Teacher's Shared Lesson / Book Page</b>
            </div>
            """, unsafe_allow_html=True)
            st.image(LIVE_BOARD_IMAGE_PATH, caption="Live Book / Qaida Page Shared by Teacher", use_container_width=True)
            st.markdown("<div style='height: 6px;'></div>", unsafe_allow_html=True)

def render_top_quick_actions_bar():
    """
    Renders a visible, bordered Top Account Bar right at the top of the main screen
    giving instant access to Refresh Dashboard, Change Password, and Log Out without opening the sidebar.
    """
    with st.container(border=True):
        role_label = {
            'admin': '👑 Super Admin',
            'teacher': '👩‍🏫 Teacher',
            'student': '🎓 Student'
        }.get(st.session_state.role, str(st.session_state.role).capitalize())
        role_color = "#4f46e5" if st.session_state.role == "admin" else ("#059669" if st.session_state.role == "teacher" else "#0284c7")

        st.markdown(f"""
        <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px; flex-wrap: wrap; gap: 6px;">
            <div style="font-size: 0.95rem; color: #1e293b;">
                <b>👤 {st.session_state.name}</b> <span style="color: #64748b; font-size: 0.85rem;">(@{st.session_state.username})</span>
            </div>
            <span style="background: {role_color}18; color: {role_color}; border: 1px solid {role_color}44; font-size: 0.78rem; font-weight: 700; padding: 2px 10px; border-radius: 9999px;">
                {role_label}
            </span>
        </div>
        """, unsafe_allow_html=True)

        col_ref, col_pwd, col_out = st.columns([1.2, 1.2, 1], gap="small")
        with col_ref:
            if st.button("🔄 Refresh Dashboard", key="top_refresh_dashboard_btn", use_container_width=True, help="Reload live class status, fee dues, notices & schedules without logging out"):
                try:
                    st.cache_data.clear()
                except Exception:
                    pass
                st.toast("✅ Dashboard updated!", icon="🔄")
                st.rerun()

        with col_pwd:
            with st.popover("🔑 Change Password", use_container_width=True):
                st.markdown(f"**Change Password (@{st.session_state.username})**")
                with st.form("topbar_pwd_form"):
                    curr_pwd = st.text_input("Current Password", type="password", key="tb_curr_pwd")
                    new_pwd = st.text_input("New Password", type="password", key="tb_new_pwd")
                    confirm_pwd = st.text_input("Confirm New Password", type="password", key="tb_conf_pwd")
                    if st.form_submit_button("Save Password", type="primary", use_container_width=True):
                        if not curr_pwd or not new_pwd:
                            st.error("Please fill both password fields.")
                        elif len(new_pwd.strip()) < 4:
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
                                    curr_h = hash_password(curr_pwd)

                                    is_match = (raw_p and curr_pwd == raw_p) or (curr_h == h_p)
                                    if not is_match:
                                        st.error("Incorrect current password.")
                                    else:
                                        new_h = hash_password(new_pwd.strip())
                                        with get_db_connection() as conn_w:
                                            conn_w.execute("""
                                            UPDATE users SET password = ?, password_hash = ? WHERE username = ?
                                            """, (new_pwd.strip(), new_h, st.session_state.username))
                                            conn_w.commit()
                                            trigger_cloud_sync(f"Password changed for @{st.session_state.username}")

                                        if is_supabase_active():
                                            supabase_request("PATCH", "users", {
                                                "password": new_pwd.strip(),
                                                "password_hash": new_h
                                            }, params=f"username=eq.{st.session_state.username}")

                                        # Update token in query_params if active
                                        try:
                                            st.query_params["t"] = make_session_token(st.session_state.username, new_h)
                                        except Exception:
                                            pass

                                        st.success("✅ Password updated successfully!")
                            except Exception as e:
                                st.error(f"Error updating password: {e}")
        with col_out:
            if st.button("🚪 Log Out", key="mobile_top_logout", type="primary", use_container_width=True):
                try:
                    st.query_params.clear()
                except Exception:
                    pass
                st.session_state.logged_in = False
                st.session_state.username = None
                st.session_state.role = None
                st.session_state.name = None
                st.session_state.live_joined = False
                st.session_state.joined_live_class = False
                st.rerun()
    st.markdown("<div style='margin-bottom: 8px;'></div>", unsafe_allow_html=True)


# ==========================================
# 7. SUPER ADMIN DASHBOARD
# ==========================================
def render_admin_dashboard():
    conn = get_db()
    c = conn.cursor()

    # Get live session status safely
    sess = get_live_class_state()
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

    gh_tok, gh_rp = get_github_config()
    if not gh_tok:
        st.warning("⚠️ **Cloud Notice:** GitHub Auto-Persistence is not locked yet. Newly created accounts could reset when Streamlit Cloud sleeps! Open the **'☁️ Permanent Cloud Lock & Backup'** tab below to paste your GitHub Token so accounts are saved to GitHub permanently.")

    tab_cred, tab_fees, tab_live, tab_recordings, tab_notices, tab_doubts, tab_att, tab_cloud = st.tabs([
        "👑 Master Credentials & Accounts",
        "💳 Student Fees & Invoices",
        "🎥 Live Classroom Broadcast",
        "📚 Study Library & Drive Folder",
        "📢 Announcements Board",
        "❓ Doubts & Discussion Moderation",
        "📊 Master Attendance Logs",
        "☁️ Permanent Cloud Lock & Backup"
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
                                trigger_cloud_sync(f"Created {new_role} account @{new_un}")

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
                                    trigger_cloud_sync(f"Updated password for @{sel_user['username']}")
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
                                        trigger_cloud_sync(f"Toggled status for @{sel_user['username']}")
                                except Exception as e:
                                    print(f"Error toggling user status: {e}")

                                if is_supabase_active():
                                    supabase_request("PATCH", "users", {"is_active": new_act}, params=f"id=eq.{sel_user['id']}")

                                st.success(f"Account @{sel_user['username']} status updated.")
                                st.rerun()

                with col_st2:
                    admin_del_key = f"admin_del_user_{sel_user['id']}"
                    if st.button("🗑️ Delete Account Permanently", key=admin_del_key, use_container_width=True, type="primary"):
                        ok, msg = delete_user_account(
                            sel_user['username'],
                            st.session_state.get('role', 'admin'),
                            st.session_state.get('username', '')
                        )
                        if ok:
                            if is_supabase_active():
                                supabase_request("DELETE", "users", params=f"id=eq.{sel_user['id']}")
                            st.success(msg)
                            st.rerun()
                        else:
                            st.error(msg)

    # ---------------------------------------------
    # ADMIN TAB 1.5: FEES MANAGEMENT
    # ---------------------------------------------
    with tab_fees:
        render_fees_management(is_admin=True)

    # ---------------------------------------------
    # ADMIN TAB 2: LIVE BROADCAST STUDIO
    # ---------------------------------------------
    with tab_live:
        st.subheader("Live Class Broadcast Engine")

        if is_live:
            # 1. Top status header with quick End button at top
            col_live_hdr, col_live_top_btn = st.columns([2.5, 1.2], gap="small")
            with col_live_hdr:
                st.markdown(f"""
                <div style="background: linear-gradient(135deg, #15803d 0%, #166534 100%); color: white; padding: 10px 16px; border-radius: 10px; box-shadow: 0 4px 15px rgba(22, 101, 52, 0.25);">
                    <div style="display:flex; align-items:center; gap:8px;">
                        <span style="width:10px; height:10px; border-radius:50%; background:#ef4444; display:inline-block; box-shadow:0 0 8px #ef4444;"></span>
                        <b style="font-size:1.0rem;">🔴 BROADCAST STATUS: LIVE NOW</b>
                    </div>
                    <div style="font-size:0.85rem; opacity:0.95; margin-top:2px;"><b>{session_topic}</b> (Host: {host_teacher} | Started: {started_at})</div>
                </div>
                """, unsafe_allow_html=True)
            with col_live_top_btn:
                col_btn_end, col_btn_rst = st.columns([1.2, 1])
                with col_btn_end:
                    with st.form("end_class_top_adm"):
                        btn_top = st.form_submit_button("🛑 End Live", type="primary", use_container_width=True)
                        if btn_top:
                            end_live_class()
                            st.warning("Live class ended.")
                            st.rerun()
                with col_btn_rst:
                    if st.button("🔄 Reset Studio", key="rst_top_adm", use_container_width=True, help="Force reset studio state"):
                        reset_studio_state()
                        st.success("Studio reset.")
                        st.rerun()

            st.markdown("<div style='height: 4px;'></div>", unsafe_allow_html=True)

            # Mobile In-Browser Lesson / Book Sharing
            render_live_board_manager(is_teacher=True)

            # 2. Render the Live Classroom video player FIRST
            render_jitsi_classroom(
                domain=server,
                room_name=room_name,
                display_name=f"{st.session_state.name} (Super Admin)",
                is_teacher=True
            )

            # 3. Big "🛑 End Live Class for All" button DIRECTLY BELOW the live video
            st.markdown("<div style='height: 10px;'></div>", unsafe_allow_html=True)
            with st.form("end_class_bottom_mobile_adm"):
                btn_stop = st.form_submit_button("🛑 End Live Class for All", type="primary", use_container_width=True)
                if btn_stop:
                    end_live_class()
                    st.warning("Live class ended. Students returned to offline waiting status.")
                    st.rerun()

            st.markdown("---")
            render_live_studio_hero_card(is_admin=True, show_stop_form=False)

        else:
            is_live, room_name, server = render_live_studio_hero_card(is_admin=True, show_stop_form=True)
            st.markdown("---")
            st.info("💡 To begin teaching or broadcasting, configure your topic and click **'Start Live Class Now'** above.")

        st.markdown("---")
        render_quick_recording_uploader(key_suffix="admin_live_studio", title="1-Click Live Class Recording Publisher")
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
            st.link_button("📂 Open Google Drive Folder", DEFAULT_DRIVE_FOLDER_URL, type="primary", use_container_width=True)
        with col_up_btn2:
            st.info(f"📁 Folder ID: `{DEFAULT_DRIVE_FOLDER_ID}`")

        render_quick_recording_uploader(key_suffix="admin_rec_tab", title="Direct Video Uploader (Local Server + Google Drive Sync)")

        st.markdown("---")
        st.markdown("#### 🎬 Spotlight Individual Video Player")
        col_r1, col_r2 = st.columns([1.2, 1.8])

        with col_r1:
            with st.form("admin_add_rec_form", clear_on_submit=True):
                r_title = st.text_input("Lecture Title", placeholder="e.g. Urdu Grammar / Arabic Reading Lesson 1")
                r_subject = st.text_input("Subject", value="Urdu / Arabic", placeholder="Type any subject e.g. Urdu, Arabic, Tajweed, Grammar...", key="admin_rec_sub")
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
                        render_recording_player(rec, is_student=False, key_suffix=f"adm_rec_{rec['id']}")
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
        st.subheader("☁️ Permanent Cloud Lock & Auto-Persistence")
        st.markdown(
            "Streamlit Community Cloud has an ephemeral filesystem that resets on sleep or restart. "
            "With **GitHub Cloud Auto-Persistence**, every Teacher/Student account, fee record, and schedule is "
            "automatically committed back to your GitHub repository in real time so **no data is ever lost!**"
        )

        gh_token, gh_repo = get_github_config()
        if gh_token and gh_repo:
            st.success(f"🟢 **GitHub Cloud Auto-Persistence is ACTIVE!** Target repository: `{gh_repo}`. Every write operation (accounts, passwords, fees, recordings) automatically syncs directly to GitHub.")
        else:
            st.warning("🟠 **GitHub Cloud Auto-Persistence is NOT fully active yet!**")
            st.markdown(
                """
                **Permanent 2-Step Setup via Streamlit Cloud Secrets (Recommended):**
                1. Go to your app on [share.streamlit.io](https://share.streamlit.io) -> Click **Manage app** (bottom-right) -> **Settings** -> **Secrets**.
                2. Paste the following and click **Save**:
                ```toml
                GITHUB_TOKEN = "ghp_yourPersonalAccessTokenHere"
                GITHUB_REPO = "AnsariAmirhasan/sisters-live-academy"
                ```
                *(Create a GitHub Personal Access Token at github.com -> Settings -> Developer Settings -> Personal access tokens -> Tokens (classic) with `repo` permission).*
                """
            )

            with st.expander("🔑 Or Paste GitHub Token Directly Here (Instant Setup)", expanded=True):
                with st.form("form_save_gh_token"):
                    custom_tok = st.text_input("GitHub Personal Access Token (classic or fine-grained with Contents: Write)", type="password", placeholder="ghp_...")
                    custom_repo = st.text_input("GitHub Repository", value=gh_repo or "AnsariAmirhasan/sisters-live-academy")
                    if st.form_submit_button("🔒 Save & Enable Auto-Persistence Now", type="primary"):
                        if custom_tok.strip():
                            try:
                                with get_db_connection() as conn_meta:
                                    conn_meta.execute("CREATE TABLE IF NOT EXISTS app_meta (key TEXT PRIMARY KEY, value TEXT)")
                                    conn_meta.execute("INSERT OR REPLACE INTO app_meta (key, value) VALUES ('github_token_override', ?)", (custom_tok.strip(),))
                                    conn_meta.execute("INSERT OR REPLACE INTO app_meta (key, value) VALUES ('github_repo_override', ?)", (custom_repo.strip(),))
                                    conn_meta.commit()
                                st.success("Token saved into database! Triggering test sync...")
                                ok, msg = sync_db_to_cloud("Initial Cloud Lock activation from Admin Dashboard")
                                if ok:
                                    st.success(f"🎉 Cloud Auto-Persistence successfully locked and verified! ({msg})")
                                else:
                                    st.warning(f"Token saved, but test sync reported: {msg}")
                                st.rerun()
                            except Exception as ex_tk:
                                st.error(f"Failed to save token: {ex_tk}")
                        else:
                            st.error("Please enter a valid GitHub token.")

        st.markdown("---")
        st.subheader("🔄 Manual Cloud Sync & Backup Actions")
        col_sync1, col_sync2 = st.columns(2)

        with col_sync1:
            if st.button("🔄 Sync Database to GitHub Cloud Now", type="primary", use_container_width=True):
                with st.spinner("Flushing WAL and committing classroom.db to GitHub..."):
                    ok_sync, msg_sync = sync_db_to_cloud(f"Manual database sync by Admin @{st.session_state.username}")
                    if ok_sync:
                        st.success(f"✅ Successfully synced to GitHub: {msg_sync}")
                    else:
                        st.error(f"❌ Sync failed: {msg_sync}")

        with col_sync2:
            flush_db_wal()
            db_bytes = b""
            try:
                with open("classroom.db", "rb") as f_db:
                    db_bytes = f_db.read()
            except Exception as e_rdb:
                st.error(f"Could not read classroom.db: {e_rdb}")

            if db_bytes:
                st.download_button(
                    label="💾 Download Full Database Backup (classroom.db)",
                    data=db_bytes,
                    file_name=f"classroom_backup_{datetime.date.today()}.db",
                    mime="application/x-sqlite3",
                    use_container_width=True
                )

        st.markdown("---")
        with st.expander("📤 Restore Database from Local Backup (.db File)"):
            st.info("Upload a previously downloaded `classroom.db` file to immediately restore all accounts, attendance, fees, and scheduled classes.")
            uploaded_db = st.file_uploader("Select classroom.db backup file", type=["db", "sqlite", "sqlite3"], key="uploader_restore_db")
            if uploaded_db is not None:
                content = uploaded_db.getvalue()
                if not content.startswith(b"SQLite format 3\x00"):
                    st.error("❌ The uploaded file is not a valid SQLite 3 database.")
                else:
                    st.warning(f"File verified: SQLite database ({len(content) / 1024:.1f} KB).")
                    if st.button("⚠️ Confirm & Overwrite Live Database", type="secondary"):
                        try:
                            # Close any lingering connections and write file
                            flush_db_wal()
                            with open("classroom.db", "wb") as f_out:
                                f_out.write(content)
                            flush_db_wal()
                            st.success("Database restored successfully!")
                            trigger_cloud_sync("Database restored from Admin panel backup file")
                            st.rerun()
                        except Exception as e_wrt:
                            st.error(f"Failed to restore database: {e_wrt}")

        st.markdown("---")
        with st.expander("⚡ Supabase Cloud Database Status (Optional Alternate Cloud)"):
            supabase_on = is_supabase_active()
            url_cfg, key_cfg = get_supabase_config()
            if supabase_on:
                st.success("🟢 Supabase Cloud Storage is fully CONNECTED and ACTIVE!")
                if url_cfg:
                    st.write(f"**Connected Supabase Project URL:** `{url_cfg}`")
            else:
                st.info("Supabase is optional. With GitHub Cloud Auto-Persistence enabled above, your database is already 100% permanently preserved.")
                st.link_button("👉 Open Supabase SQL Editor", "https://supabase.com/dashboard/project/qxfuebpmspwixaylddby/sql/new")

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

    # Get live session status safely
    sess = get_live_class_state()
    is_live = bool(sess.get('is_live', 0))
    room_name = sess.get('room_name') or 'SistersLiveClass_MasterRoom'
    session_topic = sess.get('topic') or 'General Coaching Session'
    server = sess.get('server') or "jitsi.riot.im"
    teacher_notes = sess.get('teacher_notes') or ""
    started_at = sess.get('started_at') or "Recently"

    st.markdown(f"""
    <div class="hero-banner">
        <div style="display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap;">
            <div>
                <h1>👩‍🏫 Teacher Control Center</h1>
                <p>Welcome, <b>{st.session_state.name}</b> | Urdu & Arabic Live Coaching Portal</p>
            </div>
        </div>
    </div>
    """, unsafe_allow_html=True)

    tab_live, tab_recordings, tab_fees, tab_notices, tab_doubts, tab_students = st.tabs([
        "🔴 Live Studio & Screen Share",
        "📚 Recorded Classes (Google Drive)",
        "💳 Student Fees & Invoices",
        "📢 Notice Board",
        "❓ Doubt Box & Chat",
        "👥 Attendance & Student Accounts"
    ])

    # ---------------------------------------------
    # TEACHER TAB 1: LIVE STUDIO
    # ---------------------------------------------
    with tab_live:
        st.subheader("Live Class Broadcast Engine")

        if is_live:
            # 1. Top status header with quick End button at top
            col_live_hdr, col_live_top_btn = st.columns([2.5, 1.2], gap="small")
            with col_live_hdr:
                st.markdown(f"""
                <div style="background: linear-gradient(135deg, #15803d 0%, #166534 100%); color: white; padding: 10px 16px; border-radius: 10px; box-shadow: 0 4px 15px rgba(22, 101, 52, 0.25);">
                    <div style="display:flex; align-items:center; gap:8px;">
                        <span style="width:10px; height:10px; border-radius:50%; background:#ef4444; display:inline-block; box-shadow:0 0 8px #ef4444;"></span>
                        <b style="font-size:1.0rem;">🔴 BROADCAST STATUS: LIVE NOW</b>
                    </div>
                    <div style="font-size:0.85rem; opacity:0.95; margin-top:2px;"><b>{session_topic}</b> (Host: {st.session_state.name} | Started: {started_at})</div>
                </div>
                """, unsafe_allow_html=True)
            with col_live_top_btn:
                col_btn_end, col_btn_rst = st.columns([1.2, 1])
                with col_btn_end:
                    with st.form("end_class_top_tch"):
                        btn_top = st.form_submit_button("🛑 End Live", type="primary", use_container_width=True)
                        if btn_top:
                            end_live_class()
                            st.warning("Live class ended.")
                            st.rerun()
                with col_btn_rst:
                    if st.button("🔄 Reset Studio", key="rst_top_tch", use_container_width=True, help="Force reset studio state"):
                        reset_studio_state()
                        st.success("Studio reset.")
                        st.rerun()

            st.markdown("<div style='height: 4px;'></div>", unsafe_allow_html=True)

            # Mobile In-Browser Lesson / Book Sharing
            render_live_board_manager(is_teacher=True)

            # 2. Render Live Classroom video player FIRST
            render_jitsi_classroom(
                domain=server,
                room_name=room_name,
                display_name=f"{st.session_state.name} (Teacher)",
                is_teacher=True
            )

            # 3. Big "🛑 End Live Class for All" button DIRECTLY BELOW the live video
            st.markdown("<div style='height: 10px;'></div>", unsafe_allow_html=True)
            with st.form("end_class_bottom_mobile_tch"):
                btn_stop = st.form_submit_button("🛑 End Live Class for All", type="primary", use_container_width=True)
                if btn_stop:
                    end_live_class()
                    st.warning("Live class ended. Students returned to offline waiting status.")
                    st.rerun()

            st.markdown("---")
            # Quick Stats & Google Drive folder button
            render_live_studio_hero_card(is_admin=False, show_stop_form=False)

        else:
            is_live, room_name, server = render_live_studio_hero_card(is_admin=False, show_stop_form=True)
            st.markdown("---")
            st.info("💡 To begin teaching, configure your topic and click **'Start Live Class Now'** above.")

        st.markdown("---")
        render_quick_recording_uploader(key_suffix="teacher_live_studio", title="1-Click Live Class Recording Publisher")
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
            st.link_button("📂 Open Google Drive Folder", DEFAULT_DRIVE_FOLDER_URL, type="primary", use_container_width=True)
            st.caption("Click to open the Google Drive folder in a new tab and drop your downloaded recording files directly.")
        with col_up_btn2:
            st.info(f"📁 Folder ID: `{DEFAULT_DRIVE_FOLDER_ID}`")

        render_quick_recording_uploader(key_suffix="teacher_rec_tab", title="Direct Video Uploader (Local Server + Google Drive Sync)")

        st.markdown("---")
        st.markdown("#### 🎬 Spotlight Individual Video Player")
        st.caption("You can also add an individual Google Drive or YouTube sharing link below to highlight specific lessons in the student player.")

        col_r1, col_r2 = st.columns([1.2, 1.8])

        with col_r1:
            st.markdown("### ➕ Publish Recorded Lecture")
            with st.form("add_rec_form", clear_on_submit=True):
                r_title = st.text_input("Lecture Title", placeholder="e.g. Urdu Grammar / Arabic Reading Lesson 1")
                r_subject = st.text_input("Subject", value="Urdu / Arabic", placeholder="Type any subject e.g. Urdu, Arabic, Tajweed, Grammar...", key="teacher_rec_sub")
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
                        render_recording_player(rec, is_student=False, key_suffix=f"tch_rec_{rec['id']}")
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
                                    trigger_cloud_sync(f"Created student account @{n_un}")

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
                            del_key = f"teacher_del_stu_{s['username']}"
                            if st.button("🗑️ Delete Permanently", key=del_key, use_container_width=True, type="primary"):
                                ok, msg = delete_user_account(
                                    s['username'],
                                    st.session_state.get('role', 'teacher'),
                                    st.session_state.get('username', '')
                                )
                                if ok:
                                    if is_supabase_active():
                                        supabase_request("DELETE", "users", params=f"id=eq.{s['id']}")
                                    st.success(msg)
                                    st.rerun()
                                else:
                                    st.error(msg)

    # Close connection cleanly
    try:
        conn.close()
    except Exception:
        pass


# ==========================================
# 8. STUDENT DASHBOARD
# ==========================================
def get_fragment_decorator(run_every_val="8s"):
    """
    Returns @st.fragment(run_every=...) if supported by Streamlit,
    otherwise gracefully returns a passthrough decorator.
    """
    if hasattr(st, "fragment"):
        try:
            return st.fragment(run_every=run_every_val)
        except (AttributeError, TypeError, Exception):
            pass
    if hasattr(st, "experimental_fragment"):
        try:
            return st.experimental_fragment(run_every=run_every_val)
        except (AttributeError, TypeError, Exception):
            pass
    def passthrough(fn):
        return fn
    return passthrough

@get_fragment_decorator(run_every="8s")
def render_student_top_status_fragment(student_username: str, student_name: str):
    """
    Auto-polls every 8s while the student has not joined the active video call.
    Provides instant visibility for:
      - Live class start by teacher (prominent pulsing red alert)
      - Important academy notices
      - Tuition fee reminders
    """
    # 1. Live Class Status Auto-Check
    live_sess = get_live_class_state()
    is_live = bool(live_sess.get('is_live', 0))
    if is_live:
        topic = live_sess.get('topic') or "Live Lecture"
        teacher = live_sess.get('host_teacher') or "Teacher"
        notes = live_sess.get('teacher_notes') or ""
        st.markdown(f"""
        <div style="background: linear-gradient(135deg, #ef4444 0%, #b91c1c 100%); color: white; padding: 14px 20px; border-radius: 12px; margin-bottom: 14px; box-shadow: 0 6px 20px rgba(220, 38, 38, 0.35); display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 10px;">
            <div style="display: flex; align-items: center; gap: 12px;">
                <span style="font-size: 1.6rem; line-height: 1;">🔴</span>
                <div>
                    <div style="font-weight: 800; font-size: 1.05rem; letter-spacing: 0.3px;">LIVE CLASS STARTED RIGHT NOW!</div>
                    <div style="font-size: 0.92rem; opacity: 0.95; margin-top: 2px;">
                        <b>{topic}</b> &bull; Conducted by <b>{teacher}</b> {f'— <i>{notes}</i>' if notes else ''}
                    </div>
                </div>
            </div>
            <div style="background: rgba(255, 255, 255, 0.25); border: 1px solid rgba(255,255,255,0.4); padding: 6px 14px; border-radius: 9999px; font-size: 0.82rem; font-weight: 700; letter-spacing: 0.5px;">
                🎥 SWITCH TO LIVE CLASSROOM TAB TO JOIN
            </div>
        </div>
        """, unsafe_allow_html=True)

    # 2. Top Notice Board
    notices = []
    if is_supabase_active():
        ok, rows = supabase_request("GET", "announcements", params="order=id.desc&limit=2&select=*")
        if ok:
            notices = rows

    if not notices:
        try:
            with get_db_connection() as conn_n:
                cn = conn_n.cursor()
                cn.execute("SELECT * FROM announcements ORDER BY id DESC LIMIT 2")
                notices = [dict(r) for r in cn.fetchall()]
        except Exception:
            pass

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

    # 3. Fee Dues Notification Banner
    try:
        with get_db_connection() as conn_f:
            cf = conn_f.cursor()
            cf.execute("SELECT * FROM fees WHERE student_username = ? AND status = 'Pending' ORDER BY due_date ASC", (student_username,))
            pending_fees = [dict(r) for r in cf.fetchall()]
    except Exception:
        pending_fees = []

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

def render_student_dashboard():
    conn = get_db()
    c = conn.cursor()

    st.markdown(f"""
    <div class="hero-banner">
        <h1>👋 Welcome, {st.session_state.name}!</h1>
        <p>Sister's Live Academy Student Portal | Roll No: @{st.session_state.username}</p>
    </div>
    """, unsafe_allow_html=True)

    # 1. Top Auto-Updating Live Status, Notices & Fee Banners
    # Polled every 8s via st.fragment when student is not inside live video call
    if not st.session_state.get("joined_live_class"):
        render_student_top_status_fragment(st.session_state.username, st.session_state.name)

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
        sess = get_live_class_state()
        is_live = bool(sess.get('is_live', 0))
        room_name = sess.get('room_name') or 'SistersLiveClass_MasterRoom'
        session_topic = sess.get('topic') or 'General Coaching Session'
        server = sess.get('server') or "jitsi.riot.im"
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

                col_w1, col_w2 = st.columns([2.5, 1.2])
                with col_w2:
                    with st.form("leave_waiting_lounge_top_form"):
                        if st.form_submit_button("🚪 Leave Waiting Lounge", use_container_width=True):
                            st.session_state.in_waiting_lounge = False
                            st.rerun()

                # In-Browser Shared Book Page Display
                render_live_board_manager(is_teacher=False)

                # Render embedded room for pre-class student discussion
                wl_room = next_class.get('room_name') or room_name
                render_jitsi_classroom(
                    domain=server,
                    room_name=wl_room,
                    display_name=f"{st.session_state.name} (Student - Waiting Lounge)",
                    is_teacher=False
                )

                st.markdown("<div style='height: 8px;'></div>", unsafe_allow_html=True)
                with st.form("leave_waiting_lounge_bottom_student"):
                    if st.form_submit_button("🚪 Leave Waiting Lounge", type="primary", use_container_width=True):
                        st.session_state.in_waiting_lounge = False
                        st.rerun()

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

                # In-Browser Shared Book Page Display
                render_live_board_manager(is_teacher=False)

                # Active in-app classroom embed with fullscreen button (no external redirects)
                render_jitsi_classroom(
                    domain=server,
                    room_name=room_name,
                    display_name=f"{st.session_state.name} (Student)",
                    is_teacher=False
                )

                st.markdown("<div style='height: 8px;'></div>", unsafe_allow_html=True)
                with st.form("leave_live_bottom_student"):
                    if st.form_submit_button("🚪 Leave Live Class", type="primary", use_container_width=True):
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
        existing_subs = []
        try:
            with get_db_connection() as conn_sub:
                c_sub = conn_sub.cursor()
                c_sub.execute("SELECT DISTINCT subject FROM recordings WHERE subject IS NOT NULL AND subject != ''")
                existing_subs = [row['subject'] for row in c_sub.fetchall()]
        except Exception:
            pass
        subj_filter_options = ["All Subjects", "Urdu / Arabic", "Urdu", "Arabic", "Tajweed", "Islamic Studies"]
        for s_opt in existing_subs:
            if s_opt not in subj_filter_options:
                subj_filter_options.append(s_opt)
        sub_filter = st.selectbox("Subject Filter", subj_filter_options, key="std_sub_filter")

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

                render_recording_player(r, is_student=True, key_suffix=f"std_rec_{r['id']}")
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
                d_sub = st.text_input("Subject", value="Urdu / Arabic", placeholder="Type any subject e.g. Urdu, Arabic, Tajweed, Grammar...", key="std_doubt_sub")
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
    # 1. Automatic persistent login restoration from st.query_params (pull-down/tab refresh safe)
    if not st.session_state.get("logged_in") or not st.session_state.get("username"):
        try:
            q_user = st.query_params.get("u")
            q_token = st.query_params.get("t")
            if q_user and q_token:
                valid_user = verify_session_token(q_user, q_token)
                if valid_user:
                    st.session_state.logged_in = True
                    st.session_state.username = valid_user['username']
                    st.session_state.role = valid_user['role']
                    st.session_state.name = valid_user['full_name']
                    st.session_state.user_id = valid_user.get('id')
        except Exception as e:
            logger.warning(f"Persistent login restoration error: {e}")

    if not st.session_state.get("logged_in") or not st.session_state.get("username"):
        render_login_screen()
        return

    with st.sidebar:
        st.markdown("""
        <div style="text-align: center; padding: 12px 0 16px 0;">
            <div style="display: inline-flex; align-items: center; justify-content: center; width: 48px; height: 48px; border-radius: 14px; background: linear-gradient(135deg, #4f46e5, #7c3aed); font-size: 1.8rem; box-shadow: 0 8px 16px rgba(79, 70, 229, 0.35); margin-bottom: 8px;">
                🎓
            </div>
            <h2 style="margin: 0; font-size: 1.2rem; font-weight: 800; color: #f8fafc; letter-spacing: -0.3px;">Sister's Live Academy</h2>
            <p style="color: #94a3b8; font-size: 0.8rem; margin: 3px 0 0 0; font-weight: 500;">Online Coaching & Live Classroom</p>
        </div>
        """, unsafe_allow_html=True)

        role_label = {
            'admin': '👑 Super Admin',
            'teacher': '👩‍🏫 Teacher',
            'student': '🎓 Student'
        }.get(st.session_state.role, str(st.session_state.role).capitalize())

        role_icon = {
            'admin': '👑',
            'teacher': '👩‍🏫',
            'student': '🎓'
        }.get(st.session_state.role, '👤')

        st.markdown(f"""
        <div style="background: linear-gradient(145deg, #1e293b 0%, #0f172a 100%); border: 1px solid #334155; border-radius: 14px; padding: 14px 16px; margin-bottom: 16px; box-shadow: 0 4px 18px rgba(0, 0, 0, 0.25);">
            <div style="display: flex; align-items: center; gap: 12px;">
                <div style="width: 42px; height: 42px; border-radius: 10px; background: linear-gradient(135deg, #6366f1 0%, #8b5cf6 100%); display: flex; align-items: center; justify-content: center; font-size: 1.35rem; color: white; box-shadow: 0 4px 10px rgba(99, 102, 241, 0.35); flex-shrink: 0;">
                    {role_icon}
                </div>
                <div style="overflow: hidden;">
                    <div style="font-weight: 700; color: #ffffff; font-size: 0.95rem; line-height: 1.2; text-overflow: ellipsis; white-space: nowrap; overflow: hidden;">{st.session_state.name}</div>
                    <div style="font-size: 0.78rem; color: #a5b4fc; font-weight: 600; margin-top: 2px;">{role_label}</div>
                    <div style="font-size: 0.72rem; color: #94a3b8; font-family: monospace;">@{st.session_state.username}</div>
                </div>
            </div>
        </div>
        """, unsafe_allow_html=True)

        # Storage indicator (Admin only)
        if st.session_state.role == 'admin':
            if is_supabase_active():
                st.success("🟢 Storage: Supabase Cloud Active")
            else:
                url_cfg, _ = get_supabase_config()
                if url_cfg:
                    st.warning("🟡 Storage: Local SQLite (Run SQL schema to activate Supabase)")
                else:
                    st.caption("Storage: **Local SQLite (classroom.db)**")

        # Server Selector (Default background is jitsi.riot.im; only exposed to Admin in collapsed expander)
        server_options = ["jitsi.riot.im", "meet.jit.si", "framatalk.org"]
        if st.session_state.jitsi_server not in server_options:
            st.session_state.jitsi_server = "jitsi.riot.im"

        if st.session_state.role == 'admin':
            with st.sidebar.expander("⚙️ Advanced Video Server Settings", expanded=False):
                curr_srv = st.session_state.jitsi_server
                sel_srv = st.selectbox(
                    "🌐 Video Server Selector",
                    server_options,
                    index=server_options.index(curr_srv),
                    help="Select embed-friendly server if one is congested.",
                    key="admin_sidebar_video_server"
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

                                    # Update token in query_params if active
                                    try:
                                        st.query_params["t"] = make_session_token(st.session_state.username, new_h)
                                    except Exception:
                                        pass

                                    st.success("✅ Password updated successfully!")
                        except Exception as e:
                            st.error(f"Error updating password: {e}")

        st.markdown("<div style='height: 8px;'></div>", unsafe_allow_html=True)
        with st.form("logout_form"):
            if st.form_submit_button("🚪 Sign Out", use_container_width=True):
                try:
                    st.query_params.clear()
                except Exception:
                    pass
                st.session_state.logged_in = False
                st.session_state.username = None
                st.session_state.role = None
                st.session_state.name = None
                st.session_state.live_joined = False
                st.session_state.joined_live_class = False
                st.rerun()

    render_top_quick_actions_bar()
    if st.session_state.role == 'admin':
        render_admin_dashboard()
    elif st.session_state.role == 'teacher':
        render_teacher_dashboard()
    else:
        render_student_dashboard()


if __name__ == "__main__":
    main()
