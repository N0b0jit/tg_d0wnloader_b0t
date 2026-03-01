
import os
import logging
import asyncio
from typing import Dict, Tuple, Optional, Any, List
from urllib.parse import urlparse
import glob
import uuid
from flask import Flask
from threading import Thread
import speech_recognition as sr
import subprocess
from indic_transliteration import sanscript
from indic_transliteration.sanscript import transliterate as indic_romanize
from datetime import datetime
import json
import feedparser
import schedule
import time

# Try to import git, but make it optional
try:
    import git
    GIT_AVAILABLE = True
except ImportError:
    GIT_AVAILABLE = False
    git = None

from dotenv import load_dotenv
from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    InputMediaVideo,
    InputMediaAudio,
    InputMediaDocument
)
from telegram.ext import (
    ApplicationBuilder,
    ContextTypes,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    filters,
)
import yt_dlp

# --- Load Environment ---
load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")
REQUIRED_CHANNEL_ID = os.getenv("REQUIRED_CHANNEL_ID")

# --- Configuration ---
LOG_FORMAT = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
logging.basicConfig(level=logging.INFO, format=LOG_FORMAT)
logger = logging.getLogger(__name__)

DOWNLOAD_DIR = "downloads"
if not os.path.exists(DOWNLOAD_DIR):
    os.makedirs(DOWNLOAD_DIR)

# --- In-Memory Verification Storage (Reset on restart) ---
VERIFIED_USERS = set()
URL_CACHE = {}

# --- RSS Feed Monitoring ---
RSS_FEEDS_FILE = "rss_feeds.json"
RSS_FEEDS = []
PROCESSED_POSTS = set()  # Track processed posts to avoid duplicates
ADMIN_USER_ID = None  # Will be set from environment or first user

# Load RSS feeds from file
def load_rss_feeds():
    global RSS_FEEDS, PROCESSED_POSTS
    try:
        if os.path.exists(RSS_FEEDS_FILE):
            with open(RSS_FEEDS_FILE, 'r') as f:
                data = json.load(f)
                RSS_FEEDS = data.get('feeds', [])
                PROCESSED_POSTS = set(data.get('processed_posts', []))
            logger.info(f"Loaded {len(RSS_FEEDS)} RSS feeds and {len(PROCESSED_POSTS)} processed posts")
    except Exception as e:
        logger.error(f"Error loading RSS feeds: {e}")
        RSS_FEEDS = []
        PROCESSED_POSTS = set()

# Save RSS feeds to file
def save_rss_feeds():
    try:
        data = {
            'feeds': RSS_FEEDS,
            'processed_posts': list(PROCESSED_POSTS)
        }
        with open(RSS_FEEDS_FILE, 'w') as f:
            json.dump(data, f, indent=2)
        logger.info("Saved RSS feeds configuration")
    except Exception as e:
        logger.error(f"Error saving RSS feeds: {e}")

# --- RSS Feed Monitoring Functions ---
async def check_rss_feeds(application):
    """Check all RSS feeds for new content and download automatically."""
    if not RSS_FEEDS:
        return
    
    logger.info(f"Checking {len(RSS_FEEDS)} RSS feeds for new content...")
    
    for feed_config in RSS_FEEDS:
        try:
            feed_url = feed_config['url']
            feed_name = feed_config['name']
            
            # Parse RSS feed
            feed = feedparser.parse(feed_url)
            
            for entry in feed.entries:
                post_id = entry.get('id', entry.get('link', ''))
                
                # Skip if already processed
                if post_id in PROCESSED_POSTS:
                    continue
                
                # Get the post URL
                post_url = entry.get('link', '')
                if not post_url:
                    continue
                
                # Check if it's Instagram content
                if 'instagram.com' in post_url:
                    logger.info(f"[RSS] New Instagram post found: {entry.get('title', 'No title')}")
                    
                    # Download the content
                    await download_and_notify(application, post_url, feed_name, entry.get('title', 'Instagram Post'))
                    
                    # Mark as processed
                    PROCESSED_POSTS.add(post_id)
                    
        except Exception as e:
            logger.error(f"[RSS] Error checking feed {feed_name}: {e}")
    
    # Save updated processed posts
    save_rss_feeds()

