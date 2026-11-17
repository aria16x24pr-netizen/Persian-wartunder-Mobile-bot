"""War Thunder Mobile Telegram assistant bot (Paimonak-style).

- Reply-keyboard buttons (no typing needed) in Persian/English.
- /news [tank|air|ship]: latest official article, fully translated to Persian, with photos.
- Background watcher: new season updates / events are pushed (Persian + photos)
  to the admin, all subscribed chats and everyone who ever started the bot.
- Bot auto-subscribes chats it is added to (my_chat_member).
"""
import asyncio
import io
import json
import logging
import os
import time
from datetime import time as dtime
from zoneinfo import ZoneInfo

# Sanitize no_proxy: some runtimes ship IPv6 entries (e.g. [::1]) that httpx
# cannot parse, breaking proxy use entirely. Keep it minimal.
os.environ["no_proxy"] = os.environ["NO_PROXY"] = "localhost,127.0.0.1"

from telegram import (
    ChatMemberUpdated,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    ReplyKeyboardMarkup,
    Update,
)
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    ChatMemberHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)
from telegram.request import HTTPXRequest

from . import config
from . import vehicles as veh
from .services.news import (
    TAG_MAP,
    FeedItem,
    FullArticle,
    _download_bytes,
    classify_channel,
    fetch_article,
    fetch_channel_posts,
    fetch_feed,
    fetch_news,
)
from .services.ai_chat import ask_brain
from .services.profiles import get_profile, profile_exists, save_profile
from .services.translate import translate_to_fa

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
# Never log request URLs (they embed the bot token).
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("apscheduler").setLevel(logging.WARNING)
log = logging.getLogger(__name__)

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")
SUBS_FILE = os.path.join(DATA_DIR, "subscriptions.json")
USERS_FILE = os.path.join(DATA_DIR, "users.json")
ADMINS_FILE = os.path.join(DATA_DIR, "admins.json")
SEEN_FILE = os.path.join(DATA_DIR, "seen_news.json")
AI_OFF_FILE = os.path.join(DATA_DIR, "ai_chat_off.json")


def _load_set(path: str) -> set[int]:
    try:
        with open(path, encoding="utf-8") as f:
            return set(json.load(f))
    except (FileNotFoundError, json.JSONDecodeError):
        return set()


def _save_set(path: str, values: set[int]) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(sorted(values), f)


# ---------- strings & keyboards ----------

