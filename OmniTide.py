#!/usr/bin/env bash
""":"
VENV_PY="$(dirname "$0")/OmniTide_Env/bin/python3"
if [ -x "$VENV_PY" ]; then
    exec "$VENV_PY" "$0" "$@"
fi
exec python3 "$0" "$@"
":"""
"""
OmniTide: Phone Sync & Downloader

Usage:
  ./OmniTide.py login
  ./OmniTide.py sync phone [--only NAME] [--cache-file FILE] [--read-tags]
  ./OmniTide.py sync itunes [--path XML] [--only NAME] [--cache-file FILE]
  ./OmniTide.py backup [--to {phone,itunes,folder}] [--dest DIR] [--cache-file FILE]
  ./OmniTide.py download URL [--dest DIR]
"""

import argparse
import io
import json
import os
import pathlib
import plistlib
import random
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
from collections import defaultdict
from datetime import datetime
from pathlib import Path

try:
    import mutagen.flac
    import mutagen.mp3
    import mutagen.mp4
    import mutagen.oggvorbis
    from mutagen.flac import Picture
    import requests
    import tidalapi
    from tidalapi import Quality
    from tidalapi.media import Track, Video
except ImportError as e:
    sys.exit(
        f"❌ Missing dependency: {e.name}\n\n"
        "Run the setup script once to install dependencies:\n\n"
        "  Linux/macOS:  ./setup_linux.sh\n"
        "  Windows:      setup_windows.bat\n"
    )

try:
    from ffmpeg import FFmpeg
except ImportError:
    FFmpeg = None

try:
    from pathvalidate import sanitize_filename as _sanitize_fn
    def sanitize(name: str) -> str:
        return _sanitize_fn(name, replacement_text="_").strip()
except ImportError:
    def sanitize(name: str) -> str:
        return re.sub(r'[<>:"/\\|?*]', "_", name).strip()


# ── Config ────────────────────────────────────────────────────────────────────

MUSIC_EXTS      = {".flac", ".mp3", ".m4a", ".aac", ".ogg", ".wav", ".wma"}
TAG_CLASS_BY_EXT = {
    ".flac": mutagen.flac.FLAC,
    ".ogg":  mutagen.oggvorbis.OggVorbis,
    ".mp3":  mutagen.mp3.MP3,
    ".m4a":  mutagen.mp4.MP4,
    ".aac":  mutagen.mp4.MP4,
}
ROOT_MUSIC_PATH   = "/sdcard/Music/"
TOKEN_PATH        = Path("token.json")
PHONE_CACHE_PATH  = Path(".omnitide_phone_cache.json")
ITUNES_CACHE_PATH = Path(".omnitide_itunes_cache.json")
UNMATCHED_PATH    = Path("unmatched_songs.txt")
FFMPEG_BIN        = "/usr/bin/ffmpeg"
CHUNK_SIZE        = 1024 * 1024
COVER_URL         = "https://resources.tidal.com/images/{uuid}/{size}x{size}.jpg"
OUTPUT_BASE       = Path.home() / "Tidal Download"
EXPLICIT_STR      = " (Explicit)"

ITUNES_BACKUP_BASE = Path.home() / "Music" / "OmniTide Backup"
PHONE_BACKUP_BASE  = "/sdcard/OmniTide Backup"   # sibling of /sdcard/Music, NOT inside it —
                                                   # scan_phone_via_adb walks /sdcard/Music, so
                                                   # backed-up files landing there would get
                                                   # picked up by the next `sync phone` as "new"
BACKUP_PHONE_CACHE_PATH  = Path(".omnitide_backup_phone_cache.json")
BACKUP_ITUNES_CACHE_PATH = Path(".omnitide_backup_itunes_cache.json")
BACKUP_FOLDER_CACHE_PATH = Path(".omnitide_backup_folder_cache.json")

SKIP_AS_ARTIST: set[str] = set()
SKIP_PLAYLISTS: set[str] = set()

ITUNES_SKIP_PLAYLISTS = {
    "library", "music", "downloaded", "recently added", "recently played",
    "top 25 most played", "purchases", "genius", "itunes dj", "music videos",
    "podcasts", "audiobooks", "movies", "tv shows", "home videos",
    "voice memos", "ringtones",
}

ITUNES_LIBRARY_PATHS = {
    "darwin": [
        Path.home() / "Music" / "Music" / "Music Library.xml",
        Path.home() / "Music" / "iTunes" / "iTunes Music Library.xml",
    ],
    "win32": [
        Path(os.environ.get("USERPROFILE", Path.home())) / "Music" / "iTunes" / "iTunes Music Library.xml",
        Path(os.environ.get("USERPROFILE", Path.home())) / "Music" / "Music" / "Music Library.xml",
    ],
}


# ── Auth (with auto‑refresh) ──────────────────────────────────────────────

def _save_token(session: tidalapi.Session, token_path: Path):
    with open(token_path, "w") as f:
        json.dump({
            "token_type":    session.token_type,
            "access_token":  session.access_token,
            "refresh_token": session.refresh_token,
            "expiry_time":   session.expiry_time.timestamp() if session.expiry_time else 0.0,
        }, f, indent=4)


def load_session(token_path: Path) -> tuple[tidalapi.Session, str]:
    if not token_path.exists():
        print("🔐 No token found — starting Tidal login...")
        session = tidalapi.Session(tidalapi.Config(quality=Quality.high_lossless))
        session.login_oauth_simple()
        if not session.check_login():
            sys.exit("❌ Login failed.")
        _save_token(session, token_path)
        print("✅ Logged in and token saved.\n")
        return session, session.access_token

    with open(token_path) as f:
        data = json.load(f)

    session = tidalapi.Session(tidalapi.Config(quality=Quality.high_lossless))

    retries = 3
    logged_in = False
    for attempt in range(1, retries + 1):
        try:
            session.load_oauth_session(
                token_type    = data["token_type"],
                access_token  = data["access_token"],
                refresh_token = data["refresh_token"],
                expiry_time   = datetime.fromtimestamp(data["expiry_time"]),
            )
            logged_in = session.check_login()
            break
        except (requests.exceptions.ConnectionError, requests.exceptions.Timeout, requests.exceptions.SSLError) as e:
            print(f"⚠️  Network error contacting Tidal (attempt {attempt}/{retries}): {e}")
            if attempt == retries:
                sys.exit("❌ Could not reach Tidal after several attempts. Check your connection and try again.")
            time.sleep(3)

    # ---- Auto‑refresh if token is expired or invalid ----
    if not logged_in:
        print("❌ Session invalid or expired.")
        print("🔄 Deleting token.json – please re-run `login`.")
        token_path.unlink(missing_ok=True)
        sys.exit(1)


    _save_token(session, token_path)
    name = getattr(session.user, "name", None) or str(session.user.id)
    print(f"✅ Logged in as: {name}\n")
    return session, session.access_token


