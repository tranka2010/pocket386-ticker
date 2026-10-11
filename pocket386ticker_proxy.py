#!/usr/bin/env python3
"""Pocket386 dashboard data service and serial transport.

The serial protocol remains ASCII, pipe-delimited records terminated by @END.
Network sources refresh independently in background threads. A GET command
returns the latest snapshot immediately instead of waiting for HTTP requests.
"""
import logging
import socketserver
import threading
import time
import unicodedata
import xml.etree.ElementTree as ET
from datetime import datetime, timezone

import requests
try:
    import serial
except ImportError:
    serial = None  # TCP/ESP-01-only installations do not need pyserial.

SERIAL_PORT = "/dev/ttyUSB0"
BAUD_RATE = 9600
# For ESP-01 TCP bridge use, restrict this port to your trusted LAN with the host firewall.
TCP_BIND_HOST = "0.0.0.0"
TCP_PORT = 8765
HTTP_TIMEOUT = (2.5, 4.0)
WEATHER_INTERVAL = 600
STOCKS_INTERVAL = 60
HEADLINES_INTERVAL = 300
SPORTS_INTERVAL = 30

WEATHER_POINT_URL = "https://api.weather.gov/points/42.3765,-71.2356"
# Replace this with a real contact address before deployment; NWS requests
# should identify the application and provide a valid contact method.
WEATHER_HEADERS = {
    "User-Agent": "Pocket386Dashboard (configure-your-contact@example.com)",
    "Accept": "application/geo+json",
}
RSS_URLS = [
    "https://feeds.npr.org/1001/rss.xml",
    "https://news.yahoo.com/rss/topstories",
    "https://www.realclearpolitics.com/index.xml",
]
SPORTS = [("nba", "basketball", "NBA"), ("nfl", "football", "NFL"), ("nhl", "hockey", "NHL")]

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("pocket386")

# Each record is independently refreshed. Initial values explicitly say that
# data has not yet arrived; they are never disguised as live data.
state_lock = threading.Lock()
state = {
    "weather": "@WX|Waltham, MA|Weather unavailable|H:--|L:--",
    "stocks": "@ST|DOW|--|N/A|NASDAQ|--|N/A|PTON|--|N/A",
    "headlines": "@HL|Headline unavailable|||||",
    "sports": "@SP|INFO|--|--|--|--|No games",
    "updated": {"weather": 0.0, "stocks": 0.0, "headlines": 0.0, "sports": 0.0},
}


def sanitize_ascii(value, max_len=70):
    """Convert source text to safe, single-line ASCII protocol text."""
    if value is None:
        return ""
    value = str(value).replace("|", "/").replace("\\", "/")
    value = value.replace("“", '"').replace("”", '"').replace("’", "'").replace("—", "-")
    value = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")
    value = " ".join(value.replace("\r", " ").replace("\n", " ").split())
    if len(value) > max_len:
        value = value[:max(0, max_len - 3)].rstrip() + "..."
    return value


def fetch_time():
    # Host clock should be synchronized (for example, with systemd-timesyncd/NTP).
    return datetime.now(timezone.utc).strftime("UTC %Y-%m-%d %H:%M:%S")


def get_json(url, headers=None):
    response = requests.get(url, headers=headers, timeout=HTTP_TIMEOUT)
    response.raise_for_status()
    return response.json()


def fetch_weather():
    try:
        point = get_json(WEATHER_POINT_URL, WEATHER_HEADERS)
        forecast_url = point["properties"]["forecast"]
        data = get_json(forecast_url, WEATHER_HEADERS)
        periods = data["properties"]["periods"]
        if not periods:
            raise ValueError("NWS returned no forecast periods")
        current = periods[0]
        if current.get("temperature") is None:
            raise ValueError("NWS forecast has no temperature")
        unit = current.get("temperatureUnit", "F")
        high = low = None
        for period in periods:
            if period.get("isDaytime") and high is None:
                high = period.get("temperature")
            elif not period.get("isDaytime") and low is None:
                low = period.get("temperature")
            if high is not None and low is not None:
                break
        conditions = sanitize_ascii(current.get("shortForecast", "Forecast unavailable"), 18)
        return f"@WX|Waltham, MA|{current['temperature']}{unit} {conditions}|H:{high}{unit}" + (f"|L:{low}{unit}" if low is not None else "|L:--")
    except (requests.RequestException, ValueError, KeyError, TypeError) as exc:
        log.warning("Weather refresh failed: %s", exc)
        return "@WX|Waltham, MA|Weather unavailable|H:--|L:--"