STRINGS = {
    "fa": {
        "start": (
            "سلام فرمانده! 🎖️\n"
            "من دستیار وارتاندر موبایل هستم. از دکمه‌های زیر استفاده کن 👇\n\n"
            "🤖 ساخته شده توسط Ariya team\n"
            "👤 @USA_Ariya"
        ),
        "help": (
            "❓ راهنما\n\n"
            "از دکمه‌ها استفاده کن:\n"
            "📰 آخرین اخبار — جدیدترین خبر رسمی (فارسی + عکس)\n"
            "🎖/✈️/🚢 — آخرین خبر تانک / هوایی / دریایی\n"
            "🔔 خبرهای من — انتخاب کن چه خبرهایی خودکار برات بیاد\n"
            "👥 پیدا کردن دوست — با آیدی تلگرام، یوزرنیم وارتاندر دوستت رو ببین\n"
            "⚙️ ویرایش پروفایل — یوزرنیم و اسمت رو ثبت یا ویرایش کن\n"
            "🔔 عضویت در خبرها — خبرهای جدید خودکار برات میاد\n"
            "🌐 — تغییر زبان"
        ),
        "lang_switched": "Language changed to English. 🌐",
        "github_text": (
            "🐙 پروژه ربات روی گیت‌هاب\n\n"
            "کد کامل ربات اونجا منتشر شده — می‌تونی ببینیش، ستاره بدی ⭐ و تو توسعه‌ش کمک کنی 👇"
        ),
        "github_btn": "🐙 مشاهده پروژه در گیت‌هاب",
        "subscribed": "✅ عضو شدی! خبرهای جدید سیزن و ایونت رو همینجا برات می‌فرستم.",
        "already_subscribed": "✅ قبلاً عضو بودی!",
        "unsubscribed": "❌ عضویت لغو شد.",
        "news_empty": "خبری پیدا نشد. بعداً دوباره امتحان کن.",
        "arch_title": "📚 آرشیو اخبار\nسیزن رو انتخاب کن:",
        "arch_season": "📰 اخبار سیزن {ver}",
        "arch_back_seasons": "🔙 سیزن‌ها",
        "arch_empty": "خبری برای این سیزن پیدا نشد.",
        "send_failed": "⚠️ موقع ارسال خبر مشکلی پیش اومد — لطفاً یه بار دیگه تلاش کن 🙏",
        "translating": "⏳ دارم خبر رو می‌گیرم و فارسی می‌کنم…\nحدود ۲۰ ثانیه صبر کن 🙏",
        "no_translation": "⚠️ برخی بخش‌ها ترجمه نشدند:",
        "new_badge": "🆕 خبر جدید وارتاندر موبایل",
        "vehicle_todo": "دیتابیس وسیله‌ها در حال ساخته شدنه. به‌زودی! 🛠️",
        "group_hello": "سلام! 🎖️ من رو به گروه اضافه کردی. با /subscribe خبرهای جدید رو همینجا بگیر.",
        # onboarding & profile
        "ob_ask": (
            "🎮 یه قدم مونده!\n"
            "برای اینکه دوستات بتونن تو رو توی ربات پیدا کنن، اطلاعات اکانت وارتاندر موبایلت رو وارد کن:"
        ),
        "ob_username_btn": "📝 وارد کردن یوزرنیم",
        "ob_name_btn": "👤 وارد کردن اسم",
        "ob_skip_btn": "⏭️ اکانت ندارم",
        "ob_ask_username": "یوزرنیم وارتاندر موبایلت رو بفرست 👇",
        "ob_ask_name": "اسمت رو بفرست 👇",
        "ob_saved_username": "✅ یوزرنیمت ثبت شد: {v}",
        "ob_saved_name": "✅ اسمت ثبت شد: {v}",
        "ob_skip_done": "باشه 👍 بعداً از بخش «⚙️ ویرایش پروفایل» می‌تونی اضافه‌شون کنی.",
        "profile_title": "⚙️ پروفایل من\n\n🆔 آیدی تلگرام: {uid}\n📝 یوزرنیم وارتاندر: {username}\n👤 اسم: {name}",
        "profile_has": "✅ {v}",
        "profile_empty": "❌ ثبت نشده",
        "profile_edit_username": "📝 یوزرنیم: {s}",
        "profile_edit_name": "👤 اسم: {s}",
        "profile_ask_username": "یوزرنیم جدید وارتاندرت رو بفرست 👇",
        "profile_ask_name": "اسم جدیدت رو بفرست 👇",
        "profile_deleted": "🗑️ حذف شد.",
        "profile_delete_btn": "🗑️ حذف",
        "friend_ask": (
            "👥 آیدی عددی تلگرام دوستت رو بفرست 👇\n"
            "(دوستت می‌تونه آیدیش رو از بخش «⚙️ ویرایش پروفایل» ببینه)"
        ),
        "friend_found": "👥 دوست پیدا شد!\n\n🆔 آیدی تلگرام: {uid}\n{lines}",
        "friend_found_username": "📝 یوزرنیم وارتاندر: {v}\n",
        "friend_found_name": "👤 اسم: {v}\n",
        "friend_empty_profile": "این کاربر توی ربات هست ولی هنوز یوزرنیم یا اسمی ثبت نکرده.",
        "friend_not_found": "❌ این آیدی توی ربات پیدا نشد.\nمطمئن شو دوستت اول /start رو زده باشه.",
        "friend_bad_id": "❌ آیدی باید فقط عدد باشه. دوباره بفرست 👇",
        "mynews_title": "🔔 خبرهای من\n\nانتخاب کن چه خبرهایی برات خودکار ارسال بشه 👇",
        "mynews_tank": "🎖 تانک: {s}",
        "mynews_air": "✈️ هوایی: {s}",
        "mynews_ship": "🚢 دریایی: {s}",
        "on": "✅",
        "off": "❌",
        # admin panel
        "admin_title": "🛠️ پنل ادمین\nیکی رو انتخاب کن:",
        "admin_denied": "⛔ این بخش فقط برای ادمینه.",
        "admin_stats": "📊 آمار ربات\n\n👥 کاربران (استارت‌زنندگان): {users}\n🔔 چت‌های مشترک خبرها: {subs}\n📰 خبرهای دیده‌شده: {seen}",
        "admin_bcast_ask": "📢 متن یا عکس پیام همگانی رو بفرست (لغو: /admin):",
        "admin_bcast_done": "✅ پیام به {n} چت ارسال شد.",
        "admin_bcast_cancelled": "❌ لغو شد.",
        "admin_checking": "🔄 دارم اخبار رو بررسی می‌کنم…",
        "admin_check_done": "✅ بررسی تموم شد. {n} خبر جدید پیدا و ارسال شد.",
        "admin_closed": "پنل بسته شد.",
        # owner panel (فقط مالک)
        "owner_title": "👑 پنل مالک\nفقط تو می‌بینی‌ش. یکی رو انتخاب کن:",
        "owner_add_ask": "➕ آیدی عددی تلگرام ادمین جدید رو بفرست 👇",
        "owner_add_bad": "❌ آیدی باید فقط عدد باشه. دوباره بفرست 👇",
        "owner_add_self": "😄 این که خودتی! مالک نیازی به اضافه شدن نداره.",
        "owner_add_done": "✅ ادمین اضافه شد: {uid}",
        "owner_no_admins": "هنوز ادمینی اضافه نشده.",
        "owner_del_ask": "کدوم ادمین حذف بشه؟ 👇",
        "owner_del_done": "🗑️ ادمین حذف شد: {uid}",
        "owner_users_title": "👥 کاربران ثبت‌نام‌شده: {n} نفر\n",
        "owner_bcast_ask": "📢 پیامت رو بفرست تا برای همه پیوی‌ها و گروه‌ها ارسال بشه 👇\n(متن یا عکس)",
        # database admin (owner & admins)
        "db_title": "🚗 مدیریت دیتابیس\nیکی رو انتخاب کن:",
        "db_stats": (
            "📊 آمار دیتابیس\n\n"
            "🚗 کل وسیله‌ها: {total}\n"
            "🎖 تانک: {tanks} · ✈️ هوایی: {aircraft} · 🚢 دریایی: {naval}\n"
            "🖼 عکس‌دار: {photos}\n"
            "📊 دارای آمار بازی: {stats}"
        ),
        "db_stats_btn": "📊 آمار",
        "db_reload_btn": "🔄 بارگذاری مجدد از فایل",
        "db_fill_btn": "🖼 تکمیل عکس و آمار",
        "db_reloaded": "✅ دیتابیس از فایل بارگذاری شد: {n} وسیله",
        "db_fill_started": (
            "🖼 تکمیل خودکار شروع شد؛ در پس‌زمینه عکس و آمار بازی وسیله‌ها گرفته می‌شه.\n"
            "با «📊 آمار» می‌تونی پیشرفت رو ببینی."
        ),
        "db_fill_done": "✅ تکمیل دیتابیس تموم شد: {n} وسیله به‌روز شد.",
    },
    "en": {
        "start": (
            "Hello Commander! 🎖️\n"
            "I'm your War Thunder Mobile assistant. Use the buttons below 👇\n\n"
            "🤖 Built by Ariya team\n"
            "👤 @USA_Ariya"
        ),
        "help": (
            "❓ Help\n\n"
            "Use the buttons:\n"
            "📰 Latest news — newest official article\n"
            "🎖/✈️/🚢 — latest tank / air / naval news\n"
            "🔔 Subscribe — get new season & event news automatically\n"
            "🌐 — switch language"
        ),
        "lang_switched": "زبان به فارسی تغییر کرد. 🌐",
        "github_text": (
            "🐙 The bot's project on GitHub\n\n"
            "The full source code is published there — check it out, give it a star ⭐ and help it grow 👇"
        ),
        "github_btn": "🐙 View the project on GitHub",
        "subscribed": "✅ Subscribed! I'll send new season & event news right here.",
        "already_subscribed": "✅ Already subscribed!",
        "unsubscribed": "❌ Unsubscribed.",
        "news_empty": "No news found. Try again later.",
        "arch_title": "📚 News archive\nPick a season:",
        "arch_season": "📰 Season {ver} news",
        "arch_back_seasons": "🔙 Seasons",
        "arch_empty": "No news found for this season.",
        "send_failed": "⚠️ Something went wrong while sending the news — please try again 🙏",
        "translating": "⏳ Fetching and translating…\nAbout 20 seconds 🙏",
        "no_translation": "⚠️ Translation unavailable, English text:",
        "new_badge": "🆕 New War Thunder Mobile article",
        "vehicle_todo": "Vehicle database is under construction. Soon! 🛠️",
        "group_hello": "Hello! 🎖️ Thanks for adding me. Use /subscribe to get news alerts here.",
        # onboarding & profile
        "ob_ask": "🎮 One more step!\nSo your friends can find you in the bot, enter your War Thunder Mobile account info:",
        "ob_username_btn": "📝 Enter username",
        "ob_name_btn": "👤 Enter name",
        "ob_skip_btn": "⏭️ I don't have an account",
        "ob_ask_username": "Send your War Thunder Mobile username 👇",
        "ob_ask_name": "Send your name 👇",
        "ob_saved_username": "✅ Username saved: {v}",
        "ob_saved_name": "✅ Name saved: {v}",
        "ob_skip_done": "OK 👍 You can add them later from «⚙️ Edit profile».",
        "profile_title": "⚙️ My profile\n\n🆔 Telegram ID: {uid}\n📝 WTM username: {username}\n👤 Name: {name}",
        "profile_has": "✅ {v}",
        "profile_empty": "❌ not set",
        "profile_edit_username": "📝 Username: {s}",
        "profile_edit_name": "👤 Name: {s}",
        "profile_ask_username": "Send your new WTM username 👇",
        "profile_ask_name": "Send your new name 👇",
        "profile_deleted": "🗑️ Deleted.",
        "profile_delete_btn": "🗑️ Delete",
        "friend_ask": "👥 Send your friend's numeric Telegram ID 👇\n(They can see their ID in «⚙️ Edit profile»)",
        "friend_found": "👥 Friend found!\n\n🆔 Telegram ID: {uid}\n{lines}",
        "friend_found_username": "📝 WTM username: {v}\n",
        "friend_found_name": "👤 Name: {v}\n",
        "friend_empty_profile": "This user is in the bot but hasn't set a username or name yet.",
        "friend_not_found": "❌ This ID wasn't found in the bot.\nMake sure your friend pressed /start first.",
        "friend_bad_id": "❌ ID must be numeric only. Send again 👇",
        "mynews_title": "🔔 My news\n\nChoose which news to receive automatically 👇",
        "mynews_tank": "🎖 Tanks: {s}",
        "mynews_air": "✈️ Aircraft: {s}",
        "mynews_ship": "🚢 Ships: {s}",
        "on": "✅",
        "off": "❌",
    },
}

BUTTONS = {
    "fa": {
        "news": "📰 آخرین اخبار",
        "archive": "📚 آرشیو اخبار",
        "help": "❓ راهنما",
        "github": "🐙 گیت‌هاب",
        "tank": "🎖 تانک",
        "air": "✈️ هوایی",
        "ship": "🚢 دریایی",
        "mynews": "🔔 خبرهای من",
        "vehicle": "🚗 دیتابیس وسیله‌ها",
        "friend": "👥 پیدا کردن دوست",
        "profile": "⚙️ ویرایش پروفایل",
        "sub": "🔔 عضویت در خبرها",
        "unsub": "🔕 لغو عضویت",
        "lang": "🌐 English",
    },
    "en": {
        "news": "📰 Latest news",
        "archive": "📚 News archive",
        "help": "❓ Help",
        "github": "🐙 GitHub",
        "tank": "🎖 Tanks",
        "air": "✈️ Aircraft",
        "ship": "🚢 Ships",
        "mynews": "🔔 My news",
        "vehicle": "🚗 Vehicle database",
        "friend": "👥 Find friend",
        "profile": "⚙️ Edit profile",
        "sub": "🔔 Subscribe to news",
        "unsub": "🔕 Unsubscribe",
        "lang": "🌐 فارسی",
    },
}

MODE_OF_BUTTON = {"tank": "tanks", "air": "aircraft", "ship": "ships"}

GITHUB_URL = "https://github.com/aria16x24pr-netizen/Persian-wartunder-Mobile-bot"


# ---------- admin & owner panels ----------

ADMIN_BUTTONS = {
    "stats": "📊 آمار ربات",
    "users": "👥 لیست کاربران",
    "broadcast": "📢 پیام همگانی",
    "check": "🔄 بررسی فوری اخبار",
    "db": "🚗 مدیریت دیتابیس",
    "close": "❌ بستن پنل",
}

OWNER_BUTTONS = {
    "add_admin": "➕ اضافه کردن ادمین",
    "del_admin": "➖ حذف ادمین",
    "users": "👥 لیست کاربران",
    "broadcast": "📢 پیام همگانی",
    "check": "🔄 بررسی فوری اخبار",
    "db": "🚗 مدیریت دیتابیس",
    "close": "❌ بستن پنل",
}

