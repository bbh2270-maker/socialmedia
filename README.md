# Social Media Auto-Poster (Facebook Page)

An autonomous, lightweight, production-ready Python tool that generates high-engaging captions and images using AI (or your Google Drive assets) and automatically publishes them to your **Facebook PAGE** twice a day via scheduled cron jobs.

Optimized for **Hostinger Cloud Startup** hosting (Linux) and local development (**Windows**).

---

## Table of Contents
1. [Overview & Key Features](#overview--key-features)
2. [Project Structure](#project-structure)
3. [Local Setup (Windows / macOS / Linux)](#local-setup-windows--macos--linux)
4. [Facebook App & Long-Lived Token Setup (Step-by-Step)](#facebook-app--long-lived-token-setup-step-by-step)
5. [AI Provider API Keys Setup](#ai-provider-api-keys-setup)
6. [Google Drive Image Preparation](#google-drive-image-preparation)
7. [Configuration Guide (`config.json`)](#configuration-guide-configjson)
8. [CLI Usage & Diagnostic Commands](#cli-usage--diagnostic-commands)
9. [Hostinger Cloud Deployment (Step-by-Step)](#hostinger-cloud-deployment-step-by-step)
10. [Troubleshooting Guide](#troubleshooting-guide)
11. [Verification Checklist for Real Keys](#verification-checklist-for-real-keys)

---

## 1. Overview & Key Features

- **No Always-Running Daemon**: Runs once when triggered by cron, completes its job, writes logs, and exits. Zero background memory footprint.
- **Pure-Python & Lightweight**: Relies on minimal dependencies (`requests`, `python-dotenv`, `Pillow`) via standard REST APIs — no heavy, fragile SDKs.
- **Multi-Provider AI Fallback**: Configurable priority order (`["gemini", "groq", "openrouter"]`). If one provider hits a rate limit (HTTP 429) or goes down, it automatically falls back to the next provider.
- **Multimodal & Vision Capable**: When using Google Drive images, optionally lets Google Gemini look at the image and craft a contextual caption that fits the graphic.
- **Smart Image Routing**:
  - `ai`: Generates high-resolution images via Gemini Imagen 3 or OpenRouter Flux.
  - `drive`: Automatically cycles through Google Drive images without repetition.
  - `mixed`: Randomly balances between AI generation and manual Drive assets.
  - Graceful fallback: `AI -> Drive -> Text-only`.
- **Twice-Daily Safety & 30-Post Anti-Duplicate**:
  - Automatically identifies its scheduling slot (Morning vs Evening in `Asia/Dhaka`).
  - SQLite persistence ensures the same slot is **never posted twice on the same day**.
  - Checks the last 30 posts to ensure topics and opening hooks never repeat.
- **Secret Redaction**: Logger automatically masks access tokens and API keys to prevent accidental leaks in logs or terminal outputs.

> [!NOTE]
> **Facebook Policy**: Meta's Graph API **only allows automated posting to Facebook Pages**, never to personal user profiles. This script requires a Facebook Page ID and Page Access Token.

---

## 2. Project Structure

```
socialmedia/
├── config.json               # Brand, topics, AI model & provider order, posting settings
├── .env.example              # Template for API keys and secrets
├── .env                      # Your real credentials (git-ignored)
├── .gitignore                # Protects secrets, database, logs, and outputs
├── requirements.txt          # Pure-Python dependencies
├── README.md                 # Complete documentation
├── run_post.py               # Main CLI entrypoint for manual and cron runs
├── src/
│   ├── __init__.py
│   ├── utils.py              # Timezone slots, logger with secret masking, retry decorator
│   ├── db.py                 # SQLite database models, slot check & 30-post history
│   ├── topics.py             # Smart topic selector (last 30 posts non-repetition)
│   ├── drive.py              # Google Drive download, confirm bypass, image validation
│   ├── ai_text.py            # Gemini, Groq, OpenRouter REST client with automatic fallback
│   ├── ai_image.py           # Gemini Imagen & OpenRouter generation with Drive fallback
│   └── facebook.py           # Graph API photo & feed client with error parser
├── tests/
│   ├── __init__.py
│   ├── test_drive.py         # Google Drive link parsing & download verification
│   ├── test_ai_fallback.py   # Multi-provider fallback & prompt tests
│   ├── test_db_and_slot.py   # Slot checking & 30-post anti-duplicate tests
│   └── test_facebook.py      # Facebook Graph API mocks & error parsing tests
├── data/                     # SQLite database: autoposter.db (auto-created)
├── logs/                     # Rotating app.log (auto-created)
└── output/                   # Dry-run previews and generated images (auto-created)
```

---

## 3. Local Setup (Windows / macOS / Linux)

### Step 1: Clone or Open the Workspace
```powershell
cd c:\Users\Bulbul\Documents\GitHub\socialmedia
```

### Step 2: Create and Activate Virtual Environment
**Windows (PowerShell):**
```powershell
python -m venv venv
.\venv\Scripts\Activate.ps1
```
*(If PowerShell restricts scripts, run: `Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass`)*

**Linux / macOS:**
```bash
python3 -m venv venv
source venv/bin/activate
```

### Step 3: Install Dependencies
```bash
pip install -r requirements.txt
```

### Step 4: Configure `.env`
Copy `.env.example` to `.env`:
```powershell
copy .env.example .env     # Windows
cp .env.example .env       # Linux / macOS
```
Edit `.env` and fill in your keys.

---

## 4. Facebook App & Long-Lived Token Setup (Step-by-Step)

To post to your Facebook Page, you need:
1. **Numeric Page ID**
2. **Never-Expiring (Long-Lived) Page Access Token**

### Part A: Find Your Numeric Page ID
1. Open your Facebook Page in a browser.
2. Go to the **About** tab -> **Page transparency** (or look at the URL / Page Settings).
3. Copy the numeric **Page ID** (e.g., `104829105829102`).
4. Put it in `.env`:
   ```ini
   FB_PAGE_ID=104829105829102
   ```

### Part B: Create a Meta Developer App
1. Go to [developers.facebook.com](https://developers.facebook.com/) and log in.
2. Click **My Apps** > **Create App**.
3. Choose **Other** > click **Next**.
4. Select app type: **Business** > click **Next**.
5. Give your App a name (e.g., `Social AutoPoster`) and click **Create App**.

### Part C: Generate a Long-Lived Page Access Token
1. Open the **[Graph API Explorer](https://developers.facebook.com/tools/explorer/)**.
2. In the top right:
   - **Meta App**: Select your newly created app.
   - **User or Page**: Select `User Token`.
3. In the **Permissions** dropdown, add these 3 permissions:
   - `pages_manage_posts`
   - `pages_read_engagement`
   - `pages_show_list`
4. Click **Generate Access Token** and accept the Facebook permissions popup.
5. In the `User or Page` dropdown, switch from **User Token** to your **Facebook Page**.
6. The token in the token field is now a **Page Access Token**.
7. To make this token permanent (never expire):
   - Go to the **[Access Token Debugger](https://developers.facebook.com/tools/debug/accesstoken/)**.
   - Paste the Page Access Token and click **Debug**.
   - Click the **Extend Access Token** button at the bottom.
   - The resulting token is a **long-lived Page token** that will not expire.
8. Copy this token and put it in `.env`:
   ```ini
   FB_PAGE_ACCESS_TOKEN=EAAB...
   ```

---

## 5. AI Provider API Keys Setup

Add your API keys to `.env`:

| Provider | Purpose | Where to Get |
| :--- | :--- | :--- |
| **Google Gemini** | Primary text, Imagen 3 image generation, and Vision | [Google AI Studio](https://aistudio.google.com/app/apikey) |
| **Groq** | Ultra-fast text fallback (Llama 3.3 70B) | [Groq Console](https://console.groq.com/keys) |
| **OpenRouter** | Secondary fallback (text & Flux image models) | [OpenRouter Keys](https://openrouter.ai/keys) |

Example `.env`:
```ini
GEMINI_API_KEY=AIzaSyD...
GROQ_API_KEY=gsk_...
OPENROUTER_API_KEY=sk-or-v1-...
FB_PAGE_ID=104829105829102
FB_PAGE_ACCESS_TOKEN=EAABw...
```

---

## 6. Google Drive Image Preparation

If you want to use your own curated graphics via Google Drive:

1. Upload your photos (`.jpg`, `.png`, `.webp`) to Google Drive.
2. Right-click each image > **Share** > **General access**.
3. Change access to: **"Anyone with the link"** (Role: **Viewer**).
4. Copy the link and add it to the `drive_images` array in `config.json`.

Supported Google Drive Link Formats:
- `https://drive.google.com/file/d/FILE_ID/view?usp=sharing`
- `https://drive.google.com/open?id=FILE_ID`
- `https://drive.google.com/uc?id=FILE_ID`

> [!TIP]
> The auto-poster tracks image usage in SQLite. It cycles through all images so none are repeated until every configured image has been posted at least once.

---

## 7. Configuration Guide (`config.json`)

Customize your brand voice, posting behavior, and AI preferences:

```json
{
  "brand": {
    "name": "TechPulse BD",
    "niche": "Tech Tips, AI Productivity, and Software Development",
    "target_audience": "Tech enthusiasts, developers, and freelancers",
    "language": "mixed",
    "tone": "engaging, informative, professional yet friendly",
    "emoji": true,
    "hashtags": {
      "enabled": true,
      "count": 5
    },
    "max_caption_length": 600,
    "custom_system_prompt": "Write with strong hooks, practical value, and clear bullet points."
  },
  "topics": [
    "5 Secret AI Tools That Save 10 Hours Every Week",
    "Why Every Developer Should Learn Git Branching Strategies",
    "The Future of Remote Tech Jobs for Freelancers"
  ],
  "history_check_limit": 30,
  "image_mode": "ai",
  "fallback_to_drive_on_ai_fail": true,
  "fallback_to_text_only": true,
  "drive_images": [
    "https://drive.google.com/file/d/YOUR_FILE_ID/view?usp=sharing"
  ],
  "ai": {
    "text_providers": ["gemini", "groq", "openrouter"],
    "models": {
      "gemini": "gemini-1.5-flash",
      "groq": "llama-3.3-70b-versatile",
      "openrouter": "meta-llama/llama-3.3-70b-instruct"
    },
    "image_provider": "gemini",
    "image_models": {
      "gemini": "imagen-3.0-generate-002",
      "openrouter": "black-forest-labs/flux-schnell"
    },
    "vision_enabled_for_drive": true,
    "vision_model": "gemini-1.5-flash"
  },
  "facebook": {
    "api_version": "v21.0"
  },
  "scheduler": {
    "timezone": "Asia/Dhaka",
    "morning_slot_cutoff_hour": 14
  }
}
```

---

## 8. CLI Usage & Diagnostic Commands

Run diagnostic checks before going live:

### 1. Test AI Providers
Verifies network connectivity and API keys for Gemini, Groq, and OpenRouter:
```bash
python run_post.py --test-ai
```

### 2. Test Facebook Page Connection
Verifies your Page ID, Access Token validity, and Page permissions without publishing:
```bash
python run_post.py --test-facebook
```

### 3. Test Google Drive Links
Validates that every link in `drive_images` is public and downloads as a valid image:
```bash
python run_post.py --test-drive
```

### 4. Dry-Run (Generate without Posting)
Picks an unused topic, generates caption and image, saves preview to `output/`, and does **NOT** post to Facebook:
```bash
python run_post.py --dry-run
```

### 5. Normal Run (Automated Schedule)
Checks if the slot was already posted today. If not, publishes to Facebook and logs to `data/autoposter.db`:
```bash
python run_post.py
```

### 6. Force Run
Bypasses the twice-daily slot check (useful for manual immediate posting):
```bash
python run_post.py --force
```

---

## 9. Hostinger Cloud Deployment (Step-by-Step)

Hostinger Cloud Startup uses Linux with SSH access and standard **hPanel Cron Jobs**.

### Step 1: Enable SSH in hPanel
1. Log in to [Hostinger hPanel](https://hpanel.hostinger.com/).
2. Navigate to **Advanced** > **SSH Access**.
3. Toggle SSH to **Enabled** and note the **SSH IP**, **Port**, and **Username**.

### Step 2: Connect via SSH
From your local terminal:
```bash
ssh -p 65002 u123456789@your-server-ip
```

### Step 3: Upload the Project Files
You can clone via Git or upload via SCP / SFTP to a directory, e.g., `~/autoposter`:
```bash
mkdir -p ~/autoposter
```
Upload `run_post.py`, `config.json`, `requirements.txt`, `src/`, etc.

### Step 4: Create Virtual Environment and Install Requirements
On Hostinger SSH:
```bash
cd ~/autoposter
python3 -m venv venv
./venv/bin/pip install --upgrade pip
./venv/bin/pip install -r requirements.txt
```

### Step 5: Create `.env` on Hostinger
```bash
nano .env
```
Paste your real keys (`GEMINI_API_KEY`, `FB_PAGE_ID`, `FB_PAGE_ACCESS_TOKEN`, etc.), save and exit (`Ctrl + O`, `Enter`, `Ctrl + X`).

### Step 6: Test on the Server
```bash
./venv/bin/python run_post.py --test-ai
./venv/bin/python run_post.py --test-facebook
./venv/bin/python run_post.py --dry-run
```

### Step 7: Configure hPanel Cron Job
Hostinger cron operates in **UTC**.

To post twice daily at:
- **10:00 AM Asia/Dhaka** = `04:00 UTC`
- **08:00 PM Asia/Dhaka** = `14:00 UTC`

1. In hPanel, go to **Advanced** > **Cron Jobs**.
2. Select **Custom** cron.
3. Set the schedule expression:
   ```cron
   0 4,14 * * *
   ```
4. Set the command to run (replace `/home/u123456789` with your actual home directory):
   ```bash
   /home/u123456789/autoposter/venv/bin/python /home/u123456789/autoposter/run_post.py >> /home/u123456789/autoposter/logs/cron.log 2>&1
   ```
5. Click **Save**.

---

## 10. Troubleshooting Guide

### "Google Drive file is NOT public"
- **Cause**: The file permission is restricted to specific accounts.
- **Fix**: Open the image in Google Drive > Share > change to **"Anyone with the link"** as **Viewer**.

### "Facebook Error (400 / 190): Session has expired or token is invalid"
- **Cause**: Temporary user token was used instead of a Page Access Token, or the token expired.
- **Fix**: Re-generate the token following [Section 4](#facebook-app--long-lived-token-setup-step-by-step), making sure to generate a Page token and extend it to never expire using the Access Token Debugger.

### "Notice: A post has already been successfully published for slot 'morning'..."
- **Cause**: The safety mechanism detected that the current time slot already has a successful post in `data/autoposter.db`.
- **Fix**: This is expected behavior. If you want to force an extra post immediately, pass `--force`.

### "Python was not found" or "No module named requests" in Cron
- **Cause**: Cron runs in a minimal shell that doesn't have your user `PATH`.
- **Fix**: Always specify the **absolute path** to the virtualenv python binary:
  `/home/USER/autoposter/venv/bin/python /home/USER/autoposter/run_post.py`.

---

## 11. Verification Checklist for Real Keys

When you are ready with your real Facebook Page and AI credentials:

- [ ] `.env` created with `GEMINI_API_KEY`, `FB_PAGE_ID`, and `FB_PAGE_ACCESS_TOKEN`.
- [ ] Run `python run_post.py --test-ai` -> Verify all providers output `[PASS]`.
- [ ] Run `python run_post.py --test-facebook` -> Verify output prints `[PASS] Successfully authenticated with Page: '...'`.
- [ ] Run `python run_post.py --test-drive` -> If using Drive images, verify `[PASS]` for your links.
- [ ] Run `python run_post.py --dry-run` -> Inspect generated caption and image in `output/`.
- [ ] Run `python run_post.py --force` -> Check your Facebook Page to verify live post appears with photo and caption.
- [ ] Set up the Hostinger hPanel Cron Job (`0 4,14 * * *`).
