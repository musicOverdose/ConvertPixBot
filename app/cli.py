"""Command-line administrative interface for SongTaggerBot."""

import argparse
import asyncio
from pathlib import Path
import sys

from app.config import get_settings
from app.database.connection import Database
from app.database.repository import DatabaseRepository
from app.services.api_mode_manager import ApiModeManager
from app.services.job_manager import JobManager
from app.services.message_service import MessageService


async def cmd_channels_list(repo: DatabaseRepository):
    channels = await repo.list_channels()
    if not channels:
        print("No required channels configured.")
        return
    print("Required Channels:")
    print("-" * 60)
    for c in channels:
        status = "ENABLED" if c.is_enabled else "DISABLED"
        display = c.username or c.channel_id
        print(f"[{status:8s}] {display:25s} (ID: {c.channel_id})")
    print("-" * 60)


async def cmd_channels_add(repo: DatabaseRepository, channel_arg: str):
    channel_id = channel_arg
    username = channel_arg.lstrip("@") if channel_arg.startswith("@") else None
    success = await repo.add_channel(channel_id=channel_id, username=username)
    if success:
        print(f"Successfully added required channel: {channel_arg}")
    else:
        print(f"Failed to add channel: {channel_arg}", file=sys.stderr)
        sys.exit(1)


async def cmd_channels_remove(repo: DatabaseRepository, channel_arg: str):
    success = await repo.remove_channel(channel_arg)
    if success:
        print(f"Successfully removed channel: {channel_arg}")
    else:
        print(f"Channel not found: {channel_arg}", file=sys.stderr)
        sys.exit(1)


async def cmd_channels_enable(repo: DatabaseRepository, channel_arg: str):
    success = await repo.set_channel_enabled(channel_arg, True)
    if success:
        print(f"Enabled channel: {channel_arg}")
    else:
        print(f"Channel not found: {channel_arg}", file=sys.stderr)
        sys.exit(1)


async def cmd_channels_disable(repo: DatabaseRepository, channel_arg: str):
    success = await repo.set_channel_enabled(channel_arg, False)
    if success:
        print(f"Disabled channel: {channel_arg}")
    else:
        print(f"Channel not found: {channel_arg}", file=sys.stderr)
        sys.exit(1)


async def cmd_whitelist_list(repo: DatabaseRepository):
    whitelist = await repo.list_whitelist()
    if not whitelist:
        print("Whitelist is empty.")
        return
    print("Must-Join Whitelist:")
    print("-" * 60)
    for w in whitelist:
        reason = f" - {w.reason}" if w.reason else ""
        print(f"User ID: {w.user_id}{reason}")
    print("-" * 60)


async def cmd_whitelist_add(repo: DatabaseRepository, user_id: int, reason: str = None):
    success = await repo.add_to_whitelist(user_id=user_id, reason=reason)
    if success:
        print(f"Successfully added user {user_id} to whitelist.")
    else:
        print(f"Failed to add user {user_id} to whitelist.", file=sys.stderr)
        sys.exit(1)


async def cmd_whitelist_remove(repo: DatabaseRepository, user_id: int):
    success = await repo.remove_from_whitelist(user_id=user_id)
    if success:
        print(f"Successfully removed user {user_id} from whitelist.")
    else:
        print(f"User {user_id} not found in whitelist.", file=sys.stderr)
        sys.exit(1)


async def cmd_ban_list(repo: DatabaseRepository):
    banned = await repo.list_banned()
    if not banned:
        print("Ban list is empty.")
        return
    print("Banned Users:")
    print("-" * 60)
    for b in banned:
        reason = f" - {b.reason}" if b.reason else ""
        print(f"User ID: {b.user_id}{reason}")
    print("-" * 60)


async def cmd_ban_add(repo: DatabaseRepository, user_id: int, reason: str = None):
    success = await repo.ban_user(user_id=user_id, reason=reason)
    if success:
        print(f"Successfully banned user {user_id}.")
    else:
        print(f"Failed to ban user {user_id}.", file=sys.stderr)
        sys.exit(1)


async def cmd_ban_remove(repo: DatabaseRepository, user_id: int):
    success = await repo.unban_user(user_id=user_id)
    if success:
        print(f"Successfully unbanned user {user_id}.")
    else:
        print(f"User {user_id} not found in ban list.", file=sys.stderr)
        sys.exit(1)