OWNER_PANEL_BTN = "👑 پنل مالک"


def admin_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        [
            [ADMIN_BUTTONS["stats"], ADMIN_BUTTONS["users"]],
            [ADMIN_BUTTONS["broadcast"], ADMIN_BUTTONS["check"]],
            [ADMIN_BUTTONS["db"]],
            [ADMIN_BUTTONS["close"]],
        ],
        resize_keyboard=True,
    )


def owner_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        [
            [OWNER_BUTTONS["add_admin"], OWNER_BUTTONS["del_admin"]],
            [OWNER_BUTTONS["users"], OWNER_BUTTONS["broadcast"]],
            [OWNER_BUTTONS["check"], OWNER_BUTTONS["db"]],
            [OWNER_BUTTONS["close"]],
        ],
        resize_keyboard=True,
    )


def _is_owner(update: Update) -> bool:
    user = update.effective_user
    return bool(user) and user.id == config.ADMIN_CHAT_ID and config.ADMIN_CHAT_ID != 0


def _is_admin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    if _is_owner(update):
        return True
    user = update.effective_user
    admins: set[int] = context.bot_data.get("admins", set())
    return bool(user) and user.id in admins


def _all_targets(context: ContextTypes.DEFAULT_TYPE) -> set[int]:
    targets = set(context.bot_data.get("subscriptions", set()))
    targets |= context.bot_data.get("users", set())
    if config.ADMIN_CHAT_ID:
        targets.add(config.ADMIN_CHAT_ID)
    return targets


async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Entry point: owner gets the owner panel, added admins get the admin panel."""
    if _is_owner(update):
        context.user_data.pop("await_broadcast", None)
        context.user_data.pop("await_add_admin", None)
        await update.message.reply_text(
            STRINGS["fa"]["owner_title"], reply_markup=owner_keyboard()
        )
        return
    if not _is_admin(update, context):
        await update.message.reply_text(STRINGS[_lang(context)]["admin_denied"])
        return
    context.user_data.pop("await_broadcast", None)
    await update.message.reply_text(
        STRINGS["fa"]["admin_title"], reply_markup=admin_keyboard()
    )


async def _send_user_list(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """List registered users with IDs and WTM usernames/names (owner & admins)."""
    s = STRINGS["fa"]
    users: set[int] = context.bot_data.get("users", set())
    subs: set[int] = context.bot_data.get("subscriptions", set())
    parts = [s["owner_users_title"].format(n=len(users))]
    for uid in sorted(users):
        p = get_profile(uid)
        un = p.wtm_username or "—"
        nm = p.display_name or "—"
        parts.append(f"🆔 <code>{uid}</code>\n📝 {un} | 👤 {nm}\n")
    text = "\n".join(parts)
    for chunk in _split_text(text, 3500):
        try:
            await update.message.reply_text(chunk, parse_mode="HTML")
        except Exception:
            await update.message.reply_text(chunk)
    groups = len([c for c in subs if c not in users])
    await update.message.reply_text(f"🔔 گروه/کانال‌های مشترک: {groups}")


# ---------- database admin (owner & admins) ----------

def _db_admin_menu() -> InlineKeyboardMarkup:
    s = STRINGS["fa"]
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton(s["db_stats_btn"], callback_data="db:stats")],
            [InlineKeyboardButton(s["db_reload_btn"], callback_data="db:reload")],
            [InlineKeyboardButton(s["db_fill_btn"], callback_data="db:fill")],
        ]
    )


def _db_stats_text() -> str:
    s = STRINGS["fa"]
    st = veh.db_stats()
    return s["db_stats"].format(**st)


async def _db_fill_job(
    chat_id: int, context: ContextTypes.DEFAULT_TYPE, limit: int = 40
) -> None:
    """Background enrichment: fetch photo + game stats for vehicles missing them."""
    s = STRINGS["fa"]
    candidates = [v for v in veh.get_vehicles() if not v.get("enriched")][:limit]
    done = 0
    for v in candidates:
        try:
            await veh.enrich_vehicle(v)
            done += 1
        except Exception:
            log.exception("db fill failed for %s", v.get("id"))
        await asyncio.sleep(2)  # be gentle with the wiki
    try:
        await context.bot.send_message(
            chat_id=chat_id, text=s["db_fill_done"].format(n=done)
        )
    except Exception:
        pass


async def _check_news_now(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    s = STRINGS["fa"]
    wait = await update.message.reply_text(s["admin_checking"])
    before = len(context.bot_data.get("seen_news", set()))
    await news_watcher(context)
    after = len(context.bot_data.get("seen_news", set()))
    try:
        await wait.delete()
    except Exception:
        pass
    await update.message.reply_text(s["admin_check_done"].format(n=after - before))


async def on_owner_button(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """Handle the owner panel button + the panel entry button. True if handled."""
    text = (update.message.text or "").strip()
    s = STRINGS["fa"]
    if text == OWNER_PANEL_BTN:
        if not _is_owner(update):
            return False
        context.user_data.pop("await_broadcast", None)
        context.user_data.pop("await_add_admin", None)
        await update.message.reply_text(s["owner_title"], reply_markup=owner_keyboard())
        return True
    if text not in OWNER_BUTTONS.values():
        return False
    if not _is_owner(update):
        await update.message.reply_text(s["admin_denied"])
        return True
    if text == OWNER_BUTTONS["add_admin"]:
        context.user_data["await_add_admin"] = True
        await update.message.reply_text(s["owner_add_ask"])
    elif text == OWNER_BUTTONS["del_admin"]:
        admins: set[int] = context.bot_data.get("admins", set())
        if not admins:
            await update.message.reply_text(s["owner_no_admins"])
        else:
            kb = InlineKeyboardMarkup(
                [
                    [
                        InlineKeyboardButton(
                            f"❌ {aid}", callback_data=f"adm:del:{aid}"
                        )
                    ]
                    for aid in sorted(admins)
                ]
            )
            await update.message.reply_text(s["owner_del_ask"], reply_markup=kb)
    elif text == OWNER_BUTTONS["users"]:
        await _send_user_list(update, context)
    elif text == OWNER_BUTTONS["broadcast"]:
        context.user_data["await_broadcast"] = True
        await update.message.reply_text(s["owner_bcast_ask"])
    elif text == OWNER_BUTTONS["check"]:
        await _check_news_now(update, context)
    elif text == OWNER_BUTTONS["db"]:
        await update.message.reply_text(
            STRINGS["fa"]["db_title"], reply_markup=_db_admin_menu()
        )
    elif text == OWNER_BUTTONS["close"]:
        context.user_data.pop("await_broadcast", None)
        context.user_data.pop("await_add_admin", None)
        await update.message.reply_text(
            s["admin_closed"],
            reply_markup=keyboard(
                _lang(context),
                _is_subscribed(context, update.effective_chat.id),
                is_owner=True,
            ),
        )
    return True


async def on_owner_pending(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """Capture the new admin's ID typed by the owner. True if handled."""
    if not context.user_data.get("await_add_admin"):
        return False
    text = (update.message.text or "").strip()
    s = STRINGS["fa"]
    if (
        text in OWNER_BUTTONS.values()
        or text in ADMIN_BUTTONS.values()
        or text == OWNER_PANEL_BTN
        or any(text in b.values() for b in BUTTONS.values())
        or text.startswith("/")
    ):
        context.user_data.pop("await_add_admin", None)
        return False
    if not text.isdigit():
        await update.message.reply_text(s["owner_add_bad"])
        return True
    aid = int(text)
    if aid == config.ADMIN_CHAT_ID:
        await update.message.reply_text(s["owner_add_self"])
        return True
    admins: set[int] = context.bot_data.setdefault("admins", set())
    admins.add(aid)
    _save_set(ADMINS_FILE, admins)
    context.user_data.pop("await_add_admin", None)
    await update.message.reply_text(s["owner_add_done"].format(uid=aid))
    return True


