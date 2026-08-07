# OmniTide

Sync your Android phone or iTunes/Apple Music library to Tidal as real playlists, download tracks/albums/playlists as full-metadata FLAC files, and back up your entire Tidal account — all from one single-file Python tool, no third-party sync service required.

![Python](https://img.shields.io/badge/python-3.10%2B-blue)
![License](https://img.shields.io/badge/license-GPL--3.0-green)
![Platform](https://img.shields.io/badge/platform-Windows%20%7C%20macOS%20%7C%20Linux-lightgrey)

A single-file Python tool that does three things:

- **Sync** — Scans your Android phone or iTunes/Apple Music library and creates matching playlists on Tidal
- **Download** — Downloads tracks, albums, or playlists from Tidal as FLAC files with full metadata and album art
- **Backup** — Downloads your entire Tidal account (every playlist you own, plus Liked Songs) to your phone, an iTunes-import folder, or the current folder

No third‑party sync services. Just a Tidal account.

---
## New in this version

- **Whole-account backup** – the new `backup` command downloads every playlist you own plus your Liked Songs to your phone, an iTunes-import folder, or the current folder. Incremental — re-running only fetches what's new since last time.
- **Incremental phone *and* iTunes sync** – both `sync phone` and `sync itunes` now diff against a small local cache instead of re-processing your whole library every run. Songs already synced are skipped entirely; only new or removed songs touch the Tidal API. If a song disappears from your source, OmniTide asks before removing it from the matching Tidal playlist — it never removes tracks without confirming first. If that leaves the playlist empty, it deletes the (now-empty) playlist too.
- **Tag-aware matching** – `sync phone --read-tags` reads `ARTIST`/`TITLE`/`TIDALID` from each file's embedded tags (FLAC, OGG, MP3, M4A/AAC) instead of guessing from the filename, for more accurate matching.
- **Batch adding** – up to 50 tracks per API call, making sync **up to 50× faster**.
- **Tidal ID embedding** – every downloaded track stores its Tidal ID in a custom tag, so if you ever re-add it to your phone, OmniTide already knows exactly which Tidal track it is.
- **No manual venv activation** – run `./OmniTide.py` directly (Linux/macOS) and it detects and relaunches under `OmniTide_Env` automatically. `setup_linux.sh`/`setup_windows.bat` set that environment up for you.

---

## Requirements

- A Tidal account (any plan)
- Python 3.10 or newer
- `ffmpeg` installed on your system
- For Android sync/backup: ADB (Android Debug Bridge)
- For iTunes sync: iTunes with XML sharing enabled

---

## Installing ffmpeg and ADB

`ffmpeg` remuxes downloaded tracks (used by `download` and `backup`). ADB is only needed for `sync phone` and `backup --to phone`. Neither is required for `sync itunes` or logging in.

### ffmpeg

| OS | Command |
| :--- | :--- |
| **Arch Linux** | `sudo pacman -S ffmpeg` |
| **Ubuntu / Debian** | `sudo apt install ffmpeg` |
| **Fedora** | ffmpeg isn't in Fedora's default repos (codec licensing), so first enable RPM Fusion: `sudo dnf install https://mirrors.rpmfusion.org/free/fedora/rpmfusion-free-release-$(rpm -E %fedora).noarch.rpm` — then `sudo dnf install ffmpeg` |
| **macOS** | `brew install ffmpeg` |
| **Windows** | `winget install ffmpeg`, or download a build from [ffmpeg.org](https://ffmpeg.org) and add its `bin` folder to your `PATH` |

### ADB (Android Debug Bridge)

| OS | Command |
| :--- | :--- |
| **Arch Linux** | `sudo pacman -S android-tools` |
| **Ubuntu / Debian** | `sudo apt install android-tools-adb` |
| **Fedora** | `sudo dnf install android-tools` |
| **macOS** | `brew install android-platform-tools` |
| **Windows** | `winget install Google.PlatformTools`, or download [SDK Platform Tools](https://developer.android.com/tools/releases/platform-tools) and add it to your `PATH` |

Verify either install with `ffmpeg -version` / `adb version`.

---

## Installation

**The easiest way** is to use the **pre‑built binaries** (no Python or dependencies needed).

### Option 1 — Pre‑built Binary (Recommended)

1. Go to the **[Releases](https://github.com/reveler-hub/OmniTide/releases)** page.
2. Download the latest version for your operating system:
   - `OmniTide-linux` (Linux)
   - `OmniTide.exe` (Windows)
   - `OmniTide-macos` (macOS)
3. **Linux & macOS only**: Make it executable:
   ```bash
   chmod +x OmniTide-linux    # or OmniTide-macos
   ```

### Option 2 — Python venv (for developers)

```bash
git clone https://github.com/reveler-hub/OmniTide
cd OmniTide

# Linux/macOS
./setup_linux.sh
./OmniTide.py login

# Windows
setup_windows.bat
OmniTide_Env\Scripts\activate
python OmniTide.py login
```

The setup scripts create a virtual environment in an `OmniTide_Env` folder next to the scripts and install everything from `requirements.txt`.

On **Linux/macOS**, run the scripts as `./OmniTide.py ...` (not `python3 OmniTide.py ...`) — that way they detect `OmniTide_Env` next to themselves and use it automatically, no activation needed. On **Windows** there's no equivalent auto-detection, so activate the environment first as shown above.

---

## First run — Tidal login

Run `login` first to authenticate:

```bash
./OmniTide-linux login    # Linux binary
.\OmniTide.exe login      # Windows binary
./OmniTide.py login       # Linux/macOS venv
python OmniTide.py login  # Windows venv
```

The script prints a URL. Open it in your browser, log in to Tidal, and the script continues automatically. Your session is saved to `token.json` – you won't need to log in again unless you delete it.

---

## Syncing your library to Tidal

OmniTide supports two sources: **Android phone** and **iTunes/Apple Music**.

### Android phone

1. Enable **USB Debugging** on your phone (Settings → About Phone → tap Build Number 7 times → Developer Options → USB Debugging).
2. Connect your phone via USB and accept the ADB authorisation prompt.
3. Run:

```bash
./OmniTide-linux sync phone        # Linux binary
.\OmniTide.exe sync phone          # Windows binary
./OmniTide.py sync phone           # Linux/macOS venv
python OmniTide.py sync phone      # Windows venv
```

The script scans `/sdcard/Music/`. Each subfolder becomes a Tidal playlist. By default, artist/title are guessed from filenames — add `--read-tags` to read them from each file's embedded `ARTIST`/`TITLE`/`TIDALID` tags instead (FLAC, OGG, MP3, M4A/AAC), which is more accurate but slower since it pulls a chunk of every file over ADB:

```bash
./OmniTide.py sync phone --read-tags        # Linux/macOS venv
python OmniTide.py sync phone --read-tags   # Windows venv
```

**Every run after the first is incremental.** OmniTide remembers what it already synced in a small cache file (`.omnitide_phone_cache.json` next to the script, or point elsewhere with `--cache-file FILE` if you're managing more than one phone/library). On each run it only:
- adds songs that are new since last time,
- skips songs it already added — no re-searching, no re-uploading, no duplicates,
- and if a song that was previously synced is no longer found on your phone, it prints how many and **asks before removing them from the matching Tidal playlist** (defaults to no if you don't answer, and never prompts — just skips removal — when run non-interactively). If confirming leaves the playlist with zero tracks, the playlist itself is deleted too.

Use `--only NAME` to restrict a run to playlists whose name contains `NAME`.

### iTunes / Apple Music (macOS and Windows)

```bash
./OmniTide-macos sync itunes        # macOS binary
.\OmniTide.exe sync itunes          # Windows binary
./OmniTide.py sync itunes           # macOS venv
python OmniTide.py sync itunes      # Windows venv
```

The script auto‑detects your library file at:
- **macOS:** `~/Music/Music/Music Library.xml`
- **Windows:** `%USERPROFILE%\Music\iTunes\iTunes Music Library.xml`

If your library is elsewhere, specify it:

```bash
./OmniTide.py sync itunes --path "path/to/library.xml"                  # macOS venv
python OmniTide.py sync itunes --path "C:\path\to\library.xml"          # Windows venv
```

**Like phone sync, this is incremental** — OmniTide remembers what it already synced in `.omnitide_itunes_cache.json` (or point elsewhere with `--cache-file FILE`). Re-running only adds tracks new to a playlist since last time, and prompts before removing anything from Tidal if a track was removed from the iTunes side (same behavior as phone sync — see above).

---

## Customising the sync

Near the top of `OmniTide.py` (or in the binary, you can’t edit it; use the Python version if you need this), you can set:

- **`SKIP_AS_ARTIST`** – Folder names that should **not** be used as artist when guessing from the filename. Useful for mix folders like `Workout Tracks`.
- **`SKIP_PLAYLISTS`** – Folder names to **completely ignore** during sync (e.g., audiobooks, voice memos).

---

## Downloading from Tidal

Download tracks, albums, or playlists by URL:

```bash
./OmniTide.py download "https://tidal.com/browse/track/12345678"
./OmniTide.py download "https://tidal.com/browse/album/12345678"
./OmniTide.py download "https://tidal.com/browse/playlist/xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx"
```

On Windows (venv), use `python OmniTide.py download "URL"` instead of `./OmniTide.py download "URL"`; with the binary, `.\OmniTide.exe download "URL"`.

Files are saved to your home folder under `Tidal Download/` by default (`~/Tidal Download/` on Linux/macOS, `C:\Users\<you>\Tidal Download\` on Windows) — use `--dest DIR` to change it. Downloads include full metadata, album art, and the **Tidal ID** embedded in a custom `TIDALID` tag.

---

## Backing up your whole Tidal account

While `download` fetches one track/album/playlist by URL, `backup` downloads **everything** — every playlist you own, plus every track in your Liked Songs, in one go:

```bash
./OmniTide.py backup
```

It asks where to save it:

```
Where should OmniTide back up your Tidal library to?
  1) Phone (adb push)
  2) iTunes folder
  3) Current folder
Choose [1/2/3]:
```

Pass `--to {phone,itunes,folder}` to skip the prompt (required if you're running it non-interactively — e.g. from a script or cron job, it'll exit immediately rather than hang waiting for input).

- **Phone** — pushes files to `/sdcard/OmniTide Backup/` on the connected device via ADB (deliberately kept separate from `/sdcard/Music/`, so the backup doesn't get picked up as "new local music" the next time you run `sync phone`). Each track is downloaded locally, pushed, then deleted locally before moving to the next one — it never needs double the disk space.
- **iTunes** — saves to `~/Music/OmniTide Backup/` by default (override with `--dest DIR`). This just organizes files into folders — OmniTide doesn't have a way to make iTunes actually import them or build playlists on its own; you'd add them to your iTunes library yourself afterward.
- **Current folder** — saves to wherever you run the command from (override with `--dest DIR`).

All three use the same layout: `Playlists/<name>/01. Artist - Title.flac` for owned playlists, `Liked Songs/Artist - Title.flac` for liked tracks. **If a song is both liked and in one of your playlists, it's downloaded to both places** — liking a song is treated as its own thing, not deduplicated against playlist membership.

Like phone/iTunes sync, backup is incremental — it remembers what's already been delivered (separately per destination: `.omnitide_backup_phone_cache.json`, `.omnitide_backup_itunes_cache.json`, `.omnitide_backup_folder_cache.json`, or override with `--cache-file FILE`) and only fetches what's new on later runs. Unlike sync, it doesn't mirror deletions — if you unfavorite a track or remove it from a playlist on Tidal, your already-downloaded copy is left alone.

---

## All commands

| Command | Description |
| :--- | :--- |
| `login` | Log in to Tidal and save your session token |
| `sync phone [--only NAME] [--cache-file FILE] [--read-tags]` | Incrementally sync from an Android phone over ADB |
| `sync itunes [--path XML] [--only NAME] [--cache-file FILE]` | Incrementally sync from an iTunes/Apple Music library |
| `download URL [--dest DIR]` | Download a track, album, or playlist |
| `backup [--to {phone,itunes,folder}] [--dest DIR] [--cache-file FILE]` | Download every owned playlist + Liked Songs from your account |

Run `./OmniTide.py <command> --help` for a command's full option list, or `./OmniTide.py --help` for the top-level list (on Windows: `python OmniTide.py <command> --help`, or `.\OmniTide.exe <command> --help` with the binary).

---

## Troubleshooting

**Login prompt appears every run / 401 errors**  
Delete `token.json` and run `login` again. The script will automatically refresh your token on each run – if it fails, a fresh login is needed.

**ADB says "no devices" or "unauthorized"**  
Enable USB Debugging and accept the authorisation prompt on your phone. Run `adb devices` to verify the connection. If `adb` isn't found at all, see "Installing ffmpeg and ADB" above.

**Songs not found or wrong songs added**  
Run MusicBrainz Picard on your library to fix tags. After a sync, check `unmatched_songs.txt` for a list of everything that wasn't found — unmatched songs aren't cached, so they're retried automatically on your next run. For phone sync specifically, try `sync phone --read-tags` — matching from embedded tags is more accurate than guessing from filenames.

**Phone/iTunes sync isn't picking up changes**  
They only look at what changed since the last run, tracked in `.omnitide_phone_cache.json`/`.omnitide_itunes_cache.json`. If that file gets deleted or you want to force a full re-check, just delete it (or point `--cache-file` somewhere fresh) and run again — everything will be treated as new, matched, and added, but nothing already in a Tidal playlist gets duplicated.

**Backup isn't picking up new songs, or `--to phone` fails to push**  
Backup tracks what it's already delivered in `.omnitide_backup_{phone,itunes,folder}_cache.json` (one per destination) — delete the relevant one (or use `--cache-file`) to force a fresh check. For `--to phone` push failures specifically, confirm `adb devices` shows your phone connected and authorized first (same requirement as phone sync).

**A song shows up twice after running `backup`**  
Expected, not a bug — if a track is both in a playlist and in your Liked Songs, it's downloaded to both `Playlists/<name>/` and `Liked Songs/` on purpose (see "Backing up your whole Tidal account" above).

**ffmpeg not found**  
See "Installing ffmpeg and ADB" above. Downloads will still work without it, but the seekbar may be broken.

**iTunes library not found**  
Make sure **Share iTunes Library XML** is enabled (Music → Settings → Advanced on macOS, or Edit → Preferences → Advanced on Windows). Or use `--path`.

**Batch adding fails with HTTP 400**  
The script automatically falls back to individual adds for the affected chunk – no action needed. If you see many 400s, try reducing the chunk size (edit `chunk_size = 50` to a lower number in `add_tracks_batch()`).

---

## Disclaimer

> This project is strictly for educational and personal archival purposes.
>
> You must have an active Tidal subscription to use this tool. Do not use OmniTide to distribute copyrighted material, bypass DRM for piracy, or violate Tidal's Terms of Service.
>
> The developers assume no liability for how this tool is used or any potential account bans resulting from excessive API calls. Use at your own risk.