async def cmd_maintenance(repo: DatabaseRepository, action: str):
    if action == "status":
        is_maint = await repo.is_maintenance_mode()
        print(f"Maintenance Mode: {'ENABLED (user uploads paused)' if is_maint else 'DISABLED (normal)'}")
    elif action == "enable":
        await repo.set_maintenance_mode(True)
        print("Maintenance mode ENABLED. Non-admin uploads are now blocked.")
    elif action == "disable":
        await repo.set_maintenance_mode(False)
        print("Maintenance mode DISABLED. Normal bot operations resumed.")


async def cmd_backup(repo: DatabaseRepository, settings):
    print("Creating live database backup...")
    backup_file = await repo.backup_database(settings.backups_dir, settings.backup_retention_days)
    size_kb = round(backup_file.stat().st_size / 1024, 1)
    print(f"Backup created: {backup_file} ({size_kb} KB)")


async def cmd_audit(repo: DatabaseRepository, limit: int = 20):
    logs, total = await repo.get_audit_logs(limit=limit, offset=0)
    print("=" * 65)
    print(f"       SongTaggerBot Audit Logs (Showing {len(logs)} of {total})")
    print("=" * 65)
    for log in logs:
        target_str = f" -> {log.target}" if log.target else ""
        details_str = f" | {log.details}" if log.details else ""
        ts = log.created_at[:19].replace("T", " ")
        print(f"[{ts}] [{log.action:18s}] Admin: {log.admin_id}{target_str}{details_str}")
    print("=" * 65)


async def cmd_stats(repo: DatabaseRepository):
    stats = await repo.get_stats()
    print("=" * 45)
    print("       SongTaggerBot Statistics")
    print("=" * 45)
    print(f"Files Received:        {stats.files_received}")
    print(f"Files Processed:       {stats.files_processed}")
    print(f"Files Failed:          {stats.files_failed}")
    print(f"Cuts Performed:        {stats.cuts_performed}")
    print(f"Covers Updated:        {stats.covers_updated}")
    print(f"Lyrics Updated:        {stats.lyrics_updated}")
    print(f"Unique Active Users:   {stats.unique_users}")
    print(f"Total Processed:       {stats.total_processed_mb} MB")
    print("=" * 45)


def cmd_cleanup(settings):
    job_mgr = JobManager(base_jobs_dir=settings.jobs_dir, ttl_minutes=settings.job_ttl_minutes)
    count = job_mgr.cleanup_expired_jobs()
    orphaned = job_mgr.cleanup_orphaned_job_dirs()
    print(f"Cleanup completed. Removed {count} expired and {orphaned} orphaned job directories.")


async def cmd_api_mode(repo: DatabaseRepository, settings, action: str, url: str = None):
    # Base environment values represent the baseline running server
    env_baseline_mode = settings.telegram_api_mode
    env_baseline_url = settings.effective_api_base_url

    # Apply DB overrides to reflect configured state
    db_mode = await repo.get_system_setting("telegram_api_mode", "")
    if db_mode:
        settings.telegram_api_mode = db_mode
    db_url = await repo.get_system_setting("telegram_api_base_url", "")
    if db_url:
        settings.telegram_api_base_url = db_url

    manager = ApiModeManager(
        bot=None,
        settings=settings,
        repository=repo,
        running_mode=env_baseline_mode,
        running_endpoint=env_baseline_url,
    )

    if action == "status":
        print("=" * 60)
        print("Telegram Bot API Mode & Connectivity:")
        print(f"Running Baseline:     {env_baseline_mode.upper()} ({env_baseline_url})")
        print(f"Configured Mode:      {manager.get_configured_mode().upper()}")
        print(f"Configured Endpoint:  {manager.get_configured_endpoint()}")
        print(f"DB Override Mode:     {db_mode or 'None (using env)'}")
        print(f"Restart Required:     {'YES' if manager.is_restart_required() else 'NO'}")
        print(f"Migration Required:   {'YES' if manager.is_migration_required() else 'NO'}")
        if manager.is_migration_required():
            print("-" * 60)
            print(manager.get_migration_instructions_text())
        print("=" * 60)
        return

    if action == "cloud":
        ok, msg = await manager.configure_mode("cloud", admin_id=0)
        print(f"Result: {msg}")
        return

    if action == "local":
        ok, msg = await manager.configure_mode("local", new_base_url=url, admin_id=0)
        print(f"Result: {msg}")
        return


