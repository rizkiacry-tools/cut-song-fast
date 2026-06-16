import json
import os
import platform
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request


DOWNLOAD_DIR = os.path.dirname(os.path.abspath(__file__))


def check_dep(name: str) -> None:
    if not shutil.which(name):
        print(f"error: {name} not found — install it first", file=sys.stderr)
        sys.exit(1)


def search_youtube(query: str) -> str:
    check_dep("yt-dlp")
    cmd = ["yt-dlp", "--no-warnings", f"ytsearch10:{query}", "--dump-json", "--max-downloads", "10"]
    result = subprocess.run(cmd, capture_output=True, text=True)
    try:
        lines = result.stdout.strip().splitlines()
        videos = [json.loads(line) for line in lines if line]
    except (json.JSONDecodeError, IndexError, ValueError):
        err = result.stderr.strip()
        msg = f"error: no YouTube results for '{query}'"
        if err:
            msg += f"\n{err}"
        print(msg, file=sys.stderr)
        sys.exit(1)

    query_tokens = [t.lower() for t in query.split() if len(t) > 1]

    # identify band/artist tokens: query tokens that appear in any result's channel name
    # short tokens (< 3 chars like "op", "ed", "tv") excluded — too many false substring matches
    band_tokens = set()
    for v in videos:
        ch = (v.get("channel") or "").lower()
        for t in query_tokens:
            if len(t) >= 3 and t in ch:
                band_tokens.add(t)

    def score(v):
        title = (v.get("title") or "").lower()
        desc = (v.get("description") or "").lower()
        ch = (v.get("channel") or "").lower()
        views = v.get("view_count") or 0
        followers = v.get("channel_follower_count") or 0
        verified = v.get("channel_is_verified") or False

        title_match = sum(1 for t in query_tokens if t in title)
        desc_match = sum(1 for t in query_tokens if t in desc)
        all_match = title_match + desc_match
        band_in_ch = sum(1 for t in band_tokens if t in ch)

        content = title_match * 10 + desc_match * 5

        # derivative penalty — covers, lyrics, tabs, reuploads
        derivative_kw = ["cover", "lyrics", "tabs", "vietsub", "piano",
                         "instrumental", "karaoke", "react", "remix", "tutorial",
                         "lời việt", "việt", "sub español", "letra", "tekst", "subtitle"]
        query_lower = query.lower()
        is_derivative = any(kw in title for kw in derivative_kw) and not any(kw in query_lower for kw in derivative_kw)
        if is_derivative and not band_in_ch:
            content -= 100

        # large verified channel must match most query tokens or it's a diff song
        # only apply when band_tokens identified — prevents killing JP/CN titles
        if band_tokens and verified and followers > 50000 and band_in_ch == 0 and all_match < min(2, len(query_tokens)):
            return (-1, 0)

        # channel name in title = strongest signal of official upload
        # match any significant segment (e.g. "MAISONdes" in "... / maisondes")
        ch_parts = [p.strip() for p in re.split(r'[/\-|·•]', ch) if len(p.strip()) > 3]
        ch_in_title = any(p in title for p in ch_parts) or ch in title

        if band_in_ch >= 2 or (band_in_ch >= 1 and len(band_tokens) <= 1):
            authority = 1000
        elif ch_in_title and (verified or followers >= 50000):
            authority = 500
        elif verified and all_match > 0:
            authority = min(followers / 100000, 5)
        else:
            authority = 0

        return (content + authority, views)

    best = max(videos, key=score)
    # fallback: no authority signal, no band_tokens, AND winner has <10k views
    # → likely noise; pick highest-viewed video matching >= min(2, len(tokens))
    if not band_tokens and all(score(v)[0] < 200 for v in videos) and (best.get("view_count") or 0) < 10000:
        min_tokens = min(2, len(query_tokens))
        relevant = [
            v for v in videos
            if sum(1 for t in query_tokens if t in (v.get("title") or "").lower()) >= min_tokens
        ]
        if relevant:
            best = max(relevant, key=lambda v: (v.get("view_count") or 0))
    return best["webpage_url"]


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


def video_id(url: str) -> str:
    m = re.search(r"(?:v=|youtu\.be/)([a-zA-Z0-9_-]{11})", url)
    return m.group(1) if m else ""


def fetch_nonmusic_segments(vid: str) -> list:
    if not vid:
        return []
    api = f"https://sponsor.ajay.app/api/skipSegments?videoID={vid}&categories=%5B%22music_offtopic%22%5D"
    try:
        req = urllib.request.Request(api, headers={"User-Agent": "cut-song-fast/1.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
            return [s["segment"] for s in data if s.get("category") == "music_offtopic"]
    except (urllib.error.HTTPError, urllib.error.URLError, json.JSONDecodeError, OSError):
        return []


def mmss_to_sec(mmss: str) -> int:
    if not re.fullmatch(r"\d{4}", mmss):
        print(f"error: invalid time format '{mmss}' — need 4 digits MMSS", file=sys.stderr)
        sys.exit(1)
    return int(mmss[:2]) * 60 + int(mmss[2:])


def sec_to_ts(sec: int) -> str:
    return f"{sec // 60}:{sec % 60:02d}"


def adjust_seconds(start_s: int, end_s: int, segments: list) -> tuple:
    import math
    dur = end_s - start_s
    adj_start = float(start_s)
    adj_end = float(end_s)

    for seg in sorted(segments, key=lambda s: s[0]):
        seg_s, seg_e = float(seg[0]), float(seg[1])

        if seg_s <= adj_start < seg_e:
            shift = seg_e - adj_start
            adj_start = seg_e
            adj_end = adj_start + dur
        elif seg_s < adj_end <= seg_e:
            adj_end = seg_s
        elif adj_start < seg_s and seg_e < adj_end:
            adj_end -= (seg_e - seg_s)

    if adj_start >= adj_end:
        print("error: requested range is entirely non-music (SponsorBlock)", file=sys.stderr)
        sys.exit(1)

    return math.ceil(adj_start), math.ceil(adj_end)


def main() -> None:
    if len(sys.argv) == 3 and sys.argv[1] == "search":
        url = search_youtube(sys.argv[2])
        print(f"opening: {url}", file=sys.stderr)
        opener = {"Linux": "xdg-open", "Darwin": "open"}.get(platform.system(), "termux-open-url")
        subprocess.run([opener, url])
        return

    if len(sys.argv) != 4:
        print("usage: python3 cut.py <query> <start_MMSS> <end_MMSS>", file=sys.stderr)
        print("       python3 cut.py search <query>", file=sys.stderr)
        sys.exit(1)

    query = sys.argv[1]
    start = sys.argv[2]
    end = sys.argv[3]

    start_s = mmss_to_sec(start)
    end_s = mmss_to_sec(end)

    tmpdir = tempfile.mkdtemp(prefix="cutsong_")
    try:
        print(f"searching YouTube for '{query}'...")
        url = search_youtube(query)
        print(f"found: {url}")

        vid = video_id(url)
        segments = fetch_nonmusic_segments(vid)
        if segments:
            new_s, new_e = adjust_seconds(start_s, end_s, segments)
            if new_s != start_s or new_e != end_s:
                print(f"SponsorBlock: adjusted {sec_to_ts(start_s)}→{sec_to_ts(new_s)} {sec_to_ts(end_s)}→{sec_to_ts(new_e)} (skipping non-music)")
                start_s, end_s = new_s, new_e

        start_ts = sec_to_ts(start_s)
        end_ts = sec_to_ts(end_s)

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
