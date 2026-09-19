"""Collect positive format evidence from public YouTube tabs; no login/download.
Only public IDs, types, timestamps and channel ID enter classification.json.
A failed/empty/wrong-channel tab aborts before replacing the existing feed.
"""
import argparse
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

HANDLE = '@PillaiCenter'
CHANNEL_ID = 'UC2PntFK06SGTHWsSKRQIGTg'
TABS = {'videos': 'Video', 'shorts': 'Short', 'streams': 'Livestream'}
VIDEO_ID = re.compile(r'^[A-Za-z0-9_-]{11}$')
TYPES = {*TABS.values(), 'Pending'}


def validate_tab(info, tab):
    if not isinstance(info, dict) or info.get('channel_id') != CHANNEL_ID:
        raise ValueError(f'{tab}: unexpected/missing channel ID')
    url = urlsplit(info.get('webpage_url', ''))
    if url.hostname not in ('www.youtube.com', 'youtube.com') or url.path.rstrip('/').split('/')[-1] != tab:
        raise ValueError(f'{tab}: extractor did not return the requested tab')
    entries = list(info.get('entries') or [])
    if not entries:
        raise ValueError(f'{tab}: empty response; preserving existing feed')
    ids = set()
    for entry in entries:
        if not isinstance(entry, dict) or not VIDEO_ID.fullmatch(entry.get('id', '')):
            raise ValueError(f'{tab}: invalid entry')
        if entry.get('channel_id') not in (None, CHANNEL_ID):
            raise ValueError(f'{tab}: another channel appeared in results')
        ids.add(entry['id'])
    return ids


def build_feed(previous, evidence, now):
    old_items = {}
    if previous:
        if previous.get('schema') != 1 or previous.get('channelId') != CHANNEL_ID:
            raise ValueError('Existing feed has a different schema/channel')
        old_items = previous.get('items')
        if not isinstance(old_items, dict):
            raise ValueError('Invalid existing items')
        for video_id, record in old_items.items():
            if not VIDEO_ID.fullmatch(video_id) or not isinstance(record, dict) or record.get('type') not in TYPES:
                raise ValueError('Invalid existing classification')
            observed = datetime.fromisoformat(record.get('seenAt', '').replace('Z', '+00:00'))
            if observed.tzinfo is None:
                raise ValueError('Existing timestamp must include timezone')
    seen = {}
    for tab, ids in evidence.items():
        for video_id in ids:
            seen.setdefault(video_id, set()).add(TABS[tab])
    items = {key: {'type': value['type'], 'seenAt': value['seenAt']}
             for key, value in old_items.items()}
    for video_id, kinds in seen.items():
        items[video_id] = {'type': next(iter(kinds)) if len(kinds) == 1 else 'Pending', 'seenAt': now}
    return {'schema': 1, 'channelId': CHANNEL_ID, 'channelHandle': HANDLE,
            'generatedAt': now, 'tabCounts': {tab: len(ids) for tab, ids in evidence.items()},
            'items': dict(sorted(items.items()))}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', default='classification.json')
    parser.add_argument('--limit', type=int, default=500, help='Maximum recent entries per tab')
    args = parser.parse_args()
    if args.limit < 1 or args.limit > 10000:
        raise ValueError('limit must be 1..10000')
    from yt_dlp import YoutubeDL
    path = Path(args.output)
    previous = json.loads(path.read_text()) if path.exists() else None
    evidence = {}
    options = {'extract_flat': True, 'skip_download': True, 'playlistend': args.limit,
               'ignoreerrors': False, 'quiet': True, 'socket_timeout': 20,
               'retries': 0, 'extractor_retries': 0}
    for tab in TABS:
        with YoutubeDL(options) as ydl:
            info = ydl.extract_info(f'https://www.youtube.com/{HANDLE}/{tab}', download=False)
        evidence[tab] = validate_tab(info, tab)
        print(f'{tab}: {len(evidence[tab])} public IDs verified')
    now = datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')
    feed = build_feed(previous, evidence, now)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(json.dumps(feed, indent=2) + '\n')
    os.replace(temporary, path)
    print(f'Saved {len(feed["items"])} classifications to {path}')


if __name__ == '__main__':
    main()
