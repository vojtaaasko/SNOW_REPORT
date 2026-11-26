import json
import logging
import os
import sqlite3
import time
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import requests
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")

TOKEN = os.getenv("TELEGRAM_TOKEN", "").strip()
TZ = ZoneInfo("Europe/Prague")
POLL_SECONDS = int(os.getenv("POLL_SECONDS", "600"))
FORECAST_MIN_HOURS = int(os.getenv("FORECAST_MIN_HOURS", "3"))
FORECAST_MAX_HOURS = int(os.getenv("FORECAST_MAX_HOURS", "12"))
SNOW_THRESHOLD_CM = float(os.getenv("SNOW_THRESHOLD_CM", "0.1"))
CAMERA_TIMEOUT = int(os.getenv("CAMERA_TIMEOUT", "20"))

DATA_DIR = BASE_DIR / "data"
SNAPSHOT_DIR = BASE_DIR / "snapshots"
DB_PATH = DATA_DIR / "snow_alert.sqlite3"
CAMERAS_PATH = BASE_DIR / "cameras.json"

LOCATIONS = {
    "Jičín": {"latitude": 50.437, "longitude": 15.352},
    "Vrchlabí": {"latitude": 50.626, "longitude": 15.610},
    "Špindlerův Mlýn": {"latitude": 50.726, "longitude": 15.609},
}

API_URL = "https://api.open-meteo.com/v1/forecast"
TELEGRAM_API = f"https://api.telegram.org/bot{TOKEN}"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[logging.StreamHandler()],
)
log = logging.getLogger("snow-alert")
session = requests.Session()
session.headers.update({"User-Agent": "SNOW-ALERT/0.1 (personal weather notifier)"})


