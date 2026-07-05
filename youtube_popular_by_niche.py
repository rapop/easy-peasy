#!/usr/bin/env python3
"""
Find popular YouTube videos across many niches using the official
YouTube Data API v3 (no fragile HTML scraping, no ToS violations).

Setup
-----
1. Create a project + API key at https://console.cloud.google.com/apis/credentials
   and enable "YouTube Data API v3".
2. Install the client:  pip install google-api-python-client
3. Export your key:      export YOUTUBE_API_KEY="AIza..."

Usage
-----
    python youtube_popular_by_niche.py                       # default niches
    python youtube_popular_by_niche.py "cooking" "gaming"    # custom niches
    python youtube_popular_by_niche.py --per-niche 15 --region GB --csv out.csv

Notes
-----
- Each search costs 100 quota units; the default free quota is 10,000/day
  (~100 searches). Keep --per-niche reasonable to stay within quota.
"""

import argparse
import csv
import os
import sys
from datetime import datetime, timedelta, timezone

try:
    from googleapiclient.discovery import build
    from googleapiclient.errors import HttpError
except ImportError:
    sys.exit(
        "Missing dependency. Run:\n    pip install google-api-python-client"
    )

# A starting set of niches. Override by passing niches as CLI arguments.
DEFAULT_NICHES = [
    "cooking",
    "gaming",
    "personal finance",
    "fitness",
    "travel",
    "technology reviews",
    "diy home improvement",
    "digital art",
    "language learning",
    "true crime",
]


def get_client(api_key):
    return build("youtube", "v3", developerKey=api_key, cache_discovery=False)


def search_niche(youtube, niche, per_niche, region, published_after):
    """Return a list of the most popular videos for one niche.

    Strategy: use search.list to get candidate video IDs ranked by
    viewCount, then videos.list to fetch real statistics (search results
    don't include stats).
    """
    search_resp = (
        youtube.search()
        .list(
            q=niche,
            part="id",
            type="video",
            order="viewCount",
            maxResults=min(per_niche, 50),
            regionCode=region,
            relevanceLanguage="en",
            publishedAfter=published_after,
        )
        .execute()
    )

    video_ids = [
        item["id"]["videoId"]
        for item in search_resp.get("items", [])
        if item["id"].get("videoId")
    ]
    if not video_ids:
        return []

    stats_resp = (
        youtube.videos()
        .list(part="snippet,statistics", id=",".join(video_ids))
        .execute()
    )

    videos = []
    for item in stats_resp.get("items", []):
        snippet = item["snippet"]
        stats = item.get("statistics", {})
        videos.append(
            {
                "niche": niche,
                "title": snippet["title"],
                "channel": snippet["channelTitle"],
                "published": snippet["publishedAt"][:10],
                "views": int(stats.get("viewCount", 0)),
                "likes": int(stats.get("likeCount", 0)),
                "comments": int(stats.get("commentCount", 0)),
                "url": f"https://www.youtube.com/watch?v={item['id']}",
            }
        )

    videos.sort(key=lambda v: v["views"], reverse=True)
    return videos


def parse_args():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("niches", nargs="*", default=DEFAULT_NICHES,
                   help="Niches to search (default: a built-in list).")
    p.add_argument("--per-niche", type=int, default=10,
                   help="Videos to fetch per niche (max 50). Default 10.")
    p.add_argument("--region", default="US",
                   help="ISO region code, e.g. US, GB, DE. Default US.")
    p.add_argument("--within-days", type=int, default=365,
                   help="Only videos published in the last N days. Default 365.")
    p.add_argument("--csv", metavar="FILE",
                   help="Also write results to this CSV file.")
    return p.parse_args()


def main():
    args = parse_args()

    api_key = os.environ.get("YOUTUBE_API_KEY")
    if not api_key:
        sys.exit("Set your API key first:  export YOUTUBE_API_KEY='AIza...'")

    published_after = (
        datetime.now(timezone.utc) - timedelta(days=args.within_days)
    ).strftime("%Y-%m-%dT%H:%M:%SZ")

    youtube = get_client(api_key)

    all_videos = []
    for niche in args.niches:
        try:
            videos = search_niche(
                youtube, niche, args.per_niche, args.region, published_after
            )
        except HttpError as e:
            print(f"  ! API error for '{niche}': {e}", file=sys.stderr)
            if "quotaExceeded" in str(e):
                print("  ! Daily quota exhausted — stopping.", file=sys.stderr)
                break
            continue

        all_videos.extend(videos)

        print(f"\n=== {niche.upper()} ===")
        for i, v in enumerate(videos, 1):
            print(f"{i:>2}. {v['views']:>12,} views  {v['title'][:70]}")
            print(f"      {v['channel']}  |  {v['url']}")

    if args.csv and all_videos:
        with open(args.csv, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=list(all_videos[0].keys()))
            writer.writeheader()
            writer.writerows(all_videos)
        print(f"\nWrote {len(all_videos)} rows to {args.csv}")


if __name__ == "__main__":
    main()
