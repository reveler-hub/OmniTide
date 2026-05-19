#!/usr/bin/env python3
"""
OmniTide: Phone Sync & Downloader
Usage:
  python OmniTide.py --sync                  (Scan phone, build Tidal playlists)
  python OmniTide.py --download <URL>        (Download track/album/playlist)
  python OmniTide.py --sync --download <URL> (Both)

song_files.txt format:
  [Playlist Name]
  Artist - Title
  Artist - Title

  [Another Playlist]
  Artist - Title
"""

import argparse
import json
import os
import plistlib
import mutagen.flac
import pathlib
import random
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from mutagen.flac import Picture

import requests
import tidalapi
from tidalapi import Quality
from tidalapi.media import Track, Video

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
ROOT_MUSIC_PATH = "/sdcard/Music/"
TOKEN_PATH      = Path("token.json")
SONGS_PATH      = Path("song_files.txt")
FFMPEG_BIN      = "/usr/bin/ffmpeg"
CHUNK_SIZE      = 1024 * 1024
COVER_URL       = "https://resources.tidal.com/images/{uuid}/{size}x{size}.jpg"
OUTPUT_BASE     = Path.home() / "Tidal Download"
EXPLICIT_STR    = " (Explicit)"

# Folder names that are compilations/playlists, not artist names.
# Add any folder names here that shouldn't be used as the artist when
# the filename has no "Artist - Title" separator.
SKIP_AS_ARTIST: set[str] = set()

# Playlists already on Tidal — skip during sync.
# Add playlist names here to avoid re-importing them.
SKIP_PLAYLISTS: set[str] = set()

# iTunes system playlists to ignore
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


# ── Auth ──────────────────────────────────────────────────────────────────────

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
    session.load_oauth_session(
        token_type    = data["token_type"],
        access_token  = data["access_token"],
        refresh_token = data["refresh_token"],
        expiry_time   = datetime.fromtimestamp(data["expiry_time"]),
    )
    if not session.check_login():
        sys.exit("❌ Session invalid. Delete token.json and re-run to login.")

    _save_token(session, token_path)  # write back refreshed token
    name = getattr(session.user, "name", None) or str(session.user.id)
    print(f"✅ Logged in as: {name}\n")
    return session, session.access_token


# ── Song list: ADB scan ───────────────────────────────────────────────────────

def _clean_filename(filename: str) -> tuple[str, str]:
    """Strip track numbers and junk tags, return (artist, title)."""
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