def db():
    DATA_DIR.mkdir(exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS sent_alerts (
            alert_key TEXT PRIMARY KEY,
            sent_at TEXT NOT NULL
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS camera_checks (
            camera_id TEXT PRIMARY KEY,
            checked_at TEXT NOT NULL,
            status TEXT NOT NULL,
            detail TEXT
        )
    """)
    conn.commit()
    return conn


def setting(key):
    with db() as conn:
        row = conn.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
        return row[0] if row else None


def set_setting(key, value):
    with db() as conn:
        conn.execute(
            "INSERT INTO settings(key,value) VALUES(?,?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, str(value)),
        )


def telegram(method, payload=None, files=None):
    if not TOKEN:
        raise RuntimeError("Chybí TELEGRAM_TOKEN v souboru .env")
    response = session.post(
        f"{TELEGRAM_API}/{method}",
        data=payload or {},
        files=files,
        timeout=30,
    )
    response.raise_for_status()
    data = response.json()
    if not data.get("ok"):
        raise RuntimeError(f"Telegram API: {data}")
    return data["result"]


def owner_chat_id():
    return setting("owner_chat_id") or os.getenv("TELEGRAM_CHAT_ID", "").strip() or None


def send_message(text):
    chat_id = owner_chat_id()
    if not chat_id:
        log.info("Zpráva nebyla odeslána: nejdřív napiš botovi /start.")
        return
    telegram("sendMessage", {"chat_id": chat_id, "text": text})


def send_photo(path, caption):
    chat_id = owner_chat_id()
    if not chat_id:
        return
    with open(path, "rb") as photo:
        telegram("sendPhoto", {"chat_id": chat_id, "caption": caption},
                 files={"photo": photo})


def get_weather(location_name, coords):
    params = {
        "latitude": coords["latitude"],
        "longitude": coords["longitude"],
        "hourly": (
            "temperature_2m,snowfall,precipitation_probability,"
            "snowfall_probability,snow_depth,weather_code"
        ),
        "current": "temperature_2m,snowfall,precipitation,weather_code",
        "forecast_days": 2,
        "timezone": "Europe/Prague",
    }
    response = session.get(API_URL, params=params, timeout=25)
    response.raise_for_status()
    return response.json()


def already_sent(key):
    with db() as conn:
        return conn.execute(
            "SELECT 1 FROM sent_alerts WHERE alert_key=?", (key,)
        ).fetchone() is not None


def mark_sent(key):
    with db() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO sent_alerts(alert_key,sent_at) VALUES(?,?)",
            (key, datetime.now(TZ).isoformat()),
        )


def check_forecasts():
    now = datetime.now(TZ)
    for name, coords in LOCATIONS.items():
        try:
            data = get_weather(name, coords)
            hourly = data["hourly"]
            times = hourly["time"]
            for i, time_string in enumerate(times):
                forecast_time = datetime.fromisoformat(time_string).replace(tzinfo=TZ)
                hours_ahead = (forecast_time - now).total_seconds() / 3600
                if not FORECAST_MIN_HOURS <= hours_ahead <= FORECAST_MAX_HOURS:
                    continue

                snowfall = hourly.get("snowfall", [None] * len(times))[i]
                temp = hourly.get("temperature_2m", [None] * len(times))[i]
                prob = hourly.get("snowfall_probability", [None] * len(times))[i]
                if prob is None:
                    prob = hourly.get("precipitation_probability", [None] * len(times))[i]

                # Snowfall is provided by Open-Meteo in cm for hourly forecasts.
                if snowfall is None or snowfall < SNOW_THRESHOLD_CM:
                    continue

                alert_key = f"forecast:{name}:{time_string}"
                if already_sent(alert_key):
                    continue

                message = (
                    f"❄️ SNOW ALERT – PŘEDPOVĚĎ\n\n"
                    f"📍 {name}\n"
                    f"🕒 Očekávaný začátek: {forecast_time:%d.%m. %H:%M}\n"
                    f"⏳ Přibližně za {hours_ahead:.0f} hodin\n"
                    f"🌨 Předpověď sněžení: {snowfall:.1f} cm/h\n"
                    f"🌡 Teplota: {temp if temp is not None else 'neznámá'} °C\n"
                    f"🎯 Pravděpodobnost: {prob if prob is not None else 'neuvedena'} %\n\n"
                    f"Jde o předpověď, nikoli potvrzení stavu vozovky."
                )
                send_message(message)
                mark_sent(alert_key)

            current = data.get("current", {})
            current_snow = current.get("snowfall")
            if current_snow is not None and current_snow >= SNOW_THRESHOLD_CM:
                hour_key = now.strftime("%Y-%m-%d-%H")
                alert_key = f"current:{name}:{hour_key}"
                if not already_sent(alert_key):
                    send_message(
                        f"🌨️ SNOW ALERT – MOŽNÉ AKTUÁLNÍ SNĚŽENÍ\n\n"
                        f"📍 {name}\n"
                        f"❄️ Aktuální údaj modelu: {current_snow} cm/h\n"
                        f"🌡 Teplota: {current.get('temperature_2m', '—')} °C\n\n"
                        f"Nejde o přímé pozorování silnice. Ověř stav kamerou."
                    )
                    mark_sent(alert_key)

        except Exception:
            log.exception("Chyba při kontrole počasí: %s", name)


def load_cameras():
    if not CAMERAS_PATH.exists():
        return []
    with CAMERAS_PATH.open(encoding="utf-8") as f:
        return json.load(f)


def check_cameras(notify=False):
    cameras = load_cameras()
    if not cameras:
        return "Zatím nejsou nakonfigurované žádné přímé URL snímků kamer."
    results = []
    for camera in cameras:
        camera_id = camera.get("id", "unknown")
        image_url = (camera.get("image_url") or "").strip()
        if not image_url:
            results.append(f"⚪ {camera.get('name', camera_id)} – chybí přímá URL snímku")
            continue
        try:
            response = session.get(image_url, timeout=CAMERA_TIMEOUT, stream=True)
            response.raise_for_status()
            content_type = response.headers.get("Content-Type", "")
            if not content_type.startswith("image/"):
                raise ValueError(f"URL nevrací obrázek (Content-Type: {content_type})")
            content = response.content
            if len(content) < 1000:
                raise ValueError("Snímek je podezřele malý")
            suffix = ".jpg" if "jpeg" in content_type else ".png"
            SNAPSHOT_DIR.mkdir(exist_ok=True)
            path = SNAPSHOT_DIR / f"{camera_id}_{datetime.now(TZ):%Y%m%d_%H%M%S}{suffix}"
            path.write_bytes(content)
            with db() as conn:
                conn.execute(
                    "INSERT INTO camera_checks(camera_id,checked_at,status,detail) "
                    "VALUES(?,?,?,?) ON CONFLICT(camera_id) DO UPDATE SET "
                    "checked_at=excluded.checked_at,status=excluded.status,detail=excluded.detail",
                    (camera_id, datetime.now(TZ).isoformat(), "OK", content_type),
                )
            results.append(f"🟢 {camera.get('name', camera_id)} – snímek dostupný")
            if notify:
                send_photo(path, f"📷 {camera.get('name', camera_id)}")
        except Exception as exc:
            log.warning("Kamera %s: %s", camera_id, exc)
            with db() as conn:
                conn.execute(
                    "INSERT INTO camera_checks(camera_id,checked_at,status,detail) "
                    "VALUES(?,?,?,?) ON CONFLICT(camera_id) DO UPDATE SET "
                    "checked_at=excluded.checked_at,status=excluded.status,detail=excluded.detail",
                    (camera_id, datetime.now(TZ).isoformat(), "ERROR", str(exc)),
                )
            results.append(f"🔴 {camera.get('name', camera_id)} – chyba: {exc}")
    return "\n".join(results)


def status_text():
    lines = ["❄️ SNOW ALERT – STATUS"]
    for name, coords in LOCATIONS.items():
        try:
            data = get_weather(name, coords)
            current = data.get("current", {})
            lines.append(
                f"\n📍 {name}\n"
                f"🌡 {current.get('temperature_2m', '—')} °C\n"
                f"🌨 Sněžení dle modelu: {current.get('snowfall', '—')} cm/h"
            )
        except Exception as exc:
            lines.append(f"\n📍 {name}: chyba načtení ({exc})")
    return "\n".join(lines)


def help_text():
    return (
        "❄️ SNOW ALERT – příkazy\n\n"
        "/start – registrace a úvod\n"
        "/status – aktuální počasí v lokalitách\n"
        "/forecast – kontrola předpovědi na 3–12 hodin\n"
        "/cameras – dostupnost nakonfigurovaných kamer\n"
        "/help – tato nápověda\n\n"
        "Kamery bez přímé veřejné URL snímku nelze automaticky stahovat."
    )


def handle_updates():
    offset = int(setting("telegram_offset") or "0")
    # GitHub Actions uses short scheduled runs, not a permanent long-polling process.
    updates = telegram("getUpdates", {"offset": offset, "timeout": 0})
    for update in updates:
        update_id = update["update_id"]
        message = update.get("message") or update.get("edited_message")
        if not message or not message.get("text"):
            set_setting("telegram_offset", update_id + 1)
            continue

        chat_id = str(message["chat"]["id"])
        text = message["text"].strip().split()[0]

        registered = owner_chat_id()
        if not registered and text == "/start":
            set_setting("owner_chat_id", chat_id)
            send_message(
                "✅ SNOW ALERT je propojen!\n\n"
                "Sleduji předpověď pro Jičín, Vrchlabí a Špindlerův Mlýn.\n"
                "Kamery přidáme po ověření přímých URL snímků.\n\n" + help_text()
            )
        elif registered and chat_id == str(registered):
            if text == "/start" or text == "/help":
                send_message(help_text())
            elif text == "/status":
                send_message(status_text())
            elif text == "/forecast":
                send_message("🔍 Kontroluji předpověď na 3–12 hodin...")
                check_forecasts()
                send_message("✅ Kontrola předpovědi dokončena.")
            elif text == "/cameras":
                send_message("📷 STAV KAMER\n\n" + check_cameras())
            else:
                send_message("Neznámý příkaz. Použij /help.")
        else:
            # Bot is private to the first chat that registers it.
            log.warning("Ignoruji zprávu z neautorizovaného chatu %s", chat_id)

        set_setting("telegram_offset", update_id + 1)


def main():
    """Run one monitoring cycle; GitHub Actions starts us again on schedule."""
    if not TOKEN:
        raise SystemExit("Chybí TELEGRAM_TOKEN. Nastav ho v GitHub Secrets.")
    DATA_DIR.mkdir(exist_ok=True)
    SNAPSHOT_DIR.mkdir(exist_ok=True)
    log.info("SNOW ALERT – jednorázová kontrola zahájena")

    try:
        handle_updates()
    except Exception:
        log.exception("Chyba při zpracování Telegram příkazů")

    check_forecasts()
    log.info("Kontrola veřejných kamer")
    log.info("%s", check_cameras())
    log.info("SNOW ALERT – kontrola dokončena")


if __name__ == "__main__":
    main()
