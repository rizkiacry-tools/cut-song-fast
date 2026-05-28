# cut-song-fast — Design Doc

## Goal

Single command to cut a segment from a YouTube song, save as MP3.

## Usage

```
just cut <query> <start> <end>
```

- `query` — YouTube search title
- `start`, `end` — MMSS format, zero-padded 4 digits
- Example: `just cut "ideal paradox" 0000 0015` → first 15 seconds

## Architecture

2 files: `justfile` + `cut.py`.

```
just cut "song" START END
  └─ justfile → python3 cut.py "song" START END
                    ├─ yt-dlp search → pick 1st result
                    ├─ yt-dlp download best audio to temp
                    ├─ ffmpeg cut segment
                    ├─ scan ~/storage/downloads/ → next auto-increment
                    └─ copy result, cleanup
```

## Component: cut.py

Python 3, stdlib only (`subprocess`, `os`, `re`, `tempfile`, `shutil`).

### Steps

1. **Parse args**: `query`, `start_mmss`, `end_mmss`. Validate 4-digit.
2. **Search YouTube**: `yt-dlp "ytsearch:<query>" --dump-json` → parse JSON, get first URL.
3. **Download audio**: `yt-dlp -f bestaudio --extract-audio --audio-format mp3 -o <tmp>/%(id)s.%(ext)s <url>`
4. **Cut segment**: `ffmpeg -ss <start> -to <end> -i <input> -q:a 0 -map a <tmp>/cut.mp3`
   - Convert MMSS → seconds or HH:MM:SS for ffmpeg
5. **Auto-increment output**: scan `~/storage/downloads/` for `\d{4}\.mp3`, find max, +1, zero-pad 4. Start at `0001` if none.
6. **Copy**: `shutil.copy2` to `~/storage/downloads/<n>.mp3`
7. **Cleanup**: remove temp dir (always, even on error)

### Time conversion

- `0015` → `0:15`
- `1230` → `12:30`
- `0105` → `1:05`
- Feed ffmpeg as `-ss 0:15 -to 12:30`

### Exit codes

- `0` success
- `1` any error (no results, ffmpeg fail, bad format)

### Errors

- yt-dlp not found → "yt-dlp required"
- ffmpeg not found → "ffmpeg required"
- No YouTube results → "No results for <query>"
- ffmpeg cut fails → print stderr
- All errors → cleanup temp then exit 1

## Component: justfile

```make
cut query start end:
    python3 cut.py "{{query}}" "{{start}}" "{{end}}"
```

## Output

- Path: `~/storage/downloads/XXXX.mp3`
- Naming: auto-increment 4-digit, starting at `0001`
- Overwrite: never — always increments

## Dependencies

- `yt-dlp` (must be installed, working)
- `ffmpeg` (must be installed)
- Python 3 (stdlib only)

## Non-goals

- No playlist support
- No format selection
- No metadata tagging
- No interactive search