async def download_and_notify(application, url: str, feed_name: str, title: str):
    """Download media and notify admin."""
    try:
        # Download media
        file_path, info, error_msg = await download_media(url, is_audio_only=False)
        
        if file_path and os.path.exists(file_path):
            # Send to admin
            if ADMIN_USER_ID:
                try:
                    file_size = os.path.getsize(file_path) / (1024 * 1024)  # MB
                    
                    if file_size <= 50:  # Telegram limit
                        # Generate transcript if video
                        transcript_text = None
                        file_ext = os.path.splitext(file_path)[1].lower()
                        is_video = file_ext not in ['.jpg', '.jpeg', '.png', '.webp']
                        
                        if is_video:
                            transcript_text = await generate_transcript(file_path)
                        
                        # Send file to admin
                        await application.bot.send_video(
                            chat_id=ADMIN_USER_ID,
                            video=open(file_path, 'rb'),
                            caption=f"🤖 Auto-download from {feed_name}\n📹 {title}\n🔗 {url}",
                            supports_streaming=True
                        )
                        
                        # Send transcript if available
                        if is_video and transcript_text:
                            transcript_filename = f"{DOWNLOAD_DIR}/auto_transcript_{uuid.uuid4()[:8]}.txt"
                            with open(transcript_filename, "w", encoding="utf-8") as tf:
                                tf.write(f"Auto-transcript for: {title}\n{'='*50}\n\n{transcript_text}")
                            
                            await application.bot.send_document(
                                chat_id=ADMIN_USER_ID,
                                document=open(transcript_filename, "rb"),
                                filename="Auto-Transcript.txt",
                                caption="📝 Auto-generated Transcript"
                            )
                            
                            os.remove(transcript_filename)
                            
                            # Update GitHub if available
                            if GIT_AVAILABLE:
                                await auto_update_github(transcript_text, title, f"auto_{uuid.uuid4()[:8]}")
                        
                        logger.info(f"[RSS] Successfully sent auto-download to admin: {title}")
                    else:
                        logger.warning(f"[RSS] File too large ({file_size:.2f}MB): {title}")
                    
                except Exception as e:
                    logger.error(f"[RSS] Error sending to admin: {e}")
                
                # Clean up
                os.remove(file_path)
            else:
                logger.warning("[RSS] No admin user ID set")
        else:
            logger.error(f"[RSS] Download failed: {error_msg}")
            
    except Exception as e:
        logger.error(f"[RSS] Error in download_and_notify: {e}")

def run_scheduler():
    """Run the RSS feed scheduler in a separate thread."""
    while True:
        schedule.run_pending()
        time.sleep(60)  # Check every minute

def setup_rss_scheduler(application):
    """Setup RSS feed monitoring schedule."""
    # Check feeds every 15 minutes
    schedule.every(15).minutes.do(lambda: asyncio.create_task(check_rss_feeds(application)))
    
    # Start scheduler thread
    scheduler_thread = Thread(target=run_scheduler, daemon=True)
    scheduler_thread.start()
    logger.info("RSS feed scheduler started (checking every 15 minutes)")