async def on_admin_button(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """Handle admin-panel buttons (added admins). Returns True if handled."""
    text = (update.message.text or "").strip()
    if text not in ADMIN_BUTTONS.values():
        return False
    if not _is_admin(update, context):
        await update.message.reply_text(STRINGS[_lang(context)]["admin_denied"])
        return True
    s = STRINGS["fa"]
    chat_id = update.effective_chat.id

    if text == ADMIN_BUTTONS["stats"]:
        await update.message.reply_text(
            s["admin_stats"].format(
                users=len(context.bot_data.get("users", set())),
                subs=len(context.bot_data.get("subscriptions", set())),
                seen=len(context.bot_data.get("seen_news", set())),
            )
        )
    elif text == ADMIN_BUTTONS["users"]:
        await _send_user_list(update, context)
    elif text == ADMIN_BUTTONS["broadcast"]:
        context.user_data["await_broadcast"] = True
        await update.message.reply_text(s["admin_bcast_ask"])
    elif text == ADMIN_BUTTONS["check"]:
        await _check_news_now(update, context)
    elif text == ADMIN_BUTTONS["db"]:
        await update.message.reply_text(
            STRINGS["fa"]["db_title"], reply_markup=_db_admin_menu()
        )
    elif text == ADMIN_BUTTONS["close"]:
        context.user_data.pop("await_broadcast", None)
        await update.message.reply_text(
            s["admin_closed"],
            reply_markup=keyboard(_lang(context), _is_subscribed(context, chat_id), is_owner=_is_owner(update)),
        )
    return True


async def on_broadcast_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """Capture the admin's broadcast content and send it to all targets."""
    if not context.user_data.get("await_broadcast") or not _is_admin(update, context):
        return False
    context.user_data.pop("await_broadcast", None)
    s = STRINGS["fa"]
    targets = _all_targets(context) - {update.effective_chat.id}
    sent = 0
    msg = update.message
    for chat_id in targets:
        try:
            if msg.photo:
                await context.bot.send_photo(
                    chat_id=chat_id,
                    photo=msg.photo[-1].file_id,
                    caption=msg.caption or "",
                )
            else:
                await context.bot.send_message(chat_id=chat_id, text=msg.text or "")
            sent += 1
        except Exception:
            log.warning("broadcast failed for chat %s", chat_id)
        await asyncio.sleep(0.08)
    await update.message.reply_text(
        s["admin_bcast_done"].format(n=sent),
        reply_markup=keyboard(
            _lang(context),
            _is_subscribed(context, update.effective_chat.id),
            is_owner=_is_owner(update),
        ),
    )
    return True


# ---------- profiles: onboarding, edit, friend lookup, news prefs ----------

def _onboarding_markup(lang: str) -> InlineKeyboardMarkup:
    s = STRINGS[lang]
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton(s["ob_username_btn"], callback_data="ob:username")],
            [InlineKeyboardButton(s["ob_name_btn"], callback_data="ob:name")],
            [InlineKeyboardButton(s["ob_skip_btn"], callback_data="ob:skip")],
        ]
    )


def _profile_menu(uid: int, lang: str) -> tuple[str, InlineKeyboardMarkup]:
    s = STRINGS[lang]
    p = get_profile(uid)
    un = s["profile_has"].format(v=p.wtm_username) if p.wtm_username else s["profile_empty"]
    nm = s["profile_has"].format(v=p.display_name) if p.display_name else s["profile_empty"]
    text = s["profile_title"].format(uid=uid, username=un, name=nm)
    kb = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    s["profile_edit_username"].format(
                        s=s["on"] if p.wtm_username else s["off"]
                    ),
                    callback_data="pr:edit:wtm_username",
                )
            ],
            [
                InlineKeyboardButton(
                    s["profile_edit_name"].format(
                        s=s["on"] if p.display_name else s["off"]
                    ),
                    callback_data="pr:edit:display_name",
                )
            ],
        ]
    )
    return text, kb


def _mynews_markup(uid: int, lang: str) -> InlineKeyboardMarkup:
    s = STRINGS[lang]
    p = get_profile(uid)
    rows = []
    for tag, key in (
        ("tanks", "mynews_tank"),
        ("aircraft", "mynews_air"),
        ("ships", "mynews_ship"),
    ):
        mark = s["on"] if p.news.get(tag, True) else s["off"]
        rows.append(
            [InlineKeyboardButton(s[key].format(s=mark), callback_data=f"np:{tag}")]
        )
    return InlineKeyboardMarkup(rows)


# ---------- news archive (seasons) ----------

ARCH_PAGE_SIZE = 8


def _archive_seasons_kb(lang: str) -> InlineKeyboardMarkup:
    from .services.news import get_seasons

    rows = []
    row = []
    for s in get_seasons():
        label = f"📚 {s['version']} ({s['count']})"
        row.append(InlineKeyboardButton(label, callback_data=f"arch:s:{s['version']}:0"))
        if len(row) == 2:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    return InlineKeyboardMarkup(rows)


def _archive_articles_kb(version: str, page: int, lang: str) -> InlineKeyboardMarkup:
    from .services.news import get_season_articles

    s = STRINGS[lang]
    arts = get_season_articles(version)
    total_pages = max(1, (len(arts) + ARCH_PAGE_SIZE - 1) // ARCH_PAGE_SIZE)
    page = max(0, min(page, total_pages - 1))
    rows = []
    for a in arts[page * ARCH_PAGE_SIZE:(page + 1) * ARCH_PAGE_SIZE]:
        title = (a.get("title") or "")[:60]
        rows.append([InlineKeyboardButton(f"📰 {title}", callback_data=f"arch:a:{a['id']}")])
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton("◀️", callback_data=f"arch:s:{version}:{page-1}"))
    if page < total_pages - 1:
        nav.append(InlineKeyboardButton("▶️", callback_data=f"arch:s:{version}:{page+1}"))
    if nav:
        rows.append(nav)
    rows.append([InlineKeyboardButton(s["arch_back_seasons"], callback_data="arch:seasons")])
    return InlineKeyboardMarkup(rows)