async def cmd_messages(repo: DatabaseRepository, action: str, key: str = None, text: str = None):
    svc = MessageService(repo)
    if action == "list":
        status = await svc.get_status_overview()
        print("=" * 60)
        print("Customizable Messages Overview:")
        print("-" * 60)
        for k, v in status.items():
            state = "CUSTOM" if v["is_custom"] else "DEFAULT"
            print(f"[{state:7s}] {k:10s} - {v['title']} ({v['length']} chars)")
            print(f"  Preview: {v['preview']}")
        print("=" * 60)
    elif action == "get":
        if not key:
            print("Error: Message key required (welcome, must_join, help)")
            return
        try:
            raw_text, is_custom = await svc.get_raw_message(key)
            print(f"--- Message: {key} ({'CUSTOM' if is_custom else 'DEFAULT'}) ---")
            print(raw_text)
        except Exception as e:
            print(f"Error: {e}")
    elif action == "set":
        if not key or text is None:
            print("Error: Both key and text are required for set")
            return
        ok, msg = await svc.set_message(key, text, admin_id=0)
        print(f"Result: {msg}")
    elif action == "reset":
        if not key:
            print("Error: Message key required for reset")
            return
        ok, msg = await svc.reset_message(key, admin_id=0)
        print(f"Result: {msg}")


async def cmd_settings_list(repo: DatabaseRepository, settings):
    db_mode = await repo.get_system_setting("telegram_api_mode", "")
    db_url = await repo.get_system_setting("telegram_api_base_url", "")
    db_in = await repo.get_system_setting("max_input_mb", "")
    db_out = await repo.get_system_setting("max_output_mb", "")
    db_tech = await repo.get_system_setting("show_technical_info", "")
    db_cover = await repo.get_system_setting("send_cover_separately", "")

    eff_mode = db_mode or settings.telegram_api_mode
    eff_url = db_url or (settings.telegram_api_base_url if eff_mode == "local" else "https://api.telegram.org")
    eff_in = db_in or str(settings.max_input_mb)
    eff_out = db_out or str(settings.max_output_mb)
    eff_tech = db_tech if db_tech != "" else str(settings.show_technical_info)
    eff_cover = db_cover if db_cover != "" else str(settings.send_cover_separately)

    print("=" * 60)
    print("SongTaggerBot Active Settings:")
    print("-" * 60)
    print(f"API Server Mode:       {eff_mode.upper()} ({eff_url})")
    print(f"Max Input File Size:   {eff_in} MB")
    print(f"Max Output File Size:  {eff_out} MB")
    print(f"Rate Limit:            {settings.rate_limit_uploads_per_minute} uploads/min")
    print(f"Concurrency:           {settings.max_user_concurrent_jobs}/user | {settings.max_global_concurrent_jobs} global")
    print(f"Technical Specs:       {'ON' if eff_tech in ('1', 'True', 'true') else 'OFF'}")
    print(f"Send Cover Separately: {'ON' if eff_cover in ('1', 'True', 'true') else 'OFF'}")
    print("=" * 60)


