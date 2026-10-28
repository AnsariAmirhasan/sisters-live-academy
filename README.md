# 🎓 Sister's Live Academy - Online Live Classroom & Coaching Web App

A production-ready, bug-free, mobile-responsive **Online Live Classroom & Coaching Web App** built with Python and Streamlit. Designed specifically for **1 Teacher and 10+ Students**, featuring seamless video conferencing via Jitsi Meet, interactive whiteboarding, in-browser 1-click recording, Google Drive study library, persistent doubt-solving, notice board, and automated attendance logging.

---

## 🌟 Key Features

### 1. 🔐 Role-Based Authentication & User Management
- **Auto-seeded Database:** Ready to use out of the box with SQLite (`classroom.db`).
- **Teacher Account:** Full admin privileges, moderator controls, student account management.
- **Student Accounts:** Restricted student portal with live class attendance logging.
- **Teacher Controls:** Add new students, reset passwords, block/suspend access, or delete accounts.

### 2. 🎥 Live Classroom Engine (Jitsi Meet + Interactive Whiteboard)
- **Teacher Broadcast Control:** Launch and end live classes with 1 click.
- **Full Moderator Toolbar:** Mic, camera, screen sharing, tile view, mute everyone, whiteboard, and security.
- **Student Gatekeeper:** Students can only enter when the class is marked **LIVE**; otherwise, a clean offline banner with announcements is shown.
- **Restricted Student Toolbar:** Students cannot accidentally mute others or hijack screen sharing.
- **Built-in Browser Screen & Audio Recorder:** 1-click recording tool using HTML5 `navigator.mediaDevices.getDisplayMedia` + `MediaRecorder` directly in the Teacher dashboard. Automatically downloads `.webm` class recordings to the teacher's PC.

### 3. 📚 Google Drive Recordings & Study Material Library
- **Automatic Link Converter:** Converts standard Google Drive sharing URLs (`https://drive.google.com/file/d/FILE_ID/view...`) into:
  - An embeddable in-app preview player (`https://drive.google.com/file/d/FILE_ID/preview`)
  - A direct download button (`https://drive.google.com/uc?export=download&id=FILE_ID`)
- Also supports YouTube unlisted links and external URLs.
- Students can search, filter by subject, watch in-app, or download for offline revision.

### 4. 📢 Notice Board & Alerts
- Teacher can post high-priority alerts (`Important`, `Exam`, `Holiday`, `Normal`).
- Prominently displayed at the top of the Student Portal.

### 5. ❓ Live Doubt Box & Discussion
- Students can post doubts anytime (even when video class is off).
- Teacher can write explanations, mark doubts as **Answered**, or clear resolved items.

### 6. 📊 Automated Attendance System
- Student attendance is logged automatically with date, timestamp, and topic as soon as they click **Join Live Class**.
- Teacher can view real-time logs, filter historical attendance, and export attendance records as a **CSV file**.

---

## 🔑 Default Login Credentials

| Role | Username | Password | Notes |
| :--- | :--- | :--- | :--- |
| **Teacher / Admin** | `teacher` | `teacher123` | Full controls, moderator, recording, attendance |
| **Student 1** | `student1` | `pass123` | Active student account |
| **Student 2** | `student2` | `pass123` | Active student account |
| **Students 3 to 10** | `student3` ... `student10` | `pass123` | Active student accounts |

*(Additional students can be created directly from the Teacher dashboard).*

---

## 📂 Project Structure

```
live-classroom/
├── app.py              # Complete application code (Frontend, Backend, DB, CSS)
├── classroom.db        # Persistent SQLite database (auto-generated)
├── requirements.txt    # Python dependencies
├── .gitignore          # Git exclusions
└── README.md           # Documentation & deployment guide
```

---

## 🚀 How to Run Locally

1. **Clone or navigate to the directory:**
   ```bash
   cd live-classroom
   ```

2. **(Optional) Create and activate a virtual environment:**
   ```bash
   python3 -m venv venv
   source venv/bin/activate    # On Windows: venv\Scripts\activate
   ```

3. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

4. **Start the Streamlit application:**
   ```bash
   streamlit run app.py
   ```
   Open your browser at `http://localhost:8501`.

---

## ☁️ How to Deploy to Streamlit Community Cloud (Free)

1. **Create a GitHub Repository:**
   - Go to [github.com/new](https://github.com/new) and create a new repository (e.g., `sisters-live-academy`).
   - Run in your local terminal:
     ```bash
     git init
     git add .
     git commit -m "Initial commit - Sister's Live Academy"
     git branch -M main
     git remote add origin https://github.com/YOUR_USERNAME/sisters-live-academy.git
     git push -u origin main
     ```

2. **Deploy on Streamlit Community Cloud:**
   - Visit [share.streamlit.io](https://share.streamlit.io) and log in with your GitHub account.
   - Click **"New app"**.
   - Select your repository (`sisters-live-academy`), branch (`main`), and set **Main file path** to `app.py`.
   - Click **"Deploy!"**.

3. **(Optional) Configure Supabase Cloud Database:**
   If you wish to switch from local SQLite to Supabase:
   - In your Streamlit Cloud App settings, navigate to **Settings -> Secrets** and paste:
     ```toml
     SUPABASE_URL = "https://your-project.supabase.co"
     SUPABASE_KEY = "your-anon-or-service-key"
     ```
   The app will automatically detect these credentials and use cloud storage. Without these secrets, it defaults seamlessly to persistent local SQLite without crashing.

---

## 📱 Mobile Browser Compatibility
The app includes responsive CSS and media queries tested for modern mobile browsers (Google Chrome for Android, Safari for iOS). Camera and microphone access require standard browser permissions over HTTPS (automatically provided by Streamlit Cloud).
