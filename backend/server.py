"""
VIDEO TRANSCRIBER BACKEND
Real-time processing with Socket.IO + AI Lecture Notes Generation
"""
from flask import Flask, request, jsonify, send_from_directory, Response
from flask_cors import CORS
from flask_socketio import SocketIO, emit
from werkzeug.utils import secure_filename
import os
# Fix Windows UTF-8 encoding for emoji support
os.environ['PYTHONIOENCODING'] = 'utf-8'
import json
from pathlib import Path
import subprocess
from datetime import datetime, timedelta
import cv2
import threading
import sqlite3
from contextlib import contextmanager
import hashlib
import time
import base64
from io import BytesIO
from PIL import Image
import shutil
import sys

# Load environment variables from .env file
from dotenv import load_dotenv
load_dotenv()  # This loads OPENROUTER_API_KEY from backend/.env

# OpenRouter API (no special package needed - using requests)
import requests as http_requests
import re
OPENROUTER_AVAILABLE = True

app = Flask(__name__)
CORS(app, resources={r"/*": {"origins": "*"}})
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='threading')

OUTPUT_DIR = Path("transcription_results")
OUTPUT_DIR.mkdir(exist_ok=True)
DB_PATH = OUTPUT_DIR / "transcriptions.db"

# Claude CLI temp directory for frame images
CLAUDE_TEMP_DIR = Path("claude_temp")
CLAUDE_TEMP_DIR.mkdir(exist_ok=True)

# App base URL for clickable timestamp links in PDFs
APP_BASE_URL = os.getenv('APP_BASE_URL', 'http://localhost:3000')

# API Provider Configuration: "claude_code" or "openrouter"
API_PROVIDER = os.getenv('API_PROVIDER', 'openrouter')

# OpenRouter API Configuration
OPENROUTER_API_KEY = os.getenv('OPENROUTER_API_KEY', '')
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
CLAUDE_MODEL_ID = "anthropic/claude-sonnet-4.5"

if API_PROVIDER == 'claude_code':
    NOTES_ENABLED = True
elif OPENROUTER_AVAILABLE and bool(OPENROUTER_API_KEY):
    NOTES_ENABLED = True
else:
    NOTES_ENABLED = False

if not NOTES_ENABLED:
    print("WARNING: Lecture notes generation is disabled.")
    print("   Option 1: Set API_PROVIDER=claude_code in .env (uses local Claude CLI)")
    print("   Option 2: Set OPENROUTER_API_KEY in .env (uses OpenRouter API)")

# Transcription engine: MLX (Apple Silicon / Metal GPU) — no CUDA on macOS
DEVICE = "mlx"
# Whisper model served by MLX. large-v3-turbo is fast + accurate on Apple GPU.
# Override with the WHISPER_MODEL env var (e.g. mlx-community/whisper-small-mlx for more speed).
WHISPER_MODEL = os.getenv("WHISPER_MODEL", "mlx-community/whisper-large-v3-turbo")

# Port 5000 is taken by AirPlay Receiver on macOS, so default to 5001
BACKEND_PORT = int(os.getenv("BACKEND_PORT", "5001"))

# yt-dlp installed into the venv lives next to the interpreter
_venv_yt_dlp = Path(sys.executable).parent / "yt-dlp"
YT_DLP_BIN = str(_venv_yt_dlp) if _venv_yt_dlp.exists() else "yt-dlp"

# Active processing jobs
active_jobs = {}
job_lock = threading.Lock()

# Guard against duplicate notes generation
notes_in_progress = set()
notes_in_progress_lock = threading.Lock()