# ── Song list: ADB scan ───────────────────────────────────────────────────────

def _clean_filename(filename: str) -> tuple[str, str]:
    filename = re.sub(r"^\d+[\.\-\s]+\s*", "", filename)
    filename = re.sub(r"\s*\(Explicit\)\s*$", "", filename, flags=re.IGNORECASE)
    filename = re.sub(r"\s*\(Live At[^)]*\)\s*$", "", filename, flags=re.IGNORECASE)
    filename = re.sub(r"\s*- Bonus Track\s*$", "", filename, flags=re.IGNORECASE)
    if " - " in filename:
        artist, title = filename.split(" - ", 1)
        return artist.strip(), title.strip()
    return "", filename.strip()


def _clean_folder(folder: str) -> str:
    name = re.sub(r"\s*\(Explicit\)\s*$", "", folder, flags=re.IGNORECASE)
    name = re.sub(r"\s*[-–]\s*(Deluxe.*|Original.*|Remaster.*)$", "", name, flags=re.IGNORECASE)
    return name.strip()


# ── Tag extraction (Vorbis comments, ID3, MP4) ──────────────────────────────

def _extract_tags(audio) -> tuple[str, str, str]:
    """Best-effort (artist, title, tidal_id) from a mutagen file object.

    Handles Vorbis comments (FLAC/OGG), ID3 (MP3), and MP4 (M4A/AAC) tag
    schemes, since mutagen exposes different keys per format. Missing values
    come back as "".
    """
    if audio is None:
        return "", "", ""

    def first(*keys) -> str:
        for key in keys:
            if key not in audio:
                continue
            val = audio[key]
            if hasattr(val, "text"):  # ID3 text frame
                val = val.text
            if isinstance(val, list):
                return str(val[0]) if val else ""
            return str(val)
        return ""

    artist   = first("ARTIST", "TPE1", "\xa9ART")
    title    = first("TITLE", "TIT2", "\xa9nam")
    tidal_id = first("TIDALID", "TXXX:TIDALID")
    return artist, title, tidal_id


def _read_remote_tags(remote_path: str, chunk_size: int = 2 * 1024 * 1024) -> tuple[str, str, str]:
    """Best-effort tag read from a phone file via a partial ADB pull.

    Only fetches the first chunk_size bytes (tags live near the start of the
    file for every format we care about) instead of the whole file, then lets
    mutagen parse that in memory. Returns ("", "", "") on any failure so
    callers can fall back to filename parsing.

    Picks the mutagen class from the file extension rather than using
    mutagen.File()'s content-sniffing auto-detect: on a nameless, truncated
    BytesIO buffer that auto-detect misidentifies FLAC files as MP4 and raises
    instead of falling through, even though the bytes are perfectly valid.
    """
    tag_class = TAG_CLASS_BY_EXT.get(Path(remote_path).suffix.lower())
    if tag_class is None:
        return "", "", ""
    proc = None
    try:
        proc = subprocess.Popen(["adb", "exec-out", "cat", remote_path], stdout=subprocess.PIPE)
        data = proc.stdout.read(chunk_size)
        if not data:
            return "", "", ""
        return _extract_tags(tag_class(io.BytesIO(data)))
    except Exception:
        return "", "", ""
    finally:
        if proc is not None:
            try:
                proc.stdout.close()
            except Exception:
                pass
            proc.terminate()
            try:
                proc.wait(timeout=2)
            except Exception:
                proc.kill()


# ── Incremental-sync cache (shared by phone/iTunes sync and backup) ─────────