async def _archive_callback(update: Update, context: ContextTypes.DEFAULT_TYPE, data: str) -> None:
    """Route archive callbacks (arch:*)."""
    from .services.news import get_archive_article, get_season_articles, get_seasons

    q = update.callback_query
    lang = _lang(context)
    s = STRINGS[lang]
    parts = data.split(":")
    try:
        if data == "arch:seasons":
            await q.edit_message_text(s["arch_title"], reply_markup=_archive_seasons_kb(lang))
        elif parts[1] == "s":
            version, page = parts[2], int(parts[3]) if len(parts) > 3 else 0
            arts = get_season_articles(version)
            if not arts:
                await q.edit_message_text(s["arch_empty"], reply_markup=_archive_seasons_kb(lang))
                return
            total_pages = max(1, (len(arts) + ARCH_PAGE_SIZE - 1) // ARCH_PAGE_SIZE)
            title = f"{s['arch_season'].format(ver=version)}\n📄 {len(arts)} خبر · {page+1}/{total_pages}"
            await q.edit_message_text(title, reply_markup=_archive_articles_kb(version, page, lang))
        elif parts[1] == "a":
            a = get_archive_article(parts[2])
            if not a:
                try:
                    await q.answer(s["arch_empty"], show_alert=False)
                except Exception:
                    pass
                return
            # show loading immediately (fetch can take 10+s)
            try:
                await q.edit_message_text("⏳ در حال بارگذاری خبر...")
            except Exception:
                pass
            try:
                await q.answer()
            except Exception:
                pass
            from .services.news import FeedItem, fetch_article
            from datetime import datetime as _dt
            try:
                dt = _dt.strptime(a["date"].strip(), "%d %B %Y")
            except Exception:
                dt = _dt(2000, 1, 1)
            item = FeedItem(
                id=f"arch:{a['id']}", title=a.get("title") or "", date=a.get("date") or "",
                dt=dt, url=a.get("url") or "", photo=None, tag=a.get("tag") or "",
                source="site",
            )
            # archive articles: full page download to get all photos/videos
            from .services.news import fetch_article as _fa
            full = await _fa(item.url, full_page=True)
            if full:
                await send_full_article(context, q.message.chat_id, full, lang)
            else:
                await send_feed_item(context, q.message.chat_id, item, lang)
    except Exception:
        log.exception("archive callback failed: %s", data)


async def on_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Route inline-keyboard callbacks (onboarding / profile / news prefs)."""
    q = update.callback_query
    data = q.data or ""
    lang = _lang(context)
    s = STRINGS[lang]
    uid = q.from_user.id
    if data.startswith("ai:"):
        # answered inside (admin check may need to show an alert)
        await _ai_toggle_callback(update, context, data)
        return
    try:
        await q.answer()
    except Exception:
        pass  # query too old (late delivery) — continue anyway

    if data.startswith("v:"):
        await _vehicle_callback(update, context, data)
        return

    if data.startswith("arch:"):
        await _archive_callback(update, context, data)
        return

    if data == "ob:username" or data == "ob:name":
        field = "wtm_username" if data == "ob:username" else "display_name"
        context.user_data["await_profile_field"] = field
        context.user_data["profile_origin"] = "ob"
        prompt = s["ob_ask_username"] if field == "wtm_username" else s["ob_ask_name"]
        await q.edit_message_text(prompt)
    elif data == "ob:skip":
        p = get_profile(uid)
        p.onboarded = True
        save_profile(uid, p)
        context.user_data.pop("await_profile_field", None)
        await q.edit_message_text(s["ob_skip_done"])
    elif data.startswith("pr:edit:"):
        field = data.split(":", 2)[2]
        if field not in ("wtm_username", "display_name"):
            return
        context.user_data["await_profile_field"] = field
        context.user_data["profile_origin"] = "pr"
        prompt = (
            s["profile_ask_username"]
            if field == "wtm_username"
            else s["profile_ask_name"]
        )
        kb = InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(
                        s["profile_delete_btn"], callback_data=f"pr:del:{field}"
                    )
                ]
            ]
        )
        await q.edit_message_text(prompt, reply_markup=kb)
    elif data.startswith("pr:del:"):
        field = data.split(":", 2)[2]
        if field not in ("wtm_username", "display_name"):
            return
        p = get_profile(uid)
        setattr(p, field, None)
        save_profile(uid, p)
        context.user_data.pop("await_profile_field", None)
        text, kb = _profile_menu(uid, lang)
        await q.edit_message_text(text, reply_markup=kb)
    elif data.startswith("np:"):
        tag = data.split(":", 1)[1]
        if tag not in ("tanks", "aircraft", "ships"):
            return
        p = get_profile(uid)
        p.news[tag] = not p.news.get(tag, True)
        save_profile(uid, p)
        await q.edit_message_text(
            s["mynews_title"], reply_markup=_mynews_markup(uid, lang)
        )
    elif data.startswith("adm:del:"):
        if not _is_owner(update):
            return
        try:
            aid = int(data.split(":", 2)[2])
        except ValueError:
            return
        admins: set[int] = context.bot_data.get("admins", set())
        admins.discard(aid)
        _save_set(ADMINS_FILE, admins)
        await q.edit_message_text(STRINGS["fa"]["owner_del_done"].format(uid=aid))
    elif data.startswith("db:"):
        if not _is_admin(update, context):
            return
        s = STRINGS["fa"]
        action = data.split(":", 1)[1]
        if action == "stats":
            await q.edit_message_text(
                _db_stats_text(), reply_markup=_db_admin_menu()
            )
        elif action == "reload":
            n = veh.reload_vehicles()
            context.bot_data["vehicles"] = veh.get_vehicles()
            await q.edit_message_text(
                s["db_reloaded"].format(n=n), reply_markup=_db_admin_menu()
            )
        elif action == "fill":
            if not context.bot_data.get("db_fill_running"):
                context.bot_data["db_fill_running"] = True

                async def _run():
                    try:
                        await _db_fill_job(q.message.chat_id, context)
                    finally:
                        context.bot_data["db_fill_running"] = False

                asyncio.create_task(_run())
                await q.edit_message_text(
                    s["db_fill_started"], reply_markup=_db_admin_menu()
                )
            else:
                await q.answer("⏳ تکمیل در حال انجامه…", show_alert=False)


async def on_pending_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """Handle free-text answers for profile / friend prompts. True if handled."""
    msg = update.message
    text = (msg.text or "").strip()
    if not text:
        return False
    user = update.effective_user
    lang = _lang(context)
    s = STRINGS[lang]

    field = context.user_data.get("await_profile_field")
    if field:
        # a button press cancels the pending input
        if (
            any(text in b.values() for b in BUTTONS.values())
            or text in ADMIN_BUTTONS.values()
            or text in OWNER_BUTTONS.values()
            or text == OWNER_PANEL_BTN
            or text.startswith("/")
        ):
            context.user_data.pop("await_profile_field", None)
            context.user_data.pop("profile_origin", None)
            return False
        p = get_profile(user.id)
        setattr(p, field, text[:64])
        p.onboarded = True
        save_profile(user.id, p)
        context.user_data.pop("await_profile_field", None)
        origin = context.user_data.pop("profile_origin", None)
        ok_msg = (
            s["ob_saved_username"].format(v=text)
            if field == "wtm_username"
            else s["ob_saved_name"].format(v=text)
        )
        await msg.reply_text(
            ok_msg,
            reply_markup=keyboard(lang, _is_subscribed(context, update.effective_chat.id), is_owner=_is_owner(update)),
        )
        if origin == "pr":
            menu_text, kb = _profile_menu(user.id, lang)
            await msg.reply_text(menu_text, reply_markup=kb)
        return True

    if context.user_data.get("await_friend_id"):
        if (
            any(text in b.values() for b in BUTTONS.values())
            or text in ADMIN_BUTTONS.values()
            or text in OWNER_BUTTONS.values()
            or text == OWNER_PANEL_BTN
            or text.startswith("/")
        ):
            context.user_data.pop("await_friend_id", None)
            return False
        if not text.isdigit():
            await msg.reply_text(s["friend_bad_id"])
            return True
        context.user_data.pop("await_friend_id", None)
        fuid = int(text)
        if not profile_exists(fuid):
            await msg.reply_text(s["friend_not_found"])
            return True
        fp = get_profile(fuid)
        lines = ""
        if fp.wtm_username:
            lines += s["friend_found_username"].format(v=fp.wtm_username)
        if fp.display_name:
            lines += s["friend_found_name"].format(v=fp.display_name)
        if lines:
            await msg.reply_text(s["friend_found"].format(uid=fuid, lines=lines.rstrip()))
        else:
            await msg.reply_text(s["friend_empty_profile"])
        return True
    return False


def keyboard(lang: str, subscribed: bool, is_owner: bool = False) -> ReplyKeyboardMarkup:
    b = BUTTONS[lang]
    sub_btn = b["unsub"] if subscribed else b["sub"]
    rows = [
        [b["news"], b["archive"]],
        [b["help"], b["github"]],
        [b["tank"], b["air"], b["ship"]],
        [b["vehicle"]],
        [b["mynews"], b["friend"]],
        [b["profile"], b["lang"]],
        [sub_btn],
    ]
    if is_owner:
        rows.append([OWNER_PANEL_BTN])
    return ReplyKeyboardMarkup(rows, resize_keyboard=True)


def _lang(context: ContextTypes.DEFAULT_TYPE) -> str:
    return context.user_data.get("lang", config.DEFAULT_LANG)


VEHICLES_PATH = os.path.join("data", "vehicles.json")


def _reload_vehicles(context: ContextTypes.DEFAULT_TYPE) -> int:
    """(Re)load the vehicle roster from disk into module cache + bot_data."""
    try:
        n = veh.reload_vehicles()
    except Exception:
        log.exception("failed to load vehicles.json")
        return 0
    context.bot_data["vehicles"] = veh.get_vehicles()
    context.bot_data["vehicles_by_id"] = {v["id"]: v for v in veh.get_vehicles()}
    return n


async def _vehicle_menu_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    lang = _lang(context)
    await update.message.reply_text(
        veh.STR[lang]["menu_title"], reply_markup=veh.menu_kb(lang)
    )


async def _vehicle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE, data: str) -> None:
    """Route inline-keyboard callbacks for the vehicle database (v:*)."""
    q = update.callback_query
    lang = _lang(context)
    s = veh.STR[lang]
    vehicles = context.bot_data.get("vehicles", [])
    by_id = context.bot_data.get("vehicles_by_id", {})
    parts = data.split(":")
    try:
        if data == "v:menu":
            await q.edit_message_text(s["menu_title"], reply_markup=veh.menu_kb(lang))
        elif parts[1] == "b":
            branch = veh.CODE_BRANCH[parts[2]]
            await q.edit_message_text(
                f"{veh._branch_label(branch, lang)}\n{s['nation_title']}",
                reply_markup=veh.nation_kb(branch, lang),
            )
        elif parts[1] == "n":
            branch = veh.CODE_BRANCH[parts[2]]
            nation = veh.CODE_NATION[parts[3]]
            await q.edit_message_text(
                f"{veh.NATION_FA[nation]} · {veh._branch_label(branch, lang)}\n{s['mode_title']}",
                reply_markup=veh.mode_kb(branch, nation, lang),
            )
        elif parts[1] == "mr":
            branch = veh.CODE_BRANCH[parts[2]]
            nation = veh.CODE_NATION[parts[3]]
            await q.edit_message_text(
                s["rank_title"], reply_markup=veh.rank_kb(vehicles, branch, nation, lang)
            )
        elif parts[1] == "mt":
            branch = veh.CODE_BRANCH[parts[2]]
            nation = veh.CODE_NATION[parts[3]]
            await q.edit_message_text(
                s["type_title"], reply_markup=veh.type_kb(vehicles, branch, nation, lang)
            )
        elif parts[1] in ("lr", "lt"):
            branch = veh.CODE_BRANCH[parts[2]]
            nation = veh.CODE_NATION[parts[3]]
            kind = "rank" if parts[1] == "lr" else "type"
            value = int(parts[4]) if kind == "rank" else parts[4]
            page = int(parts[5])
            kb, page, total = veh.list_kb(vehicles, branch, nation, kind, value, page, lang)
            context.user_data["v_back"] = f"v:{parts[1]}:{parts[2]}:{parts[3]}:{parts[4]}:{page}"
            items = veh._filtered(vehicles, branch, nation, kind, value)
            label = f"رنک {veh.ROMAN[value-1]}" if kind == "rank" else veh.TYPE_FA.get(value, value)
            title = (
                f"{veh.NATION_FA[nation]} · {label}\n"
                f"{s['count'].format(n=len(items))} · {page+1}/{total}"
            )
            await q.edit_message_text(title, reply_markup=kb)
        elif parts[1] == "c":
            v = by_id.get(parts[2])
            if not v:
                return
            back = context.user_data.get("v_back", "v:menu")
            # enrich photo + game stats from the wiki on first view (cached after)
            try:
                await veh.enrich_vehicle(v)
            except Exception:
                log.exception("vehicle enrich failed: %s", v.get("id"))
            try:
                await _send_with_photo(
                    context,
                    q.message.chat_id,
                    v.get("photo_url"),
                    veh.card_text(v, lang),
                    "",
                    reply_markup=veh.card_kb(v, lang, back),
                    parse_mode="HTML",
                )
            except Exception:
                log.exception("vehicle card send failed")
        elif parts[1] == "s":
            context.user_data["await_vsearch"] = True
            await q.edit_message_text(s["search_ask"])
    except Exception:
        log.exception("vehicle callback failed: %s", data)


def _is_subscribed(context: ContextTypes.DEFAULT_TYPE, chat_id: int) -> bool:
    return chat_id in context.bot_data.get("subscriptions", set())


# ---------- article rendering ----------

async def _fa(text: str) -> tuple[str, bool]:
    return await asyncio.to_thread(translate_to_fa, text)


def _split_text(text: str, limit: int = 4000) -> list[str]:
    parts, cur = [], ""
    for para in text.split("\n\n"):
        if len(cur) + len(para) + 2 > limit and cur:
            parts.append(cur)
            cur = para
        else:
            cur = (cur + "\n\n" + para).strip()
    if cur:
        parts.append(cur)
    return parts


async def _render_article(
    article: FullArticle, lang: str
) -> tuple[str, str, list[str], list[tuple[str, str]]]:
    """Return (caption, body_text, photo_urls, videos as (kind, url))."""
    s = STRINGS[lang]
    if lang == "fa":
        title, title_ok = await _fa(article.title)
        body_parts: list[str] = []
        failed = not title_ok
        for kind, value in article.blocks:
            if kind in ("img", "video", "yt"):
                continue
            if kind == "h3":
                fa_h, h_ok = await _fa(value)
                failed = failed or not h_ok
                body_parts.append(f"\n\n▪️ {fa_h}\n")
                continue
            fa, p_ok = await _fa(value)
            failed = failed or not p_ok
            body_parts.append(fa)
        body = "\n\n".join(p for p in body_parts if p).strip()
        if failed:
            body = s["no_translation"] + "\n\n" + body
    else:
        title = article.title
        body = "\n\n".join(
            (f"▪️ {v}" if k == "h3" else v)
            for k, v in article.blocks
            if k not in ("img", "video", "yt")
        )
    caption = f"📰 {title}\n📅 {article.date}"
    photos: list[str] = []
    if article.hero_image:
        photos.append(article.hero_image)
    for k, v in article.blocks:
        if k == "img" and v != article.hero_image and len(photos) < 5:
            photos.append(v)
    videos = [(k, v) for k, v in article.blocks if k in ("video", "yt")][:3]
    return caption, body, photos, videos


async def _send_with_photo(
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    photo_url: str | None,
    caption: str,
    body: str,
    reply_markup: InlineKeyboardMarkup | None = None,
    parse_mode: str | None = None,
) -> None:
    """Send caption (+photo) then body text.

    The photo is downloaded and re-uploaded because Telegram's servers can't
    fetch some CDN URLs (e.g. telesco.pe) — passing the URL fails the whole
    message. Text is always sent even if the photo fails.
    """
    sent_with_photo = False
    if photo_url:
        data = await asyncio.to_thread(_download_bytes, photo_url)
        if data:
            bio = io.BytesIO(data)
            bio.name = "photo.jpg"
            try:
                await context.bot.send_photo(
                    chat_id=chat_id,
                    photo=bio,
                    caption=caption[:1000],
                    reply_markup=reply_markup,
                    parse_mode=parse_mode,
                )
                sent_with_photo = True
            except Exception:
                log.warning("photo upload failed, falling back to text")
    if not sent_with_photo:
        await context.bot.send_message(
            chat_id=chat_id,
            text=caption[:4000],
            reply_markup=reply_markup,
            parse_mode=parse_mode,
        )
    for chunk in _split_text(body):
        await context.bot.send_message(chat_id=chat_id, text=chunk)


async def _send_videos(
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    videos: list[tuple[str, str]],
    watch_url: str | None = None,
    watch_label: str = "▶️ تماشای ویدیو",
) -> None:
    """Send article videos: mp4s are downloaded & re-uploaded, YouTube links
    go out as a watch button. Falls back to a watch link when all else fails."""
    yt_links = [url for kind, url in videos if kind == "yt"]
    mp4s = [url for kind, url in videos if kind == "video"]
    kb = None
    if yt_links or watch_url:
        kb = InlineKeyboardMarkup(
            [
                [InlineKeyboardButton(watch_label, url=u)]
                for u in (yt_links[:2] if yt_links else [watch_url])
            ]
        )
    for url in mp4s[:2]:
        data = await asyncio.to_thread(_download_bytes, url, 45_000_000)
        if not data:
            continue
        bio = io.BytesIO(data)
        bio.name = "video.mp4"
        try:
            await context.bot.send_video(chat_id=chat_id, video=bio)
        except Exception:
            log.warning("video upload failed: %s", url[:60])
    if kb and not mp4s:
        try:
            await context.bot.send_message(
                chat_id=chat_id, text="🎬", reply_markup=kb
            )
        except Exception:
            log.warning("video button failed")


async def send_full_article(
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    article: FullArticle,
    lang: str = "fa",
    badge: str | None = None,
) -> None:
    caption, body, photos, videos = await _render_article(article, lang)
    if badge:
        caption = f"{badge}\n\n{caption}"
    try:
        await _send_with_photo(
            context, chat_id, photos[0] if photos else None, caption, body
        )
        for url in photos[1:]:
            data = await asyncio.to_thread(_download_bytes, url)
            if not data:
                continue
            bio = io.BytesIO(data)
            bio.name = "photo.jpg"
            try:
                await context.bot.send_photo(chat_id=chat_id, photo=bio)
            except Exception:
                log.warning("extra photo failed")
        if videos:
            await _send_videos(context, chat_id, videos)
    except Exception:
        log.exception("send_full_article failed for chat %s", chat_id)


async def _latest_feed_item(tag: str | None) -> FeedItem | None:
    items = await fetch_feed(tag=tag, limit=1)
    return items[0] if items else None


async def send_feed_item(
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    item: FeedItem,
    lang: str = "fa",
    badge: str | None = None,
) -> None:
    """Send one merged-feed item: full website article or channel post."""
    if item.source == "site":
        full = await fetch_article(item.url)
        if not full:
            return
        await send_full_article(context, chat_id, full, lang, badge)
        return
    # channel post: the post text is the content
    title, body = item.title, item.text or item.title
    if lang == "fa":
        title, _ = await _fa(title)
        body, _ = await _fa(body)
    prefix = "🎬 " if item.has_video else "📰 "
    caption = f"{prefix}{title}\n📅 {item.date}"
    if item.has_video and item.video_duration:
        caption += f" | ⏱ {item.video_duration}"
    if badge:
        caption = f"{badge}\n\n{caption}"
    watch_kb = None
    if item.has_video:
        watch_kb = InlineKeyboardMarkup(
            [[InlineKeyboardButton("▶️ تماشای ویدیو", url=item.url)]]
        )
    try:
        await _send_with_photo(
            context, chat_id, item.photo, caption, body, reply_markup=watch_kb
        )
    except Exception:
        log.exception("send_feed_item failed for chat %s", chat_id)


# ---------- handlers ----------

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    try:
        if update.message and update.message.date:
            delay = time.time() - update.message.date.timestamp()
            if delay > 2:
                log.warning("slow /start delivery: %.1fs", delay)
    except Exception:
        pass
    if user:
        users: set[int] = context.bot_data.setdefault("users", set())
        if user.id not in users:
            users.add(user.id)
            _save_set(USERS_FILE, users)
    lang = _lang(context)
    s = STRINGS[lang]
    await update.message.reply_text(
        s["start"], reply_markup=keyboard(lang, _is_subscribed(context, update.effective_chat.id), is_owner=_is_owner(update))
    )
    # one-time onboarding, private chats only: ask for WTM username / name
    if user and update.effective_chat.type == "private":
        p = get_profile(user.id)
        if not p.onboarded:
            p.onboarded = True
            save_profile(user.id, p)
            await update.message.reply_text(
                s["ob_ask"], reply_markup=_onboarding_markup(lang)
            )


async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(STRINGS[_lang(context)]["help"])


async def news_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    lang = _lang(context)
    s = STRINGS[lang]
    tag = TAG_MAP.get(context.args[0].lower()) if context.args else None
    try:
        wait = await update.message.reply_text(s["translating"])
        item = await _latest_feed_item(tag)
        try:
            await wait.delete()
        except Exception:
            pass
        if not item:
            await update.message.reply_text(
                s["news_empty"],
                reply_markup=keyboard(lang, _is_subscribed(context, update.effective_chat.id), is_owner=_is_owner(update)),
            )
            return
        await send_feed_item(context, update.effective_chat.id, item, lang)
    except Exception:
        log.exception("news_cmd failed")
        try:
            await update.message.reply_text(s["send_failed"])
        except Exception:
            pass


async def toggle_sub(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    lang = _lang(context)
    s = STRINGS[lang]
    chat_id = update.effective_chat.id
    subs: set[int] = context.bot_data.setdefault("subscriptions", set())
    if chat_id in subs:
        subs.discard(chat_id)
        text = s["unsubscribed"]
    else:
        subs.add(chat_id)
        text = s["subscribed"]
    _save_set(SUBS_FILE, subs)
    await update.message.reply_text(
        text, reply_markup=keyboard(lang, chat_id in subs, is_owner=_is_owner(update))
    )


async def switch_lang(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    new_lang = "en" if _lang(context) == "fa" else "fa"
    context.user_data["lang"] = new_lang
    s = STRINGS[new_lang]
    await update.message.reply_text(
        s["lang_switched"],
        reply_markup=keyboard(new_lang, _is_subscribed(context, update.effective_chat.id), is_owner=_is_owner(update)),
    )


async def vehicle(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _vehicle_menu_message(update, context)


async def on_button(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Route reply-keyboard button presses (both languages)."""
    # admin broadcast content takes priority
    if await on_broadcast_message(update, context):
        return
    # owner panel (👑 button + panel buttons)
    if await on_owner_button(update, context):
        return
    # admin panel buttons
    if await on_admin_button(update, context):
        return
    # free-text answers for profile / friend prompts
    if await on_pending_text(update, context):
        return
    # owner typing a new admin's ID
    if await on_owner_pending(update, context):
        return
    # vehicle database: free-text search answer
    if context.user_data.pop("await_vsearch", None):
        lang = _lang(context)
        s = veh.STR[lang]
        results = veh.search(context.bot_data.get("vehicles", []), update.message.text or "")
        if not results:
            await update.message.reply_text(s["search_none"])
        else:
            kb = InlineKeyboardMarkup(
                [[InlineKeyboardButton(v["name"], callback_data=f"v:c:{v['id']}")]
                 for v in results]
            )
            await update.message.reply_text(s["search_results"], reply_markup=kb)
        return
    text = (update.message.text or "").strip()
    lang = _lang(context)
    # detect language of the pressed button
    for cand in ("fa", "en"):
        b = BUTTONS[cand]
        if text in b.values():
            lang = cand
            context.user_data["lang"] = cand
            break
    b = BUTTONS[lang]
    s = STRINGS[lang]
    chat_id = update.effective_chat.id

    if text == b["news"]:
        try:
            wait = await update.message.reply_text(s["translating"])
            item = await _latest_feed_item(None)
            try:
                await wait.delete()
            except Exception:
                pass
            if item:
                await send_feed_item(context, chat_id, item, lang)
            else:
                await update.message.reply_text(s["news_empty"])
        except Exception:
            log.exception("news button failed")
    elif text == b["archive"]:
        await update.message.reply_text(
            s["arch_title"], reply_markup=_archive_seasons_kb(lang)
        )
    elif text == b["github"]:
        await update.message.reply_text(
            s["github_text"],
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton(s["github_btn"], url=GITHUB_URL)]]
            ),
        )
    elif text in (b["tank"], b["air"], b["ship"]):
        mode = next(k for k, v in b.items() if v == text)
        try:
            wait = await update.message.reply_text(s["translating"])
            item = await _latest_feed_item(MODE_OF_BUTTON[mode])
            try:
                await wait.delete()
            except Exception:
                pass
            if item:
                await send_feed_item(context, chat_id, item, lang)
            else:
                await update.message.reply_text(s["news_empty"])
        except Exception:
            log.exception("mode news button failed")
            try:
                await update.message.reply_text(s["send_failed"])
            except Exception:
                pass
    elif text == b["mynews"]:
        await update.message.reply_text(
            s["mynews_title"],
            reply_markup=_mynews_markup(update.effective_user.id, lang),
        )
    elif text == b["vehicle"]:
        context.user_data.pop("await_vsearch", None)
        await _vehicle_menu_message(update, context)
    elif text == b["friend"]:
        context.user_data["await_friend_id"] = True
        await update.message.reply_text(s["friend_ask"])
    elif text == b["profile"]:
        menu_text, kb = _profile_menu(update.effective_user.id, lang)
        await update.message.reply_text(menu_text, reply_markup=kb)
    elif text in (b["sub"], b["unsub"]):
        await toggle_sub(update, context)
    elif text == b["lang"]:
        await switch_lang(update, context)
    elif text == b["help"]:
        await update.message.reply_text(s["help"])
    # AI group chat (mention / reply-to-bot triggers) — only reached when
    # the text matched no button and no pending flow consumed it.
    await on_ai_chat(update, context)


