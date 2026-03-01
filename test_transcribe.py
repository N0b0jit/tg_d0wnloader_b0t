import speech_recognition as sr
import os
import subprocess

def test_transcribe(video_path):
    wav_path = video_path + ".wav"
    
    print(f"[1/3] Converting video to WAV: {video_path}")
    result = subprocess.run(
        ["ffmpeg", "-y", "-i", video_path, "-ac", "1", "-ar", "16000", wav_path],
        stdout=subprocess.DEVNULL, stderr=subprocess.PIPE
    )
    if result.returncode != 0:
        print("❌ FFmpeg failed. Make sure ffmpeg is installed and the file path is correct.")
        return
    
    print("[2/3] Extracting audio and sending to Google Speech-to-Text...")
    recognizer = sr.Recognizer()
    with sr.AudioFile(wav_path) as source:
        audio = recognizer.record(source, duration=60)

    try:
        text = recognizer.recognize_google(audio)
        print(f"\n✅ Transcript:\n{text}\n")

        # Save to .txt
        txt_path = video_path + "_transcript.txt"
        with open(txt_path, "w", encoding="utf-8") as f:
            f.write(text)
        print(f"[3/3] Transcript saved to: {txt_path}")

    except sr.UnknownValueError:
        print("⚠️ Could not detect speech in the video (maybe no dialogue?).")
    except sr.RequestError as e:
        print(f"❌ Google Speech API error: {e}")
    finally:
        if os.path.exists(wav_path):
            os.remove(wav_path)
            print("Cleaned up temporary WAV file.")


# ---- EDIT THIS PATH to point to a real downloaded video ----
VIDEO_PATH = "downloads/Kramer the movie expert [Seinfeld S7E08] Moviephone.mp4"

if not os.path.exists(VIDEO_PATH):
    print(f"❌ Video not found at: {VIDEO_PATH}")
    print("   Please download a reel first and update VIDEO_PATH in this script.")
else:
    test_transcribe(VIDEO_PATH)