def load_cache(cache_path: Path) -> dict[str, dict[str, str]]:
    if not cache_path.exists():
        return {}
    try:
        with open(cache_path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_cache(cache_path: Path, cache: dict[str, dict[str, str]]) -> None:
    fd, tmp_path = tempfile.mkstemp(dir=cache_path.parent, prefix=".omnitide_cache_")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(cache, f, indent=2)
        os.replace(tmp_path, cache_path)
    except Exception:
        Path(tmp_path).unlink(missing_ok=True)
        raise


def scan_phone_via_adb(read_tags: bool = False) -> dict[str, dict[str, str]]:
    """Scans /sdcard/Music via ADB and returns {phone_path: {artist, title, tidal_id, playlist}}."""
    print("📱 Scanning phone via ADB...")
    try:
        result = subprocess.run(
            ["adb", "shell", "find", "/sdcard/Music", "-type", "f"],
            capture_output=True, text=True, timeout=60
        )
        if result.returncode != 0 or not result.stdout.strip():
            sys.exit(f"❌ ADB scan failed: {result.stderr.strip()}")
    except FileNotFoundError:
        sys.exit("❌ ADB not found. Install android-tools and connect your phone.")

    scanned: dict[str, dict[str, str]] = {}
    tagged = 0
    for line in result.stdout.splitlines():
        path = line.strip()
        if not path or Path(path).suffix.lower() not in MUSIC_EXTS:
            continue
        filename = Path(path).stem
        relative = path.replace(ROOT_MUSIC_PATH, "")
        parts    = relative.split("/")
        folder   = parts[0] if len(parts) > 1 else "Misc"
        playlist = _clean_folder(folder)

        artist = title = tidal_id = ""
        if read_tags:
            artist, title, tidal_id = _read_remote_tags(path)
        if artist and title:
            tagged += 1
        else:
            f_artist, f_title = _clean_filename(filename)
            artist, title = artist or f_artist, title or f_title

        if not artist:
            if not any(s in folder.lower() for s in SKIP_AS_ARTIST):
                artist = folder.split(" - ")[0].strip()

        scanned[path] = {"artist": artist, "title": title, "tidal_id": tidal_id, "playlist": playlist}

    tag_note = f", {tagged} via embedded tags" if read_tags else ""
    print(f"✅ Found {len(scanned)} songs on phone{tag_note}\n")
    return scanned


# ── Tidal search & add (individual, robust) ───────────────────────────────

def _artist_match(artist_lower: str, track_artists: list[str]) -> bool:
    if not artist_lower:
        return True
    return any(artist_lower in a or a in artist_lower for a in track_artists)


def _title_match(title_lower: str, track_name: str) -> bool:
    t = track_name.lower()
    return title_lower in t or t in title_lower


def search_track(session: tidalapi.Session, artist: str, title: str,
                 tidal_id: str | None = None, retries: int = 3):
    if tidal_id:
        try:
            track = session.track(tidal_id)
            if track:
                return track
        except Exception:
            pass
        print(f"    ⚠️  Tidal ID {tidal_id} not found — falling back to search")

    query = f"{artist} {title}" if artist else title
    title_lower = title.lower()
    artist_lower = artist.lower()
    for attempt in range(1, retries + 1):
        try:
            results = session.search(query, models=[tidalapi.Track], limit=10)
            tracks = results.get("tracks", [])
            if not tracks:
                return None
            for track in tracks:
                ta = [a.name.lower() for a in track.artists]
                if _title_match(title_lower, track.name) and _artist_match(artist_lower, ta):
                    return track
            if artist_lower:
                for track in tracks:
                    ta = [a.name.lower() for a in track.artists]
                    if _artist_match(artist_lower, ta):
                        print(f"    ⚠️  Loose match: '{track.name}' by {', '.join(a.name for a in track.artists)}")
                        return track
                return None
            return tracks[0]
        except Exception as e:
            print(f"    ⚠️  Search error (attempt {attempt}/{retries}): {e}")
            if attempt < retries:
                time.sleep(3)
    return None


def add_track_with_retry(session: tidalapi.Session, access_token: str, playlist,
                         track_id: int, retries: int = 3, delay: float = 5.0) -> bool:
    """
    Add a single track with retries.
    If we get 401, refresh the session via check_login() and retry.
    """
    for attempt in range(1, retries + 1):
        try:
            # Use form data, not JSON (the API expects application/x-www-form-urlencoded)
            raw = session.request_session.post(
                f"https://api.tidal.com/v1/playlists/{playlist.id}/items",
                params={
                    "sessionId": session.session_id,
                    "countryCode": session.country_code,
                    "limit": 100
                },
                data={
                    "onArtifactNotFound": "SKIP",
                    "trackIds": str(track_id),          # send as string, as before
                    "toIndex": playlist.num_tracks,
                    "onDupes": "ADD"
                },
                headers={
                    "If-None-Match": "*",
                    "Authorization": f"Bearer {access_token}"
                },
            )

            if raw.status_code == 401:
                print("    🔄 Token expired, refreshing session...")
                if session.check_login():
                    access_token = session.access_token
                    _save_token(session, TOKEN_PATH)
                    print("    ✅ Token refreshed, retrying...")
                    time.sleep(2)
                    continue
                else:
                    print("    ❌ Failed to refresh token.")
                    return False

            if raw.status_code == 429:
                wait = delay * 2
                print(f"    ⚠️  Rate limited, waiting {wait:.1f}s...")
                time.sleep(wait)
                continue

            if raw.status_code >= 500:
                print(f"    ⚠️  Server error {raw.status_code}, retrying...")
                if attempt < retries:
                    time.sleep(delay)
                    continue
                return False

            if not raw.ok:
                print(f"    ⚠️  HTTP {raw.status_code} (attempt {attempt}/{retries})")
                # If we get 400, we might want to see the response body for debugging
                if raw.status_code == 400:
                    print(f"    ⚠️  Response body: {raw.text[:200]}")
                if attempt < retries:
                    time.sleep(delay)
                    continue
                return False

            # Success
            resp = raw.json()
            if track_id in resp.get("addedItemIds", []):
                playlist.num_tracks += 1
                return True
            else:
                print(f"    ⚠️  Track {track_id} not added (already in playlist?)")
                return False

        except (requests.exceptions.ConnectionError, requests.exceptions.Timeout) as e:
            print(f"    ⚠️  Network error (attempt {attempt}/{retries}): {e}")
            if attempt < retries:
                time.sleep(delay * 2)
            else:
                return False
        except Exception as e:
            print(f"    ⚠️  Unexpected error (attempt {attempt}/{retries}): {e}")
            if attempt < retries:
                time.sleep(delay)
            else:
                return False

    return False


def _find_owned_playlist(session: tidalapi.Session, name: str):
    """Returns the caller's own playlist named `name`, or None."""
    try:
        for pl in session.user.playlist_and_favorite_playlists():
            if getattr(pl, "name", None) == name and getattr(pl, "creator", None):
                if pl.creator.id == session.user.id:
                    return pl
    except Exception as e:
        print(f"    ⚠️  Could not check existing playlists: {e}")
    return None


def get_or_create_playlist(session: tidalapi.Session, name: str, keep_existing: bool):
    existing = _find_owned_playlist(session, name)

    if existing:
        if keep_existing:
            print(f"    ➕ Adding to existing '{name}'")
            return existing
        print(f"    ♻️  Replacing existing '{name}'")
        existing.delete()
        time.sleep(1)

    pl = session.user.create_playlist(name, "")
    pl.num_tracks = 0
    return pl


# ── iTunes parser ─────────────────────────────────────────────────────────────

def find_itunes_library() -> Path | None:
    candidates = ITUNES_LIBRARY_PATHS.get(sys.platform, [])
    return next((p for p in candidates if p.exists()), None)


def parse_itunes_library(xml_path: Path) -> dict[str, dict[str, str]]:
    """Returns {itunes_track_id: {artist, title, tidal_id: "", playlist}}."""
    print(f"📖 Reading iTunes library: {xml_path}")
    with open(xml_path, "rb") as f:
        library = plistlib.load(f)
    raw_tracks = library.get("Tracks", {})
    tracks: dict[str, tuple[str, str]] = {}
    for tid, info in raw_tracks.items():
        if any(x in info.get("Kind", "").lower() for x in ["podcast", "video", "audiobook", "book"]):
            continue
        name = info.get("Name", "").strip()
        if not name:
            continue
        tracks[tid] = (info.get("Artist", "").strip(), name)

    playlist_tracks: dict[str, list[str]] = {}
    for pl in library.get("Playlists", []):
        name = pl.get("Name", "").strip()
        if name.lower() in ITUNES_SKIP_PLAYLISTS:
            continue
        if pl.get("Master") or pl.get("Distinguished Kind") or pl.get("Smart Info"):
            continue
        items = [str(i.get("Track ID", "")) for i in pl.get("Playlist Items", []) if str(i.get("Track ID", "")) in tracks]
        if items:
            playlist_tracks[name] = items

    seen: set[str] = set()
    scanned: dict[str, dict[str, str]] = {}
    for pl_name, ids in playlist_tracks.items():
        for tid in ids:
            if tid in seen:
                continue
            seen.add(tid)
            artist, title = tracks[tid]
            scanned[tid] = {"artist": artist, "title": title, "tidal_id": "", "playlist": pl_name}
    for tid, (artist, title) in tracks.items():
        if tid in seen:
            continue
        scanned[tid] = {"artist": artist, "title": title, "tidal_id": "", "playlist": "Music"}
    playlists = {r["playlist"] for r in scanned.values()}
    print(f"✅ Found {len(scanned)} tracks across {len(playlists)} playlists\n")
    return scanned


# ── Incremental sync engine (shared by phone and iTunes sync) ───────────────

def sync_incremental(session: tidalapi.Session, access_token: str,
                     scanned: dict[str, dict[str, str]], cache_path: Path,
                     only: str | None, source_label: str):
    cache = load_cache(cache_path)

    def selected(playlist_name: str) -> bool:
        if playlist_name in SKIP_PLAYLISTS:
            return False
        if only:
            return only.lower() in playlist_name.lower()
        return True

    scanned_selected = {p: r for p, r in scanned.items() if selected(r["playlist"])}
    cache_selected    = {p: r for p, r in cache.items() if selected(r["playlist"])}
    cache_unselected  = {p: r for p, r in cache.items() if not selected(r["playlist"])}

    if only and not scanned_selected and not cache_selected:
        print(f"❌ No playlists matching '{only}'")
        return

    new, unchanged, removed = diff_scan(scanned_selected, cache_selected)

    new_by_playlist: dict[str, list[tuple[str, dict]]] = defaultdict(list)
    for item_id, rec in new.items():
        new_by_playlist[rec["playlist"]].append((item_id, rec))

    removed_by_playlist: dict[str, list[tuple[str, dict]]] = defaultdict(list)
    for item_id, rec in removed.items():
        removed_by_playlist[rec["playlist"]].append((item_id, rec))

    final_cache = {**cache_unselected, **unchanged}

    playlist_names = sorted(set(new_by_playlist) | set(removed_by_playlist))
    if not playlist_names:
        print("✅ Nothing changed since the last scan.\n")
        save_cache(cache_path, final_cache)
        return

    all_unmatched = []
    current_token = access_token

    for playlist_name in playlist_names:
        new_entries = new_by_playlist.get(playlist_name, [])
        removed_entries = removed_by_playlist.get(playlist_name, [])

        print(f"\n{'─'*55}")
        print(f"🎵  '{playlist_name}'  (+{len(new_entries)} new, -{len(removed_entries)} gone)")
        print(f"{'─'*55}")

        if new_entries:
            tidal_pl = get_or_create_playlist(session, playlist_name, keep_existing=True)
            track_ids_to_add = []
            item_by_track_id = {}
            for i, (item_id, rec) in enumerate(new_entries, 1):
                display = f"{rec['artist']} - {rec['title']}" if rec["artist"] else rec["title"]
                print(f"  [{i}/{len(new_entries)}] {display}")
                track = search_track(session, rec["artist"], rec["title"], rec["tidal_id"] or None)
                time.sleep(0.5)
                if not track:
                    print(f"    ❌ No match")
                    all_unmatched.append(f"[{source_label}] [{playlist_name}] {display}")
                    continue
                print(f"    🔍 {', '.join(a.name for a in track.artists)} - {track.name}")
                track_ids_to_add.append(track.id)
                item_by_track_id[track.id] = (item_id, rec)

            if track_ids_to_add:
                print(f"  ➕ Adding {len(track_ids_to_add)} tracks in batches...")
                added_ids = add_tracks_batch(session, current_token, tidal_pl, track_ids_to_add)
                print(f"  ✅ {len(added_ids)} added  |  💀 {len(track_ids_to_add) - len(added_ids)} failed")
                current_token = session.access_token
                for tid in added_ids:
                    item_id, rec = item_by_track_id[tid]
                    final_cache[item_id] = {**rec, "tidal_id": str(tid)}

        if removed_entries:
            tidal_pl = _find_owned_playlist(session, playlist_name)
            if tidal_pl and confirm_removal(source_label, playlist_name, len(removed_entries)):
                ids_to_remove = [rec["tidal_id"] for _, rec in removed_entries if rec.get("tidal_id")]
                if ids_to_remove:
                    remove_tracks_from_playlist(tidal_pl, ids_to_remove)
                    print(f"    🗑️  Removed {len(ids_to_remove)} track(s) from '{playlist_name}'")
                    if len(tidal_pl.tracks()) == 0:
                        tidal_pl.delete()
                        print(f"    🗑️  '{playlist_name}' is now empty — deleted from Tidal")
            # Either way, these items are gone from the source and drop out of the cache below.

    save_cache(cache_path, final_cache)

    if all_unmatched:
        UNMATCHED_PATH.write_text("\n".join(all_unmatched), encoding="utf-8")
        print(f"\n📄 Unmatched saved to: {UNMATCHED_PATH}")

    print(f"\n{'='*55}")
    print(f"  DONE — {len(new)} new  {len(removed)} gone  {len(unchanged)} unchanged")
    print(f"{'='*55}")


def sync_phone(session: tidalapi.Session, access_token: str,
              only: str | None, read_tags: bool, cache_path: Path):
    scanned = scan_phone_via_adb(read_tags=read_tags)
    sync_incremental(session, access_token, scanned, cache_path, only, source_label="phone")


def sync_itunes(session: tidalapi.Session, access_token: str,
                only: str | None, itunes_path: str | None, cache_path: Path):
    xml_path = Path(itunes_path) if itunes_path else find_itunes_library()
    if not xml_path or not xml_path.exists():
        sys.exit("❌ iTunes library not found. Use --path to specify it.")
    scanned = parse_itunes_library(xml_path)
    sync_incremental(session, access_token, scanned, cache_path, only, source_label="iTunes")

# ── Batch Upload ────────────────────────────────────────

def add_tracks_batch(session: tidalapi.Session, access_token: str, playlist,
                     track_ids: list[int], retries: int = 3, delay: float = 5.0) -> list[int]:
    """
    Add multiple tracks in one API call (up to 50 per request).
    Uses form data (not JSON). Returns list of track IDs that were actually added.
    """
    if not track_ids:
        return []
    chunk_size = 50
    added = []
    for i in range(0, len(track_ids), chunk_size):
        chunk = track_ids[i:i+chunk_size]
        ids_str = ",".join(str(tid) for tid in chunk)  # comma-separated
        success = False
        for attempt in range(1, retries + 1):
            try:
                raw = session.request_session.post(
                    f"https://api.tidal.com/v1/playlists/{playlist.id}/items",
                    params={
                        "sessionId": session.session_id,
                        "countryCode": session.country_code,
                        "limit": 100
                    },
                    data={
                        "onArtifactNotFound": "SKIP",
                        "trackIds": ids_str,
                        "toIndex": playlist.num_tracks,
                        "onDupes": "ADD"
                    },
                    headers={
                        "If-None-Match": "*",
                        "Authorization": f"Bearer {access_token}"
                    },
                )

                if raw.status_code == 401:
                    print("    🔄 Token expired, refreshing...")
                    if session.check_login():
                        access_token = session.access_token
                        _save_token(session, TOKEN_PATH)
                        print("    ✅ Token refreshed, retrying chunk...")
                        time.sleep(2)
                        continue
                    else:
                        print("    ❌ Failed to refresh token – falling back to individual adds...")
                        break  # break retry, go to fallback

                if raw.status_code == 429:
                    wait = delay * 2
                    print(f"    ⚠️  Rate limited, waiting {wait:.1f}s...")
                    time.sleep(wait)
                    continue

                if raw.status_code >= 500:
                    print(f"    ⚠️  Server error {raw.status_code}, retrying chunk...")
                    if attempt < retries:
                        time.sleep(delay)
                        continue
                    else:
                        print("    ⤵️  Falling back to individual adds for this chunk...")
                        break  # fallback

                if raw.status_code == 400:
                    print(f"    ⚠️  Batch 400 – falling back to individual adds for this chunk...")
                    break  # fallback

                if not raw.ok:
                    print(f"    ⚠️  Batch HTTP {raw.status_code} (attempt {attempt}/{retries})")
                    if attempt < retries:
                        time.sleep(delay)
                        continue
                    else:
                        print("    ⤵️  Falling back to individual adds for this chunk...")
                        break  # fallback

                # Success
                resp = raw.json()
                added_ids = resp.get("addedItemIds", [])
                added.extend(added_ids)
                playlist.num_tracks += len(added_ids)
                success = True
                break  # chunk done

            except (requests.exceptions.ConnectionError, requests.exceptions.Timeout) as e:
                print(f"    ⚠️  Network error (attempt {attempt}/{retries}): {e}")
                if attempt < retries:
                    time.sleep(delay * 2)
                else:
                    print("    ⤵️  Falling back to individual adds for this chunk...")
                    break
            except Exception as e:
                print(f"    ⚠️  Batch exception (attempt {attempt}/{retries}): {e}")
                if attempt < retries:
                    time.sleep(delay)
                else:
                    print("    ⤵️  Falling back to individual adds for this chunk...")
                    break

        # If batch failed for this chunk, add individually
        if not success:
            for tid in chunk:
                if add_track_with_retry(session, access_token, playlist, tid, retries=1, delay=1):
                    added.append(tid)

        time.sleep(1)  # short delay between chunks

    return added


# ── Diff & removal helpers (used by sync_incremental) ───────────────────────

def diff_scan(scanned: dict[str, dict[str, str]],
              cache: dict[str, dict[str, str]]) -> tuple[dict, dict, dict]:
    """Returns (new, unchanged, removed) — each a {item_id: record} subset.

    "unchanged" keeps the cache's record (it already has a resolved tidal_id
    from a previous successful match) rather than the fresh scan's record —
    a plain rescan never re-resolves IDs on its own, so using the scanned
    record here would silently wipe out IDs already known to be correct. The
    one case where the fresh scan wins is when it found a tidal_id (e.g. via
    --read-tags on a phone rescan) that the cache didn't have yet.
    """
    new = {p: r for p, r in scanned.items() if p not in cache}
    unchanged = {}
    for p, cached_rec in cache.items():
        if p not in scanned:
            continue
        merged = dict(cached_rec)
        if not merged.get("tidal_id") and scanned[p].get("tidal_id"):
            merged["tidal_id"] = scanned[p]["tidal_id"]
        unchanged[p] = merged
    removed = {p: r for p, r in cache.items() if p not in scanned}
    return new, unchanged, removed


def confirm_removal(source_label: str, playlist_name: str, count: int) -> bool:
    if not sys.stdin.isatty():
        print(f"    ⚠️  {count} track(s) gone from {source_label} for '{playlist_name}' — "
              f"not removing from Tidal (no interactive terminal to confirm).")
        return False
    answer = input(f"    {count} track(s) gone from {source_label} for '{playlist_name}'. "
                   f"Remove them from the Tidal playlist too? [y/N] ").strip().lower()
    return answer == "y"


def remove_tracks_from_playlist(playlist, track_ids: list[str]) -> bool:
    return playlist.delete_by_id([str(t) for t in track_ids])



# ── Download engine (embeds Tidal ID) ────────────────────────────────────────

def explicit_tag(is_explicit: bool) -> str:
    return EXPLICIT_STR if is_explicit else ""


def cover_bytes(album) -> bytes | None:
    try:
        uuid = album.cover.replace("-", "/")
        with urllib.request.urlopen(COVER_URL.format(uuid=uuid, size=1280), timeout=15) as r:
            return r.read()
    except Exception:
        return None


def _download_segments(urls: list[str], dest: pathlib.Path) -> bool:
    try:
        with open(dest, "wb") as out:
            for url in urls:
                with urllib.request.urlopen(url, timeout=60) as r:
                    while True:
                        chunk = r.read(CHUNK_SIZE)
                        if not chunk: break
                        out.write(chunk)
        return True
    except Exception as e:
        print(f"  ❌ Download error: {e}")
        return False


def _ffmpeg_remux(src: pathlib.Path, dst: pathlib.Path):
    if FFmpeg is None:
        print("  ⚠️  python-ffmpeg not installed — skipping remux")
        shutil.copy2(src, dst)
        return
    codec = "copy" if src.suffix.lower() == ".flac" else "flac"
    try:
        (FFmpeg(executable=FFMPEG_BIN)
         .option("y").option("hide_banner").option("nostdin")
         .input(url=str(src))
         .output(url=str(dst), acodec=codec, map=0, map_metadata="0:g",
                 movflags="use_metadata_tags", loglevel="quiet")
         .execute())
    except Exception as e:
        print(f"  ⚠️  ffmpeg error: {e} — falling back to copy")
        shutil.copy2(src, dst)


def _embed_metadata(path_file: pathlib.Path, track: Track, cover: bytes | None):
    try:
        m = mutagen.flac.FLAC(str(path_file))
        album = track.album
        if not m.tags: m.add_tags()
        artists    = ", ".join(a.name for a in track.artists)
        alb_artist = ", ".join(
            a.name for a in album.artists
            if any("MAIN" in str(r).upper() for r in getattr(a, "roles", []))
        ) if album and hasattr(album, "artists") else artists
        if not alb_artist: alb_artist = artists
        m.tags["TITLE"]       = track.full_name if hasattr(track, "full_name") else track.name
        m.tags["ARTIST"]      = artists
        m.tags["ALBUMARTIST"] = alb_artist
        m.tags["ALBUM"]       = album.name if album else ""
        m.tags["TRACKNUMBER"] = str(getattr(track, "track_num",  0))
        m.tags["TRACKTOTAL"]  = str(getattr(album, "num_tracks",  0) if album else 0)
        m.tags["DISCNUMBER"]  = str(getattr(track, "volume_num", 1))
        m.tags["DISCTOTAL"]   = str(getattr(album, "num_volumes", 1) if album else 1)
        m.tags["DATE"]        = str(album.release_date.year) if album and getattr(album, "release_date", None) else ""
        m.tags["ISRC"]        = getattr(track, "isrc",      "") or ""
        m.tags["COPYRIGHT"]   = getattr(track, "copyright", "") or ""
        m.tags["TIDALID"] = str(track.id)
        if cover:
            pic = Picture()
            pic.type, pic.mime, pic.data = 3, "image/jpeg", cover
            m.clear_pictures()
            m.add_picture(pic)
        m.save()
    except Exception as e:
        print(f"  ⚠️  Metadata error: {e}")


def download_track(session: tidalapi.Session, track: Track, dest_no_ext: pathlib.Path) -> bool:
    dest_final = pathlib.Path(str(dest_no_ext) + ".flac")
    if dest_final.exists():
        print(f"  ↪️  Exists: {dest_final.name}")
        return True
    if not getattr(track, "allow_streaming", False):
        print(f"  ⚠️  Not streamable: {track.name}")
        return False
    try:
        full_track = session.track(str(track.id), with_album=True)
        manifest   = full_track.get_stream().get_stream_manifest()
    except Exception as e:
        print(f"  ❌ Stream error: {e}")
        return False
    if manifest.is_encrypted:
        print(f"  ⚠️  Encrypted stream — skipping")
        return False
    dest_final.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(suffix=manifest.file_extension, delete=False) as tmp:
        tmp_path = pathlib.Path(tmp.name)
    print(f"  ⬇️  {full_track.name} ({len(manifest.get_urls())} segment(s))")
    if not _download_segments(manifest.get_urls(), tmp_path):
        tmp_path.unlink(missing_ok=True)
        return False
    print(f"  🔧 Remuxing...")
    _ffmpeg_remux(tmp_path, dest_final)
    tmp_path.unlink(missing_ok=True)
    if not dest_final.exists():
        print(f"  ❌ Output file not created")
        return False
    _embed_metadata(dest_final, full_track, cover_bytes(full_track.album) if full_track.album else None)
    print(f"  ✅ {dest_final.name}")
    time.sleep(random.uniform(2, 8))
    return True


def parse_tidal_url(url: str) -> tuple[str, str]:
    url   = re.sub(r"[?#].*$", "", url.strip())
    match = re.search(r"tidal\.com/(?:browse/)?(track|album|playlist|mix)/([a-zA-Z0-9\-]+)", url)
    if not match:
        sys.exit(f"❌ Could not parse URL: {url}")
    return match.group(1), match.group(2)


def process_download(session: tidalapi.Session, url: str):
    media_type, media_id = parse_tidal_url(url)
    print(f"\n🔍 {media_type}  (id: {media_id})")
    print(f"📁 Output: {OUTPUT_BASE}\n")
    if media_type == "track":
        track = session.track(media_id, with_album=True)
        artist = sanitize(", ".join(a.name for a in track.artists))
        title  = sanitize(track.full_name if hasattr(track, "full_name") else track.name)
        exp    = explicit_tag(getattr(track, "explicit", False))
        download_track(session, track, OUTPUT_BASE / "Tracks" / f"{artist} - {title}{exp}")
    elif media_type == "album":
        album  = session.album(media_id)
        tracks = album.tracks()
        alb_artist  = sanitize(album.artist.name if getattr(album, "artist", None) else "Unknown")
        alb_title   = sanitize(album.name)
        alb_exp     = explicit_tag(getattr(album, "explicit", False))
        num_volumes = getattr(album, "num_volumes", 1) or 1
        width       = max(2, len(str(len(tracks))))
        print(f"💿 {album.name} — {len(tracks)} track(s)")
        for i, track in enumerate(tracks, 1):
            print(f"\n  [{i}/{len(tracks)}] {track.name}")
            disc_prefix = f"{getattr(track, 'volume_num', 1)}-" if num_volumes > 1 else ""
            num    = f"{disc_prefix}{str(getattr(track, 'track_num', i)).zfill(width)}"
            artist = sanitize(", ".join(a.name for a in track.artists))
            title  = sanitize(track.full_name if hasattr(track, "full_name") else track.name)
            exp    = explicit_tag(getattr(track, "explicit", False))
            dest   = OUTPUT_BASE / "Albums" / f"{alb_artist} - {alb_title}{alb_exp}" / f"{num}. {artist} - {title}{exp}"
            download_track(session, track, dest)
    elif media_type in ("playlist", "mix"):
        playlist = session.playlist(media_id)
        items    = playlist.tracks()
        pl_name  = sanitize(playlist.name)
        width    = max(2, len(str(len(items))))
        print(f"📋 {playlist.name} — {len(items)} track(s)")
        for i, track in enumerate(items, 1):
            if isinstance(track, Video):
                print(f"  [{i}] ⏭️  Skipping video")
                continue
            print(f"\n  [{i}/{len(items)}] {track.name}")
            artist = sanitize(", ".join(a.name for a in track.artists))
            title  = sanitize(track.full_name if hasattr(track, "full_name") else track.name)
            dest   = OUTPUT_BASE / "Playlists" / pl_name / f"{str(i).zfill(width)}. {artist} - {title}"
            download_track(session, track, dest)
    else:
        sys.exit(f"❌ Unsupported type: {media_type}")


# ── Backup: download the whole Tidal account ─────────────────────────────────

def _iter_owned_playlists(session: tidalapi.Session):
    """Yields every playlist owned by the logged-in user, paginating past
    Tidal's 50-per-page cap on playlist_and_favorite_playlists()."""
    offset, limit = 0, 50
    while True:
        page = session.user.playlist_and_favorite_playlists(offset=offset, limit=limit)
        if not page:
            return
        for pl in page:
            if getattr(pl, "creator", None) and pl.creator.id == session.user.id:
                yield pl
        if len(page) < limit:
            return
        offset += limit


def push_to_phone(local_path: pathlib.Path, remote_path: str) -> bool:
    """adb-pushes local_path to remote_path, creating the remote parent dir first.

    remote_path is passed through `adb shell` as part of a reconstructed remote
    command line, so its directory needs shlex.quote(); adb push's own two argv
    items never go through a remote shell, so they need no quoting at all.
    """
    remote_dir = remote_path.rsplit("/", 1)[0] if "/" in remote_path else "."
    try:
        mkdir = subprocess.run(
            ["adb", "shell", f"mkdir -p {shlex.quote(remote_dir)}"],
            capture_output=True, text=True, timeout=15,
        )
        if mkdir.returncode != 0:
            print(f"  ❌ adb mkdir failed for {remote_dir}: {mkdir.stderr.strip()}")
            return False
        push = subprocess.run(
            ["adb", "push", str(local_path), remote_path],
            capture_output=True, text=True, timeout=300,
        )
        if push.returncode != 0:
            print(f"  ❌ adb push failed for {remote_path}: {push.stderr.strip()}")
            return False
        return True
    except FileNotFoundError:
        sys.exit("❌ ADB not found. Install android-tools and connect your phone.")


def _deliver_track(session: tidalapi.Session, track: Track, dest_no_ext: pathlib.Path,
                   destination: str, remote_no_ext: str | None = None) -> bool:
    """Downloads one track and delivers it to the chosen destination.

    'itunes'/'folder': a plain download_track() call. 'phone': downloads to a
    local temp path, adb-pushes it, then deletes the local copy immediately —
    never stages more than one track's worth of local disk at a time.
    """
    if destination != "phone":
        return download_track(session, track, dest_no_ext)
    if not download_track(session, track, dest_no_ext):
        return False
    local_final = pathlib.Path(str(dest_no_ext) + ".flac")
    delivered = push_to_phone(local_final, remote_no_ext + ".flac")
    local_final.unlink(missing_ok=True)
    return delivered


def backup_tidal(session: tidalapi.Session, destination: str,
                 dest_path: Path | None, cache_path: Path) -> None:
    """Downloads every owned playlist + Liked Songs to the chosen destination.

    Liked tracks are intentionally NOT deduped against playlist tracks — a
    track that's both liked and in a playlist is delivered to both, since
    liking is its own signal independent of playlist membership. Cache keys
    are scoped per-playlist/per-liked (not bare track IDs) specifically to
    support this — a bare-ID cache would deliver a shared track once and
    incorrectly skip it the second time.

    Incremental only in the "what's new" direction — if a track is unfavorited
    or removed from a playlist on Tidal after being backed up, the local/phone
    copy and its cache entry are left untouched. Deliberate scope boundary.
    """
    cache = load_cache(cache_path)

    if destination == "phone":
        base = PHONE_BACKUP_BASE
    elif destination == "itunes":
        base = str(dest_path) if dest_path else str(ITUNES_BACKUP_BASE)
    else:
        base = str(dest_path) if dest_path else str(Path.cwd())

    tmp_dir_ctx = tempfile.TemporaryDirectory(prefix="omnitide_backup_") if destination == "phone" else None
    tmp_dir = Path(tmp_dir_ctx.name) if tmp_dir_ctx else None

    def deliver(track: Track, local_rel: pathlib.Path, remote_rel: str) -> bool:
        if destination == "phone":
            local_dest  = tmp_dir / str(track.id)
            remote_dest = f"{base}/{remote_rel}"
            return _deliver_track(session, track, local_dest, "phone", remote_dest)
        return _deliver_track(session, track, Path(base) / local_rel, destination)

    delivered_count = skipped_count = 0
    try:
        print("📋 Enumerating owned playlists...")
        playlists = list(_iter_owned_playlists(session))
        print(f"✅ Found {len(playlists)} owned playlist(s)\n")

        for pl in playlists:
            print(f"\n{'─'*55}")
            print(f"🎵  '{pl.name}'")
            print(f"{'─'*55}")
            tracks = pl.tracks_paginated()
            width = max(2, len(str(len(tracks))))
            for i, track in enumerate(tracks, 1):
                if isinstance(track, Video):
                    continue
                scope = f"playlist::{pl.name}"
                key = f"{scope}::{track.id}"
                if key in cache:
                    skipped_count += 1
                    continue
                artist = sanitize(", ".join(a.name for a in track.artists))
                title  = sanitize(track.full_name if hasattr(track, "full_name") else track.name)
                fname  = f"{str(i).zfill(width)}. {artist} - {title}"
                print(f"  [{i}/{len(tracks)}] {artist} - {title}")
                local_rel  = pathlib.Path("Playlists") / sanitize(pl.name) / fname
                remote_rel = f"Playlists/{sanitize(pl.name)}/{fname}"
                if deliver(track, local_rel, remote_rel):
                    cache[key] = {"tidal_id": str(track.id), "artist": artist, "title": title, "playlist": scope}
                    save_cache(cache_path, cache)
                    delivered_count += 1

        print(f"\n{'─'*55}")
        print(f"💛  Liked Songs")
        print(f"{'─'*55}")
        liked = session.user.favorites.tracks_paginated()
        print(f"✅ Found {len(liked)} liked track(s)\n")
        for i, track in enumerate(liked, 1):
            scope = "liked"
            key = f"{scope}::{track.id}"
            if key in cache:
                skipped_count += 1
                continue
            artist = sanitize(", ".join(a.name for a in track.artists))
            title  = sanitize(track.full_name if hasattr(track, "full_name") else track.name)
            exp    = explicit_tag(getattr(track, "explicit", False))
            fname  = f"{artist} - {title}{exp}"
            print(f"  [{i}/{len(liked)}] {artist} - {title}")
            local_rel  = pathlib.Path("Liked Songs") / fname
            remote_rel = f"Liked Songs/{fname}"
            if deliver(track, local_rel, remote_rel):
                cache[key] = {"tidal_id": str(track.id), "artist": artist, "title": title, "playlist": scope}
                save_cache(cache_path, cache)
                delivered_count += 1
    finally:
        if tmp_dir_ctx:
            tmp_dir_ctx.cleanup()

    print(f"\n{'='*55}")
    print(f"  DONE — {delivered_count} delivered, {skipped_count} already backed up")
    print(f"{'='*55}")


def prompt_destination() -> str:
    if not sys.stdin.isatty():
        sys.exit("❌ Not running interactively — pass --to {phone,itunes,folder} to skip the prompt.")
    print("Where should OmniTide back up your Tidal library to?")
    print("  1) Phone (adb push)")
    print("  2) iTunes folder")
    print("  3) Current folder")
    for _ in range(3):
        choice = input("Choose [1/2/3]: ").strip()
        dest = {"1": "phone", "2": "itunes", "3": "folder"}.get(choice)
        if dest:
            return dest
        print("  ⚠️  Please enter 1, 2, or 3.")
    sys.exit("❌ No valid selection after 3 attempts.")


# ── Main ──────────────────────────────────────────────────────────────────────

def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="OmniTide",
        description="OmniTide: Phone Sync & Downloader",
    )
    commands = parser.add_subparsers(dest="command")

    commands.add_parser("login", help="Log in to Tidal and save your session token")

    sync_common = argparse.ArgumentParser(add_help=False)
    sync_common.add_argument("--only", type=str,
                             help="Sync only playlists whose names contain this substring")

    sync_parser = commands.add_parser("sync", help="Sync a music library to Tidal")
    sync_sources = sync_parser.add_subparsers(dest="source", required=True)

    phone_parser = sync_sources.add_parser("phone", parents=[sync_common],
                                           help="Sync from an Android phone over ADB")
    phone_parser.add_argument("--cache-file", type=str, default=None, metavar="FILE",
                              help=f"Where to store the incremental phone-scan cache "
                                   f"(default: {PHONE_CACHE_PATH})")
    phone_parser.add_argument("--read-tags", action="store_true",
                              help="Read ARTIST/TITLE/TIDALID from each file's embedded tags instead of "
                                   "guessing from the filename (more accurate, slower — pulls a chunk of "
                                   "every file over ADB)")

    itunes_parser = sync_sources.add_parser("itunes", parents=[sync_common],
                                            help="Sync from an iTunes/Apple Music library")
    itunes_parser.add_argument("--path", type=str, metavar="XML",
                               help="Path to iTunes Music Library.xml (auto-detected if omitted)")
    itunes_parser.add_argument("--cache-file", type=str, default=None, metavar="FILE",
                               help=f"Where to store the incremental iTunes-scan cache "
                                    f"(default: {ITUNES_CACHE_PATH})")

    download_parser = commands.add_parser("download", help="Download a track, album, or playlist from Tidal")
    download_parser.add_argument("url", type=str, help="Tidal track/album/playlist URL")
    download_parser.add_argument("--dest", type=str, metavar="DIR",
                                 help=f"Output directory (default: {OUTPUT_BASE})")

    backup_parser = commands.add_parser("backup",
        help="Download your entire Tidal account (owned playlists + Liked Songs) to Phone/iTunes-folder/current folder")
    backup_parser.add_argument("--to", choices=["phone", "itunes", "folder"], default=None,
                               help="Destination to back up to; skips the interactive prompt "
                                    "(required when not running interactively)")
    backup_parser.add_argument("--dest", type=str, metavar="DIR", default=None,
                               help="Override the destination folder for 'itunes'/'folder' backups "
                                    f"(defaults: iTunes → {ITUNES_BACKUP_BASE}, folder → current directory; "
                                    "ignored for --to phone)")
    backup_parser.add_argument("--cache-file", type=str, default=None, metavar="FILE",
                               help="Where to store the incremental backup-delivery cache "
                                    "(default depends on --to: .omnitide_backup_{phone,itunes,folder}_cache.json)")

    return parser