async def async_main():
    settings = get_settings()
    db = Database(settings.db_path)
    repo = DatabaseRepository(db)

    parser = argparse.ArgumentParser(
        prog="cli",
        description="SongTaggerBot Administrative CLI",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    # channels subparser
    channels_parser = subparsers.add_parser("channels", help="Manage required broadcast channels")
    channels_sub = channels_parser.add_subparsers(dest="action", required=True)
    channels_sub.add_parser("list", help="List all configured required channels")
    add_p = channels_sub.add_parser("add", help="Add a required channel")
    add_p.add_argument("channel", help="Channel @username or ID")
    remove_p = channels_sub.add_parser("remove", help="Remove a required channel")
    remove_p.add_argument("channel", help="Channel @username or ID")
    enable_p = channels_sub.add_parser("enable", help="Enable a required channel")
    enable_p.add_argument("channel", help="Channel @username or ID")
    disable_p = channels_sub.add_parser("disable", help="Disable a required channel")
    disable_p.add_argument("channel", help="Channel @username or ID")

    # whitelist subparser
    wl_parser = subparsers.add_parser("whitelist", help="Manage must-join whitelist")
    wl_sub = wl_parser.add_subparsers(dest="action", required=True)
    wl_sub.add_parser("list", help="List whitelisted users")
    wl_add_p = wl_sub.add_parser("add", help="Add user to whitelist")
    wl_add_p.add_argument("user_id", type=int, help="Telegram user ID")
    wl_add_p.add_argument("--reason", default=None, help="Optional reason")
    wl_rem_p = wl_sub.add_parser("remove", help="Remove user from whitelist")
    wl_rem_p.add_argument("user_id", type=int, help="Telegram user ID")

    # ban subparser
    ban_parser = subparsers.add_parser("ban", help="Manage banned users")
    ban_sub = ban_parser.add_subparsers(dest="action", required=True)
    ban_sub.add_parser("list", help="List banned users")
    ban_add_p = ban_sub.add_parser("add", help="Ban a user")
    ban_add_p.add_argument("user_id", type=int, help="Telegram user ID")
    ban_add_p.add_argument("--reason", default=None, help="Optional reason")
    ban_rem_p = ban_sub.add_parser("remove", help="Unban a user")
    ban_rem_p.add_argument("user_id", type=int, help="Telegram user ID")

    # maintenance subparser
    maint_parser = subparsers.add_parser("maintenance", help="Manage maintenance mode")
    maint_sub = maint_parser.add_subparsers(dest="action", required=True)
    maint_sub.add_parser("status", help="Show current maintenance status")
    maint_sub.add_parser("enable", help="Enable maintenance mode")
    maint_sub.add_parser("disable", help="Disable maintenance mode")

    # api-mode subparser
    api_parser = subparsers.add_parser("api-mode", help="Manage Telegram Bot API mode (cloud vs local)")
    api_sub = api_parser.add_subparsers(dest="action", required=True)
    api_sub.add_parser("status", help="Show current API server mode and URL")
    api_sub.add_parser("cloud", help="Switch to Cloud Mode (official Telegram servers)")
    local_p = api_sub.add_parser("local", help="Switch to Local Mode (centralized server)")
    local_p.add_argument("url", nargs="?", default=None, help="Optional Local Bot API URL")

    # settings subparser
    subparsers.add_parser("settings", help="List all current bot settings and DB overrides")

    # backup subparser
    subparsers.add_parser("backup", help="Create live database backup")

    # audit subparser
    audit_parser = subparsers.add_parser("audit", help="View recent admin audit logs")
    audit_parser.add_argument("--limit", type=int, default=20, help="Number of records to show")

    # stats parser
    subparsers.add_parser("stats", help="Show usage statistics")

    # messages subparser
    msg_parser = subparsers.add_parser("messages", help="Manage customizable bot messages")
    msg_sub = msg_parser.add_subparsers(dest="action", required=True)
    msg_sub.add_parser("list", help="List all customizable messages")
    get_p = msg_sub.add_parser("get", help="Get a message template")
    get_p.add_argument("key", choices=["welcome", "must_join", "help"], help="Message key")
    set_p = msg_sub.add_parser("set", help="Set a custom message template")
    set_p.add_argument("key", choices=["welcome", "must_join", "help"], help="Message key")
    set_p.add_argument("text", help="New message text (HTML supported)")
    res_p = msg_sub.add_parser("reset", help="Reset a message template to default")
    res_p.add_argument("key", choices=["welcome", "must_join", "help"], help="Message key")

    # cleanup parser
    subparsers.add_parser("cleanup", help="Trigger cleanup of expired jobs")

    args = parser.parse_args()

    try:
        if args.command == "channels":
            if args.action == "list":
                await cmd_channels_list(repo)
            elif args.action == "add":
                await cmd_channels_add(repo, args.channel)
            elif args.action == "remove":
                await cmd_channels_remove(repo, args.channel)
            elif args.action == "enable":
                await cmd_channels_enable(repo, args.channel)
            elif args.action == "disable":
                await cmd_channels_disable(repo, args.channel)
        elif args.command == "whitelist":
            if args.action == "list":
                await cmd_whitelist_list(repo)
            elif args.action == "add":
                await cmd_whitelist_add(repo, args.user_id, args.reason)
            elif args.action == "remove":
                await cmd_whitelist_remove(repo, args.user_id)
        elif args.command == "ban":
            if args.action == "list":
                await cmd_ban_list(repo)
            elif args.action == "add":
                await cmd_ban_add(repo, args.user_id, args.reason)
            elif args.action == "remove":
                await cmd_ban_remove(repo, args.user_id)
        elif args.command == "maintenance":
            await cmd_maintenance(repo, args.action)
        elif args.command == "api-mode":
            await cmd_api_mode(repo, settings, args.action, getattr(args, "url", None))
        elif args.command == "messages":
            await cmd_messages(
                repo,
                args.action,
                key=getattr(args, "key", None),
                text=getattr(args, "text", None),
            )
        elif args.command == "settings":
            await cmd_settings_list(repo, settings)
        elif args.command == "backup":
            await cmd_backup(repo, settings)
        elif args.command == "audit":
            await cmd_audit(repo, args.limit)
        elif args.command == "stats":
            await cmd_stats(repo)
        elif args.command == "cleanup":
            cmd_cleanup(settings)
    finally:
        await db.close()


def main():
    asyncio.run(async_main())


if __name__ == "__main__":
    main()
