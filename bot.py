
import os
import logging
import asyncio
from typing import Dict, Tuple, Optional, Any
from urllib.parse import urlparse
import glob
import uuid
from flask import Flask
from threading import Thread
import speech_recognition as sr
import subprocess
from indic_transliteration import sanscript
from indic_transliteration.sanscript import transliterate as indic_romanize

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
    ("ur-PK",  "Urdu",       sanscript.SHARADA),
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
            logger.info(f"[Transcript] FFmpeg extracting audio: {video_path}")
            result = subprocess.run(
                ["ffmpeg", "-y", "-i", video_path, "-ac", "1", "-ar", "16000", wav_path],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE
            )
            if result.returncode != 0:
                logger.error(f"[Transcript] FFmpeg error: {result.stderr.decode('utf-8', errors='replace')}")
                return None

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

def main():
    if not BOT_TOKEN:
        print("Error: BOT_TOKEN not found in .env file.")
        return

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

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CallbackQueryHandler(verify_socials_callback, pattern="^verify_socials$"))
    application.add_handler(CallbackQueryHandler(handle_mp3_conversion, pattern=r"^convert_mp3\|"))
    
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_url))

    keep_alive()
    print("Bot is running...")
    application.run_polling()

if __name__ == '__main__':
    main()