# --- GitHub Auto-Update Function ---
async def auto_update_github(transcript_text: str, title: str, url_id: str):
    """Automatically commits and pushes transcript to GitHub repository."""
    if not GIT_AVAILABLE:
        logger.warning("[GitHub] Git not available - skipping GitHub update")
        return False
        
    try:
        loop = asyncio.get_event_loop()
        def github_update():
            try:
                # Get repository path (current directory)
                repo_path = os.getcwd()
                repo = git.Repo(repo_path)
                
                # Create transcripts directory if it doesn't exist
                transcripts_dir = os.path.join(repo_path, "transcripts")
                if not os.path.exists(transcripts_dir):
                    os.makedirs(transcripts_dir)
                
                # Create transcript file with timestamp
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                transcript_filename = f"{timestamp}_{url_id}.txt"
                transcript_path = os.path.join(transcripts_dir, transcript_filename)
                
                # Write transcript to file
                with open(transcript_path, "w", encoding="utf-8") as f:
                    f.write(f"Title: {title}\n")
                    f.write(f"URL ID: {url_id}\n")
                    f.write(f"Timestamp: {timestamp}\n")
                    f.write(f"{'='*50}\n\n")
                    f.write(transcript_text)
                
                # Git operations
                if repo.is_dirty(untracked_files=True):
                    repo.git.add(transcript_path)
                    commit_message = f"Add transcript: {title[:50]}... ({timestamp})"
                    repo.git.commit("-m", commit_message)
                    
                    # Push to remote
                    origin = repo.remote(name='origin')
                    origin.push()
                    
                    logger.info(f"[GitHub] Successfully pushed transcript: {transcript_filename}")
                    return True
                else:
                    logger.info("[GitHub] No changes to commit")
                    return False
                    
            except git.InvalidGitRepositoryError:
                logger.error("[GitHub] Not a valid git repository")
                return False
            except Exception as e:
                logger.error(f"[GitHub] Error updating repository: {e}")
                return False
        
        return await loop.run_in_executor(None, github_update)
        
    except Exception as e:
        logger.error(f"[GitHub] Auto-update failed: {e}")
        return False

# --- Keep Alive Server for Render ---
app = Flask('')

@app.route('/')
def home():
    return "I'm alive"

def run_flask():
    port = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=port)

def keep_alive():
    t = Thread(target=run_flask)
    t.start()

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    
    # Check if user is already verified (clicked the button previously)
    if user.id in VERIFIED_USERS:
        await update.message.reply_text(
            f"Welcome back, {user.first_name}! 👋\n\n"
            "✅ You are verified.\n"
            "Send me a link from Instagram, TikTok, YouTube, or Facebook to start downloading!",
            parse_mode='Markdown'
        )
        return

    welcome_message = (
        f"Hello {user.first_name}! 👋\n\n"
        "To use the **Universal Media Downloader Bot**, you must **Subscribe & Follow** our official channels:\n\n"
        "1️⃣ **Subscribe** to YouTube\n"
        "2️⃣ **Follow** on Instagram & TikTok\n"
        "3️⃣ **Follow** on Facebook\n\n"
        "👇 Click the buttons below to follow, then click **'✅ I Have Subscribed'** to unlock the bot."
    )
    
    # Social Media Links
    social_buttons = [
        [InlineKeyboardButton("YouTube", url="https://www.youtube.com/@NobojitNexus"),
         InlineKeyboardButton("Instagram", url="https://www.instagram.com/mr_nobojit.m")],
        [InlineKeyboardButton("TikTok", url="https://www.tiktok.com/@nobojitnexus"),
         InlineKeyboardButton("Facebook", url="https://www.facebook.com")] 
    ]
    
    keyboard = []
    keyboard.extend(social_buttons)
    # The "Verification" button
    keyboard.append([InlineKeyboardButton("✅ I Have Subscribed", callback_data="verify_socials")])

    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(welcome_message, reply_markup=reply_markup, parse_mode='Markdown')

async def verify_socials_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    
    # "Simulate" verification (since we can't actually check external follows via API easily)
    VERIFIED_USERS.add(user_id)
    
    await query.answer("Verification Successful!")
    
    await query.edit_message_text(
        "🎉 **Verification Successful!**\n\n"
        "Thank you for subscribing! You now have full access.\n"
        "**Send me a link** to start downloading.",
        parse_mode='Markdown'
    )

# --- Media Processing Logic ---
def get_platform(url: str) -> str:
    domain = urlparse(url).netloc.lower()
    if 'instagram' in domain: return 'Instagram'
    if 'tiktok' in domain: return 'TikTok'
    if 'youtube' in domain or 'youtu.be' in domain: return 'YouTube'
    if 'facebook' in domain or 'fb.watch' in domain: return 'Facebook'
    if 'pinterest' in domain: return 'Pinterest'
    if 'twitter' in domain or 'x.com' in domain: return 'Twitter'
    return 'Unknown'

