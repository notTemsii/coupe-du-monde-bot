import discord
import asyncio
import os
import requests
from datetime import datetime, timezone, timedelta

# ─── CONFIG ───────────────────────────────────────────────────────────────────
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


def get_journee_cdm() -> tuple[datetime, datetime]:
    """
    Retourne le début et la fin de la 'journée CDM' courante.
    La journée CDM commence à 6h01 et se termine à 6h00 le lendemain.
    Ex: le 13/06 à 21h → journée du 13/06 (6h01) au 14/06 (6h00)
        le 14/06 à 3h  → journée du 13/06 (6h01) au 14/06 (6h00)
    """
    now = datetime.now(PARIS)
    # Si on est entre minuit et 6h00, la journée CDM a commencé la veille
    if now.hour < 6 or (now.hour == 6 and now.minute == 0):
        debut = now.replace(hour=6, minute=1, second=0, microsecond=0) - timedelta(days=1)
    else:
        debut = now.replace(hour=6, minute=1, second=0, microsecond=0)
    fin = debut + timedelta(hours=24)
    return debut, fin


def get_matches_journee() -> list[dict]:
    """Récupère tous les matchs de la journée CDM, uniquement ceux à venir."""
    resp = requests.get(ICS_URL, timeout=10)
    resp.raise_for_status()

    now           = datetime.now(PARIS)
    debut, fin    = get_journee_cdm()
    matches       = []
    current       = {}

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
                    if debut <= dt <= fin:
                        summary = current["summary"]
                        if "(" in summary:
                            summary = summary[:summary.rfind("(")].strip()
                        matches.append({"dt": dt, "match": summary, "passe": dt < now})
                except Exception:
                    pass
            current = {}

    matches.sort(key=lambda m: m["dt"])
    return matches


def build_message(matches: list[dict]) -> str:
    now        = datetime.now(PARIS)
    debut, _   = get_journee_cdm()
    jour       = JOURS_FR[debut.weekday()]
    date_str   = f"{jour} {debut.day} {MOIS_FR[debut.month]} {debut.year}"

    # Filtrer uniquement les matchs à venir
    a_venir = [m for m in matches if not m["passe"]]

    if not matches:
        return f"⚽ **Coupe du Monde 2026 — {date_str}**\n\nPas de match prévu aujourd'hui. 😴"

    if not a_venir:
        return f"⚽ **Coupe du Monde 2026 — {date_str}**\n\nTous les matchs du jour sont terminés. ✅"

    lines = [f"<@&1515376252414853211>\n⚽ **Coupe du Monde 2026 — {date_str}**\n"]
    for m in a_venir:
        lines.append(f"🕐 **{m['dt'].strftime('%Hh%M')}** — {m['match']}")
    lines.append(f"\n_Horaires en heure française · {len(a_venir)} match(s) à venir_")
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
            matches = get_matches_journee()
            await channel.send(build_message(matches))
            print(f"[BOT] ✅ Message envoyé ({len([m for m in matches if not m['passe']])} matchs à venir)")
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
            matches = get_matches_journee()
            await message.channel.send(build_message(matches))
        except Exception as e:
            await message.channel.send(f"❌ Erreur : {e}")


client.run(DISCORD_TOKEN)