def scan_phone_via_adb(songs_path: Path):
    """Scan phone via ADB and write clean song_files.txt."""
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

    # Parse paths into playlists
    playlists: dict[str, list[str]] = defaultdict(list)
    for line in result.stdout.splitlines():
        path = line.strip()
        if not path or Path(path).suffix.lower() not in MUSIC_EXTS:
            continue

        filename = Path(path).stem
        relative = path.replace(ROOT_MUSIC_PATH, "")
        parts    = relative.split("/")
        folder   = parts[0] if len(parts) > 1 else "Misc"
        playlist = _clean_folder(folder)

        artist, title = _clean_filename(filename)
        if not artist:
            if not any(s in folder.lower() for s in SKIP_AS_ARTIST):
                artist = folder.split(" - ")[0].strip()

        entry = f"{artist} - {title}" if artist else title
        playlists[playlist].append(entry)

    # Write clean format
    lines = []
    for playlist, songs in sorted(playlists.items()):
        lines.append(f"[{playlist}]")
        lines.extend(songs)
        lines.append("")  # blank line between playlists

    with open(songs_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    total = sum(len(v) for v in playlists.values())
    print(f"✅ Found {total} songs in {len(playlists)} playlists — saved to {songs_path}\n")


# ── Song list: parser ─────────────────────────────────────────────────────────

def parse_song_list(songs_path: Path) -> dict[str, list[tuple[str, str, str]]]:
    """
    Parse song_files.txt in section format:
      [Playlist Name]
      Artist - Title
      ...
    Returns { playlist_name: [(artist, title, display)] }
    """
    with open(songs_path, encoding="utf-8") as f:
        lines = [l.rstrip() for l in f]

    playlists: dict[str, list] = defaultdict(list)
    current_playlist = "Misc"

    for line in lines:
        if not line.strip():
            continue
        if line.startswith("[") and line.endswith("]"):
            current_playlist = line[1:-1].strip()
            continue

        # Parse "Artist - Title" or just "Title"
        if " - " in line:
            artist, title = line.split(" - ", 1)
            artist, title = artist.strip(), title.strip()
        else:
            artist, title = "", line.strip()

        display = f"{artist} - {title}" if artist else title
        playlists[current_playlist].append((artist, title, display))

    return dict(playlists)


# ── Tidal search & add ────────────────────────────────────────────────────────

def _artist_match(artist_lower: str, track_artists: list[str]) -> bool:
    if not artist_lower:
        return True
    return any(artist_lower in a or a in artist_lower for a in track_artists)


def _title_match(title_lower: str, track_name: str) -> bool:
    t = track_name.lower()
    return title_lower in t or t in title_lower


def search_track(session: tidalapi.Session, artist: str, title: str, retries: int = 3):
    query        = f"{artist} {title}" if artist else title
    title_lower  = title.lower()
    artist_lower = artist.lower()

    for attempt in range(1, retries + 1):
        try:
            results = session.search(query, models=[tidalapi.Track], limit=10)
            tracks  = results.get("tracks", [])
            if not tracks:
                return None

            # Pass 1: title + artist both match
            for track in tracks:
                ta = [a.name.lower() for a in track.artists]
                if _title_match(title_lower, track.name) and _artist_match(artist_lower, ta):
                    return track

            # Pass 2: artist matches but title is loose — warn but return
            if artist_lower:
                for track in tracks:
                    ta = [a.name.lower() for a in track.artists]
                    if _artist_match(artist_lower, ta):
                        print(f"    ⚠️  Loose match: '{track.name}' by {', '.join(a.name for a in track.artists)}")
                        return track
                return None  # artist known but nothing matched — don't add wrong song

            return tracks[0]  # no artist info, take first result

        except Exception as e:
            print(f"    ⚠️  Search error (attempt {attempt}/{retries}): {e}")
            if attempt < retries:
                time.sleep(3)
    return None


def add_track_with_retry(session: tidalapi.Session, access_token: str, playlist,
                         track_id: int, retries: int = 3, delay: float = 5.0) -> bool:
    for attempt in range(1, retries + 1):
        try:
            raw = session.request_session.post(
                f"https://api.tidal.com/v1/playlists/{playlist.id}/items",
                params={"sessionId": session.session_id, "countryCode": session.country_code, "limit": 100},
                data={"onArtifactNotFound": "SKIP", "trackIds": track_id,
                      "toIndex": playlist.num_tracks, "onDupes": "ADD"},
                headers={"If-None-Match": "*", "Authorization": f"Bearer {access_token}"},
            )
            if not raw.ok:
                print(f"    ⚠️  HTTP {raw.status_code} (attempt {attempt}/{retries})")
                if attempt < retries: time.sleep(delay)
                continue
            if track_id in raw.json().get("addedItemIds", []):
                playlist.num_tracks += 1
                return True
            print(f"    ⚠️  addedItemIds=[] (attempt {attempt}/{retries})")
            if attempt < retries: time.sleep(delay)
        except Exception as e:
            print(f"    ⚠️  Exception (attempt {attempt}/{retries}): {e}")
            if attempt < retries: time.sleep(delay)
    return False


def get_or_create_playlist(session: tidalapi.Session, name: str, keep_existing: bool):
    if not keep_existing:
        try:
            for pl in session.user.playlist_and_favorite_playlists():
                if getattr(pl, "name", None) == name and getattr(pl, "creator", None):
                    if pl.creator.id == session.user.id:
                        print(f"    ♻️  Replacing existing '{name}'")
                        pl.delete()
                        time.sleep(1)
                        break
        except Exception as e:
            print(f"    ⚠️  Could not check existing playlists: {e}")
    pl = session.user.create_playlist(name, "")
    pl.num_tracks = 0
    return pl



# ── iTunes parser ─────────────────────────────────────────────────────────────

def find_itunes_library() -> Path | None:
    candidates = ITUNES_LIBRARY_PATHS.get(sys.platform, [])
    return next((p for p in candidates if p.exists()), None)


def parse_itunes_library(xml_path: Path) -> dict[str, list[tuple[str, str, str]]]:
    print(f"📖 Reading iTunes library: {xml_path}")
    with open(xml_path, "rb") as f:
        library = plistlib.load(f)

    # Build track id -> (artist, title)
    raw_tracks = library.get("Tracks", {})
    tracks: dict[str, tuple[str, str]] = {}
    for tid, info in raw_tracks.items():
        if any(x in info.get("Kind", "").lower() for x in ["podcast", "video", "audiobook", "book"]):
            continue
        name = info.get("Name", "").strip()
        if not name:
            continue
        tracks[tid] = (info.get("Artist", "").strip(), name)

    # Build playlist -> track ids, skipping system playlists
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

    # Assign each track to its first playlist, remainder to "Music"
    seen: set[str] = set()
    playlists: dict[str, list] = defaultdict(list)

    for pl_name, ids in playlist_tracks.items():
        for tid in ids:
            if tid in seen:
                continue
            seen.add(tid)
            artist, title = tracks[tid]
            display = f"{artist} - {title}" if artist else title
            playlists[pl_name].append((artist, title, display))

    for tid, (artist, title) in tracks.items():
        if tid in seen:
            continue
        display = f"{artist} - {title}" if artist else title
        playlists["Music"].append((artist, title, display))

    total = sum(len(v) for v in playlists.values())
    print(f"✅ Found {total} tracks across {len(playlists)} playlists\n")
    return dict(playlists)


# ── Sync engine ───────────────────────────────────────────────────────────────

def sync_library(session: tidalapi.Session, access_token: str,
                 rescan: bool, keep_existing: bool, only: str | None,
                 source: str = "android", itunes_path: str | None = None):

    if source == "itunes":
        xml_path = Path(itunes_path) if itunes_path else find_itunes_library()
        if not xml_path or not xml_path.exists():
            sys.exit("❌ iTunes library not found. Use --itunes-path to specify it.")
        playlists = parse_itunes_library(xml_path)
    else:
        if not SONGS_PATH.exists() or rescan:
            scan_phone_via_adb(SONGS_PATH)
        print(f"📂 Reading {SONGS_PATH}...")
        playlists = parse_song_list(SONGS_PATH)

    for name in list(playlists):
        if name in SKIP_PLAYLISTS:
            print(f"⏭️  Skipping '{name}'")
            del playlists[name]

    if only:
        playlists = {k: v for k, v in playlists.items() if only.lower() in k.lower()}
        if not playlists:
            print(f"❌ No playlists matching '{only}'")
            return

    total = sum(len(v) for v in playlists.values())
    print(f"📋 {len(playlists)} playlists, {total} songs\n")

    all_unmatched   = []
    grand_matched   = grand_unmatched = grand_failed = 0

    for playlist_name, songs in playlists.items():
        print(f"\n{'─'*55}")
        print(f"🎵  '{playlist_name}'  ({len(songs)} songs)")
        print(f"{'─'*55}")

        tidal_pl = get_or_create_playlist(session, playlist_name, keep_existing)
        matched  = unmatched = failed = added = 0

        for i, (artist, title, display) in enumerate(songs, 1):
            print(f"  [{i}/{len(songs)}] {display}")
            track = search_track(session, artist, title)
            time.sleep(0.5)

            if not track:
                print(f"    ❌ No match")
                unmatched += 1
                all_unmatched.append(f"[{playlist_name}] {display}")
                continue

            matched += 1
            print(f"    🔍 {', '.join(a.name for a in track.artists)} - {track.name}")

            if add_track_with_retry(session, access_token, tidal_pl, track.id):
                added += 1
                print(f"    ✅ Added ({added} so far)")
            else:
                failed += 1
                print(f"    💀 Failed to add")

            time.sleep(2.0)

        grand_matched   += matched
        grand_unmatched += unmatched
        grand_failed    += failed
        print(f"\n  ✅ {added} added  |  ❌ {unmatched} not found  |  💀 {failed} failed")

    print(f"\n{'='*55}")
    print(f"  DONE — {len(playlists)} playlists")
    print(f"  ✅ Matched: {grand_matched}  ❌ Not found: {grand_unmatched}  💀 Failed: {grand_failed}")
    print(f"{'='*55}")

    if all_unmatched:
        out = SONGS_PATH.parent / "unmatched_songs.txt"
        out.write_text("\n".join(all_unmatched), encoding="utf-8")
        print(f"\n📄 Unmatched saved to: {out}")


# ── Download engine ───────────────────────────────────────────────────────────

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
    """Re-mux to FLAC — fixes seekbar on all players."""
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
        m     = mutagen.flac.FLAC(str(path_file))
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


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="OmniTide: Phone Sync & Downloader")
    parser.add_argument("--sync",          action="store_true", help="Scan phone and sync to Tidal playlists")
    parser.add_argument("--itunes",        action="store_true", help="Sync from iTunes/Apple Music library instead of phone")
    parser.add_argument("--itunes-path",   type=str, metavar="PATH", help="Path to iTunes Music Library.xml (auto-detected if omitted)")
    parser.add_argument("--download",      type=str, metavar="URL", help="Download track/album/playlist from Tidal")
    parser.add_argument("--only",          type=str, help="Sync only playlists matching this name")
    parser.add_argument("--rescan",        action="store_true", help="Force re-scan phone even if song_files.txt exists")
    parser.add_argument("--keep-existing", action="store_true", help="Don't replace existing same-name playlists")
    args = parser.parse_args()

    if not args.sync and not args.download:
        parser.print_help()
        sys.exit(1)

    session, access_token = load_session(TOKEN_PATH)

    if args.sync or args.itunes:
        print("\n🚀 Syncing...")
        source = "itunes" if args.itunes else "android"
        sync_library(session, access_token,
                     rescan=args.rescan, keep_existing=args.keep_existing, only=args.only,
                     source=source, itunes_path=args.itunes_path)

    if args.download:
        print("\n🚀 Downloading...")
        process_download(session, args.download)

    print("\n✨ Done.")


if __name__ == "__main__":
    main()
