# OmniTide

A single-file Python tool that does two things:

- **Sync** — Scans your music library (Android phone or iTunes/Apple Music) and creates matching playlists on Tidal
- **Download** — Downloads tracks, albums, or playlists from Tidal as FLAC files with full metadata and album art

No third‑party sync services. Just a Tidal account.

---

## New in this version

- **Batch adding** – up to 50 tracks per API call, making sync **up to 50× faster**.
- **Tidal ID embedding** – every downloaded track stores its Tidal ID in a custom tag. Future syncs use these IDs for **instant, 100% accurate** additions – no searching, no mismatches.
- **Local library indexing** – `--build-local` scans your music folder and builds a song file with Tidal IDs.
- **ID fetching** – `--fetch-ids` reads an existing song file, searches Tidal for missing IDs, and updates it (and can write IDs back into the audio files).
- **Custom song file** – `--song-file` lets you use any filename, so you can manage multiple libraries.
- **Backup your playlists** – the included `Omni_List.py` exports all your Tidal playlists with track IDs, ready to re‑import.

---

## Requirements

- A Tidal account (any plan)
- Python 3.10 or newer
- `ffmpeg` installed on your system
- For Android sync: ADB (Android Debug Bridge)
- For iTunes sync: iTunes with XML sharing enabled

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

# Create and activate a virtual environment
python3 -m venv ~/OmniTide_Env
source ~/OmniTide_Env/bin/activate   # Linux/macOS
# or OmniTide_Env\Scripts\activate   # Windows

# Install dependencies
pip install tidalapi requests mutagen pathvalidate python-ffmpeg

# Run
./OmniTide.py --login
```

---

## First run — Tidal login

Run `--login` first to authenticate:

```bash
./OmniTide-linux --login    # Linux binary
.\OmniTide.exe --login      # Windows binary
./OmniTide.py --login       # venv
```

The script prints a URL. Open it in your browser, log in to Tidal, and the script continues automatically. Your session is saved to `token.json` – you won't need to log in again unless you delete it.

---

## Syncing your library to Tidal

OmniTide supports three sources: **Android phone**, **iTunes/Apple Music**, and **manual song files**.

### Android phone

1. Enable **USB Debugging** on your phone (Settings → About Phone → tap Build Number 7 times → Developer Options → USB Debugging).
2. Connect your phone via USB and accept the ADB authorisation prompt.
3. Run:

```bash
./OmniTide-linux --sync        # binary
./OmniTide.py --sync           # venv
```

The script scans `/sdcard/Music/`. Each subfolder becomes a Tidal playlist. Songs are matched on Tidal by artist and title.

### iTunes / Apple Music (macOS and Windows)

```bash
./OmniTide-macos --sync --source itunes   # binary
./OmniTide.py --sync --source itunes      # venv
```

The `--itunes` flag is an alias for `--source itunes` (so `--sync --itunes` still works).

The script auto‑detects your library file at:
- **macOS:** `~/Music/Music/Music Library.xml`
- **Windows:** `%USERPROFILE%\Music\iTunes\iTunes Music Library.xml`

If your library is elsewhere, specify it:

```bash
./OmniTide.py --sync --source itunes --itunes-path "path/to/library.xml"
```

### Manual song file

Create a plain text file (default: `song_files.txt`) with this format:

```
[Playlist Name]
Artist - Song Title
Artist - Song Title [TID:123456789]   # optional Tidal ID

[Another Playlist]
Artist - Song Title
```

Then run:

```bash
./OmniTide.py --sync --song-file my_songs.txt
```

If a line includes `[TID:...]`, the track is added instantly – no search, no errors. If the ID is missing, the script falls back to searching by artist/title.

---

## Building a song file from your local music folder

If you have a folder of downloaded music (e.g., from OmniTide downloads or elsewhere), you can index it and generate a `song_files.txt` with Tidal IDs.

```bash
# Basic scan – reads existing TIDALID tags if present
./OmniTide.py --build-local ~/Tidal\ Download