def fetch_stocks():
    parts = ["@ST"]
    headers = {"User-Agent": "Pocket386Dashboard/1.0"}
    for symbol, label in [("^DJI", "DOW"), ("^IXIC", "NASDAQ"), ("PTON", "PTON")]:
        try:
            url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?interval=1d"
            data = get_json(url, headers)
            results = data.get("chart", {}).get("result")
            if not results:
                raise ValueError("No chart result")
            meta = results[0]["meta"]
            price = float(meta["regularMarketPrice"])
            previous = float(meta.get("chartPreviousClose", price))
            change = (price - previous) / previous * 100.0 if previous else 0.0
            parts.extend([label, f"{price:.1f}" if price >= 1000 else f"{price:.2f}", f"{change:+.1f}%"])
        except (requests.RequestException, ValueError, KeyError, TypeError, IndexError) as exc:
            log.warning("%s quote unavailable: %s", label, exc)
            parts.extend([label, "--", "N/A"])
    return "|".join(parts)


def fetch_headlines():
    headlines, seen = [], set()
    headers = {"User-Agent": "Pocket386Dashboard/1.0"}
    for url in RSS_URLS:
        if len(headlines) >= 6:
            break
        try:
            response = requests.get(url, headers=headers, timeout=HTTP_TIMEOUT)
            response.raise_for_status()
            root = ET.fromstring(response.content)
            items = root.findall("./channel/item")
            if not items:
                items = root.findall(".//{http://www.w3.org/2005/Atom}entry")
            for item in items:
                title = item.find("title")
                if title is None:
                    title = item.find("{http://www.w3.org/2005/Atom}title")
                if title is not None and title.text:
                    headline = sanitize_ascii(title.text, 70)
                    if headline and headline not in seen:
                        seen.add(headline)
                        headlines.append(headline)
                        if len(headlines) == 6:
                            break
        except (requests.RequestException, ET.ParseError, ValueError) as exc:
            log.warning("RSS feed unavailable (%s): %s", url, exc)
    if not headlines:
        headlines = ["Headlines unavailable"]
    headlines.extend([""] * (6 - len(headlines)))
    return "@HL|" + "|".join(headlines[:6])


def fetch_sports():
    boston_games, other_games = [], []
    headers = {"User-Agent": "Pocket386Dashboard/1.0"}
    boston_abbreviations = {"BOS", "NE", "NWE"}
    boston_names = ("celtics", "patriots", "bruins")
    for league_code, sport, label in SPORTS:
        url = f"https://site.api.espn.com/apis/site/v2/sports/{sport}/{league_code}/scoreboard"
        try:
            data = get_json(url, headers)
            for event in data.get("events", []):
                competitions = event.get("competitions", [])
                if not competitions:
                    continue
                comp = competitions[0]
                teams = comp.get("competitors", [])
                if len(teams) < 2:
                    continue
                t1, t2 = teams[0], teams[1]
                team1, team2 = t1.get("team", {}), t2.get("team", {})
                a1, a2 = sanitize_ascii(team1.get("abbreviation", "?"), 4), sanitize_ascii(team2.get("abbreviation", "?"), 4)
                n1, n2 = team1.get("displayName", ""), team2.get("displayName", "")
                status = comp.get("status", {}).get("type", {}).get("shortDetail", "Status?")
                entry = [label, a1, sanitize_ascii(t1.get("score", "--"), 4), a2,
                         sanitize_ascii(t2.get("score", "--"), 4), sanitize_ascii(status, 8)]
                names = (n1 + " " + n2).lower()
                if a1 in boston_abbreviations or a2 in boston_abbreviations or any(n in names for n in boston_names):
                    boston_games.append(entry)
                else:
                    other_games.append(entry)
        except (requests.RequestException, ValueError, KeyError, TypeError) as exc:
            log.warning("%s scoreboard refresh failed: %s", label, exc)
    games = (boston_games + other_games)[:10]
    parts = ["@SP"]
    for game in games:
        parts.extend(game)
    if not games:
        parts.extend(["INFO", "--", "--", "--", "--", "No games"])
    return "|".join(parts)


