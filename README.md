# Video Extractor (Transcriber Pro)

Transcribe lecture videos on your Mac's GPU and turn them into AI-generated lecture notes as PDFs.

- **Transcription**: Whisper (`large-v3-turbo`) running locally on Apple Silicon via [MLX](https://github.com/ml-explore/mlx). It's free, offline, and fast.
- **Lecture notes and translation**: Claude Sonnet, through [OpenRouter](https://openrouter.ai) or your local [Claude Code](https://claude.com/claude-code) CLI.
- **UI**: Next.js, used in the browser or wrapped in Electron.

> **Requirements:** a Mac with Apple Silicon (M1 or later). Intel Macs, Windows, and Linux aren't supported, because transcription uses MLX.

---

## Features

- Upload a video (any format FFmpeg can read) and get a transcript (`.txt`, `.srt`, `.json`) with timestamps
- Live progress in the browser while it processes
- Frame snapshots at a chosen interval, shown next to the transcript
- Clickable timestamps that jump to that point in the video
- AI lecture notes (full notes, summary, key definitions, or a custom prompt) rendered as a styled PDF, with math, code, and Hebrew/RTL support
- Translate a transcript into another language
- Upload a PDF (e.g. slides) and generate notes from it
- A library of everything you've processed, stored locally in SQLite

---

## Prerequisites

Install [Homebrew](https://brew.sh) if you don't have it, then:

```bash
brew install node python@3.11 ffmpeg
```

| Tool | Version |
|---|---|
| macOS on Apple Silicon | M1 or later |
| Node.js | 18+ |
| Python | 3.10 – 3.12 (3.11 recommended) |
| FFmpeg | any recent version |

For lecture notes you also need **one** of:
- an **OpenRouter API key** ([get one here](https://openrouter.ai/keys), pay-as-you-go), or
- **Claude Code** installed and logged in, so the `claude` command works in your terminal.

Transcription works without either.

---

## Setup

### 1. Clone and install the frontend

```bash
git clone https://github.com/SohelDaniel/video-extractor.git
cd video-extractor
npm install
```

### 2. Set up the Python backend

```bash
cd backend
python3.11 -m venv venv
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
playwright install chromium     # used to render notes to PDF
cd ..
```

### 3. Configure

```bash
cp backend/.env.example backend/.env
```

Open `backend/.env` and set **one** of these:

```env
# Option A: OpenRouter
API_PROVIDER=openrouter
OPENROUTER_API_KEY=sk-or-v1-...

# Option B: local Claude Code CLI (no key needed)
API_PROVIDER=claude_code
```

Never commit `backend/.env`. It's already listed in `.gitignore`.

---

## Running

From the project root:

```bash
npm run dev:web
```

This starts the Python backend on **http://localhost:5001** and the frontend on **http://localhost:3000**. Open [http://localhost:3000](http://localhost:3000).

You can also run them in two terminals:

```bash
npm run backend   # terminal 1
npm run dev       # terminal 2
```

**First run:** the Whisper model (~1.5 GB) downloads from Hugging Face the first time you transcribe, so the first job is slower.

### Desktop window (Electron)

```bash
npm run electron:dev
```

This opens the app in a desktop window and starts the backend automatically.

---

## Usage

1. **Upload**: on the home page, choose a video, set its title and spoken language, and pick a frame interval.
2. **Processing**: watch progress on the Processing page (extract audio → transcribe → save).
3. **Result**: read the transcript next to the video and click a timestamp to jump there.
4. **Generate notes**: click *Generate Notes*, pick English and/or Hebrew and a note type, and the PDF appears inline when it's ready.
5. **Library**: every past transcription is listed here. You can open or delete them.

Everything (videos, transcripts, notes, database) is stored locally in `backend/transcription_results/`.

---

## Configuration

All settings live in `backend/.env`:

| Variable | Default | Purpose |
|---|---|---|
| `API_PROVIDER` | `openrouter` | `openrouter` or `claude_code` |
| `OPENROUTER_API_KEY` | (empty) | Needed for notes when using OpenRouter |
| `APP_BASE_URL` | `http://localhost:3000` | Base for clickable timestamp links in PDFs |
| `WHISPER_MODEL` | `mlx-community/whisper-large-v3-turbo` | e.g. `mlx-community/whisper-small-mlx` for faster, less accurate results |
| `BACKEND_PORT` | `5001` | If you change it, also update `API_URL` in `lib/api.js` |

---

## Troubleshooting

| Problem | Fix |
|---|---|
| Frontend shows no data or "failed to fetch" | Make sure the backend is running (`npm run backend`) and printed `Server: http://localhost:5001`. |
| `Address already in use` | Something else is on port 5001. Set `BACKEND_PORT` in `.env` and update `lib/api.js`. |
| "Lecture Notes: DISABLED" at startup | Set `OPENROUTER_API_KEY`, or set `API_PROVIDER=claude_code`, in `backend/.env`. |
| `ffmpeg: command not found` | `brew install ffmpeg` |
| PDF generation fails | Run `playwright install chromium` with the venv activated. |
| `No module named mlx` / install errors | You need an Apple Silicon Mac and an arm64 Python (`python3 -c "import platform; print(platform.machine())"` should print `arm64`). |

---

## Project structure

```
app/                 Next.js pages (home/upload, processing, library, result/[id])
components/          PDF viewer, notes modal
lib/api.js           Backend API client + Socket.IO
electron/main.js     Electron wrapper (starts the backend)
backend/server.py    Flask + Socket.IO API, transcription, notes generation
backend/html_notes/  Prompt building + HTML→PDF rendering for notes
```

## Tech stack

Next.js 14 · React 18 · Tailwind CSS · Electron · Flask 3 · Flask-SocketIO · MLX Whisper · Claude Sonnet (OpenRouter / Claude Code) · Playwright · PyMuPDF · SQLite
