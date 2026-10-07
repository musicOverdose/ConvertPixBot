# Telegram Bot Production Template & Boilerplate

A production-ready Telegram Bot boilerplate built with **Python 3.13**, **aiogram 3.x**, **aiosqlite**, and **Docker**.

Includes all pre-configured common infrastructure so you can build new bots (e.g., Image Converter, Downloader, Converter, Utility bots) in minutes without re-solving deployment, permissions, and Telegram API limits.

---

## 🌟 Built-in Features (Common Core)

1. **Centralized Local Telegram Bot API Support**:
   - Out-of-the-box integration with `http://telegram-bot-api:8081`.
   - Dual-mode `FileAcquisitionService`: fast local filesystem copying with automatic HTTP streaming fallback.
   - Pre-configured non-root Docker user (`botuser`) joined with `tgapi` group (GID 101) to eliminate `PermissionError` [Errno 13].

2. **Immediate Must-Join Channel Gate**:
   - Enforced immediately on `/start` and all user interactions.
   - Dynamic buttons with real Channel Titles: `[ 📢 Channel Title ]`.
   - `[ 🔄 I've joined ]` verification callback that confirms membership and smoothly transitions to the personalized Welcome Message.
   - Automatic bypass for Admins and Whitelisted users.

3. **Complete Admin Panel (`/admin`)**:
   - 📊 **Statistics Dashboard**: Real-time users, active queue jobs, memory/disk usage, and uptime.
   - 📢 **Must-Join Channels**: 3-column rows (`📢 Title`, `🟢 On / 🔴 Off`, `🗑 Delete`). Auto-resolves channel titles via `bot.get_chat`, verifies bot admin permissions, and includes `[ 🔄 Sync Info ]`.
   - ⭐ **Whitelist Management**: Add VIPs with optional titles/roles, display modal info cards, and sync names.
   - 🚫 **Ban Management**: Ban users with reasons, instant middleware rejection, and sync info.
   - 📣 **Broadcast System**: Full broadcast wizard with live progress tracking and rate limit backoff.
   - 🛡 **200-Character Alert Safety**: All popup alerts wrapped in `_safe_alert()` to prevent `TelegramBadRequest: MESSAGE_TOO_LONG`.

4. **Async Worker Queue & Isolated Workspaces**:
   - In-memory `asyncio.Queue` with configurable worker concurrency (`WORKER_CONCURRENCY=2`).
   - Isolated temporary workspaces in `/tmp/bot-app/jobs/<uuid>` with guaranteed cleanup in `finally` blocks.

---

## 📁 Project Structure

```text
telegram-bot-template/
├── app/
│   ├── config.py                 # Pydantic Settings & environment variables
│   ├── main.py                   # Bot startup, DB init, queue & polling wireup
│   ├── cli.py                    # Admin CLI utilities
│   ├── database/
│   │   ├── connection.py         # aiosqlite connection manager
│   │   ├── models.py             # Dataclass models (User, Job, Whitelist, Ban, Channel)
│   │   └── repository.py         # Full asynchronous CRUD database methods
│   ├── services/
│   │   ├── file_acquisition.py   # Local copy + HTTP streaming fallback
│   │   ├── job_manager.py        # Workspace lifecycle and isolation
│   │   ├── queue_manager.py      # Background worker queue
│   │   ├── must_join_service.py  # Channel membership checker & cache
│   │   ├── broadcast_service.py  # User broadcast dispatcher
│   │   ├── rate_limiter.py       # User rate limiting with bypass
│   │   └── message_service.py    # Safe message editing & templates
│   ├── engine/
│   │   └── processor.py          # Domain processor (Image converter, etc.)
│   └── bot/
│       ├── formatting.py         # Text formatting & markdown helpers
│       ├── permissions.py        # Admin & whitelist checks
│       ├── middleware/
│       │   └── must_join_middleware.py # Immediate channel gate middleware
│       ├── keyboards/
│       │   ├── main_menu.py      # Start & user action keyboards
│       │   ├── admin_menu.py     # Admin panel keyboards
│       │   └── must_join_menu.py # Channel join keyboards
│       └── handlers/
│           ├── common.py         # /start, /help, /cancel, must_join_verify
│           ├── admin_handlers.py # Complete admin panel handlers
│           └── job_handler.py    # Media upload & worker processing handler
├── tests/                        # Comprehensive pytest test suite (13 tests)
├── Dockerfile                    # Python 3.13 slim + GID 101 tgapi permissions
├── docker-entrypoint.sh          # Non-root privilege dropper
├── compose.yaml                  # Portainer & Docker Compose configuration
├── requirements.txt              # Production dependencies
└── .env.example                  # Environment variable blueprint
```

---

## 🚀 How to Create a New Bot (e.g. Image Converter Bot)

### Step 1: Copy the Template
```bash
cp -r /home/farzad/telegram-bot-template /home/farzad/image-converter-bot
cd /home/farzad/image-converter-bot
```

### Step 2: Configure Environment
```bash
cp .env.example .env
nano .env
```
Set your `BOT_TOKEN`, `BOT_NAME`, `ADMIN_IDS`, and container name.

### Step 3: Implement Your Bot Logic
1. Customize `app/engine/processor.py` for your specific tasks (already includes Pillow image conversion).
2. Customize `app/bot/handlers/job_handler.py` for your custom user interactions and options.

### Step 4: Run Tests
```bash
pytest -v
```

### Step 5: Run or Deploy with Docker
```bash
docker compose up -d --build
```
```