async def download_media(url: str, is_audio_only: bool = False) -> Tuple[Optional[str], Optional[Dict], Optional[str]]:
    """
    Downloads media using yt-dlp. Returns (file_path, info, error_message).
    """
    cookies_path = 'cookies.txt'
    use_cookies = os.path.exists(cookies_path)

    ydl_opts = {
        'outtmpl': f'{DOWNLOAD_DIR}/%(title).100s.%(ext)s', 
        'quiet': True,
        'no_warnings': True,
        'nocheckcertificate': True,
        'geo_bypass': True,
        'retries': 5,
        'fragment_retries': 10,
        'extractor_retries': 5,
        'file_access_retries': 5,
        'socket_timeout': 60,
        'force_ipv4': True,
        'extractor_args': {
            'youtube': {
                'player_client': ['android', 'ios', 'mweb', 'tv'],
            }
        },
        'format': 'bestvideo[vcodec^=avc1]+bestaudio[acodec^=mp4a]/best[vcodec^=avc1][acodec^=mp4a]/best[ext=mp4]/best',
        'http_headers': {
             'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36',
             'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8',
             'Accept-Language': 'en-US,en;q=0.9',
             'Sec-Fetch-Mode': 'navigate',
        }
    }

    if use_cookies:
        ydl_opts['cookiefile'] = cookies_path
        logger.info("Using cookies for download.")

    if is_audio_only:
        ydl_opts.update({
            'format': 'bestaudio/best',
            'postprocessors': [{'key': 'FFmpegExtractAudio','preferredcodec': 'mp3','preferredquality': '192'}],
        })

    try:
        loop = asyncio.get_event_loop()
        def run_ydl():
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                if url.startswith("ytsearch"):
                    info = ydl.extract_info(url, download=False)
                    if 'entries' in info and len(info['entries']) > 0:
                        first_entry = info['entries'][0]
                        real_url = first_entry['webpage_url']
                        info = ydl.extract_info(real_url, download=True)
                    else:
                        raise Exception("No search results found.")
                else:
                    info = ydl.extract_info(url, download=True)
                
                filename = ydl.prepare_filename(info)
                if is_audio_only:
                    base, _ = os.path.splitext(filename)
                    filename = base + ".mp3"
                return filename, info, None
        
        return await loop.run_in_executor(None, run_ydl)

    except Exception as e:
        error_str = str(e)
        logger.error(f"Download error: {error_str}")
        
        custom_error = "❌ Failed to download media."
        if "confirm you're not a bot" in error_str or "Sign in to confirm you're not a bot" in error_str:
            custom_error = (
                "❌ YouTube bot detection blocked the download.\n\n"
                "To fix this:\n"
                "1. Export your YouTube cookies as `cookies.txt` and place them in the bot folder.\n"
                "2. Ensure you are using the latest version of yt-dlp."
            )
        elif "Private video" in error_str:
            custom_error = "❌ This video is private."
        elif "Login required" in error_str:
            custom_error = "❌ Login required to view this content."
            
        return None, None, custom_error

# --- Language detection config: (google_lang_code, display_name, indic_script or None) ---
LANGUAGE_ATTEMPTS = [
    ("hi-IN",  "Hindi",      sanscript.DEVANAGARI),
    ("bn-IN",  "Bengali",    sanscript.BENGALI),
    ("ur-PK",  "Urdu",       sanscript.ARABIC),
    ("mr-IN",  "Marathi",    sanscript.DEVANAGARI),
    ("gu-IN",  "Gujarati",   sanscript.GUJARATI),
    ("pa-IN",  "Punjabi",    sanscript.GURMUKHI),
    ("ta-IN",  "Tamil",      sanscript.TAMIL),
    ("te-IN",  "Telugu",     sanscript.TELUGU),
    ("kn-IN",  "Kannada",    sanscript.KANNADA),
    ("ml-IN",  "Malayalam",  sanscript.MALAYALAM),
    ("ar-AE",  "Arabic",     None),
    ("en-US",  "English",    None),
]

