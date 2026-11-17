# ربات تلگرام War Thunder Mobile 🎖️

دستیار تلگرامی فارسی برای بازی **War Thunder Mobile**.

ربات زنده: [@PersianWarTunder_bot](https://t.me/PersianWarTunder_bot)

سازنده: [@USA_Ariya](https://t.me/USA_Ariya)

## قابلیت‌ها

- 📰 **اخبار رسمی** — آخرین اخبار از سایت رسمی و کانال رسمی بازی، با فیلتر تانک / هواپیما / کشتی، آرشیو ۶۹۳ مقاله در ۲۸ سیزن و ارسال خودکار روزانه (ساعت ۹ صبح تهران)
- 🚗 **دیتابیس وسایل نقلیه** — ۹۵۹ وسیله با عکس و آمار کامل، جستجو و مرور دکمه‌ای بر اساس کشور و نوع
- 🤖 **مغز چت هوش مصنوعی** — پاسخ‌گویی در گروه و پیوی با منشن یا ریپلای، با پنل روشن/خاموش `/aichat` برای ادمین‌ها
- 📖 **راهنمای جامع فارسی** بازی
- 🔘 رابط کاملاً دکمه‌ای — بدون نیاز به تایپ دستور

## نصب و اجرا

```bash
git clone <repo-url>
cd war-thunder-mobile-bot
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # توکن ربات از BotFather را داخلش بگذار
python -m bot.main
```

## ساختار پروژه

- `bot/main.py` — نقطه ورود و ثبت هندلرها
- `bot/handlers/` — هندلرهای دستورات و دکمه‌ها
- `bot/services/` — سرویس اخبار، دیتابیس وسایل و مغز چت هوش مصنوعی
- `data/` — دیتابیس وسایل نقلیه و آرشیو اخبار

## فناوری‌ها

Python 3 · python-telegram-bot v21 · Groq API

---

ساخته شده توسط **Ariya team** — [@USA_Ariya](https://t.me/USA_Ariya)
