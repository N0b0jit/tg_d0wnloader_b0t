# How to Host Your Telegram Bot for Free on Render.com

This guide will help you deploy your Telegram bot so it runs 24/7 in the cloud for free.

## Prerequisites (Already prepared for you)
We have added three key files to your project:
1. **`Dockerfile`**: Tells Render how to build your bot and install `ffmpeg`.
2. **`requirements.txt`**: Added `flask` so we can keep the bot alive.
3. **`bot.py`**: Added a small web server to satisfy Render's requirements.

## Step 1: Push Changes to GitHub
You need to save these changes to your GitHub repository first.
Run these commands in your terminal:

```bash
git add .
git commit -m "Prepare for Render hosting"
git push origin main
```

*(Note: It might be `master` instead of `main` depending on your repo settings. Check `git branch` if unsure).*

## Step 2: Create a Web Service on Render
1. Go to [Render.com](https://render.com) and sign up/login.
2. Click **New +** and select **Web Service**.
3. Connect your GitHub account and select your repository: `tg_d0wnloader_b0t`.
4. Configure the service:
   - **Name**: `tg-downloader-bot` (or anything you like)
   - **Region**: Choose one close to you (e.g., Singapore, Frankfurt).
   - **Branch**: `main` (or `master`)
   - **Runtime**: **Docker** (This is important! Do not select Python).
   - **Instance Type**: **Free**.

5. Scroll down to **Environment Variables** and add:
   - `BOT_TOKEN`: Your Telegram Bot Token (from .env).
   - `REQUIRED_CHANNEL_ID`: Your Channel ID (from .env).
   - `COOKIES_CONTENT`: (Optional) Paste the contents of `cookies.txt` here if your bot requires login for specific sites.

6. Click **Create Web Service**.

## Step 3: Keep the Bot Alive
Render's free tier sleeps after 15 minutes of inactivity. To prevent this:
1. Once your service is live, copy the **Service URL** (e.g., `https://tg-downloader-bot.onrender.com`).
2. Go to [UptimeRobot.com](https://uptimerobot.com) (it's free).
3. Create a **New Monitor**:
   - **Monitor Type**: HTTP(s)
   - **Friendly Name**: My Bot
   - **URL**: Paste your Render Service URL.
   - **Monitoring Interval**: 5 minutes.
4. Click **Create Monitor**.

This will ping your bot every 5 minutes, preventing it from sleeping.

## Troubleshooting
- **Build Failed?** Check the logs in Render. Ensure `ffmpeg` installed correctly (the Dockerfile handles this).
- **Bot not responding?** Check if the `BOT_TOKEN` is correct in Environment Variables.
- **Cookies issues?** If downloads fail due to login, paste your `cookies.txt` content into the `COOKIES_CONTENT` environment variable.
