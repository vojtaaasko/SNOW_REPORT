
const LOCATIONS = [
  { name: "Jičín", lat: 50.437, lon: 15.351 },
  { name: "Vrchlabí", lat: 50.626, lon: 15.610 },
  { name: "Špindlerův Mlýn", lat: 50.726, lon: 15.609 }
];

const TIME_ZONE = "Europe/Prague";

function formatTime(dateString) {
  return new Intl.DateTimeFormat("cs-CZ", {
    timeZone: TIME_ZONE,
    hour: "2-digit",
    minute: "2-digit",
    day: "2-digit",
    month: "2-digit"
  }).format(new Date(dateString));
}

async function sendTelegram(env, message) {
  const response = await fetch(
    `https://api.telegram.org/bot${env.TELEGRAM_TOKEN}/sendMessage`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        chat_id: env.CHAT_ID,
        text: message
      })
    }
  );

  if (!response.ok) {
    throw new Error(`Telegram error: ${await response.text()}`);
  }
}

async function checkLocation(location, env) {
  const url = new URL("https://api.open-meteo.com/v1/forecast");

  url.search = new URLSearchParams({
    latitude: location.lat,
    longitude: location.lon,
    hourly: "snowfall,precipitation_probability",
    forecast_days: "2",
    timezone: "UTC"
  });

  const response = await fetch(url);

  if (!response.ok) {
    throw new Error(`Open-Meteo error for ${location.name}`);
  }

  const data = await response.json();
  const now = Date.now();

  const snowHours = data.hourly.time
    .map((time, index) => ({
      time,
      snowfall: data.hourly.snowfall[index] || 0,
      probability:
        data.hourly.precipitation_probability[index] || 0,
      timestamp: new Date(time + ":00Z").getTime()
    }))
    .filter(hour =>
      hour.timestamp >= now + 3 * 60 * 60 * 1000 &&
      hour.timestamp <= now + 12 * 60 * 60 * 1000 &&
      hour.snowfall >= 0.1
    );

  if (snowHours.length === 0) return;

  const first = snowHours[0];
  const key = `snow-alert:${location.name}:${first.time}`;

  const alreadySent = await env.SNOW_ALERT_STATE.get(key);

  if (alreadySent) return;

  const totalSnow = snowHours.reduce(
    (sum, hour) => sum + hour.snowfall,
    0
  );

  const message =
    `❄️ SNOW ALERT – ${location.name}\n\n` +
    `Očekává se sněžení!\n` +
    `Začátek přibližně: ${formatTime(first.time + ":00Z")}\n` +
    `Předpokládané sněžení: ${totalSnow.toFixed(1)} cm\n` +
    `Pravděpodobnost srážek: ${first.probability}%\n\n` +
    `Předpověď na následujících 12 hodin.\n` +
    `Zdroj: Open-Meteo`;

  await sendTelegram(env, message);

  await env.SNOW_ALERT_STATE.put(key, "sent", {
    expirationTtl: 60 * 60 * 48
  });
}

export default {
  async fetch(request, env) {
    return new Response("SNOW ALERT běží! ❄️", {
      headers: {
        "Content-Type": "text/plain; charset=UTF-8"
      }
    });
  },

  async scheduled(controller, env, ctx) {
    const results = await Promise.allSettled(
      LOCATIONS.map(location => checkLocation(location, env))
    );

    for (const result of results) {
      if (result.status === "rejected") {
        console.error("SNOW ALERT error:", result.reason);
      }
    }
  }
};