def main():
    parser = build_arg_parser()
    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(1)

    session, access_token = load_session(TOKEN_PATH)

    if args.command == "login":
        print("✅ Login complete.")
        return

    if args.command == "sync":
        print("\n🚀 Syncing...")
        if args.source == "phone":
            sync_phone(session, access_token,
                      only=args.only,
                      read_tags=args.read_tags,
                      cache_path=Path(args.cache_file) if args.cache_file else PHONE_CACHE_PATH)
        elif args.source == "itunes":
            sync_itunes(session, access_token,
                       only=args.only,
                       itunes_path=args.path,
                       cache_path=Path(args.cache_file) if args.cache_file else ITUNES_CACHE_PATH)
        print("\n✨ Done.")
        return

    if args.command == "download":
        if args.dest:
            global OUTPUT_BASE
            OUTPUT_BASE = Path(args.dest)
        print("\n🚀 Downloading...")
        process_download(session, args.url)
        print("\n✨ Done.")
        return

    if args.command == "backup":
        destination = args.to or prompt_destination()
        cache_default = {"phone": BACKUP_PHONE_CACHE_PATH,
                         "itunes": BACKUP_ITUNES_CACHE_PATH,
                         "folder": BACKUP_FOLDER_CACHE_PATH}[destination]
        print("\n🚀 Backing up your Tidal account...")
        backup_tidal(session, destination,
                    dest_path=Path(args.dest) if args.dest else None,
                    cache_path=Path(args.cache_file) if args.cache_file else cache_default)
        print("\n✨ Done.")
        return


if __name__ == "__main__":
    main()
