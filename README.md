# OmniTide

A single-file Python tool that does two things:

- **Sync** — Scans your music library (Android phone or iTunes/Apple Music) and creates matching playlists on Tidal
- **Download** — Downloads tracks, albums, or playlists from Tidal as FLAC files with full metadata and album art

No third-party sync services. Just a Tidal account.

---

## Requirements

- A Tidal account (any plan)
- Python 3.10 or newer
- `ffmpeg` installed on your system
- For Android sync: ADB (Android Debug Bridge)

---

## Installation

There are three ways to run OmniTide. Pick one.

---

### Option 1 — Compiled binary (easiest, Linux only)

Download `OmniTide` from the releases page. No Python required.

```bash
chmod +x OmniTide
./OmniTide --sync
```

> Built for Linux x86_64. Windows and macOS users should use Option 2 or 3.

---

### Option 2 — Python script, system-wide

Install the dependencies globally. Simple, but mixes packages with your system Python.

#### Linux

```bash
# Arch / Manjaro
sudo pacman -S python python-pip ffmpeg android-tools

# Debian / Ubuntu / Mint
sudo apt install python3 python3-pip ffmpeg adb

# Fedora
sudo dnf install python3 python3-pip ffmpeg android-tools
```

```bash
pip install tidalapi requests mutagen pathvalidate python-ffmpeg --break-system-packages
```

> `--break-system-packages` is required on newer Linux distros that protect the system Python.

#### macOS

```bash
# Install Homebrew if you don't have it: https://brew.sh
brew install python ffmpeg android-platform-tools
pip3 install tidalapi requests mutagen pathvalidate python-ffmpeg
```

#### Windows

