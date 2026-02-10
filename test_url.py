
import yt_dlp
import json
import sys

url = "https://www.instagram.com/p/DUi3n2hDY0j/?utm_source=ig_web_copy_link&igsh=NTc4MTIwNjQ2YQ=="

ydl_opts = {
    'quiet': True,
    'no_warnings': True,
    'http_headers': {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8',
        'Accept-Language': 'en-US,en;q=0.9',
        'Sec-Fetch-Mode': 'navigate',
    }
}

print(f"Analyzing URL: {url}")
try:
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=False)
        print("SUCCESS: Found media info")
        print(f"Title: {info.get('title')}")
        print(f"Type: {info.get('_type', 'video')}")
        print(f"Ext: {info.get('ext')}")
        if 'entries' in info:
            print(f"Carousel/Playlist detected: {len(info['entries'])} items")
            for i, entry in enumerate(info['entries']):
                print(f"  Item {i+1}: {entry.get('title')} ({entry.get('ext')})")
except Exception as e:
    print(f"ERROR: {e}")
