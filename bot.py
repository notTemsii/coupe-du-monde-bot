import discord
import asyncio
import os
import requests
from datetime import datetime, timezone, timedelta

# ─── CONFIG ───────────────────────────────────────────────────────────────────
DISCORD_TOKEN = os.environ["DISCORD_TOKEN"]
CHANNEL_ID    = int(os.environ["CHANNEL_ID"])
ICS_URL       = os.environ.get("ICS_URL", "https://pub.fotmob.com/prod/pub/api/v2/calendar/league/77.ics")
POST_HOUR     = int(os.environ.get("POST_HOUR", "6"))
POST_MINUTE   = int(os.environ.get("POST_MINUTE", "0"))
ROLE_ID       = 1515376252414853211
PARIS         = timezone(timedelta(hours=2))
# ──────────────────────────────────────────────────────────────────────────────

JOURS_FR = ["Lundi","Mardi","Mercredi","Jeudi","Vendredi","Samedi","Dimanche"]
MOIS_FR  = ["","Janvier","Février","Mars","Avril","Mai","Juin","Juillet",
             "Août","Septembre","Octobre","Novembre","Décembre"]

intents = discord.Intents.default()
intents.message_content = True
client = discord.Client(intents=intents)

rappels_envoyes = set()


# ─── ICS ──────────────────────────────────────────────────────────────────────

def parse_dt(s):
    dt = datetime(int(s[0:4]), int(s[4:6]), int(s[6:8]),
                  int(s[9:11]), int(s[11:13]), int(s[13:15]),
                  tzinfo=timezone.utc)
    return dt.astimezone(PARIS)


def get_all_matches_ics():
    resp = requests.get(ICS_URL, timeout=10)
    resp.raise_for_status()
    matches, current = [], {}
    for line in resp.text.splitlines():
        line = line.strip()
        if line == "BEGIN:VEVENT":
            current = {}
        elif line.startswith("DTSTART:"):
            current["start"] = line[8:]
        elif line.startswith("SUMMARY:"):
            current["summary"] = line[8:]
        elif line.startswith("UID:"):
            current["uid"] = line[4:]
        elif line == "END:VEVENT":
            if "start" in current and "summary" in current:
                try:
                    dt = parse_dt(current["start"])
                    summary = current["summary"]
                    if "(" in summary:
                        summary = summary[:summary.rfind("(")].strip()
                    matches.append({"dt": dt, "match": summary, "uid": current.get("uid", str(dt))})
                except Exception:
                    pass
            current = {}
    matches.sort(key=lambda m: m["dt"])
    return matches


def get_matches_du_jour(reference: datetime):
    """
    Retourne tous les matchs du jour civil (minuit → minuit)
    basé sur la date de référence, filtrés à venir uniquement.
    """
    now = datetime.now(PARIS)
    jour = reference.date()
    matchs = [m for m in get_all_matches_ics() if m["dt"].date() == jour]
    # Pour le message du matin : on montre TOUS les matchs du jour (pas encore passés)
    return [m for m in matchs if m["dt"] >= reference]


# ─── EMBEDS ───────────────────────────────────────────────────────────────────

def build_embed_journee(matches, reference):
    jour     = JOURS_FR[reference.weekday()]
    date_str = f"{jour} {reference.day} {MOIS_FR[reference.month]} {reference.year}"

    embed = discord.Embed(title=f"⚽ Coupe du Monde 2026 — {date_str}", color=0x2ECC71)
    if not matches:
        embed.description = "Pas de match prévu aujourd'hui. 😴"
    else:
        embed.description = "\n".join(
            f"🕐 **{m['dt'].strftime('%Hh%M')}** — {m['match']}" for m in matches
        )
        embed.set_footer(text=f"Horaires en heure française · {len(matches)} match(s) au programme")
    return f"<@&{ROLE_ID}>", embed


def build_embed_rappel(match):
    embed = discord.Embed(
        title="⏰ Match dans 30 minutes !",
        description=f"**{match['match']}**\n🕐 Coup d'envoi à **{match['dt'].strftime('%Hh%M')}** (heure française)",
        color=0xE67E22
    )
    return f"<@&{ROLE_ID}>", embed


# ─── TÂCHES ───────────────────────────────────────────────────────────────────

async def post_daily_matches():
    await client.wait_until_ready()
    channel = client.get_channel(CHANNEL_ID)
    while not client.is_closed():
        now = datetime.now(PARIS)
        next_post = now.replace(hour=POST_HOUR, minute=POST_MINUTE, second=0, microsecond=0)
        if now >= next_post:
            next_post += timedelta(days=1)
        await asyncio.sleep((next_post - now).total_seconds())

        try:
            # On prend la date du jour au moment de l'envoi
            ref = datetime.now(PARIS)
            matches = get_matches_du_jour(ref.replace(hour=0, minute=0, second=0, microsecond=0))
            ping, embed = build_embed_journee(matches, ref)
            await channel.send(content=ping, embed=embed)
            print(f"[BOT] ✅ Récap envoyé ({len(matches)} matchs)")
        except Exception as e:
            print(f"[BOT] ❌ Erreur récap : {e}")
        await asyncio.sleep(61)


async def check_rappels():
    await client.wait_until_ready()
    channel = client.get_channel(CHANNEL_ID)
    while not client.is_closed():
        now = datetime.now(PARIS)
        try:
            for m in get_all_matches_ics():
                rappel_dt = m["dt"] - timedelta(minutes=30)
                uid = f"rappel_{m['uid']}"
                diff = (now - rappel_dt).total_seconds()
                if 0 <= diff <= 60 and uid not in rappels_envoyes:
                    ping, embed = build_embed_rappel(m)
                    await channel.send(content=ping, embed=embed)
                    rappels_envoyes.add(uid)
                    print(f"[BOT] 🔔 Rappel : {m['match']}")
        except Exception as e:
            print(f"[BOT] ❌ Erreur rappel : {e}")
        await asyncio.sleep(60)


@client.event
async def on_ready():
    print(f"[BOT] Connecté : {client.user}")
    client.loop.create_task(post_daily_matches())
    client.loop.create_task(check_rappels())


@client.event
async def on_message(message):
    if message.author == client.user:
        return
    if message.content.strip().lower() == "!matchs":
        try:
            ref = datetime.now(PARIS)
            matches = get_matches_du_jour(ref)
            ping, embed = build_embed_journee(matches, ref)
            await message.channel.send(content=ping, embed=embed)
        except Exception as e:
            await message.channel.send(f"❌ Erreur : {e}")


client.run(DISCORD_TOKEN)
