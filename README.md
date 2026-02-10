# Universal Media Downloader Bot

A Telegram bot that downloads videos and audio from various platforms (YouTube, Instagram, TikTok, Facebook, etc.) and allows searching for songs.

## Features
- **User Verification**: Forces users to join a channel before using the bot.
- **Multi-Platform Support**: Downloads from Instagram, TikTok, YouTube, Facebook, Pinterest, Twitter/X.
- **Audio Extraction**: Option to convert any video download to MP3.
- **Song Search**: Search for songs by name (fetches from YouTube).

## Setup

1.  **Install Python**: Ensure Python 3.8+ is installed.
2.  **Install FFmpeg**: Required for audio conversion.
     - Windows: Download from [gyan.dev](https://www.gyan.dev/ffmpeg/builds/) (already installed in this environment).
3.  **Install python dependencies**:
    ```bash
    pip install -r requirements.txt
    ```
4.  **Configure Environment Variables**:
    - Open `.env` file.
    - Set `BOT_TOKEN` to your Telegram Bot Token (from @BotFather).
    - Set `REQUIRED_CHANNEL_ID` to your channel username (e.g., @mychannel).
    - **Note**: The bot must be an **Administrator** in your channel to verify membership.

## Running the Bot

Run the bot by double-clicking `start.bat` or executing:
```bash
start.bat
```
Or manually:
```bash
python bot.py
```

## Usage
- Start the bot with `/start`.
- Join the required channel and click "Verify Membership".
- Send a link to download video.
- Click "Download as MP3" on the video to get audio.
- Determine a song by typing its name (e.g., "Despacito").
