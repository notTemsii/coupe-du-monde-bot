import discord
import asyncio
import os
import requests
from datetime import datetime, timezone, timedelta

# ─── CONFIG ───────────────────────────────────────────────────────────────────
DISCORD_TOKEN  = os.environ["DISCORD_TOKEN"]
CHANNEL_ID     = int(os.environ["CHANNEL_ID"])
ICS_URL        = os.environ.get("ICS_URL", "https://pub.fotmob.com/prod/pub/api/v2/calendar/league/77.ics")
RAPIDAPI_KEY   = os.environ["RAPIDAPI_KEY"]
POST_HOUR      = int(os.environ.get("POST_HOUR", "6"))
POST_MINUTE    = int(os.environ.get("POST_MINUTE", "0"))
ROLE_ID        = 1515376252414853211
PARIS          = timezone(timedelta(hours=2))
CDM_TOURNAMENT = 16
RAPIDAPI_HOST  = "sofascore.p.rapidapi.com"
# ──────────────────────────────────────────────────────────────────────────────

JOURS_FR = ["Lundi","Mardi","Mercredi","Jeudi","Vendredi","Samedi","Dimanche"]
MOIS_FR  = ["","Janvier","Février","Mars","Avril","Mai","Juin","Juillet",
             "Août","Septembre","Octobre","Novembre","Décembre"]

intents = discord.Intents.default()
intents.message_content = True
client = discord.Client(intents=intents)

rappels_envoyes = set()
scores_precedents = {}  # {match_id: (home_score, away_score)}
fins_envoyes = set()


# ─── ICS ──────────────────────────────────────────────────────────────────────

def parse_dt(s):
    dt = datetime(int(s[0:4]), int(s[4:6]), int(s[6:8]),
                  int(s[9:11]), int(s[11:13]), int(s[13:15]),
                  tzinfo=timezone.utc)
    return dt.astimezone(PARIS)


def get_journee_cdm():
    now = datetime.now(PARIS)
    if now.hour < 6 or (now.hour == 6 and now.minute == 0):
        debut = now.replace(hour=6, minute=1, second=0, microsecond=0) - timedelta(days=1)
    else:
        debut = now.replace(hour=6, minute=1, second=0, microsecond=0)
    return debut, debut + timedelta(hours=24)


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


def get_matches_journee():
    now = datetime.now(PARIS)
    debut, fin = get_journee_cdm()
    return [{**m, "passe": m["dt"] < now} for m in get_all_matches_ics() if debut <= m["dt"] <= fin]


# ─── SOFASCORE ────────────────────────────────────────────────────────────────

def sofascore_get(endpoint, params={}):
    url = f"https://{RAPIDAPI_HOST}/{endpoint}"
    headers = {
        "x-rapidapi-host": RAPIDAPI_HOST,
        "x-rapidapi-key":  RAPIDAPI_KEY,
        "Content-Type":    "application/json",
    }
    resp = requests.get(url, headers=headers, params=params, timeout=10)
    resp.raise_for_status()
    return resp.json()


def get_live_cdm_matches():
    # Récupère les matchs live de la catégorie World (1468)
    data = sofascore_get("tournaments/get-live-events", {"categoryId": 1468})
    return [
        e for e in data.get("events", [])
        if e.get("tournament", {}).get("uniqueTournament", {}).get("id") == CDM_TOURNAMENT
    ]


