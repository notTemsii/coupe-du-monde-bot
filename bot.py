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
client  = discord.Client(intents=intents)

# Garde en mémoire les rappels déjà envoyés pour éviter les doublons
rappels_envoyes = set()


def parse_dt(s: str) -> datetime:
    dt = datetime(int(s[0:4]), int(s[4:6]), int(s[6:8]),
                  int(s[9:11]), int(s[11:13]), int(s[13:15]),
                  tzinfo=timezone.utc)
    return dt.astimezone(PARIS)


def get_journee_cdm() -> tuple[datetime, datetime]:
    now = datetime.now(PARIS)
    if now.hour < 6 or (now.hour == 6 and now.minute == 0):
        debut = now.replace(hour=6, minute=1, second=0, microsecond=0) - timedelta(days=1)
    else:
        debut = now.replace(hour=6, minute=1, second=0, microsecond=0)
    fin = debut + timedelta(hours=24)
    return debut, fin


def get_all_matches() -> list[dict]:
    """Récupère tous les matchs du calendrier."""
    resp = requests.get(ICS_URL, timeout=10)
    resp.raise_for_status()
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
        elif line.startswith("UID:"):
            current["uid"] = line[4:]
        elif line == "END:VEVENT":
            if "start" in current and "summary" in current:
                try:
                    dt = parse_dt(current["start"])
                    summary = current["summary"]
                    if "(" in summary:
                        summary = summary[:summary.rfind("(")].strip()
                    matches.append({
                        "dt":      dt,
                        "match":   summary,
                        "uid":     current.get("uid", str(dt))
                    })
                except Exception:
                    pass
            current = {}
    matches.sort(key=lambda m: m["dt"])
    return matches


def get_matches_journee() -> list[dict]:
    """Matchs de la journée CDM courante."""
    now        = datetime.now(PARIS)
    debut, fin = get_journee_cdm()
    all_m      = get_all_matches()
    return [
        {**m, "passe": m["dt"] < now}
        for m in all_m
        if debut <= m["dt"] <= fin
    ]


def build_embed(matches: list[dict]) -> tuple[str, discord.Embed]:
    now      = datetime.now(PARIS)
    debut, _ = get_journee_cdm()
    jour     = JOURS_FR[debut.weekday()]
    date_str = f"{jour} {debut.day} {MOIS_FR[debut.month]} {debut.year}"
    a_venir  = [m for m in matches if not m["passe"]]

    embed = discord.Embed(
        title=f"⚽ Coupe du Monde 2026 — {date_str}",
        color=0x2ECC71
    )

    if not matches or not a_venir:
        embed.description = "Pas de match à venir aujourd'hui. 😴"
    else:
        lignes = "\n".join(f"🕐 **{m['dt'].strftime('%Hh%M')}** — {m['match']}" for m in a_venir)
        embed.description = lignes
        embed.set_footer(text=f"Horaires en heure française · {len(a_venir)} match(s) à venir")

    return f"<@&{ROLE_ID}>", embed


def build_rappel_embed(match: dict) -> tuple[str, discord.Embed]:
    embed = discord.Embed(
        title="⏰ Match dans 30 minutes !",
        description=f"**{match['match']}**\n🕐 Coup d'envoi à **{match['dt'].strftime('%Hh%M')}** (heure française)",
        color=0xE67E22  # orange
    )
    return f"<@&{ROLE_ID}>", embed


async def post_daily_matches():
    """Envoie le récap quotidien à l'heure configurée."""
    await client.wait_until_ready()
    channel = client.get_channel(CHANNEL_ID)
    while not client.is_closed():
        now       = datetime.now(PARIS)
        next_post = now.replace(hour=POST_HOUR, minute=POST_MINUTE, second=0, microsecond=0)
        if now >= next_post:
            next_post += timedelta(days=1)
        await asyncio.sleep((next_post - now).total_seconds())
        try:
            matches     = get_matches_journee()
            ping, embed = build_embed(matches)
            await channel.send(content=ping, embed=embed)
            print(f"[BOT] ✅ Récap quotidien envoyé")
        except Exception as e:
            print(f"[BOT] ❌ Erreur récap : {e}")
        await asyncio.sleep(61)


async def check_rappels():
    """Vérifie toutes les minutes s'il faut envoyer un rappel 30 min avant un match."""
    await client.wait_until_ready()
    channel = client.get_channel(CHANNEL_ID)
    while not client.is_closed():
        now = datetime.now(PARIS)
        try:
            matches = get_all_matches()
            for m in matches:
                rappel_dt = m["dt"] - timedelta(minutes=30)
                uid_rappel = f"rappel_{m['uid']}"
                # Envoie le rappel si on est dans la fenêtre 30min avant (±1 minute)
                diff = (now - rappel_dt).total_seconds()
                if 0 <= diff <= 60 and uid_rappel not in rappels_envoyes:
                    ping, embed = build_rappel_embed(m)
                    await channel.send(content=ping, embed=embed)
                    rappels_envoyes.add(uid_rappel)
                    print(f"[BOT] 🔔 Rappel envoyé : {m['match']}")
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
            matches     = get_matches_journee()
            ping, embed = build_embed(matches)
            await message.channel.send(content=ping, embed=embed)
        except Exception as e:
            await message.channel.send(f"❌ Erreur : {e}")


client.run(DISCORD_TOKEN)