async def generate_transcript(video_path: str) -> Optional[str]:
    """Auto-detects language, transcribes, and romanizes to Hinglish/Banglish style."""
    loop = asyncio.get_event_loop()
    def transcribe():
        wav_path = video_path + ".wav"
        try:
            logger.info(f"[Transcript] FFmpeg extracting + filtering audio: {video_path}")
            result = subprocess.run(
                [
                    "ffmpeg", "-y", "-i", video_path,
                    "-ac", "1", "-ar", "16000",
                    # Speech isolation filters:
                    # highpass=200  -> cut bass/music beats below 200Hz
                    # lowpass=3500  -> cut high noise above 3500Hz
                    # dynaudnorm    -> normalize quiet speech dynamically
                    # volume=4      -> boost overall volume 4x
                    "-af", "highpass=f=200,lowpass=f=3500,dynaudnorm,volume=4",
                    wav_path
                ],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE
            )
            if result.returncode != 0:
                logger.error(f"[Transcript] FFmpeg error: {result.stderr.decode('utf-8', errors='replace')}")
                return None
            logger.info("[Transcript] FFmpeg audio filtering done.")

            recognizer = sr.Recognizer()
            with sr.AudioFile(wav_path) as source:
                audio = recognizer.record(source, duration=60)

            # Try each language until one succeeds
            for lang_code, lang_name, script in LANGUAGE_ATTEMPTS:
                try:
                    logger.info(f"[Transcript] Trying language: {lang_name} ({lang_code})")
                    raw_text = recognizer.recognize_google(audio, language=lang_code)
                    if not raw_text:
                        continue
                    logger.info(f"[Transcript] Detected {lang_name}: {raw_text[:80]}")

                    # Romanize if it's an Indic script (Hinglish / Banglish style)
                    if script:
                        try:
                            romanized = indic_romanize(raw_text, script, sanscript.ITRANS)
                        except Exception as re:
                            logger.warning(f"[Transcript] Romanization failed: {re}")
                            romanized = raw_text
                        return (
                            f"Detected Language: {lang_name}\n"
                            f"{'=' * 40}\n\n"
                            f"🔤 Romanized ({lang_name}lish style):\n{romanized}\n\n"
                            f"📜 Original Script:\n{raw_text}"
                        )
                    else:
                        # Arabic or English — return as-is
                        return (
                            f"Detected Language: {lang_name}\n"
                            f"{'=' * 40}\n\n"
                            f"{raw_text}"
                        )

                except sr.UnknownValueError:
                    logger.info(f"[Transcript] No match for {lang_name}, trying next...")
                    continue
                except sr.RequestError as e:
                    logger.error(f"[Transcript] Google API error: {e}")
                    return f"[Speech API error: {e}]"

            logger.warning("[Transcript] No language matched audio.")
            return "[Could not detect speech in any supported language]"

        except Exception as e:
            logger.error(f"[Transcript] Unexpected error: {e}")
            return None
        finally:
            if os.path.exists(wav_path):
                os.remove(wav_path)
                logger.info("[Transcript] WAV cleaned up.")
    return await loop.run_in_executor(None, transcribe)

