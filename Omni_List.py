#!/usr/bin/env python3
"""
List all user-created playlists and their tracks with Tidal IDs.
Output format (OmniTide song_files.txt compatible):
  [Playlist Name]
  Artist - Title [TID:123456]
  Artist - Title [TID:789012]

  [Another Playlist]
  Artist - Title [TID:345678]
...
Usage: ./list_playlists.py > my_library.txt
"""

import sys
import json
from pathlib import Path
from datetime import datetime
import tidalapi
from tidalapi import Quality

TOKEN_PATH = Path("token.json")

def load_session(token_path: Path) -> tidalapi.Session:
    if not token_path.exists():
        sys.exit("❌ No token found. Run './OmniTide.py --login' first.")
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
        sys.exit("❌ Session invalid. Delete token.json and re-run login.")
    return session

def main():
    session = load_session(TOKEN_PATH)
    user = session.user

    # Get all playlists and favorites (only user-created ones)
    all_playlists = session.user.playlist_and_favorite_playlists()
    user_playlists = [pl for pl in all_playlists
                      if hasattr(pl, 'creator') and pl.creator and pl.creator.id == user.id]

    if not user_playlists:
        print("⚠️  No user-created playlists found.", file=sys.stderr)
        return

    print(f"📋 Found {len(user_playlists)} user playlists. Fetching tracks...", file=sys.stderr)

    for pl in user_playlists:
        print(f"[{pl.name}]")
        try:
            tracks = pl.tracks()
            for track in tracks:
                if hasattr(track, 'id'):
                    artists = ", ".join([a.name for a in track.artists])
                    title = track.name
                    print(f"{artists} - {title} [TID:{track.id}]")
        except Exception as e:
            print(f"⚠️  Could not fetch tracks for '{pl.name}': {e}", file=sys.stderr)
        print()  # blank line between playlists

if __name__ == "__main__":
    main()