def get_minute(match):
    """Calcule la minute approximative du match."""
    status = match.get("status", {}).get("description", "")
    time_data = match.get("time", {})
    status_time = match.get("statusTime", {})

    if "half" in match.get("status", {}).get("type", ""):
        initial = status_time.get("initial", 0)
        start_ts = status_time.get("timestamp", 0)
        extra = status_time.get("extra", 0)
        if start_ts:
            elapsed = int((datetime.now(timezone.utc).timestamp() - start_ts) + initial)
            minute = min(elapsed // 60, (initial + extra) // 60)
            return f"{minute}'"
    return status


# ─── EMBEDS ───────────────────────────────────────────────────────────────────

def build_embed_journee(matches):
    now = datetime.now(PARIS)
    debut, _ = get_journee_cdm()
    date_str = f"{JOURS_FR[debut.weekday()]} {debut.day} {MOIS_FR[debut.month]} {debut.year}"
    a_venir = [m for m in matches if not m["passe"]]

    embed = discord.Embed(title=f"⚽ Coupe du Monde 2026 — {date_str}", color=0x2ECC71)
    if not a_venir:
        embed.description = "Pas de match à venir aujourd'hui. 😴"
    else:
        embed.description = "\n".join(
            f"🕐 **{m['dt'].strftime('%Hh%M')}** — {m['match']}" for m in a_venir
        )
        embed.set_footer(text=f"Horaires en heure française · {len(a_venir)} match(s) à venir")
    return f"<@&{ROLE_ID}>", embed


def build_embed_rappel(match):
    embed = discord.Embed(
        title="⏰ Match dans 30 minutes !",
        description=f"**{match['match']}**\n🕐 Coup d'envoi à **{match['dt'].strftime('%Hh%M')}** (heure française)",
        color=0xE67E22
    )
    return f"<@&{ROLE_ID}>", embed


def build_embed_but(home, away, hs, as_, minute):
    embed = discord.Embed(
        title="⚽ BUT !",
        description=f"**{home} {hs} - {as_} {away}**\n\n🕐 {minute}",
        color=0xF1C40F
    )
    return embed


def build_embed_carton(home, away, joueur, team, couleur, minute):
    if couleur == "yellow":
        emoji, titre, color = "🟨", "Carton Jaune", 0xF1C40F
    elif couleur == "yellowRed":
        emoji, titre, color = "🟨🟥", "Double Carton Jaune", 0xFF6B00
    else:
        emoji, titre, color = "🟥", "Carton Rouge", 0xE74C3C
    embed = discord.Embed(
        title=f"{emoji} {titre} !",
        description=f"**{home} - {away}**\n\n{emoji} **{joueur}** ({team}) — {minute}",
        color=color
    )
    return embed


def build_embed_fin(home, away, hs, as_):
    if hs > as_:
        result = f"🏆 **{home}** remporte le match !"
    elif as_ > hs:
        result = f"🏆 **{away}** remporte le match !"
    else:
        result = "🤝 Match nul !"
    embed = discord.Embed(
        title="🔚 Fin du match !",
        description=f"**{home} {hs} - {as_} {away}**\n\n{result}",
        color=0x95A5A6
    )
    return embed


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
            matches = get_matches_journee()
            ping, embed = build_embed_journee(matches)
            await channel.send(content=ping, embed=embed)
            print("[BOT] ✅ Récap quotidien envoyé")
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


async def check_live_scores():
    """Détecte les buts via changement de score + cartons via incidents si dispo."""
    await client.wait_until_ready()
    channel = client.get_channel(CHANNEL_ID)

    while not client.is_closed():
        try:
            live_matches = get_live_cdm_matches()
            for match in live_matches:
                mid  = match["id"]
                home = match["homeTeam"]["name"]
                away = match["awayTeam"]["name"]
                hs   = match["homeScore"].get("current", 0)
                as_  = match["awayScore"].get("current", 0)
                status = match["status"]["type"]
                minute = get_minute(match)

                # Fin de match
                if status == "finished" and mid not in fins_envoyes:
                    embed = build_embed_fin(home, away, hs, as_)
                    await channel.send(embed=embed)
                    fins_envoyes.add(mid)
                    scores_precedents.pop(mid, None)
                    print(f"[BOT] 🔚 Fin : {home} {hs}-{as_} {away}")
                    continue

                if status != "inprogress":
                    continue

                # Détection but par changement de score
                prev = scores_precedents.get(mid)
                if prev is None:
                    scores_precedents[mid] = (hs, as_)
                    continue

                prev_hs, prev_as = prev
                if hs > prev_hs or as_ > prev_as:
                    embed = build_embed_but(home, away, hs, as_, minute)
                    await channel.send(embed=embed)
                    print(f"[BOT] ⚽ But détecté : {home} {hs}-{as_} {away} {minute}")

                scores_precedents[mid] = (hs, as_)

        except Exception as e:
            print(f"[BOT] ❌ Erreur live : {e}")

        await asyncio.sleep(60)


@client.event
async def on_ready():
    print(f"[BOT] Connecté : {client.user}")
    client.loop.create_task(post_daily_matches())
    client.loop.create_task(check_rappels())
    client.loop.create_task(check_live_scores())


@client.event
async def on_message(message):
    if message.author == client.user:
        return
    if message.content.strip().lower() == "!matchs":
        try:
            matches = get_matches_journee()
            ping, embed = build_embed_journee(matches)
            await message.channel.send(content=ping, embed=embed)
        except Exception as e:
            await message.channel.send(f"❌ Erreur : {e}")


client.run(DISCORD_TOKEN)
