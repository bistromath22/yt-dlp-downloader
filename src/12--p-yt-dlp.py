#!/usr/bin/env python3
"""
yt-dlp smart downloader
- Video: prefer given height (default 480), else next lower height (smallest size)
- Audio: <50kbps, prefer English
- Subtitles: English (manual + auto) if available
"""

import sys
import time
import argparse
from collections import defaultdict
import yt_dlp
from yt_dlp.utils import DownloadError

def get_info(url: str):
    ydl_opts = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=False)
        return info

def select_video(formats, preferred_height=480):
    by_height = defaultdict(list)

    for f in formats:
        height = f.get("height")
        if height is None:
            continue
        if f.get("vcodec") in (None, "none"):
            continue
        if f.get("acodec") not in (None, "none"):
            continue

        filesize = f.get("filesize") or f.get("filesize_approx") or float("inf")
        by_height[height].append((filesize, f))

    if not by_height:
        raise ValueError("No suitable video formats found")

    available_heights = sorted(by_height.keys(), reverse=True)

    target_height = None
    for h in available_heights:
        if h <= preferred_height:
            target_height = h
            break

    if target_height is None:
        raise ValueError(f"No video with height ≤ {preferred_height}")

    candidates = by_height[target_height]
    candidates.sort(key=lambda x: x[0])  # smallest first
    best = candidates[0][1]

    return best, target_height, candidates

def select_audio(formats, max_abr=50):
    english = []
    others = []

    for f in formats:
        if f.get("vcodec") not in (None, "none"):
            continue
        if f.get("acodec") in (None, "none"):
            continue

        abr = f.get("abr")
        if abr is None or abr >= max_abr:
            continue

        lang = (f.get("language") or "").lower()
        filesize = f.get("filesize") or f.get("filesize_approx") or float("inf")
        item = (abr, filesize, f)

        if lang.startswith("en"):
            english.append(item)
        else:
            others.append(item)

    candidates = english if english else others

    if not candidates:
        raise ValueError(f"No audio format found with bitrate < {max_abr} kbps")

    candidates.sort(key=lambda x: (x[0], x[1]))
    return candidates[0][2]

def main():
    parser = argparse.ArgumentParser(
        description="Download YouTube video with smart quality + English audio + subtitles",
        add_help=False          # ← disables default -h
    )

    parser.add_argument("url", help="YouTube URL")

    parser.add_argument(
        "-h", "--height",
        type=int,
        default=480,
        metavar="HEIGHT",
        help="Preferred maximum height (default: 480). Will take next lower if not available."
    )

    parser.add_argument(
        "--help",
        action="help",
        default=argparse.SUPPRESS,
        help="Show this help message and exit"
    )

    args = parser.parse_args()
    url = args.url.strip()
    preferred_height = args.height

    print(f"Preferred height : {preferred_height}p")
    print("Fetching video information...")

    info = get_info(url)
    formats = info.get("formats", [])
    title = info.get("title", "video")

    print(f"\nTitle : {title}")
    print(f"Total formats: {len(formats)}")

    # --- Video ---
    try:
        video, chosen_height, all_at_height = select_video(formats, preferred_height)
    except ValueError as e:
        print(f"Error (video): {e}")
        sys.exit(1)

    print(f"\n=== Video candidates at {chosen_height}p ===")
    print(f"{'ID':<12} {'Resolution':<12} {'Codec':<22} {'Size':>12}  Note")
    print("-" * 75)
    for filesize, f in sorted(all_at_height, key=lambda x: x[0]):
        res = f"{f.get('width')}x{f.get('height')}"
        size_str = f"{filesize/1024/1024:.1f} MiB" if filesize != float("inf") else "unknown"
        print(f"{f['format_id']:<12} {res:<12} {f.get('vcodec',''):<22} {size_str:>12}  {f.get('format_note','')}")

    print("\nSelected video:")
    print(f"  ID        : {video['format_id']}")
    print(f"  Resolution: {video.get('width')}x{video.get('height')}")
    print(f"  Codec     : {video.get('vcodec')}")
    size = video.get('filesize') or video.get('filesize_approx')
    print(f"  Size      : {size/1024/1024:.1f} MiB" if size else "  Size      : unknown")
    print(f"  Note      : {video.get('format_note', '')}")

    # --- Audio ---
    try:
        audio = select_audio(formats, max_abr=50)
    except ValueError as e:
        print(f"Error (audio): {e}")
        sys.exit(1)

    print("\nSelected audio:")
    print(f"  ID        : {audio['format_id']}")
    print(f"  Language  : {audio.get('language')}")
    print(f"  Bitrate   : {audio.get('abr')} kbps")
    print(f"  Codec     : {audio.get('acodec')}")
    size = audio.get('filesize') or audio.get('filesize_approx')
    print(f"  Size      : {size/1024/1024:.1f} MiB" if size else "  Size      : unknown")
    print(f"  Note      : {audio.get('format_note', '')}")

    format_str = f"{video['format_id']}+{audio['format_id']}"
    outtmpl = "%(title)s [%(id)s].%(ext)s"
    sub_opts = {
        "writesubtitles": True,
        "writeautomaticsub": True,
        "subtitleslangs": ["en", "en-US", "en-GB"],
        "subtitlesformat": "srt/best",
    }

    # --- Stage 1: subtitles (non-fatal) ---
    print("\nTrying to download English subtitles (if available)...")
    subs_ok = False
    try:
        with yt_dlp.YoutubeDL({
            "skip_download": True,
            "outtmpl": outtmpl,
            "quiet": True,
            "no_warnings": True,
            **sub_opts,
        }) as ydl:
            sub_info = ydl.extract_info(url, download=True)
            subs_ok = bool(sub_info.get("requested_subtitles"))
        if subs_ok:
            print("✓ Subtitles downloaded.")
        else:
            print("⚠ No English subtitles available.")
    except Exception as e:
        print(f"⚠ Subtitles cannot be downloaded: {e}")
        print("  Continuing without subtitles.")

    print("Waiting 2 seconds before downloading video/audio...")
    time.sleep(2)

    # --- Stage 2: video + audio ---
    print(f"\nDownloading → {format_str}")
    base_opts = {
        "format": format_str,
        "merge_output_format": "mp4",
        "outtmpl": outtmpl,
        "quiet": False,
    }

    attempts = []
    if subs_ok:
        attempts.append({
            **base_opts,
            **sub_opts,
            "postprocessors": [{"key": "FFmpegEmbedSubtitle"}],
        })
    attempts.append(base_opts)  # fallback: no subtitles

    for i, opts in enumerate(attempts):
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                ydl.download([url])
            print("\n✓ Download finished successfully!")
            return
        except DownloadError as e:
            if i < len(attempts) - 1:
                print(f"\n⚠ Download with subtitles failed: {e}")
                print("  Retrying without subtitles in 2 seconds...")
                time.sleep(2)
            else:
                print(f"\nDownload failed: {e}")
                sys.exit(1)

if __name__ == "__main__":
    main()