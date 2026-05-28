# cut-song-fast Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** One‑command `just cut <query> <start> <end>` that searches YouTube, downloads audio, cuts a segment, and saves auto‑numbered MP3 to `~/storage/downloads/`.

**Architecture:** Python script (`cut.py`) handles all logic (YouTube search, download, ffmpeg cut, file naming). `justfile` wraps it with a clean CLI. No pip dependencies — only Python stdlib + system `yt-dlp` + `ffmpeg`.

**Tech Stack:** Python 3.13, yt-dlp, ffmpeg, just

---

### Task 1: Fix yt-dlp interpreter

**Files:**
- Modify: `/data/data/com.termux/files/usr/bin/yt-dlp` (shebang line 1)

- [ ] **Step 1: Check current shebang**

Run: `head -1 /data/data/com.termux/files/usr/bin/yt-dlp`
Expected: `#!/data/data/com.termux/files/usr/bin/python3.12`

- [ ] **Step 2: Fix shebang to python3.13**

Run: `sed -i '1s/python3\.12/python3.13/' /data/data/com.termux/files/usr/bin/yt-dlp`

- [ ] **Step 3: Verify it works**

Run: `yt-dlp --version`
Expected: version string (e.g., `2025.xx.xx`), no interpreter error

---

### Task 2: Write cut.py

**Files:**
- Create: `cut.py` (project root)

- [ ] **Step 1: Write cut.py**

```python
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile


DOWNLOAD_DIR = os.path.expanduser("~/storage/downloads")


def parse_mmss(mmss: str) -> str:
    if not re.fullmatch(r"\d{4}", mmss):
        print(f"error: invalid time format '{mmss}' — need 4 digits MMSS", file=sys.stderr)
        sys.exit(1)
    m = int(mmss[:2])
    s = int(mmss[2:])
    return f"{m}:{s:02d}"


def check_dep(name: str) -> None:
    if not shutil.which(name):
        print(f"error: {name} not found — install it first", file=sys.stderr)
        sys.exit(1)


def search_youtube(query: str) -> str:
    cmd = ["yt-dlp", f"ytsearch:{query}", "--dump-json", "--max-downloads", "1"]
    try:
        out = subprocess.check_output(cmd, stderr=subprocess.DEVNULL, text=True)
    except subprocess.CalledProcessError:
        print(f"error: no YouTube results for '{query}'", file=sys.stderr)
        sys.exit(1)
    data = json.loads(out.strip().splitlines()[0])
    return data["webpage_url"]


def download_audio(url: str, outdir: str) -> str:
    check_dep("yt-dlp")
    outtmpl = os.path.join(outdir, "%(id)s.%(ext)s")
    cmd = [
        "yt-dlp", "-f", "bestaudio", "--extract-audio",
        "--audio-format", "mp3", "--audio-quality", "0",
        "-o", outtmpl, url
    ]
    subprocess.run(cmd, check=True, stderr=subprocess.PIPE, text=True)
    # find the downloaded file
    for f in os.listdir(outdir):
        if f.endswith(".mp3"):
            return os.path.join(outdir, f)
    print("error: downloaded file not found", file=sys.stderr)
    sys.exit(1)


def cut_audio(inpath: str, start: str, end: str, outpath: str) -> None:
    check_dep("ffmpeg")
    start_ts = parse_mmss(start)
    end_ts = parse_mmss(end)
    cmd = [
        "ffmpeg", "-ss", start_ts, "-to", end_ts,
        "-i", inpath, "-q:a", "0", "-map", "a", "-y", outpath
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print("error: ffmpeg failed", file=sys.stderr)
        print(result.stderr, file=sys.stderr)
        sys.exit(1)


def get_next_filename(directory: str) -> str:
    os.makedirs(directory, exist_ok=True)
    max_num = 0
    pat = re.compile(r"^(\d{4})\.mp3$")
    for f in os.listdir(directory):
        m = pat.match(f)
        if m:
            n = int(m.group(1))
            if n > max_num:
                max_num = n
    return f"{max_num + 1:04d}.mp3"


def main() -> None:
    if len(sys.argv) != 4:
        print("usage: python3 cut.py <query> <start_MMSS> <end_MMSS>", file=sys.stderr)
        sys.exit(1)

    query = sys.argv[1]
    start = sys.argv[2]
    end = sys.argv[3]

    parse_mmss(start)
    parse_mmss(end)

    tmpdir = tempfile.mkdtemp(prefix="cutsong_")
    try:
        print(f"searching YouTube for '{query}'...")
        url = search_youtube(query)
        print(f"found: {url}")
        print("downloading...")
        audio_path = download_audio(url, tmpdir)
        print(f"cutting {start} → {end}...")
        cut_path = os.path.join(tmpdir, "cut.mp3")
        cut_audio(audio_path, start, end, cut_path)
        outname = get_next_filename(DOWNLOAD_DIR)
        outpath = os.path.join(DOWNLOAD_DIR, outname)
        shutil.copy2(cut_path, outpath)
        print(f"saved: {outpath}")
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Verify cut.py syntax**

Run: `python3 -c "import py_compile; py_compile.compile('cut.py', doraise=True)"`
Expected: no output (syntax OK)

---

### Task 3: Create justfile

**Files:**
- Create: `justfile` (project root)

- [ ] **Step 1: Write justfile**

```make
cut query start end:
    python3 cut.py "{{query}}" "{{start}}" "{{end}}"
```

- [ ] **Step 2: Verify just reads it**

Run: `just --list`
Expected: output includes `cut query start end`

---

### Task 4: Integration test

- [ ] **Step 1: Run a real cut**

Run: `just cut "ideal paradox" 0000 0015`

Expected:
- Progress output from yt-dlp
- ffmpeg cut completes
- File appears in `~/storage/downloads/0001.mp3`
- Exit code 0

Run: `ls -la ~/storage/downloads/0001.mp3`
Expected: file exists, size > 0

- [ ] **Step 2: Run again — verify auto-increment**

Run: `just cut "ideal paradox" 0000 0015`
Expected: `~/storage/downloads/0002.mp3` created (0001 still exists)

- [ ] **Step 3: Error case — bad time format**

Run: `just cut "test" 123 456` (3 digits instead of 4)
Expected: error message about invalid time format, exit code 1