async def handle_song_search(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query_text = update.message.text
    status_msg = await update.message.reply_text(f"🔎 Searching for '{query_text}'...")

    search_url = f"ytsearch1:{query_text}"
    
    try:
        file_path, info, error_msg = await download_media(search_url, is_audio_only=True)
        
        if file_path and os.path.exists(file_path):
             await status_msg.edit_text("📤 Found! Uploading...")
             
             # Extract title/uploader safely
             if 'entries' in info: 
                 info = info['entries'][0]
                 
             title = info.get('title', query_text)
             uploader = info.get('uploader', 'Unknown')

             with open(file_path, 'rb') as f:
                await update.message.reply_audio(
                    audio=f,
                    title=title,
                    performer=uploader,
                    caption=f"🎵 **{title}**\nMatches: {query_text}",
                    parse_mode='Markdown'
                )
             os.remove(file_path)
             await status_msg.delete()
        else:
             await status_msg.edit_text(error_msg or "❌ No results found or download failed.")

    except Exception as e:
        logger.error(f"Search error: {e}")
        await status_msg.edit_text(f"An error occurred during search: {str(e)}")

async def handle_mp3_conversion(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer("Converting...")
    
    try:
        data_parts = query.data.split("|", 1)
        if len(data_parts) < 2:
            return
        _, url_id = data_parts
        
        # Look up URL from cache
        url = URL_CACHE.get(url_id)
        if not url:
             await query.message.reply_text("❌ Link expired. Please search again.")
             return
        
        status_msg = await query.message.reply_text("⏳ Converting audio...")
        
        file_path, info, error_msg = await download_media(url, is_audio_only=True)
        
        if file_path and os.path.exists(file_path):
            await status_msg.edit_text("📤 Uploading Audio...")
            title = info.get('title', 'Audio')
            with open(file_path, 'rb') as f:
                await query.message.reply_audio(
                    audio=f,
                    title=title,
                    performer=info.get('uploader', 'Unknown'),
                    caption=f"🎵 **{title}**",
                    parse_mode='Markdown'
                )
            os.remove(file_path)
            await status_msg.delete()
        else:
             await status_msg.edit_text(error_msg or "❌ Failed to convert audio.")

    except Exception as e:
        logger.error(f"Error converting MP3: {e}")
        # Need to check context for reply if status_msg exist
        if 'status_msg' in locals():
            await status_msg.edit_text(f"Error converting audio: {str(e)}")

async def handle_url(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.message
    if not message or not message.text:
            return
    url = message.text.strip()
    user = message.from_user
    
    # 1. Verify Membership (Socials Gatekeeper)
    if user.id not in VERIFIED_USERS:
        await message.reply_text(
            "🔒 **Access Denied**\n"
            "Please run /start and follow our social media accounts to unlock the bot.",
            parse_mode='Markdown'
        )
        return

    # 2. Detect Platform
    platform = get_platform(url)
    logger.info(f"User {user.first_name} requested {platform} link: {url}")

    if platform == 'Unknown' and not (url.startswith('http') or url.startswith('www')):
        await handle_song_search(update, context)
        return
        
    status_msg = await message.reply_text(f"⏳ Processing link from {platform}...")

    # 3. Download
    try:
        logger.info("Starting download...")
        file_path, info, error_msg = await download_media(url, is_audio_only=False)
        
        if not file_path or not os.path.exists(file_path):
            logger.error("Download failed or file not found.")
            await status_msg.edit_text(error_msg or "❌ Failed to download media. The link might be private or invalid.")
            return

        title = info.get('title', 'Media')
        file_size = os.path.getsize(file_path) / (1024 * 1024) # MB
        logger.info(f"Download success. File: {file_path}, Size: {file_size:.2f}MB")
        
        # 4. Upload
        if file_size > 50:
            await status_msg.edit_text(f"❌ File is too large ({file_size:.2f}MB). Telegram bot limit is 50MB.")
            os.remove(file_path)
            return

        await status_msg.edit_text("📤 Uploading...")
        
        # Determine URL for callback - use cache for long URLs
        # Generate short ID
        url_id = str(uuid.uuid4())[:8]
        URL_CACHE[url_id] = url
        
        # Determine file type
        file_ext = os.path.splitext(file_path)[1].lower()
        is_video = file_ext not in ['.jpg', '.jpeg', '.png', '.webp']

        # --- Generate transcript BEFORE opening file for upload ---
        transcript_text = None
        if is_video:
            await status_msg.edit_text("🗣️ Generating transcript...")
            transcript_text = await generate_transcript(file_path)
            logger.info(f"[Transcript] Result: {transcript_text}")

        await status_msg.edit_text("📤 Uploading...")

        keyboard = []
        if is_video:
            keyboard.append([InlineKeyboardButton("Download as MP3", callback_data=f"convert_mp3|{url_id}")])
        reply_markup = InlineKeyboardMarkup(keyboard) if keyboard else None

        # --- Upload video/photo (separate file handle, closed after) ---
        if is_video:
            with open(file_path, 'rb') as f:
                await message.reply_video(
                    video=f,
                    caption=f"🎥 {title}\nDownloaded via Universal Bot",
                    reply_markup=reply_markup,
                    supports_streaming=True,
                    read_timeout=120,
                    write_timeout=120,
                    connect_timeout=60
                )
        else:
            with open(file_path, 'rb') as f:
                await message.reply_photo(
                    photo=f,
                    caption=f"📸 {title}\nDownloaded via Universal Bot",
                    reply_markup=reply_markup,
                    read_timeout=120,
                    write_timeout=120,
                    connect_timeout=60
                )

        os.remove(file_path)

        # --- Send transcript AFTER video is fully uploaded and file is closed ---
        if is_video and transcript_text:
            transcript_filename = f"{DOWNLOAD_DIR}/transcript_{url_id}.txt"
            try:
                with open(transcript_filename, "w", encoding="utf-8") as tf:
                    tf.write(f"Transcript for: {title}\n{'='*50}\n\n{transcript_text}")
                with open(transcript_filename, "rb") as tf:
                    await message.reply_document(
                        document=tf,
                        filename="Transcript.txt",
                        caption="📝 Auto-generated Transcript"
                    )
                logger.info("[Transcript] Sent transcript to user.")
                
                # --- Auto-update GitHub with transcript ---
                if GIT_AVAILABLE:
                    await status_msg.edit_text("🔄 Updating GitHub...")
                    github_success = await auto_update_github(transcript_text, title, url_id)
                    if github_success:
                        logger.info("[Transcript] GitHub update successful.")
                    else:
                        logger.warning("[Transcript] GitHub update failed.")
                else:
                    logger.info("[Transcript] GitHub integration not available - skipping.")
                    
            except Exception as e:
                logger.error(f"[Transcript] Failed to send transcript file: {e}")
            finally:
                if os.path.exists(transcript_filename):
                    os.remove(transcript_filename)

        await status_msg.delete()
        logger.info("Upload completed.")

    except Exception as e:
        logger.error(f"Error handling URL: {e}")
        await status_msg.edit_text(f"An error occurred: {str(e)}")

# --- RSS Admin Commands ---
async def add_rss_feed(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Add RSS feed for monitoring. Usage: /add_rss <name> <rss_url>"""
    user_id = update.effective_user.id
    
    # Set admin if not set (first user to use admin commands)
    global ADMIN_USER_ID
    if ADMIN_USER_ID is None:
        ADMIN_USER_ID = user_id
        logger.info(f"Set admin user ID: {ADMIN_USER_ID}")
    
    # Check if user is admin
    if user_id != ADMIN_USER_ID:
        await update.message.reply_text("❌ Admin only command!")
        return
    
    try:
        args = context.args
        if len(args) < 2:
            await update.message.reply_text("Usage: /add_rss <name> <rss_url>\n\nExample: /add_rss mycreator https://rss.app/feeds/xyz")
            return
        
        name = args[0]
        rss_url = args[1]
        
        # Validate RSS URL
        try:
            feed = feedparser.parse(rss_url)
            if feed.bozo:
                await update.message.reply_text("❌ Invalid RSS feed URL!")
                return
        except:
            await update.message.reply_text("❌ Failed to parse RSS feed!")
            return
        
        # Add to feeds
        RSS_FEEDS.append({
            'name': name,
            'url': rss_url,
            'added_date': datetime.now().isoformat()
        })
        
        save_rss_feeds()
        
        await update.message.reply_text(
            f"✅ RSS feed added successfully!\n\n"
            f"📝 Name: {name}\n"
            f"🔗 URL: {rss_url}\n"
            f"⏰ Checking every 15 minutes"
        )
        
        logger.info(f"[RSS] Added feed: {name} - {rss_url}")
        
    except Exception as e:
        logger.error(f"[RSS] Error adding feed: {e}")
        await update.message.reply_text("❌ Failed to add RSS feed!")

async def list_rss_feeds(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """List all RSS feeds."""
    user_id = update.effective_user.id
    
    if user_id != ADMIN_USER_ID:
        await update.message.reply_text("❌ Admin only command!")
        return
    
    if not RSS_FEEDS:
        await update.message.reply_text("📭 No RSS feeds configured.")
        return
    
    message = "📋 **Active RSS Feeds:**\n\n"
    for i, feed in enumerate(RSS_FEEDS, 1):
        message += f"{i}. **{feed['name']}**\n"
        message += f"   🔗 {feed['url']}\n"
        message += f"   📅 Added: {feed.get('added_date', 'Unknown')}\n\n"
    
    message += f"🔄 Total: {len(RSS_FEEDS)} feeds\n⏰ Checking every 15 minutes"
    
    await update.message.reply_text(message, parse_mode='Markdown')

async def remove_rss_feed(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Remove RSS feed. Usage: /remove_rss <name>"""
    user_id = update.effective_user.id
    
    if user_id != ADMIN_USER_ID:
        await update.message.reply_text("❌ Admin only command!")
        return
    
    try:
        args = context.args
        if len(args) < 1:
            await update.message.reply_text("Usage: /remove_rss <name>")
            return
        
        name = args[0]
        
        # Find and remove feed
        original_count = len(RSS_FEEDS)
        RSS_FEEDS = [feed for feed in RSS_FEEDS if feed['name'] != name]
        
        if len(RSS_FEEDS) < original_count:
            save_rss_feeds()
            await update.message.reply_text(f"✅ Removed RSS feed: {name}")
            logger.info(f"[RSS] Removed feed: {name}")
        else:
            await update.message.reply_text(f"❌ RSS feed not found: {name}")
            
    except Exception as e:
        logger.error(f"[RSS] Error removing feed: {e}")
        await update.message.reply_text("❌ Failed to remove RSS feed!")

async def check_rss_now(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Manually trigger RSS feed check."""
    user_id = update.effective_user.id
    
    if user_id != ADMIN_USER_ID:
        await update.message.reply_text("❌ Admin only command!")
        return
    
    await update.message.reply_text("🔄 Checking RSS feeds for new content...")
    
    # Get the application context
    application = context.application
    await check_rss_feeds(application)
    
    await update.message.reply_text("✅ RSS feed check completed!")

def main():
    if not BOT_TOKEN:
        print("Error: BOT_TOKEN not found in .env file.")
        return

    # Load RSS feeds on startup
    load_rss_feeds()

    # Write cookies from ENV if available (for cloud hosting)
    cookies_content = os.getenv("COOKIES_CONTENT")
    if cookies_content:
        # Detect if it's JSON and convert to Netscape format
        if cookies_content.strip().startswith("[") and cookies_content.strip().endswith("]"):
            try:
                import json
                cookies = json.loads(cookies_content)
                netscape_text = "# Netscape HTTP Cookie File\n"
                for c in cookies:
                    domain = c.get('domain', '')
                    include_subdomains = "TRUE" if domain.startswith('.') else "FALSE"
                    path = c.get('path', '/')
                    secure = "TRUE" if c.get('secure') else "FALSE"
                    expiry = int(c.get('expirationDate', 0))
                    name = c.get('name', '')
                    value = c.get('value', '')
                    netscape_text += f"{domain}\t{include_subdomains}\t{path}\t{secure}\t{expiry}\t{name}\t{value}\n"
                cookies_content = netscape_text
                logger.info("Detected JSON cookies. Converted to Netscape format successfully.")
            except Exception as e:
                logger.error(f"Error converting JSON cookies: {e}")

        with open("cookies.txt", "w") as f:
            f.write(cookies_content)

    # Increase global timeouts
    from telegram.request import HTTPXRequest
    request = HTTPXRequest(connection_pool_size=8, read_timeout=120, write_timeout=120, connect_timeout=60)

    application = ApplicationBuilder().token(BOT_TOKEN).request(request).build()

    # Register handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("add_rss", add_rss_feed))
    application.add_handler(CommandHandler("list_rss", list_rss_feeds))
    application.add_handler(CommandHandler("remove_rss", remove_rss_feed))
    application.add_handler(CommandHandler("check_rss", check_rss_now))
    application.add_handler(CallbackQueryHandler(verify_socials_callback, pattern="^verify_socials$"))
    application.add_handler(CallbackQueryHandler(handle_mp3_conversion, pattern=r"^convert_mp3\|"))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_url))

    # Setup RSS scheduler
    setup_rss_scheduler(application)

    keep_alive()
    print("Bot is running...")
    application.run_polling()

if __name__ == '__main__':
    main()