def init_db():
    with get_db() as conn:
        conn.execute('''
            CREATE TABLE IF NOT EXISTS transcriptions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                video_id TEXT UNIQUE NOT NULL,
                url TEXT NOT NULL,
                title TEXT,
                language TEXT,
                duration REAL,
                frame_count INTEGER,
                segment_count INTEGER,
                status TEXT,
                folder_path TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                completed_at TIMESTAMP,
                auto_generate_notes BOOLEAN DEFAULT FALSE,
                notes_generated BOOLEAN DEFAULT FALSE,
                notes_en_path TEXT,
                notes_he_path TEXT,
                notes_generated_at TIMESTAMP
            )
        ''')
        conn.execute('''
            CREATE TABLE IF NOT EXISTS segments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                video_id TEXT NOT NULL,
                start_time REAL,
                end_time REAL,
                text TEXT,
                frame_path TEXT,
                FOREIGN KEY (video_id) REFERENCES transcriptions(video_id)
            )
        ''')
        conn.execute('''
            CREATE TABLE IF NOT EXISTS translated_segments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                video_id TEXT,
                language TEXT,
                segments_json TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(video_id, language)
            )
        ''')
        conn.execute('''
            CREATE TABLE IF NOT EXISTS notes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                video_id TEXT NOT NULL,
                note_type TEXT NOT NULL DEFAULT 'full',
                language TEXT NOT NULL,
                custom_prompt TEXT,
                filename TEXT NOT NULL,
                display_name TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')

        # Migrate existing databases to add notes columns if needed
        try:
            cursor = conn.cursor()
            cursor.execute("PRAGMA table_info(transcriptions)")
            columns = [row[1] for row in cursor.fetchall()]

            if 'thumbnail' not in columns:
                print("Migrating database: Adding thumbnail column...")
                conn.execute("ALTER TABLE transcriptions ADD COLUMN thumbnail TEXT")
                print("Thumbnail column added")

            if 'auto_generate_notes' not in columns:
                print("Migrating database: Adding lecture notes columns...")
                conn.execute("ALTER TABLE transcriptions ADD COLUMN auto_generate_notes BOOLEAN DEFAULT FALSE")
                conn.execute("ALTER TABLE transcriptions ADD COLUMN notes_generated BOOLEAN DEFAULT FALSE")
                conn.execute("ALTER TABLE transcriptions ADD COLUMN notes_en_path TEXT")
                conn.execute("ALTER TABLE transcriptions ADD COLUMN notes_he_path TEXT")
                conn.execute("ALTER TABLE transcriptions ADD COLUMN notes_generated_at TIMESTAMP")
                print("Database migration completed")

            if 'source_type' not in columns:
                print("Migrating database: Adding PDF support columns...")
                conn.execute("ALTER TABLE transcriptions ADD COLUMN source_type TEXT DEFAULT 'video'")
                conn.execute("ALTER TABLE transcriptions ADD COLUMN pdf_filename TEXT")
                print("PDF support columns added")

            # Migrate existing notes_en_path / notes_he_path into new notes table
            rows = conn.execute(
                'SELECT video_id, notes_en_path, notes_he_path, notes_generated_at FROM transcriptions WHERE notes_generated = 1'
            ).fetchall()
            for row in rows:
                vid = row['video_id']
                already = conn.execute('SELECT COUNT(*) as c FROM notes WHERE video_id=?', (vid,)).fetchone()['c']
                if already == 0:
                    if row['notes_en_path']:
                        conn.execute(
                            'INSERT INTO notes (video_id, note_type, language, filename, display_name, created_at) VALUES (?,?,?,?,?,?)',
                            (vid, 'full', 'en', row['notes_en_path'], 'Full Lecture Notes (English)', row['notes_generated_at'])
                        )
                    if row['notes_he_path']:
                        conn.execute(
                            'INSERT INTO notes (video_id, note_type, language, filename, display_name, created_at) VALUES (?,?,?,?,?,?)',
                            (vid, 'full', 'he', row['notes_he_path'], 'Full Lecture Notes (Hebrew)', row['notes_generated_at'])
                        )
                    if row['notes_en_path'] or row['notes_he_path']:
                        print(f"Migrated existing notes for {vid} into notes table")
        except Exception as e:
            print(f"Migration check failed: {e}")

@contextmanager
def get_db():
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()

def generate_video_id(url):
    return hashlib.md5(url.encode()).hexdigest()[:12]

def emit_log(video_id, message, progress=None):
    timestamp = datetime.now().strftime("%H:%M:%S")
    log_entry = f"[{timestamp}] {message}"

    # Handle Windows encoding issues with emojis
    try:
        print(log_entry)
    except UnicodeEncodeError:
        # Fallback: print without problematic characters
        print(log_entry.encode('ascii', 'ignore').decode('ascii'))

    with job_lock:
        if video_id in active_jobs:
            active_jobs[video_id]['logs'].append(log_entry)
            if progress is not None:
                active_jobs[video_id]['progress'] = progress

    socketio.emit('job_update', {
        'video_id': video_id,
        'log': log_entry,
        'progress': progress,
        'timestamp': timestamp
    })

def format_time(seconds):
    td = timedelta(seconds=seconds)
    h, r = divmod(td.seconds, 3600)
    m, s = divmod(r, 60)
    ms = td.microseconds // 1000
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"

def transcribe_audio(audio_path, lang, video_id):
    """Transcribe a WAV file on the Apple GPU via MLX.

    Returns a dict with 'language' and 'segments' (each segment has start/end/text),
    matching the structure the rest of the pipeline consumes. The MLX model is
    downloaded from HuggingFace on first use (~1.5 GB) and cached thereafter.
    """
    import mlx_whisper
    emit_log(video_id, f"🎤 Loading Whisper (MLX / Apple GPU): {WHISPER_MODEL}...", 45)
    kwargs = {"path_or_hf_repo": WHISPER_MODEL}
    if lang and lang != "auto":
        kwargs["language"] = lang
    emit_log(video_id, "🎤 Transcribing on Apple GPU...", 55)
    result = mlx_whisper.transcribe(str(audio_path), **kwargs)
    emit_log(video_id, "✅ Transcription complete", 80)
    return result

def parse_curl_command(curl_str):
    """
    Parse a cURL command (from browser DevTools) to extract URL and headers.
    Supports both Unix/bash style and Windows CMD style cURL commands.

    Returns: (url, headers_dict) or (None, None) if parsing fails

    Example Unix input:
        curl 'https://example.com/video.m3u8' \\
          -H 'cookie: session=abc123' \\
          -H 'referer: https://site.com/'

    Example Windows CMD input:
        curl ^"https://example.com/video.m3u8^" ^
          -H ^"cookie: session=abc123^" ^
          -H ^"referer: https://site.com/^"

    Example output:
        ('https://example.com/video.m3u8', {'Cookie': 'session=abc123', 'Referer': 'https://site.com/'})
    """
    try:
        # Step 1: Normalize Windows CMD format
        # Windows uses ^ for escaping and line continuation
        # First, handle escaped quotes: ^\^" becomes "
        curl_str = curl_str.replace(r'^\^"', '"').replace(r'^\^\'', "'")

        # Remove line continuations (both Unix \ and Windows ^)
        curl_str = curl_str.replace('\\\n', ' ').replace('^ ', ' ').replace('^', '')

        # Normalize whitespace
        curl_str = ' '.join(curl_str.split())

        # Step 2: Extract URL (first argument after curl)
        # Try to match URL in quotes first
        url_match = re.search(r'curl\s+"([^"]+)"', curl_str)
        if not url_match:
            url_match = re.search(r"curl\s+'([^']+)'", curl_str)
        if not url_match:
            # Try without quotes
            url_match = re.search(r'curl\s+(\S+)', curl_str)

        if not url_match:
            print("Could not extract URL from cURL command")
            return None, None

        url = url_match.group(1).strip("'\"")

        # Step 3: Extract all -H headers
        headers = {}

        # Try quoted headers first (most common)
        header_pattern = r'-H\s+"([^"]+)"'
        matches = list(re.finditer(header_pattern, curl_str, re.IGNORECASE))

        if not matches:
            # Try single quotes
            header_pattern = r"-H\s+'([^']+)'"
            matches = list(re.finditer(header_pattern, curl_str, re.IGNORECASE))

        for match in matches:
            header_content = match.group(1)

            # Split header into name and value
            if ':' in header_content:
                header_name, header_value = header_content.split(':', 1)
                header_name = header_name.strip()
                header_value = header_value.strip()

                # Capitalize header names properly (e.g., "user-agent" -> "User-Agent")
                header_name = '-'.join(word.capitalize() for word in header_name.split('-'))
                headers[header_name] = header_value

        print(f"✅ Parsed cURL: URL={url[:50]}..., Headers={len(headers)}")
        return url, headers

    except Exception as e:
        print(f"❌ Error parsing cURL command: {e}")
        import traceback
        traceback.print_exc()
        return None, None

def emit_notes_log(video_id, message, stage, progress=None):
    """Emit progress logs for lecture notes generation"""
    timestamp = datetime.now().strftime("%H:%M:%S")
    log_entry = f"[{timestamp}] {message}"

    # Handle Windows encoding issues with emojis
    try:
        print(log_entry)
    except UnicodeEncodeError:
        # Fallback: print without problematic characters
        print(log_entry.encode('ascii', 'ignore').decode('ascii'))

    socketio.emit('notes_progress', {
        'video_id': video_id,
        'stage': stage,
        'message': message,
        'progress': progress,
        'timestamp': timestamp
    })

def sample_frames_for_notes(video_file, segments, duration, max_frames=3):
    """
    Intelligently sample frames for lecture notes generation
    Returns list of (timestamp, base64_image) tuples
    """
    sampled_frames = []

    try:
        cap = cv2.VideoCapture(str(video_file))
        fps = cap.get(cv2.CAP_PROP_FPS)

        # Calculate timestamps to sample
        timestamps = []

        # Always include first and last frame
        timestamps.append(0.0)
        if duration > 5:
            timestamps.append(duration - 1)

        # Add evenly distributed frames in between
        middle_frames = max_frames - 2  # Excluding first and last
        if middle_frames > 0 and duration > 10:
            interval = duration / (middle_frames + 1)
            for i in range(1, middle_frames + 1):
                timestamps.append(i * interval)

        # Sort and remove duplicates
        timestamps = sorted(set(timestamps))[:max_frames]

        # Extract frames and convert to base64
        for ts in timestamps:
            cap.set(cv2.CAP_PROP_POS_FRAMES, int(ts * fps))
            ret, frame = cap.read()
            if ret:
                # Resize frame to reduce API costs (800x600 is reasonable)
                height, width = frame.shape[:2]
                target_width = 600
                target_height = int(height * (target_width / width))
                resized = cv2.resize(frame, (target_width, target_height))

                # Convert to RGB (OpenCV uses BGR)
                rgb_frame = cv2.cvtColor(resized, cv2.COLOR_BGR2RGB)

                # Convert to PIL Image
                pil_image = Image.fromarray(rgb_frame)

                # Convert to base64 JPEG
                buffer = BytesIO()
                pil_image.save(buffer, format='JPEG', quality=60)
                img_base64 = base64.b64encode(buffer.getvalue()).decode('utf-8')

                sampled_frames.append((ts, img_base64))

        cap.release()
        try:
            print(f"✓ Sampled {len(sampled_frames)} frames for notes generation")
        except UnicodeEncodeError:
            print(f"[OK] Sampled {len(sampled_frames)} frames for notes generation")

    except Exception as e:
        error_msg = str(e).encode('ascii', 'ignore').decode('ascii')
        try:
            print(f"✗ Error sampling frames: {error_msg}")
        except UnicodeEncodeError:
            print(f"[ERROR] Error sampling frames: {error_msg}")

    return sampled_frames


def sample_pdf_pages(pdf_path, max_pages=5):
    """
    Sample representative pages from a PDF and render them as JPEG images.
    Returns list of (page_number_1indexed, base64_image) tuples.
    """
    sampled_pages = []

    try:
        import fitz  # PyMuPDF
        doc = fitz.open(str(pdf_path))
        total_pages = len(doc)

        # Build page indices: always first, always last (if >1), distribute rest evenly
        indices = [0]
        if total_pages > 1:
            indices.append(total_pages - 1)

        middle_slots = max_pages - 2
        if middle_slots > 0 and total_pages > 2:
            interval = (total_pages - 1) / (middle_slots + 1)
            for i in range(1, middle_slots + 1):
                indices.append(int(round(i * interval)))

        indices = sorted(set(indices))[:max_pages]

        for page_idx in indices:
            page = doc[page_idx]
            # Render at ~600px width
            page_width = page.rect.width
            zoom = 600.0 / page_width if page_width > 0 else 1.0
            mat = fitz.Matrix(zoom, zoom)
            pix = page.get_pixmap(matrix=mat)

            pil_image = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)

            buffer = BytesIO()
            pil_image.save(buffer, format='JPEG', quality=60)
            img_base64 = base64.b64encode(buffer.getvalue()).decode('utf-8')

            sampled_pages.append((page_idx + 1, img_base64))  # 1-indexed page number

        doc.close()
        try:
            print(f"✓ Sampled {len(sampled_pages)} pages from PDF ({total_pages} total)")
        except UnicodeEncodeError:
            print(f"[OK] Sampled {len(sampled_pages)} pages from PDF ({total_pages} total)")

    except Exception as e:
        error_msg = str(e).encode('ascii', 'ignore').decode('ascii')
        try:
            print(f"✗ Error sampling PDF pages: {error_msg}")
        except UnicodeEncodeError:
            print(f"[ERROR] Error sampling PDF pages: {error_msg}")

    return sampled_pages


def call_claude_code_cli(text_prompt, sampled_frames, video_id=None,
                         allowed_tools="Read", max_turns="2", json_schema=None,
                         system_prompt_suffix=None):
    """
    Call the local Claude Code CLI (claude -p) to generate notes.
    Saves frames as temp JPGs so Claude can Read them, then pipes the prompt via stdin.

    Args:
        allowed_tools: Tool name(s) to allow (e.g. "Read"), or None to disallow all tools.
        max_turns: Max agentic turns for the CLI.
        json_schema: If provided, a dict schema passed via --json-schema to enforce structured output.
        system_prompt_suffix: Custom system prompt suffix. If None, uses a default.

    Returns:
        The raw response text, or raises an exception.
    """
    frame_dir = CLAUDE_TEMP_DIR / (video_id or "temp")
    frame_dir.mkdir(exist_ok=True, parents=True)
    saved_paths = []

    try:
        # Save base64 frames as JPG files
        if sampled_frames:
            for i, (ts, base64_img) in enumerate(sampled_frames):
                img_path = frame_dir / f"frame_{i:03d}_{float(ts):.2f}s.jpg"
                img_data = base64.b64decode(base64_img)
                with open(img_path, 'wb') as f:
                    f.write(img_data)
                saved_paths.append(str(img_path.resolve()))

        # Build prompt with image file references
        full_prompt = ""
        if saved_paths:
            full_prompt += "I have saved lecture video frames as images. Please Read each file to see them:\n\n"
            for p in saved_paths:
                # Use forward slashes for consistency
                full_prompt += f"  {p.replace(chr(92), '/')}\n"
            full_prompt += "\nAfter reading the frames, use them along with the transcript below to generate the notes.\n\n"

        full_prompt += text_prompt

        # Run claude CLI
        claude_bin = shutil.which("claude")
        if not claude_bin:
            raise FileNotFoundError("claude not on PATH")
        if system_prompt_suffix is None:
            if json_schema:
                system_prompt_suffix = "You MUST output ONLY the raw JSON object/array requested. No explanations, no summaries, no markdown. Start your response with { or [ and end with } or ]. If the output would be very long, still output the complete JSON — never truncate or summarize it."
            else:
                system_prompt_suffix = "Output ONLY the content requested. No explanations, no conversational text, no summaries."

        cmd = [
            claude_bin, "-p",
            "--output-format", "json",
            "--max-turns", max_turns,
            "--append-system-prompt",
            system_prompt_suffix
        ]
        if allowed_tools:
            cmd += ["--allowedTools", allowed_tools]
        if json_schema:
            cmd += ["--json-schema", json.dumps(json_schema)]

        print(f"[Claude CLI] Running claude -p with {len(saved_paths)} frame images...")
        print(f"[Claude CLI] Prompt length: {len(full_prompt)} chars")

        result = subprocess.run(
            cmd,
            input=full_prompt,
            capture_output=True,
            text=True,
            timeout=600,
            encoding='utf-8',
            errors='replace'
        )

        if result.returncode != 0:
            stderr_preview = (result.stderr or "")[:500]
            raise RuntimeError(f"Claude CLI exited with code {result.returncode}: {stderr_preview}")

        # Parse the JSON envelope: {"type":"result","result":"<text>"}
        try:
            envelope = json.loads(result.stdout)
        except json.JSONDecodeError:
            # Maybe it returned plain text
            print(f"[Claude CLI] Warning: output is not JSON envelope, using raw stdout")
            return result.stdout.strip()

        if json_schema and isinstance(envelope, dict) and 'structured_output' in envelope:
            return json.dumps(envelope['structured_output'])
        elif isinstance(envelope, dict) and 'result' in envelope:
            return envelope['result']
        else:
            # Unexpected structure, return raw
            print(f"[Claude CLI] Warning: unexpected JSON structure, keys={list(envelope.keys()) if isinstance(envelope, dict) else type(envelope)}")
            return result.stdout.strip()

    except FileNotFoundError:
        raise RuntimeError(
            "Claude CLI ('claude') not found. Make sure Claude Code is installed and 'claude' is on your PATH."
        )
    except subprocess.TimeoutExpired:
        raise RuntimeError("Claude CLI timed out after 600 seconds.")
    finally:
        # Clean up temp frame files
        try:
            if frame_dir.exists():
                shutil.rmtree(frame_dir)
        except Exception as cleanup_err:
            print(f"[Claude CLI] Warning: failed to clean up {frame_dir}: {cleanup_err}")





def ensure_browser_compatible_video(video_file, video_id):
    """Probe video codec/profile/pix_fmt and re-encode if not browser-compatible.
    Returns the (possibly re-encoded) video file path."""
    video_file = Path(video_file)
    folder = video_file.parent
    temp_faststart = folder / "video_faststart.mp4"
    try:
        probe_cmd = [
            'ffprobe', '-v', 'error', '-select_streams', 'v:0',
            '-show_entries', 'stream=codec_name,profile,pix_fmt',
            '-of', 'json',
            str(video_file)
        ]
        probe_result = subprocess.run(probe_cmd, capture_output=True, text=True, timeout=30)
        import json as _json
        probe_data = _json.loads(probe_result.stdout)
        stream = probe_data.get('streams', [{}])[0]
        video_codec = stream.get('codec_name', '').lower()
        video_profile = stream.get('profile', '').lower()
        video_pix_fmt = stream.get('pix_fmt', '').lower()

        emit_log(video_id, f"📊 Video probe: codec={video_codec}, profile={video_profile}, pix_fmt={video_pix_fmt}", None)
        print(f"[ffprobe] codec={video_codec}, profile={video_profile}, pix_fmt={video_pix_fmt}")

        needs_reencode = False
        reencode_reason = ""

        if video_codec not in ('h264', 'avc1', 'avc'):
            needs_reencode = True
            reencode_reason = f"non-H.264 codec ({video_codec})"
        elif 'high 10' in video_profile or 'hi10' in video_profile or 'high 4:4:4' in video_profile:
            needs_reencode = True
            reencode_reason = f"10-bit H.264 profile ({video_profile})"
        elif video_pix_fmt and video_pix_fmt not in ('yuv420p', 'yuvj420p', 'nv12', 'nv21'):
            needs_reencode = True
            reencode_reason = f"unsupported pixel format ({video_pix_fmt})"

        if needs_reencode:
            emit_log(video_id, f"🔄 Re-encoding: {reencode_reason}...", None)
            print(f"[ffmpeg] Re-encoding: {reencode_reason}")
            faststart_cmd = [
                'ffmpeg', '-i', str(video_file),
                '-c:v', 'libx264', '-preset', 'fast', '-crf', '23',
                '-pix_fmt', 'yuv420p',
                '-c:a', 'aac', '-b:a', '128k',
                '-movflags', '+faststart',
                str(temp_faststart), '-y', '-loglevel', 'error'
            ]
        else:
            faststart_cmd = [
                'ffmpeg', '-i', str(video_file),
                '-c', 'copy', '-movflags', '+faststart',
                str(temp_faststart), '-y', '-loglevel', 'error'
            ]

        subprocess.run(faststart_cmd, check=True, timeout=1800, encoding='utf-8', errors='replace')
        os.replace(str(temp_faststart), str(video_file))
        emit_log(video_id, "✅ Video optimized for streaming", None)
    except Exception as e:
        emit_log(video_id, f"⚠️ Video optimization failed: {e}", None)
        print(f"[ffmpeg] Video optimization error: {e}")
        if temp_faststart.exists():
            temp_faststart.unlink()
    return video_file


def process_uploaded_video(video_path, original_filename, lang, interval, video_id, auto_generate_notes=False, title=None):
    """Process an uploaded video file (skips download step)"""
    try:
        with job_lock:
            active_jobs[video_id] = {
                'url': f'upload:{original_filename}',
                'status': 'processing',
                'progress': 0,
                'logs': [],
                'started_at': datetime.now().isoformat()
            }

        socketio.emit('job_started', {'video_id': video_id, 'url': f'upload:{original_filename}'})

        folder = OUTPUT_DIR / video_id
        emit_log(video_id, f"🎯 Processing uploaded file: {original_filename}", 10)

        # Default title to filename without extension
        if not title:
            title = os.path.splitext(original_filename)[0]

        # Update database
        with get_db() as conn:
            conn.execute('''
                INSERT OR REPLACE INTO transcriptions
                (video_id, url, title, language, status, folder_path, auto_generate_notes)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            ''', (video_id, f'upload:{original_filename}', title, lang, 'processing', str(folder), auto_generate_notes))

        # Skip download - file already saved at video_path
        video_file = Path(video_path)
        emit_log(video_id, "✅ File uploaded successfully", 30)

        # Ensure video is browser-compatible (probe + re-encode if needed)
        video_file = ensure_browser_compatible_video(video_file, video_id)

        # Extract audio
        audio_file = folder / "audio.wav"
        emit_log(video_id, "🎵 Extracting audio...", 35)
        cmd = ['ffmpeg', '-i', str(video_file), '-ar', '16000', '-ac', '1',
               '-c:a', 'pcm_s16le', str(audio_file), '-y', '-loglevel', 'error']
        subprocess.run(cmd, check=True, encoding='utf-8', errors='replace')
        emit_log(video_id, "✅ Audio extracted", 40)

        # Transcribe (Apple GPU via MLX)
        result = transcribe_audio(audio_file, lang, video_id)

        # Save transcripts
        emit_log(video_id, "💾 Saving transcripts...", 85)

        with open(folder / "transcript.json", 'w', encoding='utf-8') as f:
            json.dump(result, f, indent=2, ensure_ascii=False)

        with open(folder / "subtitles.srt", 'w', encoding='utf-8') as f:
            for i, seg in enumerate(result["segments"], 1):
                start = format_time(seg["start"])
                end = format_time(seg["end"])
                f.write(f"{i}\n{start} --> {end}\n{seg['text'].strip()}\n\n")

        with open(folder / "transcript.txt", 'w', encoding='utf-8') as f:
            for seg in result["segments"]:
                f.write(f"[{format_time(seg['start'])} -> {format_time(seg['end'])}] {seg['text'].strip()}\n")

        # Insert segments into database
        with get_db() as conn:
            for seg in result["segments"]:
                frame_name = f"frame_{seg['start']:.2f}s.jpg"
                conn.execute('''
                    INSERT INTO segments (video_id, start_time, end_time, text, frame_path)
                    VALUES (?, ?, ?, ?, ?)
                ''', (video_id, seg["start"], seg["end"], seg["text"], frame_name))

        emit_log(video_id, "✅ Transcripts saved", 90)

        # Extract frames
        emit_log(video_id, "🎞️ Extracting frames...", 92)
        frames_dir = folder / "frames"
        frames_dir.mkdir(exist_ok=True)

        cap = cv2.VideoCapture(str(video_file))
        fps = cap.get(cv2.CAP_PROP_FPS)
        duration = cap.get(cv2.CAP_PROP_FRAME_COUNT) / fps

        if interval > 0:
            timestamps = list(range(0, int(duration), interval))
        else:
            timestamps = [seg["start"] for seg in result["segments"]]

        for timestamp in timestamps:
            frame_num = int(timestamp * fps)
            cap.set(cv2.CAP_PROP_POS_FRAMES, frame_num)
            ret, frame = cap.read()
            if ret:
                cv2.imwrite(str(frames_dir / f"frame_{timestamp:06.2f}s.jpg"), frame)

        cap.release()
        frame_count = len(list(frames_dir.glob("*.jpg")))
        emit_log(video_id, f"✅ Extracted {frame_count} frames", 95)

        # Generate thumbnail from first extracted frame
        thumbnail_name = None
        extracted_frames = sorted(frames_dir.glob("*.jpg"))
        if extracted_frames:
            thumbnail_dest = folder / "thumbnail.jpg"
            shutil.copy2(str(extracted_frames[0]), str(thumbnail_dest))
            thumbnail_name = "thumbnail.jpg"

        # Update database with complete metadata
        with get_db() as conn:
            conn.execute('''
                UPDATE transcriptions
                SET duration=?, frame_count=?, segment_count=?, status=?, thumbnail=?, completed_at=CURRENT_TIMESTAMP
                WHERE video_id=?
            ''', (duration, frame_count, len(result["segments"]), 'completed', thumbnail_name, video_id))

        emit_log(video_id, "✅ Processing complete!", 100)

        with job_lock:
            if video_id in active_jobs:
                active_jobs[video_id]['status'] = 'completed'
                active_jobs[video_id]['progress'] = 100

        socketio.emit('job_completed', {'video_id': video_id})

        # Auto-generate lecture notes if requested
        if auto_generate_notes and NOTES_ENABLED:
            emit_log(video_id, "📝 Auto-generating lecture notes...", None)
            generate_lecture_notes(video_id)

    except Exception as e:
        error_msg = f"❌ Error: {str(e)}"
        emit_log(video_id, error_msg, None)

        with get_db() as conn:
            conn.execute('UPDATE transcriptions SET status=? WHERE video_id=?', ('failed', video_id))

        with job_lock:
            if video_id in active_jobs:
                active_jobs[video_id]['status'] = 'failed'
                active_jobs[video_id]['error'] = str(e)

        socketio.emit('job_failed', {'video_id': video_id, 'error': str(e)})
        print(f"Error processing uploaded video: {e}")
        import traceback
        traceback.print_exc()

def process_video(url, lang, interval, video_id, auto_generate_notes=False):
    try:
        with job_lock:
            active_jobs[video_id] = {
                'url': url,
                'status': 'processing',
                'progress': 0,
                'logs': [],
                'started_at': datetime.now().isoformat()
            }
        
        socketio.emit('job_started', {'video_id': video_id, 'url': url})
        
        folder = OUTPUT_DIR / video_id
        folder.mkdir(exist_ok=True)
        
        emit_log(video_id, f"🎯 Starting video {video_id[:8]}...", 5)
        
        # Update database
        with get_db() as conn:
            conn.execute('''
                INSERT OR REPLACE INTO transcriptions
                (video_id, url, language, status, folder_path, auto_generate_notes)
                VALUES (?, ?, ?, ?, ?, ?)
            ''', (video_id, url, lang, 'processing', str(folder), auto_generate_notes))
        
        # Download using yt-dlp (better at handling CDN protections and HLS streams)
        video_file = folder / "video.mp4"
        emit_log(video_id, "⬇️ Downloading video...", 10)

        # Check if input is a cURL command (from browser DevTools)
        parsed_url = url
        custom_headers = {}

        if url.strip().startswith('curl'):
            emit_log(video_id, "📋 Detected cURL command, parsing headers...", 12)
            parsed_url, custom_headers = parse_curl_command(url)
            if parsed_url:
                emit_log(video_id, f"✅ Extracted {len(custom_headers)} headers from cURL", 14)
                url = parsed_url  # Update URL for database
            else:
                emit_log(video_id, "⚠️ Failed to parse cURL, using as plain URL", 13)

        # Build yt-dlp command with custom headers if available
        cmd = [
            YT_DLP_BIN,
            '-f', 'bestvideo[vcodec^=avc1][height<=1080]+bestaudio[acodec^=mp4a]/bestvideo[vcodec^=avc1]+bestaudio/best[ext=mp4]/best',
            '--merge-output-format', 'mp4',
            '--no-playlist',
            '--no-warnings',
            '-o', str(video_file)
        ]

        # Add custom headers from cURL
        for header_name, header_value in custom_headers.items():
            cmd.extend(['--add-header', f'{header_name}: {header_value}'])

        cmd.append(parsed_url)

        try:
            result = subprocess.run(cmd, check=True, timeout=600, capture_output=True, encoding='utf-8', errors='replace')
            emit_log(video_id, "✅ Video downloaded", 30)
        except FileNotFoundError:
            # yt-dlp not found, fallback to ffmpeg with custom headers
            emit_log(video_id, "⚠️ yt-dlp not found, trying ffmpeg...", 15)

            # Build headers string for ffmpeg (format: "Name: value\r\nName2: value2")
            headers_str = ""
            if custom_headers:
                headers_str = "\r\n".join([f"{name}: {value}" for name, value in custom_headers.items()])
            else:
                # Default headers if no cURL provided
                headers_str = "Referer: https://www.google.com/"

            cmd = [
                'ffmpeg',
                '-user_agent', custom_headers.get('User-Agent', 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'),
                '-headers', headers_str + '\r\n',
                '-i', parsed_url,
                '-c', 'copy',
                '-bsf:a', 'aac_adtstoasc',
                str(video_file),
                '-y',
                '-loglevel', 'error'
            ]
            try:
                subprocess.run(cmd, check=True, timeout=600, encoding='utf-8', errors='replace')
                emit_log(video_id, "✅ Video downloaded", 30)
            except subprocess.CalledProcessError as e:
                error_msg = "❌ Download failed. Try using the full cURL command from your browser's DevTools."
                emit_log(video_id, error_msg, None)
                raise Exception(error_msg)
        except subprocess.CalledProcessError as e:
            error_msg = f"❌ Download failed (yt-dlp error). Please check if the URL is valid and accessible."
            emit_log(video_id, error_msg, None)
            print(f"yt-dlp stderr: {e.stderr if hasattr(e, 'stderr') else 'No stderr'}")
            raise Exception(error_msg)

        # Ensure video is browser-compatible (probe + re-encode if needed)
        video_file = ensure_browser_compatible_video(video_file, video_id)

        # Extract audio
        audio_file = folder / "audio.wav"
        emit_log(video_id, "🎵 Extracting audio...", 35)
        cmd = ['ffmpeg', '-i', str(video_file), '-ar', '16000', '-ac', '1', 
               '-c:a', 'pcm_s16le', str(audio_file), '-y', '-loglevel', 'error']
        subprocess.run(cmd, check=True, encoding='utf-8', errors='replace')
        emit_log(video_id, "✅ Audio extracted", 40)
        
        # Transcribe (Apple GPU via MLX)
        result = transcribe_audio(audio_file, lang, video_id)

        # Save transcripts
        emit_log(video_id, "💾 Saving transcripts...", 85)
        
        with open(folder / "transcript.json", 'w', encoding='utf-8') as f:
            json.dump(result, f, indent=2, ensure_ascii=False)
        
        with open(folder / "subtitles.srt", 'w', encoding='utf-8') as f:
            for i, seg in enumerate(result["segments"], 1):
                start = format_time(seg["start"])
                end = format_time(seg["end"])
                f.write(f"{i}\n{start} --> {end}\n{seg['text'].strip()}\n\n")
        
        with open(folder / "transcript.txt", 'w', encoding='utf-8') as f:
            for seg in result["segments"]:
                f.write(f"[{format_time(seg['start'])} -> {format_time(seg['end'])}] {seg['text'].strip()}\n")
        
        emit_log(video_id, "✅ Transcripts saved", 90)
        
        # Extract frames
        emit_log(video_id, "🎞️ Extracting frames...", 92)
        frames_dir = folder / "frames"
        frames_dir.mkdir(exist_ok=True)
        
        cap = cv2.VideoCapture(str(video_file))
        fps = cap.get(cv2.CAP_PROP_FPS)
        duration = cap.get(cv2.CAP_PROP_FRAME_COUNT) / fps
        
        if interval > 0:
            timestamps = list(range(0, int(duration), interval))
        else:
            timestamps = [seg["start"] for seg in result["segments"]]
        
        for ts in timestamps:
            cap.set(cv2.CAP_PROP_POS_FRAMES, int(ts * fps))
            ret, frame = cap.read()
            if ret:
                cv2.imwrite(str(frames_dir / f"frame_{ts:.2f}s.jpg"), frame)
        
        cap.release()
        emit_log(video_id, f"✅ Extracted {len(timestamps)} frames", 95)
        
        # Save to database
        with get_db() as conn:
            conn.execute('''
                UPDATE transcriptions 
                SET duration=?, frame_count=?, segment_count=?, status=?, completed_at=?
                WHERE video_id=?
            ''', (duration, len(timestamps), len(result["segments"]), 'completed', 
                  datetime.now(), video_id))
            
            for seg in result["segments"]:
                frame_name = f"frame_{seg['start']:.2f}s.jpg"
                conn.execute('''
                    INSERT INTO segments (video_id, start_time, end_time, text, frame_path)
                    VALUES (?, ?, ?, ?, ?)
                ''', (video_id, seg["start"], seg["end"], seg["text"], frame_name))
        
        emit_log(video_id, f"✅ COMPLETE!", 100)

        with job_lock:
            active_jobs[video_id]['status'] = 'completed'
            active_jobs[video_id]['completed_at'] = datetime.now().isoformat()

        socketio.emit('job_completed', {
            'video_id': video_id,
            'segments': len(result["segments"]),
            'frames': len(timestamps),
            'duration': duration
        })

        # Generate lecture notes if requested
        if auto_generate_notes and NOTES_ENABLED:
            emit_log(video_id, "📚 Auto-generating lecture notes...", None)
            threading.Thread(
                target=generate_lecture_notes,
                args=(video_id,),
                daemon=True
            ).start()

    except Exception as e:
        emit_log(video_id, f"❌ ERROR: {str(e)}", None)
        with job_lock:
            if video_id in active_jobs:
                active_jobs[video_id]['status'] = 'failed'
                active_jobs[video_id]['error'] = str(e)
        
        with get_db() as conn:
            conn.execute('UPDATE transcriptions SET status=? WHERE video_id=?', ('failed', video_id))
        
        socketio.emit('job_failed', {'video_id': video_id, 'error': str(e)})

@app.route('/api/device-info')
def device_info():
    return jsonify({
        'device': 'mlx',
        'name': 'Apple Silicon (MLX / Metal)',
        'model': WHISPER_MODEL
    })

@app.route('/api/upload', methods=['POST'])
def upload_video():
    """Handle direct video file uploads"""
    if 'video' not in request.files:
        return jsonify({'success': False, 'error': 'No video file provided'}), 400

    file = request.files['video']
    if file.filename == '':
        return jsonify({'success': False, 'error': 'No file selected'}), 400

    # Get form parameters
    lang = request.form.get('language', 'en')
    interval = int(request.form.get('interval', 5))
    auto_generate_notes = request.form.get('autoGenerateNotes', 'false').lower() == 'true'

    # Get title (default to filename without extension)
    filename = secure_filename(file.filename)
    title = request.form.get('title', '').strip() or os.path.splitext(file.filename)[0]

    # Generate video ID from filename
    video_id = generate_video_id(f"upload:{filename}")

    # Create folder and save file
    folder = OUTPUT_DIR / video_id
    folder.mkdir(exist_ok=True)
    video_path = folder / "video.mp4"

    try:
        file.save(str(video_path))
        try:
            print(f"✅ Uploaded file saved: {video_path}")
        except UnicodeEncodeError:
            print(f"[SUCCESS] Uploaded file saved: {video_path}")

        # Start processing in background (skip download step)
        threading.Thread(
            target=process_uploaded_video,
            args=(str(video_path), filename, lang, interval, video_id, auto_generate_notes, title),
            daemon=True
        ).start()

        return jsonify({'success': True, 'job_ids': [video_id], 'notes_enabled': NOTES_ENABLED})

    except Exception as e:
        error_msg = str(e).encode('ascii', 'ignore').decode('ascii')
        try:
            print(f"❌ Upload error: {error_msg}")
        except UnicodeEncodeError:
            print(f"[ERROR] Upload error: {error_msg}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/upload-pdf', methods=['POST'])
def upload_pdf():
    """Handle PDF file uploads for note generation."""
    if 'pdf' not in request.files:
        return jsonify({'success': False, 'error': 'No PDF file provided'}), 400

    file = request.files['pdf']
    if file.filename == '':
        return jsonify({'success': False, 'error': 'No file selected'}), 400

    # Validate PDF extension
    if not file.filename.lower().endswith('.pdf'):
        return jsonify({'success': False, 'error': 'File must be a PDF'}), 400

    # Check file size (30MB limit — Claude's limit is 32MB)
    file.seek(0, 2)
    file_size = file.tell()
    file.seek(0)
    if file_size > 30 * 1024 * 1024:
        return jsonify({'success': False, 'error': 'PDF must be under 30MB'}), 400

    filename = secure_filename(file.filename)
    title = request.form.get('title', '').strip() or os.path.splitext(file.filename)[0]
    lang = request.form.get('language', 'en')

    video_id = generate_video_id(f"pdf:{filename}")

    folder = OUTPUT_DIR / video_id
    folder.mkdir(exist_ok=True)
    pdf_path = folder / "source.pdf"

    try:
        file.save(str(pdf_path))
        print(f"PDF uploaded: {pdf_path} ({file_size / 1024 / 1024:.1f}MB)")

        with get_db() as conn:
            conn.execute('''
                INSERT OR REPLACE INTO transcriptions
                (video_id, url, title, language, status, folder_path, source_type, pdf_filename, completed_at)
                VALUES (?, ?, ?, ?, 'completed', ?, 'pdf', ?, CURRENT_TIMESTAMP)
            ''', (video_id, f"pdf:{filename}", title, lang, str(folder), file.filename))

        return jsonify({'success': True, 'video_id': video_id, 'notes_enabled': NOTES_ENABLED})

    except Exception as e:
        print(f"PDF upload error: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/process', methods=['POST'])
def start_process():
    data = request.json
    urls = data.get('urls', [])
    lang = data.get('language', 'en')
    interval = data.get('interval', 5)
    auto_generate_notes = data.get('autoGenerateNotes', False)

    job_ids = []
    for url in urls:
        video_id = generate_video_id(url)
        job_ids.append(video_id)
        threading.Thread(
            target=process_video,
            args=(url, lang, interval, video_id, auto_generate_notes),
            daemon=True
        ).start()

    return jsonify({'success': True, 'job_ids': job_ids, 'notes_enabled': NOTES_ENABLED})

@app.route('/api/jobs')
def get_jobs():
    with job_lock:
        return jsonify(list(active_jobs.values()))

@app.route('/api/job/<video_id>')
def get_job(video_id):
    with job_lock:
        job = active_jobs.get(video_id)
    if job:
        return jsonify(job)
    
    # Check database
    with get_db() as conn:
        video = conn.execute('SELECT * FROM transcriptions WHERE video_id=?', (video_id,)).fetchone()
    if video:
        return jsonify(dict(video))
    
    return jsonify({'error': 'Job not found'}), 404

@app.route('/api/history')
def get_history():
    with get_db() as conn:
        rows = conn.execute('''
            SELECT * FROM transcriptions 
            ORDER BY created_at DESC 
            LIMIT 50
        ''').fetchall()
    return jsonify([dict(row) for row in rows])

@app.route('/api/result/<video_id>')
def get_result(video_id):
    with get_db() as conn:
        video = conn.execute('SELECT * FROM transcriptions WHERE video_id=?', (video_id,)).fetchone()
        segments = conn.execute('''
            SELECT * FROM segments WHERE video_id=? ORDER BY start_time
        ''', (video_id,)).fetchall()
    
    if not video:
        return jsonify({'error': 'Not found'}), 404
    
    return jsonify({
        'video': dict(video),
        'segments': [dict(s) for s in segments]
    })

@app.route('/api/generate-notes/<video_id>', methods=['POST'])
def generate_notes_route(video_id):
    """Trigger lecture notes generation for a specific video.

    Request body (optional):
        languages: List of languages to generate ('en', 'he', or both). Default: ['en', 'he']
        note_type: 'full', 'definitions', or 'custom'. Default: 'full'
        custom_prompt: Custom instruction text (only used when note_type='custom')
    """
    if not NOTES_ENABLED:
        return jsonify({
            'success': False,
            'error': 'Notes generation disabled (API key not set)'
        }), 400

    with get_db() as conn:
        video = conn.execute('SELECT * FROM transcriptions WHERE video_id=?', (video_id,)).fetchone()
        if not video:
            return jsonify({'success': False, 'error': 'Video not found'}), 404
        if video['status'] != 'completed':
            return jsonify({'success': False, 'error': 'Video transcription not complete'}), 400

    data = request.json or {}
    languages = data.get('languages', ['en', 'he'])
    note_type = data.get('note_type', 'full')
    custom_prompt = data.get('custom_prompt', None)

    if not isinstance(languages, list) or not all(lang in ['en', 'he'] for lang in languages):
        return jsonify({'success': False, 'error': 'Invalid languages parameter'}), 400

    if note_type not in ('full', 'summary', 'definitions', 'custom'):
        return jsonify({'success': False, 'error': 'Invalid note_type parameter'}), 400

    if note_type == 'custom' and not custom_prompt:
        return jsonify({'success': False, 'error': 'custom_prompt is required when note_type is custom'}), 400

    with notes_in_progress_lock:
        if video_id in notes_in_progress:
            return jsonify({'success': False, 'error': 'Notes generation already in progress'}), 409
        notes_in_progress.add(video_id)

    threading.Thread(
        target=generate_lecture_notes,
        args=(video_id, languages, note_type, custom_prompt),
        daemon=True
    ).start()

    return jsonify({'success': True, 'message': 'Notes generation started', 'languages': languages, 'note_type': note_type})


def generate_single_language_notes(video_id, language, transcript_text, sampled_frames, progress_offset=0, note_type='full', custom_prompt=None):
    """Generate lecture notes for a single language using the HTML+Playwright pipeline."""
    from html_notes import render_html_to_pdf
    from html_notes.prompt_builder import build_html_prompt

    lang_name = "English" if language == 'en' else "Hebrew"

    provider_label = "Claude Code CLI" if API_PROVIDER == 'claude_code' else "OpenRouter"
    emit_notes_log(video_id, f"Calling {provider_label} for {lang_name} (HTML)...", f"calling_api_{language}", progress_offset + 5)

    content_parts = build_html_prompt(transcript_text, language, sampled_frames, note_type=note_type, custom_prompt=custom_prompt)

    if API_PROVIDER == 'claude_code':
        # --- Claude Code CLI path ---
        try:
            text_prompt = content_parts[-1]['text']
            response_text = call_claude_code_cli(
                text_prompt, sampled_frames, video_id=video_id,
                system_prompt_suffix="Output ONLY the HTML content requested. No explanations, no conversational text, no markdown code fences. Start directly with the first HTML element."
            )
            emit_notes_log(video_id, f"{lang_name} Claude CLI response received", f"parsing_{language}", progress_offset + 25)
        except Exception as e:
            emit_notes_log(video_id, f"{lang_name} Claude CLI error: {str(e)}", "failed", 0)
            print(f"Claude CLI error: {e}")
            return None
    else:
        # --- OpenRouter HTTP path (with retry) ---
        response_text = None
        max_attempts = 2
        for attempt in range(1, max_attempts + 1):
            try:
                if attempt > 1:
                    emit_notes_log(video_id, f"Retrying {lang_name} API call (attempt {attempt}/{max_attempts})...", f"calling_api_{language}", progress_offset + 5)
                    time.sleep(3)

                response = http_requests.post(
                    url=f"{OPENROUTER_BASE_URL}/chat/completions",
                    headers={
                        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
                        "HTTP-Referer": "http://localhost:3000",
                        "X-Title": "Video Transcriber Pro",
                        "Content-Type": "application/json"
                    },
                    json={
                        "model": CLAUDE_MODEL_ID,
                        "max_tokens": 16000,
                        "temperature": 0.3,
                        "messages": [{
                            "role": "user",
                            "content": content_parts
                        }]
                    },
                    timeout=180
                )

                if response.status_code != 200:
                    print(f"{lang_name} API error (attempt {attempt}): {response.status_code} - {response.text[:300]}")
                    if attempt < max_attempts:
                        continue
                    emit_notes_log(video_id, f"{lang_name} API error: {response.status_code}", "failed", 0)
                    return None

                result = response.json()
                response_text = result['choices'][0]['message']['content']
                emit_notes_log(video_id, f"{lang_name} API response received", f"parsing_{language}", progress_offset + 25)
                break

            except http_requests.exceptions.Timeout:
                print(f"{lang_name} API timeout (attempt {attempt})")
                if attempt < max_attempts:
                    continue
                emit_notes_log(video_id, f"{lang_name} API timeout after {max_attempts} attempts", "failed", 0)
                return None
            except Exception as e:
                print(f"{lang_name} API error (attempt {attempt}): {e}")
                if attempt < max_attempts:
                    continue
                emit_notes_log(video_id, f"{lang_name} API error: {str(e)}", "failed", 0)
                return None

        if response_text is None:
            emit_notes_log(video_id, f"{lang_name} API returned no content", "failed", 0)
            return None

    # Extract HTML body from response — strip code fences if present
    html_body = response_text.strip()
    if html_body.startswith('```'):
        html_body = html_body[html_body.index('\n') + 1:]
    if html_body.endswith('```'):
        html_body = html_body[:-3].strip()

    if not html_body:
        emit_notes_log(video_id, f"{lang_name} response was empty", "failed", 0)
        return None

    emit_notes_log(video_id, f"Rendering {lang_name} PDF (Playwright)...", f"rendering_{language}", progress_offset + 30)

    # Render PDF with timestamped filename
    timestamp_str = datetime.now().strftime('%Y%m%d_%H%M%S')
    lang_code = language.upper()
    output_name = f"notes_{note_type}_{lang_code}_{timestamp_str}.pdf"
    folder = OUTPUT_DIR / video_id
    folder.mkdir(parents=True, exist_ok=True)
    output_path = folder / output_name

    pdf_path = render_html_to_pdf(
        html_body, str(output_path),
        language=language, video_id=video_id, base_url=APP_BASE_URL
    )

    if not pdf_path:
        emit_notes_log(video_id, f"{lang_name} PDF rendering failed", "failed", 0)
        return None

    # Build display name
    type_labels = {'full': 'Full Lecture Notes', 'summary': 'Summary', 'definitions': 'Key Definitions & Theorems', 'custom': 'Custom Notes'}
    lang_labels = {'en': 'English', 'he': 'Hebrew'}
    display_name = f"{type_labels.get(note_type, note_type)} ({lang_labels.get(language, language)})"

    # Insert into notes table
    with get_db() as conn:
        conn.execute(
            'INSERT INTO notes (video_id, note_type, language, custom_prompt, filename, display_name) VALUES (?,?,?,?,?,?)',
            (video_id, note_type, language, custom_prompt if note_type == 'custom' else None, output_name, display_name)
        )

    emit_notes_log(video_id, f"{lang_name} notes generated", f"completed_{language}", progress_offset + 45)
    return pdf_path


def generate_single_language_notes_pdf(video_id, language, pdf_base64, progress_offset=0, note_type='full', custom_prompt=None, sampled_pages=None):
    """Generate notes from a PDF source for a single language using the HTML+Playwright pipeline."""
    from html_notes import render_html_to_pdf
    from html_notes.prompt_builder import build_html_prompt_for_pdf

    lang_name = "English" if language == 'en' else "Hebrew"

    provider_label = "Claude Code CLI" if API_PROVIDER == 'claude_code' else "OpenRouter"
    emit_notes_log(video_id, f"Calling {provider_label} for {lang_name} (PDF source, HTML output)...", f"calling_api_{language}", progress_offset + 5)

    content_parts = build_html_prompt_for_pdf(pdf_base64, language, note_type=note_type, custom_prompt=custom_prompt, sampled_pages=sampled_pages)

    if API_PROVIDER == 'claude_code':
        # Claude Code CLI path — pass PDF as document block
        try:
            text_prompt = content_parts[-1]['text']
            # For CLI, we pass the text prompt; PDF reading is handled by the CLI's Read tool
            response_text = call_claude_code_cli(
                text_prompt, [], video_id=video_id,
                system_prompt_suffix="Output ONLY the HTML content requested. No explanations, no conversational text, no markdown code fences. Start directly with the first HTML element."
            )
            emit_notes_log(video_id, f"{lang_name} Claude CLI response received", f"parsing_{language}", progress_offset + 25)
        except Exception as e:
            emit_notes_log(video_id, f"{lang_name} Claude CLI error: {str(e)}", "failed", 0)
            print(f"Claude CLI error: {e}")
            return None
    else:
        # OpenRouter HTTP path (with retry) — send document content block
        response_text = None
        max_attempts = 2
        for attempt in range(1, max_attempts + 1):
            try:
                if attempt > 1:
                    emit_notes_log(video_id, f"Retrying {lang_name} API call (attempt {attempt}/{max_attempts})...", f"calling_api_{language}", progress_offset + 5)
                    time.sleep(3)

                response = http_requests.post(
                    url=f"{OPENROUTER_BASE_URL}/chat/completions",
                    headers={
                        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
                        "HTTP-Referer": "http://localhost:3000",
                        "X-Title": "Video Transcriber Pro",
                        "Content-Type": "application/json"
                    },
                    json={
                        "model": CLAUDE_MODEL_ID,
                        "max_tokens": 16000,
                        "temperature": 0.3,
                        "messages": [{
                            "role": "user",
                            "content": content_parts
                        }]
                    },
                    timeout=300  # PDFs can be large; allow more time
                )

                if response.status_code != 200:
                    print(f"{lang_name} API error (attempt {attempt}): {response.status_code} - {response.text[:300]}")
                    if attempt < max_attempts:
                        continue
                    emit_notes_log(video_id, f"{lang_name} API error: {response.status_code}", "failed", 0)
                    return None

                result = response.json()
                response_text = result['choices'][0]['message']['content']
                emit_notes_log(video_id, f"{lang_name} API response received", f"parsing_{language}", progress_offset + 25)
                break

            except http_requests.exceptions.Timeout:
                print(f"{lang_name} API timeout (attempt {attempt})")
                if attempt < max_attempts:
                    continue
                emit_notes_log(video_id, f"{lang_name} API timeout after {max_attempts} attempts", "failed", 0)
                return None
            except Exception as e:
                print(f"{lang_name} API error (attempt {attempt}): {e}")
                if attempt < max_attempts:
                    continue
                emit_notes_log(video_id, f"{lang_name} API error: {str(e)}", "failed", 0)
                return None

        if response_text is None:
            emit_notes_log(video_id, f"{lang_name} API returned no content", "failed", 0)
            return None

    # Extract HTML body from response — strip code fences if present
    html_body = response_text.strip()
    if html_body.startswith('```'):
        html_body = html_body[html_body.index('\n') + 1:]
    if html_body.endswith('```'):
        html_body = html_body[:-3].strip()

    if not html_body:
        emit_notes_log(video_id, f"{lang_name} response was empty", "failed", 0)
        return None

    emit_notes_log(video_id, f"Rendering {lang_name} PDF (Playwright)...", f"rendering_{language}", progress_offset + 30)

    # Render PDF with timestamped filename
    timestamp_str = datetime.now().strftime('%Y%m%d_%H%M%S')
    lang_code = language.upper()
    output_name = f"notes_{note_type}_{lang_code}_{timestamp_str}.pdf"
    folder = OUTPUT_DIR / video_id
    folder.mkdir(parents=True, exist_ok=True)
    output_path = folder / output_name

    pdf_path = render_html_to_pdf(
        html_body, str(output_path),
        language=language, video_id=video_id, base_url=APP_BASE_URL
    )

    if not pdf_path:
        emit_notes_log(video_id, f"{lang_name} PDF rendering failed", "failed", 0)
        return None

    # Build display name
    type_labels = {'full': 'Full Notes', 'summary': 'Summary', 'definitions': 'Key Definitions & Theorems', 'custom': 'Custom Notes'}
    lang_labels = {'en': 'English', 'he': 'Hebrew'}
    display_name = f"{type_labels.get(note_type, note_type)} ({lang_labels.get(language, language)})"

    # Insert into notes table
    with get_db() as conn:
        conn.execute(
            'INSERT INTO notes (video_id, note_type, language, custom_prompt, filename, display_name) VALUES (?,?,?,?,?,?)',
            (video_id, note_type, language, custom_prompt if note_type == 'custom' else None, output_name, display_name)
        )

    emit_notes_log(video_id, f"{lang_name} notes generated", f"completed_{language}", progress_offset + 45)
    return pdf_path


def generate_lecture_notes(video_id, languages=None, note_type='full', custom_prompt=None):
    """Generate AI-powered lecture notes using the HTML+Playwright pipeline."""
    if languages is None:
        languages = ['en', 'he']

    if not NOTES_ENABLED:
        with notes_in_progress_lock:
            notes_in_progress.discard(video_id)
        emit_notes_log(video_id, "Notes generation disabled", "failed", 0)
        return False

    try:
        generate_en = 'en' in languages
        generate_he = 'he' in languages

        lang_desc = []
        if generate_en:
            lang_desc.append("English")
        if generate_he:
            lang_desc.append("Hebrew")
        lang_str = " and ".join(lang_desc)

        type_labels = {'full': 'Full Lecture Notes', 'summary': 'Summary', 'definitions': 'Key Definitions & Theorems', 'custom': 'Custom Notes'}
        type_label = type_labels.get(note_type, note_type)

        emit_notes_log(video_id, f"Starting {lang_str} {type_label} generation (HTML pipeline)...", "starting", 2)

        with get_db() as conn:
            video = conn.execute('SELECT * FROM transcriptions WHERE video_id=?', (video_id,)).fetchone()
            if not video:
                emit_notes_log(video_id, "Video not found", "failed", 0)
                return False

            segments = conn.execute('SELECT * FROM segments WHERE video_id=? ORDER BY start_time', (video_id,)).fetchall()

        source_type = video['source_type'] if video['source_type'] else 'video'
        folder = OUTPUT_DIR / video_id

        # Calculate offsets
        if generate_en and generate_he:
            en_offset, he_offset = 10, 55
        elif generate_en:
            en_offset, he_offset = 10, 0
        else:
            en_offset, he_offset = 0, 10

        en_pdf = None
        he_pdf = None

        if source_type == 'pdf':
            # --- PDF source path ---
            pdf_file = folder / "source.pdf"
            if not pdf_file.exists():
                emit_notes_log(video_id, "Source PDF file not found", "failed", 0)
                return False

            emit_notes_log(video_id, "Reading source PDF...", "preparing", 5)
            pdf_base64 = base64.b64encode(pdf_file.read_bytes()).decode('utf-8')

            emit_notes_log(video_id, "Sampling PDF page images...", "sampling_pages", 7)
            sampled_pages = sample_pdf_pages(pdf_file, max_pages=5)

            if generate_en:
                en_pdf = generate_single_language_notes_pdf(video_id, 'en', pdf_base64, en_offset, note_type=note_type, custom_prompt=custom_prompt, sampled_pages=sampled_pages)
            if generate_he:
                he_pdf = generate_single_language_notes_pdf(video_id, 'he', pdf_base64, he_offset, note_type=note_type, custom_prompt=custom_prompt, sampled_pages=sampled_pages)
        else:
            # --- Video source path (existing flow) ---
            video_file = folder / "video.mp4"

            if not video_file.exists():
                emit_notes_log(video_id, "Video file not found", "failed", 0)
                return False

            # Build transcript
            emit_notes_log(video_id, "Preparing transcript...", "preparing", 5)
            transcript_text = "\n\n".join([
                f"[{format_time(seg['start_time'])} -> {format_time(seg['end_time'])}]\n{seg['text']}"
                for seg in segments
            ])

            # Sample frames
            emit_notes_log(video_id, "Sampling key frames...", "sampling_frames", 8)
            duration = float(video['duration']) if video['duration'] else 60
            sampled_frames = sample_frames_for_notes(video_file, segments, duration)
            if not sampled_frames:
                sampled_frames = []

            if generate_en:
                en_pdf = generate_single_language_notes(video_id, 'en', transcript_text, sampled_frames, en_offset, note_type=note_type, custom_prompt=custom_prompt)
            if generate_he:
                he_pdf = generate_single_language_notes(video_id, 'he', transcript_text, sampled_frames, he_offset, note_type=note_type, custom_prompt=custom_prompt)

        # Check results
        en_saved = en_pdf is not None
        he_saved = he_pdf is not None

        if not en_saved and not he_saved:
            emit_notes_log(video_id, "Failed to generate any PDF", "failed", 0)
            socketio.emit('notes_completed', {
                'video_id': video_id,
                'has_english': False,
                'has_hebrew': False,
                'failed': True
            })
            return False

        # Mark that notes have been generated on the transcriptions row
        with get_db() as conn:
            conn.execute(
                'UPDATE transcriptions SET notes_generated=1, notes_generated_at=? WHERE video_id=?',
                (datetime.now(), video_id)
            )

        success_parts = []
        if en_saved:
            success_parts.append("English")
        if he_saved:
            success_parts.append("Hebrew")

        emit_notes_log(video_id, f"{' and '.join(success_parts)} {type_label} generated!", "done", 100)
        socketio.emit('notes_completed', {
            'video_id': video_id,
            'has_english': en_saved,
            'has_hebrew': he_saved
        })
        return True

    except Exception as e:
        emit_notes_log(video_id, f"Error: {str(e)}", "failed", 0)
        socketio.emit('notes_completed', {
            'video_id': video_id,
            'has_english': False,
            'has_hebrew': False,
            'failed': True
        })
        import traceback
        traceback.print_exc()
        return False
    finally:
        with notes_in_progress_lock:
            notes_in_progress.discard(video_id)


@app.route('/api/notes/<video_id>')
def get_notes_info(video_id):
    """Get information about generated notes for a video"""
    with get_db() as conn:
        video = conn.execute('SELECT * FROM transcriptions WHERE video_id=?', (video_id,)).fetchone()
        if not video:
            return jsonify({'error': 'Video not found'}), 404

        notes_rows = conn.execute(
            'SELECT id, note_type, language, custom_prompt, filename, display_name, created_at FROM notes WHERE video_id=? ORDER BY created_at DESC',
            (video_id,)
        ).fetchall()

        notes = []
        for row in notes_rows:
            notes.append({
                'id': row['id'],
                'note_type': row['note_type'],
                'language': row['language'],
                'custom_prompt': row['custom_prompt'],
                'filename': row['filename'],
                'display_name': row['display_name'],
                'created_at': row['created_at']
            })

        return jsonify({
            'video_id': video_id,
            'notes_enabled': NOTES_ENABLED,
            'notes': notes
        })


@app.route('/api/note/<int:note_id>', methods=['DELETE'])
def delete_note(note_id):
    """Delete a single note by its ID"""
    try:
        with get_db() as conn:
            note = conn.execute('SELECT * FROM notes WHERE id=?', (note_id,)).fetchone()
            if not note:
                return jsonify({'success': False, 'error': 'Note not found'}), 404

            video_id = note['video_id']
            filename = note['filename']

            # Delete file from disk
            pdf_file = OUTPUT_DIR / video_id / filename
            if pdf_file.exists():
                pdf_file.unlink()

            # Delete DB row
            conn.execute('DELETE FROM notes WHERE id=?', (note_id,))

        return jsonify({'success': True, 'message': 'Note deleted'})

    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/video/<video_id>', methods=['DELETE'])
def delete_video(video_id):
    """Delete a video and all associated files and database records"""
    try:
        # Check if video exists
        with get_db() as conn:
            video = conn.execute('SELECT * FROM transcriptions WHERE video_id=?', (video_id,)).fetchone()
            if not video:
                return jsonify({'success': False, 'error': 'Video not found'}), 404

            # Delete from database
            conn.execute('DELETE FROM notes WHERE video_id=?', (video_id,))
            conn.execute('DELETE FROM segments WHERE video_id=?', (video_id,))
            conn.execute('DELETE FROM transcriptions WHERE video_id=?', (video_id,))
            conn.commit()

        # Delete files from disk
        video_dir = OUTPUT_DIR / video_id
        if video_dir.exists():
            import shutil
            shutil.rmtree(video_dir)
            print(f"Deleted directory: {video_dir}")

        return jsonify({'success': True, 'message': 'Video deleted successfully'})

    except Exception as e:
        print(f"Error deleting video {video_id}: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/video/<video_id>', methods=['PUT'])
def update_video(video_id):
    """Update video metadata (e.g. title)"""
    data = request.json
    if not data or 'title' not in data:
        return jsonify({'success': False, 'error': 'Missing title'}), 400

    with get_db() as conn:
        video = conn.execute('SELECT * FROM transcriptions WHERE video_id=?', (video_id,)).fetchone()
        if not video:
            return jsonify({'success': False, 'error': 'Video not found'}), 404
        conn.execute('UPDATE transcriptions SET title=? WHERE video_id=?', (data['title'], video_id))

    return jsonify({'success': True})

@app.route('/api/files/<video_id>/<path:filename>')
def serve_file(video_id, filename):
    return send_from_directory(str(OUTPUT_DIR / video_id), filename, conditional=True)

@app.route('/api/translate/<video_id>', methods=['POST'])
def translate_transcript(video_id):
    """Translate transcript segments to a target language using Claude CLI."""
    data = request.json
    if not data or 'language' not in data:
        return jsonify({'success': False, 'error': 'Missing language'}), 400

    language_name = data['language']

    # Check cache first
    with get_db() as conn:
        cached = conn.execute(
            'SELECT segments_json FROM translated_segments WHERE video_id=? AND language=?',
            (video_id, language_name)
        ).fetchone()
        if cached:
            return jsonify({'success': True, 'language': language_name, 'segments': json.loads(cached['segments_json'])})

        # Load original segments
        rows = conn.execute(
            'SELECT start_time, end_time, text FROM segments WHERE video_id=? ORDER BY start_time',
            (video_id,)
        ).fetchall()
        if not rows:
            return jsonify({'success': False, 'error': 'No segments found'}), 404

    segments_list = [{'start_time': r['start_time'], 'end_time': r['end_time'], 'text': r['text']} for r in rows]

    socketio.emit('notes_progress', {
        'video_id': video_id,
        'stage': 'translating',
        'message': f'Translating transcript to {language_name}...',
        'progress': 30
    })

    try:
        prompt = f"""Translate these transcript segments to {language_name}.
Return ONLY a JSON array where each element has: "start_time", "end_time", "text" (translated).
Keep start_time and end_time identical. Translate only the "text" field.
Do not wrap the output in markdown code fences.

Segments:
{json.dumps(segments_list)}"""

        translation_schema = {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "start_time": {"type": "number"},
                    "end_time": {"type": "number"},
                    "text": {"type": "string"}
                },
                "required": ["start_time", "end_time", "text"]
            }
        }
        result_text = call_claude_code_cli(prompt, sampled_frames=[], video_id=video_id,
                                           json_schema=translation_schema, allowed_tools=None, max_turns="2")

        # Parse JSON array from response
        try:
            translated = json.loads(result_text)
        except (json.JSONDecodeError, ValueError):
            # Fallback: try to find JSON array in the response
            json_match = re.search(r'\[.*\]', result_text, re.DOTALL)
            if not json_match:
                return jsonify({'success': False, 'error': 'Failed to parse translation result'}), 500
            translated = json.loads(json_match.group())

        # Cache in database
        with get_db() as conn:
            conn.execute(
                'INSERT OR REPLACE INTO translated_segments (video_id, language, segments_json) VALUES (?, ?, ?)',
                (video_id, language_name, json.dumps(translated))
            )

        socketio.emit('notes_progress', {
            'video_id': video_id,
            'stage': 'done',
            'message': f'Translation to {language_name} complete!',
            'progress': 100
        })

        return jsonify({'success': True, 'language': language_name, 'segments': translated})

    except Exception as e:
        print(f"Translation error: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/translations/<video_id>', methods=['GET'])
def get_translations(video_id):
    """Return list of available cached translations for a video."""
    with get_db() as conn:
        rows = conn.execute(
            'SELECT language FROM translated_segments WHERE video_id=?',
            (video_id,)
        ).fetchall()
    return jsonify({'translations': [r['language'] for r in rows]})

if __name__ == '__main__':
    print("="*70)
    print("VIDEO TRANSCRIBER BACKEND")
    print("="*70)
    print(f"Device: {DEVICE.upper()} (Apple Silicon / Metal)")
    print(f"Whisper Model: {WHISPER_MODEL}")
    print(f"Database: {DB_PATH}")
    print(f"Server: http://localhost:{BACKEND_PORT}")
    if NOTES_ENABLED:
        if API_PROVIDER == 'claude_code':
            notes_status = "ENABLED via Claude Code CLI"
        else:
            notes_status = "ENABLED via OpenRouter"
    else:
        notes_status = "DISABLED (no provider configured)"
    print(f"Lecture Notes: {notes_status}")
    print("="*70)

    init_db()
    socketio.run(app, host='0.0.0.0', port=BACKEND_PORT, debug=False, allow_unsafe_werkzeug=True)