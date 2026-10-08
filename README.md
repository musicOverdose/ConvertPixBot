# Convert Pix Bot

A fast, lightweight, and reliable Telegram bot that converts images and **static Telegram stickers** into standard image formats and single-page PDFs.

Built with Python 3.13, aiogram 3, Pillow, and `pillow-heif`, integrated with local worker queues, persistent storage, and non-root Docker security.

---

## Features

- **Supported Inputs**:
  - `PNG`, `JPG`, `JPEG`, `WEBP`, `BMP`, `ICO`, `HEIC`, `HEIF`, `AVIF`, `PSD`
  - **Static Telegram Stickers** (WebP static stickers sent directly from Telegram)
  - Automatic rejection of animated (`.TGS`) and video (`.WEBM`) stickers
- **Supported Outputs**:
  - `PNG` (Lossless, transparency preserved)
  - `JPG` (Quality 92, flattened on clean white background)
  - `WEBP` (Quality 90, transparency preserved, original dimensions maintained)
  - `PDF` (1 page, exact aspect ratio preserved, no distortion)
  - `ICO` (Multi-resolution: 16×16, 32×32, 48×48, 64×64, 128×128, 256×256)
  - `BMP` (Standard RGB bitmap)
- **Authoritative Delivery**:
  - Visual photo preview sent via `sendPhoto` for immediate visual convenience.
  - Exact, uncompressed converted file sent via `sendDocument` with size delta statistics.
- **Production Architecture**:
  - Centralized Local Telegram Bot API support (`http://telegram-bot-api:8081`).
  - Dual-mode file acquisition: fast local filesystem copy with automatic HTTP streaming fallback.
  - Background worker queue (`asyncio.Queue`) with isolated per-job workspaces (`/tmp/bot-app/jobs/<uuid>`).
  - Automatic cleanup of temporary files on completion, failure, or cancellation.
  - Decompression bomb and pixel count safety limits.
  - Immediate Must-Join channel verification gate and `/admin` management dashboard.

---

## Deploying with Portainer (VPS)

1. Open **Portainer** on your server.
2. Go to **Stacks** → **Add stack**.
3. Select **Repository**:
   - **Repository URL**: `https://github.com/musicOverdose/ConvertPixBot`
   - **Repository reference**: `refs/heads/main`
   - **Compose path**: `compose.yaml` (or `docker-compose.yml`)
4. Add **Environment Variables**:
   | Variable | Example / Description |
   |---|---|
   | `BOT_TOKEN` | `123456789:ABCdefGhIJKlmNoPQRsTUVwxyZ` *(Required)* |
   | `ADMIN_IDS` | `12345678,87654321` *(Your Telegram user ID)* |
   | `BOT_NAME` | `ConvertPixBot` |
   | `TELEGRAM_API_MODE` | `local` (or `cloud`) |
   | `TELEGRAM_API_BASE_URL` | `http://telegram-bot-api:8081` (or `https://api.telegram.org`) |
   | `MAX_INPUT_MB` | `50` |
   | `MAX_OUTPUT_MB` | `50` |
5. Click **Deploy the stack**.

---

## Deploying via Docker Compose (CLI)

```bash
git clone https://github.com/musicOverdose/ConvertPixBot.git
cd ConvertPixBot

# Configure environment
cp .env.example .env
nano .env

# Start stack
docker compose up -d --build
```

---

## Running Tests

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pytest -v
```
