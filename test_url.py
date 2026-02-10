
import yt_dlp
import json
import sys
import os

url = "https://www.youtube.com/shorts/qM79_itR0Nc"

ydl_opts = {
    'outtmpl': 'downloads/%(title).100s.%(ext)s', 
    'quiet': False,
    'no_warnings': False,
    'nocheckcertificate': True,
    'geo_bypass': True,
    'retries': 3,
    'fragment_retries': 3,
    'force_ipv4': True,
    'extractor_args': {
        'youtube': {
            'player_client': ['ios', 'android', 'web'],
            'player_skip': ['webpage', 'configs'],
        }
    },
    'format': 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best',
    'http_headers': {
         'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36',
         'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8',
         'Accept-Language': 'en-US,en;q=0.9',
         'Sec-Fetch-Mode': 'navigate',
    }
}

if not os.path.exists('downloads'):
    os.makedirs('downloads')

print(f"Analyzing URL: {url}")
try:
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=True)
        print("SUCCESS: Downloaded media")
        print(f"Title: {info.get('title')}")
except Exception as e:
    print(f"ERROR: {e}")
