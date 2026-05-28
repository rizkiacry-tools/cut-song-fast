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
    check_dep("yt-dlp")
    cmd = ["yt-dlp", "--no-warnings", f"ytsearch5:{query}", "--dump-json", "--max-downloads", "5"]
    result = subprocess.run(cmd, capture_output=True, text=True)
    try:
        lines = result.stdout.strip().splitlines()
        best = max(
            (json.loads(line) for line in lines),
            key=lambda v: v.get("view_count") or 0
        )
        return best["webpage_url"]
    except (json.JSONDecodeError, IndexError, KeyError, ValueError):
        err = result.stderr.strip()
        msg = f"error: no YouTube results for '{query}'"
        if err:
            msg += f"\n{err}"
        print(msg, file=sys.stderr)
        sys.exit(1)


def download_audio(url: str, outdir: str) -> str:
    check_dep("yt-dlp")
    outtmpl = os.path.join(outdir, "%(id)s.%(ext)s")
    cmd = [
        "yt-dlp", "--no-warnings", "-f", "bestaudio", "--extract-audio",
        "--audio-format", "mp3", "--audio-quality", "0",
        "-o", outtmpl, url
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    for f in os.listdir(outdir):
        if f.endswith(".mp3"):
            return os.path.join(outdir, f)
    err = result.stderr.strip()
    msg = "error: yt-dlp download failed"
    if err:
        msg += f"\n{err}"
    print(msg, file=sys.stderr)
    sys.exit(1)


def cut_audio(inpath: str, start_ts: str, end_ts: str, outpath: str) -> None:
    check_dep("ffmpeg")
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

    start_ts = parse_mmss(start)
    end_ts = parse_mmss(end)

    tmpdir = tempfile.mkdtemp(prefix="cutsong_")
    try:
        print(f"searching YouTube for '{query}'...")
        url = search_youtube(query)
        print(f"found: {url}")
        print("downloading...")
        audio_path = download_audio(url, tmpdir)
        print(f"cutting {start_ts} → {end_ts}...")
        cut_path = os.path.join(tmpdir, "cut.mp3")
        cut_audio(audio_path, start_ts, end_ts, cut_path)
        outname = get_next_filename(DOWNLOAD_DIR)
        outpath = os.path.join(DOWNLOAD_DIR, outname)
        shutil.copy2(cut_path, outpath)
        print(f"saved: {outpath}")
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


if __name__ == "__main__":
    main()