1. Install [Python](https://python.org/downloads) — tick **"Add Python to PATH"** during setup
2. Install [ffmpeg](https://ffmpeg.org/download.html) and add it to your PATH
3. For Android sync, download [ADB Platform Tools](https://developer.android.com/tools/releases/platform-tools) and add to PATH
4. Open a terminal and run:

```bat
pip install tidalapi requests mutagen pathvalidate python-ffmpeg
```

Then run the script:

```bat
python OmniTide.py --sync
```

---

### Option 3 — Python venv (recommended)

A virtual environment keeps OmniTide's dependencies isolated from everything else. This is the cleanest approach.

> **Important:** If you reinstall or upgrade Python, you'll need to delete and recreate the venv. Your `token.json` and `song_files.txt` are stored outside the venv and won't be affected.

#### Linux / macOS

```bash
# Create the venv
python -m venv ~/OmniTide_Env

# Activate it
source ~/OmniTide_Env/bin/activate        # bash or zsh
source ~/OmniTide_Env/bin/activate.fish   # fish shell

# Install dependencies
pip install tidalapi requests mutagen pathvalidate python-ffmpeg

# Run
python OmniTide.py --sync
```

To use it again in future, just activate the venv first:

```bash
source ~/OmniTide_Env/bin/activate
python OmniTide.py --sync
```

#### Windows

```bat
python -m venv OmniTide_Env
OmniTide_Env\Scripts\activate
pip install tidalapi requests mutagen pathvalidate python-ffmpeg
python OmniTide.py --sync
```

---

## First run — Tidal login

On first run, the script will print a URL and wait for you to log in:

```
🔐 No token found — starting Tidal login...
Please visit: https://link.tidal.com/XXXXX
```

Open the URL in your browser, log in to Tidal, and the script continues automatically. Your session is saved to `token.json` — you won't need to log in again unless you delete it. The token refreshes itself on each run.

---

## Syncing your library to Tidal

### Android phone

1. Enable **USB Debugging** on your phone:
   - Go to **Settings → About Phone** and tap **Build Number** 7 times to unlock Developer Options
   - Go to **Settings → Developer Options** and enable **USB Debugging**
2. Connect your phone via USB
3. Accept the ADB authorisation prompt on your phone when it appears
4. Run:

```bash
python OmniTide.py --sync
```

The script scans `/sdcard/Music/` on your phone. Each subfolder becomes a Tidal playlist. Songs are matched on Tidal by artist and title.

To confirm ADB can see your phone before running:

```bash
adb devices
```

You should see your device listed. If it shows `unauthorized`, accept the prompt on your phone.

---

### iTunes / Apple Music (macOS and Windows)

```bash
python OmniTide.py --itunes
```

The script auto-detects your library file at:
- **macOS:** `~/Music/Music/Music Library.xml`
- **Windows:** `%USERPROFILE%\Music\iTunes\iTunes Music Library.xml`

If your library is in a different location:

```bash
python OmniTide.py --itunes --itunes-path "path/to/iTunes Music Library.xml"
```

Tracks are grouped by your iTunes playlists. Tracks not in any playlist go into a `Music` playlist on Tidal.

> **Note:** You may need to enable XML sharing in iTunes/Music. On macOS: **Music → Settings → Advanced → Share iTunes Library XML with other applications.**

---

### Manual mode — provide your own song list

If you can't use ADB or iTunes, create a plain text file called `song_files.txt` in the same folder as the script. Use this format:

```
[Playlist Name]
Artist - Song Title
Artist - Song Title

[Another Playlist]
Artist - Song Title
```

Then run:

```bash
python OmniTide.py --sync
```

The script will use `song_files.txt` automatically if it exists.

---

### iPhone

Direct iPhone scanning is not supported. Use one of these alternatives:

- **iTunes on Mac or Windows** — use the `--itunes` flag above
- **Manual mode** — create `song_files.txt` by hand or export from another app

---

### Getting your tags right — MusicBrainz Picard

The sync matches songs by artist and title. If your files have missing or wrong tags, some songs may not be found or the wrong version may be added.

**[MusicBrainz Picard](https://picard.musicbrainz.org/)** is a free tool that fingerprints your audio files and automatically corrects their tags. It's recommended for any music library that wasn't downloaded from a streaming service.

1. Download Picard from [picard.musicbrainz.org](https://picard.musicbrainz.org/)
2. Drag your music folder into Picard
3. Click **Lookup** for files that already have tags, or **Scan** to fingerprint files with missing or wrong tags
4. Review the matches and click **Save**
5. Run the sync — matching accuracy will be significantly better

---

## Customising the sync

Near the top of `OmniTide.py`, there are two configuration sets you can edit to fix common syncing issues.

### `SKIP_AS_ARTIST` — For mixes and compilations

**What it does:** Prevents OmniTide from using the folder name as the artist when searching, but still syncs the songs.

**Why you need it:** If a song file doesn't have the artist in its filename (e.g., `01 - Get Lucky.flac`), OmniTide guesses the artist from the folder name. If the folder is called `Daft Punk` this works perfectly. However, if the folder is a mix called `Workout Tracks`, OmniTide will search Tidal for a band named "Workout Tracks" and fail to find the song.

Adding the folder name here tells OmniTide: *"Sync these songs, but don't assume the folder name is the artist."*

```python
# Add your mix/compilation folder names here
SKIP_AS_ARTIST: set[str] = {"Workout Tracks", "Summer 2024", "misc"}
```

### `SKIP_PLAYLISTS` — Ignore folders entirely

**What it does:** Completely skips these folders during sync.

**Why you need it:** If you have folders containing audiobooks, voice memos, or playlists you've already imported and don't want touched again, add them here to save time.

```python
# OmniTide will completely ignore these folders
SKIP_PLAYLISTS: set[str] = {"Audiobooks", "Voice Records", "My Perfect Playlist"}
```

---

## Downloading from Tidal

Paste any Tidal URL for a track, album, or playlist:

```bash
# Single track
python OmniTide.py --download "https://tidal.com/browse/track/12345678"

# Album
python OmniTide.py --download "https://tidal.com/browse/album/12345678"

# Playlist
python OmniTide.py --download "https://tidal.com/browse/playlist/xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx"
```

Files are saved to `~/Tidal Download/` and organised as:

```
~/Tidal Download/
  Tracks/
    Artist - Title.flac
  Albums/
    Artist - Album Name/
      01. Artist - Title.flac
  Playlists/
    Playlist Name/
      01. Artist - Title.flac
```

Each file includes full metadata: title, artist, album artist, track number, disc number, year, ISRC, copyright, and album art.

> Encrypted streams (Hi-Res / Dolby Atmos) are not supported. Standard FLAC streams work fine on all Tidal plans.

---

## Running sync and download together

```bash
python OmniTide.py --sync --download "https://tidal.com/browse/album/12345678"
```

---

## All options

| Flag | Description |
|---|---|
| `--sync` | Scan Android phone and sync to Tidal playlists |
| `--itunes` | Sync from iTunes / Apple Music library |
| `--itunes-path PATH` | Path to iTunes Library XML (auto-detected if not provided) |
| `--download URL` | Download a track, album, or playlist from Tidal |
| `--only NAME` | Only sync playlists whose name contains NAME |
| `--rescan` | Force re-scan phone even if `song_files.txt` already exists |
| `--keep-existing` | Don't delete and replace existing same-name Tidal playlists |

---

## Building the binary yourself

```bash
pip install pyinstaller
pyinstaller --onefile OmniTide.py
```

The binary will be at `dist/OmniTide`. It runs on the same OS and architecture it was built on — build on Linux for Linux, Windows for Windows.

---

## Troubleshooting

**Login prompt appears every run / 401 errors**
Delete `token.json` and run again. A fresh login will be performed automatically.

**ADB says "no devices" or "unauthorized"**
Make sure USB Debugging is enabled and you've accepted the authorisation prompt on your phone. Run `adb devices` to check the connection. Try unplugging and reconnecting the USB cable.

**Songs not found or wrong songs added**
Run MusicBrainz Picard on your library to fix tags before syncing. After a sync run, check `unmatched_songs.txt` for a full list of everything that wasn't found.

**ffmpeg not found**
Make sure ffmpeg is installed and on your PATH. On Linux: `sudo pacman -S ffmpeg` or `sudo apt install ffmpeg`. Downloads will still work without it but the seekbar may be broken in some players.

**iTunes library not found**
On macOS, make sure **Share iTunes Library XML** is enabled under Music → Settings → Advanced. Or pass the path manually with `--itunes-path`.

**Venv broken after Python update**
Delete the venv folder (`rm -rf ~/OmniTide_Env` on Linux/macOS, or delete the `OmniTide_Env` folder on Windows) and recreate it following the venv instructions above. Your `token.json` and `song_files.txt` are safe.

**Download stops partway through**
Re-run the same command. Already-downloaded files are skipped automatically so it picks up where it left off.

---

## Disclaimer

> This project is strictly for educational and personal archival purposes.
>
> You must have an active Tidal subscription to use this tool. Do not use OmniTide to distribute copyrighted material, bypass DRM for piracy, or violate Tidal's Terms of Service.
>
> The developers assume no liability for how this tool is used or any potential account bans resulting from excessive API calls. Use at your own risk.
