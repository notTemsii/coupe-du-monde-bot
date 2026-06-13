import discord
import asyncio
import os
import requests
from datetime import datetime, timezone, timedelta

# ─── CONFIG (variables d'environnement Railway) ────────────────────────────────
DISCORD_TOKEN = os.environ["DISCORD_TOKEN"]
CHANNEL_ID    = int(os.environ["CHANNEL_ID"])
ICS_URL       = os.environ.get("ICS_URL", "https://pub.fotmob.com/prod/pub/api/v2/calendar/league/77.ics")
POST_HOUR     = int(os.environ.get("POST_HOUR", "5"))
POST_MINUTE   = int(os.environ.get("POST_MINUTE", "0"))
PARIS         = timezone(timedelta(hours=2))
# ──────────────────────────────────────────────────────────────────────────────

JOURS_FR = ["Lundi","Mardi","Mercredi","Jeudi","Vendredi","Samedi","Dimanche"]
MOIS_FR  = ["","Janvier","Février","Mars","Avril","Mai","Juin","Juillet",
             "Août","Septembre","Octobre","Novembre","Décembre"]

intents = discord.Intents.default()
intents.message_content = True
client  = discord.Client(intents=intents)


def parse_dt(s: str) -> datetime:
    dt = datetime(int(s[0:4]), int(s[4:6]), int(s[6:8]),
                  int(s[9:11]), int(s[11:13]), int(s[13:15]),
                  tzinfo=timezone.utc)
    return dt.astimezone(PARIS)


def get_matches_today() -> list[dict]:
    resp = requests.get(ICS_URL, timeout=10)
    resp.raise_for_status()
    today   = datetime.now(PARIS).date()
    matches = []
    current = {}
    for line in resp.text.splitlines():
        line = line.strip()
        if line == "BEGIN:VEVENT":
            current = {}
        elif line.startswith("DTSTART:"):
            current["start"] = line[8:]
        elif line.startswith("SUMMARY:"):
            current["summary"] = line[8:]
        elif line == "END:VEVENT":
            if "start" in current and "summary" in current:
                try:
                    dt = parse_dt(current["start"])
                    if dt.date() == today:
                        summary = current["summary"]
                        if "(" in summary:
                            summary = summary[:summary.rfind("(")].strip()
                        matches.append({"dt": dt, "match": summary})
                except Exception:
                    pass
            current = {}
    matches.sort(key=lambda m: m["dt"])
    return matches


def build_message(matches: list[dict]) -> str:
    now      = datetime.now(PARIS)
    date_str = f"{JOURS_FR[now.weekday()]} {now.day} {MOIS_FR[now.month]} {now.year}"
    if not matches:
        return f"⚽ **Coupe du Monde 2026 — {date_str}**\n\nPas de match prévu aujourd'hui. 😴"
    lines = [f"⚽ **Coupe du Monde 2026 — {date_str}**\n"]
    for m in matches:
        lines.append(f"🕐 **{m['dt'].strftime('%Hh%M')}** — {m['match']}")
    lines.append(f"\n_Horaires en heure française · {len(matches)} match(s) au programme_")
    return "\n".join(lines)


async def post_daily_matches():
    await client.wait_until_ready()
    channel = client.get_channel(CHANNEL_ID)
    while not client.is_closed():
        now       = datetime.now(PARIS)
        next_post = now.replace(hour=POST_HOUR, minute=POST_MINUTE, second=0, microsecond=0)
        if now >= next_post:
            next_post += timedelta(days=1)
        await asyncio.sleep((next_post - now).total_seconds())
        try:
            matches = get_matches_today()
            await channel.send(build_message(matches))
            print(f"[BOT] ✅ Message envoyé ({len(matches)} matchs)")
        except Exception as e:
            print(f"[BOT] ❌ Erreur : {e}")
        await asyncio.sleep(61)


@client.event
async def on_ready():
    print(f"[BOT] Connecté : {client.user}")
    client.loop.create_task(post_daily_matches())


@client.event
async def on_message(message):
    if message.author == client.user:
        return
    if message.content.strip().lower() == "!matchs":
        try:
            matches = get_matches_today()
            await message.channel.send(build_message(matches))
        except Exception as e:
            await message.channel.send(f"❌ Erreur : {e}")


client.run(DISCORD_TOKEN)