# Also fetch missing IDs from Tidal (searches by artist/title)
./OmniTide.py --build-local ~/Tidal\ Download --fetch-ids
```

The script reads metadata from FLAC files, extracts `ARTIST`, `TITLE`, and the custom `TIDALID` tag (if present), and writes a `song_files.txt` in the current directory.

If you use `--fetch-ids`, it searches Tidal for any file missing a `TIDALID` and writes the ID back into the file **and** into the generated song file.

### Fetch IDs for an existing song file

If you already have a song file without IDs (e.g., an old backup), you can update it:

```bash
./OmniTide.py --fetch-ids --song-file old_backup.txt
```

This reads `old_backup.txt`, searches Tidal for every line without a `[TID:...]`, and rewrites the file with the found IDs.

---

## Backing up your Tidal playlists

The included script `Omni_List.py` exports all your user‑created playlists with track Tidal IDs.

```bash
./Omni_List.py > my_backup.txt
```

The output is a `song_files.txt`‑compatible file – you can later sync it to a new account instantly:

```bash
./OmniTide.py --sync --song-file my_backup.txt
```

---

## Customising the sync

Near the top of `OmniTide.py` (or in the binary, you can’t edit it; use the Python version if you need this), you can set:

- **`SKIP_AS_ARTIST`** – Folder names that should **not** be used as artist when guessing from the filename. Useful for mix folders like `Workout Tracks`.
- **`SKIP_PLAYLISTS`** – Folder names to **completely ignore** during sync (e.g., audiobooks, voice memos).

---

## Downloading from Tidal

Download tracks, albums, or playlists by URL:

```bash
./OmniTide.py --download "https://tidal.com/browse/track/12345678"
./OmniTide.py --download "https://tidal.com/browse/album/12345678"
./OmniTide.py --download "https://tidal.com/browse/playlist/xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx"
```

Files are saved to `~/Tidal Download/` with full metadata, album art, and the **Tidal ID** embedded in a custom `TIDALID` tag.

---

## All command‑line options

| Flag | Description |
| :--- | :--- |
| `--login` | Log in to Tidal and save your session token |
| `--sync` | Sync from your chosen source (phone or iTunes) |
| `--source {phone,itunes}` | Source to sync from (default: phone) |
| `--itunes` | Alias for `--source itunes` (kept for compatibility) |
| `--itunes-path PATH` | Path to iTunes Music Library.xml |
| `--download URL` | Download a track, album, or playlist |
| `--only NAME` | Only sync playlists whose names contain NAME |
| `--rescan` | Force re‑scan the source even if a song file exists |
| `--keep-existing` | Don't delete and replace existing Tidal playlists (add to them) |
| `--song-file FILE` | Use a custom song list file (default: `song_files.txt`) |
| `--build-local PATH` | Scan a local music folder and build a song file with Tidal IDs |
| `--fetch-ids` | Read a song file, search Tidal for missing IDs, and update it |

---

## Troubleshooting

**Login prompt appears every run / 401 errors**  
Delete `token.json` and run `--login` again. The script will automatically refresh your token on each run – if it fails, a fresh login is needed.

**ADB says "no devices" or "unauthorized"**  
Enable USB Debugging and accept the authorisation prompt on your phone. Run `adb devices` to verify the connection.

**Songs not found or wrong songs added**  
Run MusicBrainz Picard on your library to fix tags. After a sync, check `unmatched_songs.txt` for a list of everything that wasn’t found.

**ffmpeg not found**  
Install ffmpeg (`sudo apt install ffmpeg` on Linux, or download from ffmpeg.org). Downloads will still work without it, but the seekbar may be broken.

**iTunes library not found**  
Make sure **Share iTunes Library XML** is enabled (Music → Settings → Advanced on macOS, or Edit → Preferences → Advanced on Windows). Or use `--itunes-path`.

**Batch adding fails with HTTP 400**  
The script automatically falls back to individual adds for the affected chunk – no action needed. If you see many 400s, try reducing the chunk size (edit `chunk_size = 50` to a lower number in `add_tracks_batch()`).

---

## Disclaimer

> This project is strictly for educational and personal archival purposes.
>
> You must have an active Tidal subscription to use this tool. Do not use OmniTide to distribute copyrighted material, bypass DRM for piracy, or violate Tidal's Terms of Service.
>
> The developers assume no liability for how this tool is used or any potential account bans resulting from excessive API calls. Use at your own risk.
```