def refresh_loop(key, fetcher, interval):
    """Refresh one source independently; failures retain an explicit safe record."""
    while True:
        started = time.monotonic()
        try:
            record = fetcher()
            with state_lock:
                state[key] = record
                state["updated"][key] = time.time()
        except Exception:
            # Defensive catch: one broken provider must not kill its worker.
            log.exception("Unexpected %s refresh failure", key)
        elapsed = time.monotonic() - started
        time.sleep(max(1.0, interval - elapsed))


def start_refresh_workers():
    workers = [
        ("weather", fetch_weather, WEATHER_INTERVAL),
        ("stocks", fetch_stocks, STOCKS_INTERVAL),
        ("headlines", fetch_headlines, HEADLINES_INTERVAL),
        ("sports", fetch_sports, SPORTS_INTERVAL),
    ]
    for key, fetcher, interval in workers:
        thread = threading.Thread(target=refresh_loop, args=(key, fetcher, interval), name=f"refresh-{key}", daemon=True)
        thread.start()


def generate_payload():
    """Build a snapshot from cached records; never performs network I/O."""
    now = time.time()
    with state_lock:
        records = [state["weather"], state["stocks"], state["headlines"], state["sports"]]
        ages = []
        for key, short in (("weather", "W"), ("stocks", "S"), ("headlines", "H"), ("sports", "P")):
            stamp = state["updated"][key]
            age = str(max(0, int((now - stamp) / 60))) + "m" if stamp else "--"
            ages.append(short + age)
    # Field 1 is the host UTC time; field 2 shows age of the latest refresh
    # attempt for each source (not a guarantee that the upstream data is live).
    lines = [f"#DASHBOARD_V1|{fetch_time()}|{' '.join(ages)}|REFRESH=15"] + records + ["@END"]
    return "\n".join(lines) + "\n"


def serve_serial_forever():
    """Serve the original serial connection; retry if the adapter disconnects."""
    if serial is None:
        log.info("pyserial is not installed; continuing in TCP-only mode")
        return
    while True:
        try:
            log.info("Opening serial %s at %d baud", SERIAL_PORT, BAUD_RATE)
            with serial.Serial(SERIAL_PORT, BAUD_RATE, timeout=1, write_timeout=10) as ser:
                while True:
                    raw = ser.readline()
                    if not raw:
                        continue
                    command = raw.decode("ascii", errors="ignore").strip()
                    if command == "GET":
                        payload = generate_payload().encode("ascii", errors="replace")
                        ser.write(payload)
                        ser.flush()
                        log.info("Served serial GET (%d bytes)", len(payload))
        except (serial.SerialException, OSError):
            log.exception("Serial I/O error; retrying in 5 seconds")
            time.sleep(5)


class DashboardTCPHandler(socketserver.StreamRequestHandler):
    """Simple line-oriented TCP transport for a custom ESP-01 serial bridge."""
    def handle(self):
        self.request.settimeout(10)
        try:
            while True:
                raw = self.rfile.readline(32)
                if not raw:
                    return
                command = raw.decode("ascii", errors="ignore").strip()
                if command == "GET":
                    payload = generate_payload().encode("ascii", errors="replace")
                    self.wfile.write(payload)
                    self.wfile.flush()
                    log.info("Served TCP GET from %s (%d bytes)", self.client_address[0], len(payload))
                elif command:
                    log.warning("Ignoring unknown TCP command from %s", self.client_address[0])
        except (OSError, TimeoutError):
            log.info("TCP client %s disconnected/timed out", self.client_address[0])


class DashboardTCPServer(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


def main():
    start_refresh_workers()
    serial_thread = threading.Thread(target=serve_serial_forever, name="serial-server", daemon=True)
    serial_thread.start()
    try:
        with DashboardTCPServer((TCP_BIND_HOST, TCP_PORT), DashboardTCPHandler) as server:
            log.info("TCP dashboard endpoint listening on %s:%d", TCP_BIND_HOST, TCP_PORT)
            log.info("If using the ESP-01 bridge, allow TCP port %d only from your trusted LAN", TCP_PORT)
            server.serve_forever(poll_interval=0.5)
    except KeyboardInterrupt:
        log.info("Server stopped")
    except OSError as exc:
        log.error("Could not open TCP listener %s:%d: %s", TCP_BIND_HOST, TCP_PORT, exc)


if __name__ == "__main__":
    main()