async def _ai_reply(update: Update, context: ContextTypes.DEFAULT_TYPE, prompt: str) -> None:
    """Send one AI-brain reply for an already-triggered chat request."""
    chat_id = update.effective_chat.id
    now = time.monotonic()
    last: dict = context.bot_data.setdefault("ai_last", {})
    if now - last.get(chat_id, 0.0) < 4.0:
        return  # per-chat cooldown (also matches the free provider's rate limit)
    last[chat_id] = now
    try:
        await context.bot.send_chat_action(chat_id=chat_id, action="typing")
    except Exception:
        pass
    name = (update.effective_user.first_name if update.effective_user else None) or "رفیق"
    reply = await ask_brain(chat_id, name, prompt)
    if reply:
        await update.message.reply_text(reply)
    else:
        await update.message.reply_text("مغزم یه لحظه هنگ کرد 😅 یه بار دیگه بپرس")


async def on_ai_chat(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """AI chat: groups answer on @mention / reply-to-bot; DM answers any text."""
    msg = update.message
    if msg is None or not msg.text:
        return
    chat = update.effective_chat
    if chat is None or chat.type not in ("group", "supergroup", "private"):
        return
    user = update.effective_user
    if user is None or user.is_bot:
        return
    text = msg.text.strip()
    # never hijack a reply-keyboard button press
    for cand in ("fa", "en"):
        if text in BUTTONS[cand].values():
            return
    if chat.type == "private":
        # DM: just type — no /ask needed. Only reached when no button
        # and no pending flow consumed the text (see on_button fallthrough).
        if chat.id in context.bot_data.get("ai_off", set()):
            return
        if text:
            await _ai_reply(update, context, text)
        return
    if chat.id in context.bot_data.get("ai_off", set()):
        return
    prompt = text
    triggered = False
    if (
        msg.reply_to_message is not None
        and msg.reply_to_message.from_user is not None
        and msg.reply_to_message.from_user.id == context.bot.id
    ):
        triggered = True
    else:
        bot_user = context.bot.username
        if bot_user:
            needle = f"@{bot_user}".lower()
            idx = text.lower().find(needle)
            if idx >= 0:
                triggered = True
                prompt = (text[:idx] + text[idx + len(needle):]).strip(" :,-") or prompt
    if not triggered:
        return
    if prompt == text and prompt.startswith("@"):
        prompt = ""
    if not prompt:
        prompt = "سلام کن و خیلی کوتاه و بامزه خودت رو معرفی کن"
    await _ai_reply(update, context, prompt)


async def ai_ask_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/ask <question> — explicit AI chat, works in groups and in DM."""
    chat = update.effective_chat
    if (
        chat is not None
        and chat.id in context.bot_data.get("ai_off", set())
    ):
        await update.message.reply_text("چت هوش مصنوعی این چت خاموشه 🔇 از پنل /aichat روشنش کن")
        return
    prompt = " ".join(context.args or []).strip()
    if not prompt:
        await update.message.reply_text("بپرس ببینم 😄 مثلاً:\n/ask یه جوک کوتاه بگو")
        return
    await _ai_reply(update, context, prompt)


async def ai_chat_toggle(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/chatoff and /chaton — group admins (or the bot owner) toggle AI chat."""
    chat = update.effective_chat
    if chat is None or chat.type not in ("group", "supergroup"):
        await update.message.reply_text("این دستور فقط توی گروه کار می‌کنه 👥")
        return
    user_id = update.effective_user.id if update.effective_user else 0
    allowed = user_id == config.ADMIN_CHAT_ID
    if not allowed:
        try:
            member = await context.bot.get_chat_member(chat.id, user_id)
            allowed = member.status in ("administrator", "creator")
        except Exception:
            allowed = False
    if not allowed:
        await update.message.reply_text("فقط ادمین‌های گروه می‌تونن چت رو خاموش/روشن کنن 🔐")
        return
    off: set[int] = context.bot_data.setdefault("ai_off", set())
    cmd = (update.message.text or "").split()[0].split("@")[0].lower()
    if cmd == "/chatoff":
        off.add(chat.id)
        _save_set(AI_OFF_FILE, off)
        await update.message.reply_text("چت هوش مصنوعی خاموش شد 🔇 از پنل /aichat دوباره روشنم کن")
    else:
        off.discard(chat.id)
        _save_set(AI_OFF_FILE, off)
        await update.message.reply_text("چت هوش مصنوعی روشن شد 🔊 صدام کنین گپ بزنیم 😄")


def _ai_panel(chat_id: int, off: set[int]) -> tuple[str, InlineKeyboardMarkup]:
    """Status text + one on/off button for the AI chat of one chat."""
    if chat_id in off:
        return (
            "🧠 چت هوش مصنوعی این چت الان خاموشه 🔇\nدکمه زیر رو بزن تا روشنش کنی:",
            InlineKeyboardMarkup(
                [[InlineKeyboardButton("🔊 روشن کردن چت", callback_data="ai:on")]]
            ),
        )
    return (
        "🧠 چت هوش مصنوعی این چت الان روشنه 🔊\n"
        "کافیه روی پیام‌های ربات ریپلای بزنی یا منشنش کنی تا جواب بده 😄\n"
        "دکمه زیر رو بزن تا خاموشش کنی:",
        InlineKeyboardMarkup(
            [[InlineKeyboardButton("🔇 خاموش کردن چت", callback_data="ai:off")]]
        ),
    )


async def ai_chat_panel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/aichat — AI chat status panel with an inline on/off button."""
    chat = update.effective_chat
    if chat is None:
        return
    off: set[int] = context.bot_data.setdefault("ai_off", set())
    text, kb = _ai_panel(chat.id, off)
    await update.message.reply_text(text, reply_markup=kb)


async def _ai_toggle_callback(
    update: Update, context: ContextTypes.DEFAULT_TYPE, data: str
) -> None:
    """ai:on / ai:off — panel button. Groups: admins/owner only; DM: the user."""
    q = update.callback_query
    chat = q.message.chat if q is not None and q.message is not None else None
    if q is None or chat is None:
        return
    uid = q.from_user.id
    allowed = uid == config.ADMIN_CHAT_ID or chat.type == "private"
    if not allowed and chat.type in ("group", "supergroup"):
        try:
            member = await context.bot.get_chat_member(chat.id, uid)
            allowed = member.status in ("administrator", "creator")
        except Exception:
            allowed = False
    if not allowed:
        try:
            await q.answer("فقط ادمین‌های گروه می‌تونن 🔐", show_alert=True)
        except Exception:
            pass
        return
    off: set[int] = context.bot_data.setdefault("ai_off", set())
    if data == "ai:off":
        off.add(chat.id)
    else:
        off.discard(chat.id)
    _save_set(AI_OFF_FILE, off)
    try:
        await q.answer("انجام شد ✅")
    except Exception:
        pass
    text, kb = _ai_panel(chat.id, off)
    try:
        await q.edit_message_text(text, reply_markup=kb)
    except Exception:
        pass


async def on_chat_member(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Auto-subscribe chats the bot is added to; drop chats it leaves."""
    m: ChatMemberUpdated = update.my_chat_member
    new_status = m.new_chat_member.status
    chat_id = m.chat.id
    subs: set[int] = context.bot_data.setdefault("subscriptions", set())
    if new_status in ("member", "administrator"):
        if chat_id not in subs:
            subs.add(chat_id)
            _save_set(SUBS_FILE, subs)
            try:
                await context.bot.send_message(chat_id=chat_id, text=STRINGS["fa"]["group_hello"])
            except Exception:
                pass
            log.info("auto-subscribed chat %s", chat_id)
    elif new_status in ("left", "kicked"):
        subs.discard(chat_id)
        _save_set(SUBS_FILE, subs)


async def news_watcher(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Push new official news (website + channel, Persian + photos).

    Respects each user's news-category preferences; group/channel subscribers
    get everything.
    """
    items = await fetch_feed(limit=15)
    if not items:
        return
    seen: set = context.bot_data.setdefault("seen_news", set())
    if not seen:
        seen.update(i.id for i in items)  # baseline silently on first run
        _save_set(SEEN_FILE, seen)
        return
    fresh = [i for i in items if i.id not in seen]
    seen.update(i.id for i in items)
    _save_set(SEEN_FILE, seen)
    if not fresh:
        return
    users: set[int] = context.bot_data.get("users", set())
    targets = set(context.bot_data.get("subscriptions", set())) | users
    if config.ADMIN_CHAT_ID:
        targets.add(config.ADMIN_CHAT_ID)
    if not targets:
        return
    s = STRINGS["fa"]
    for item in reversed(fresh):  # oldest first
        full = None
        if item.source == "site":
            full = await fetch_article(item.url)
            if not full:
                continue
        for chat_id in targets:
            if chat_id in users and item.tag:
                if not get_profile(chat_id).news.get(item.tag, True):
                    continue
            try:
                if full:
                    await send_full_article(
                        context, chat_id, full, "fa", badge=s["new_badge"]
                    )
                else:
                    await send_feed_item(
                        context, chat_id, item, "fa", badge=s["new_badge"]
                    )
            except Exception:
                log.warning("broadcast failed for chat %s", chat_id)
            await asyncio.sleep(0.1)


def main() -> None:
    app = (
        Application.builder()
        .token(config.BOT_TOKEN)
        .request(
            HTTPXRequest(
                connection_pool_size=32,
                connect_timeout=15.0,
                read_timeout=30.0,
                write_timeout=30.0,
                pool_timeout=10.0,
            )
        )
        .build()
    )
    app.bot_data["subscriptions"] = _load_set(SUBS_FILE)
    app.bot_data["users"] = _load_set(USERS_FILE)
    app.bot_data["admins"] = _load_set(ADMINS_FILE)
    app.bot_data["seen_news"] = _load_set(SEEN_FILE)
    app.bot_data["ai_off"] = _load_set(AI_OFF_FILE)
    _reload_vehicles(app)
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CommandHandler("news", news_cmd))
    app.add_handler(CommandHandler("subscribe", toggle_sub))
    app.add_handler(CommandHandler("unsubscribe", toggle_sub))
    app.add_handler(CommandHandler("vehicle", vehicle))
    app.add_handler(CommandHandler("lang", switch_lang))
    app.add_handler(CommandHandler("admin", admin_panel))
    app.add_handler(CommandHandler("ask", ai_ask_cmd))
    app.add_handler(CommandHandler("aichat", ai_chat_panel))
    app.add_handler(CommandHandler("chatoff", ai_chat_toggle))
    app.add_handler(CommandHandler("chaton", ai_chat_toggle))
    app.add_handler(CallbackQueryHandler(on_callback))
    app.add_handler(
        MessageHandler((filters.TEXT & ~filters.COMMAND) | filters.PHOTO, on_button)
    )
    app.add_handler(ChatMemberHandler(on_chat_member, ChatMemberHandler.MY_CHAT_MEMBER))
    # Daily news digest at 09:00 Tehran time (was every 30 min — user found it spammy)
    app.job_queue.run_daily(
        news_watcher,
        time=dtime(hour=9, minute=0, tzinfo=ZoneInfo("Asia/Tehran")),
        name="daily_news_digest",
    )
    log.info(
        "Bot starting… admin=%s subscribers=%d users=%d vehicles=%d",
        config.ADMIN_CHAT_ID,
        len(app.bot_data["subscriptions"]),
        len(app.bot_data["users"]),
        len(app.bot_data["vehicles"]),
    )
    # drop stale queued updates (e.g. after VM replacement) so new
    # /start messages aren't stuck behind 2-minute-old ones
    app.run_polling(
        poll_interval=1.0,
        timeout=20,
        bootstrap_retries=3,
        drop_pending_updates=True,
    )


if __name__ == "__main__":
    main()
