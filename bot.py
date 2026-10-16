import discord
from discord.ext import commands
import logging
import os
import threading
from flask import Flask

# Logging to file + console so we can diagnose
logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] %(levelname)s %(name)s: %(message)s",
    handlers=[
        logging.FileHandler("bot.log", encoding="utf-8"),
        logging.StreamHandler(),
    ],
)
log = logging.getLogger("ticket-bot")

TOKEN = os.getenv("DISCORD_TOKEN", "")

TRANSFER_MESSAGE = """***البنك:` الراجحي`



`اسم  المستفيد :  طارق حمدان السبيعي`




رقم الحساب:`  639000010006086076811`




الآيبان:  ` SA2580000639608016076811`




في حال اردت التحويل برق  من رقم الجوال: `0558839503`***"""

PAYMENT_MESSAGE = "‏https://am4e.00stores.com/product/fJjzcLqFqcXv"

# صورة التحويل: خياران (الأولوية لملف محلي)
# 1) حط صورة باسم transfer.png بجانب bot.py وارفعها معه على GitHub
# 2) أو حط رابط مباشر للصورة هنا
TRANSFER_IMAGE_FILE = "transfer.jpg"
TRANSFER_IMAGE_URL = ""

# روم المصيدة: أي شخص (مو بوت) يكتب فيه يتبند وتنحذف رسائله
HONEYPOT_CHANNEL_ID = 1551986572646293665

intents = discord.Intents.default()
intents.message_content = True
intents.guilds = True
intents.messages = True

bot = commands.Bot(command_prefix="!", intents=intents, help_command=None)


def normalize(text: str) -> str:
    # يشيل المسافات والتشكيل البسيط حتى لو العميل كتب " تحويل " يرد عليه
    t = (text or "").strip()
    t = t.replace("ـ", "")  # يشيل التطويل
    t = " ".join(t.split())  # يوحد المسافات
    return t


async def safe_reply(message: discord.Message, text: str):
    # reply يحتاج صلاحية Read Message History، لو فشل نرسل رسالة عادية
    try:
        await message.reply(text)
    except discord.Forbidden:
        log.warning("No permission to reply, sending plain message in %s", message.channel)
        await message.channel.send(f"{message.author.mention}\n{text}")
    except discord.HTTPException as e:
        log.error("Failed to send message: %s", e)
        await message.channel.send(f"{message.author.mention}\n{text}")


@bot.event
async def on_ready():
    log.info("Logged in as %s (id=%s)", bot.user, bot.user.id)
    log.info("Connected to %d guild(s)", len(bot.guilds))
    for g in bot.guilds:
        log.info(" - Guild: %s (id=%s)", g.name, g.id)


@bot.event
async def on_disconnect():
    log.warning("Disconnected from Discord gateway")


@bot.event
async def on_resumed():
    log.info("Session resumed")


@bot.event
async def on_error(event, *args, **kwargs):
    log.exception("Error in event %s", event)


async def send_transfer(message: discord.Message):
    # يرسل نص التحويل + الصورة (ملف محلي أولاً، ثم رابط، ثم نص فقط)
    try:
        if os.path.isfile(TRANSFER_IMAGE_FILE):
            try:
                await message.reply(TRANSFER_MESSAGE, file=discord.File(TRANSFER_IMAGE_FILE))
            except discord.Forbidden:
                await message.channel.send(
                    f"{message.author.mention}\n{TRANSFER_MESSAGE}",
                    file=discord.File(TRANSFER_IMAGE_FILE),
                )
        elif TRANSFER_IMAGE_URL:
            embed = discord.Embed(description=TRANSFER_MESSAGE)
            embed.set_image(url=TRANSFER_IMAGE_URL)
            try:
                await message.reply(embed=embed)
            except discord.Forbidden:
                await message.channel.send(f"{message.author.mention}", embed=embed)
        else:
            await safe_reply(message, TRANSFER_MESSAGE)
    except Exception:
        log.exception("Failed to send transfer message")
        await safe_reply(message, TRANSFER_MESSAGE)


async def handle_honeypot(message: discord.Message):
    # حذف رسالته + باند مع حذف كل رسائله بآخر 7 أيام من كل السيرفر
    member = message.author
    guild = message.guild
    try:
        try:
            await message.delete()
        except (discord.NotFound, discord.Forbidden):
            pass
        await guild.ban(
            member,
            reason="Honeypot: كتب في روم الحماية",
            delete_message_seconds=7 * 24 * 3600,
        )
        log.warning("HONEYPOT banned %s (id=%s)", member, member.id)
    except discord.Forbidden:
        log.error("HONEYPOT failed: missing Ban Members permission or role hierarchy for %s", member)
    except Exception:
        log.exception("HONEYPOT ban failed")


@bot.event
async def on_message(message: discord.Message):
    try:
        if message.author == bot.user:
            return
        if message.author.bot:
            return  # يتجاهل البوتات الثانية (بوت التكتات) عشان ما يعلق

        # المصيدة أولاً: تنطبق على هذا الروم فقط
        if message.guild is not None and message.channel.id == HONEYPOT_CHANNEL_ID:
            await handle_honeypot(message)
            return

        content = normalize(message.content)

        if content == "تحويل":
            log.info("Reply TRANSFER to %s in #%s guild=%s", message.author, getattr(message.channel, "name", "?"), getattr(message.guild, "name", "DM"))
            await send_transfer(message)
        elif content == "دفع":
            log.info("Reply PAYMENT to %s in #%s guild=%s", message.author, getattr(message.channel, "name", "?"), getattr(message.guild, "name", "DM"))
            await safe_reply(message, PAYMENT_MESSAGE)

        await bot.process_commands(message)
    except Exception:
        log.exception("Exception in on_message")


# --- Keep-alive web server (for Render + cron-job.org) ---
app = Flask(__name__)

@app.route("/")
def home():
    return "Bot is alive!", 200

@app.route("/health")
def health():
    return "OK", 200

def run_web():
    port = int(os.getenv("PORT", 10000))
    # use_reloader=False مهم عشان ما يشتغل سيرفرين
    app.run(host="0.0.0.0", port=port, use_reloader=False)

if __name__ == "__main__":
    if not TOKEN or TOKEN == "YOUR_BOT_TOKEN_HERE":
        raise SystemExit("TOKEN ناقص! حط التوكن في DISCORD_TOKEN أو داخل الملف")
    threading.Thread(target=run_web, daemon=True).start()
    log.info("Keep-alive web server started")
    bot.run(TOKEN, reconnect=True)
