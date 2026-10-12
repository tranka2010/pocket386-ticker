"""Pocket386 Dashboard server for Raspberry Pi Pico W (MicroPython).

Keeps the original client protocol unchanged:
  GET\n -> #DASHBOARD_V1|... followed by @WX, @ST, @HL, @SP and @END records.

Data refreshes are cooperative and sequential to avoid the RAM cost of four
background threads. A refresh can temporarily delay servicing serial/TCP input;
network calls have finite timeouts, and the client has a 100-second timeout.
"""
import gc
import time
import socket
import network
import machine
import ujson
import urequests

try:
    import ntptime
except ImportError:
    ntptime = None

import config

RSS_URLS = (
    "https://feeds.npr.org/1001/rss.xml",
    "https://news.yahoo.com/rss/topstories",
    "https://www.realclearpolitics.com/index.xml",
)
SPORTS = (("nba", "basketball", "NBA"), ("nfl", "football", "NFL"), ("nhl", "hockey", "NHL"))

state = {
    "weather": "@WX|Waltham, MA|Weather unavailable|H:--|L:--",
    "stocks": "@ST|DOW|--|N/A|NASDAQ|--|N/A|PTON|--|N/A",
    "headlines": "@HL|Headline unavailable|||||",
    "sports": "@SP|INFO|--|--|--|--|No games",
    "updated": {"weather": 0, "stocks": 0, "headlines": 0, "sports": 0},
}
last_refresh = {"weather": 0, "stocks": 0, "headlines": 0, "sports": 0}


def log(*args):
    print("[Pocket386]", *args)


def sanitize_ascii(value, max_len=70):
    if value is None:
        return ""
    value = str(value).replace("|", "/").replace("\\", "/")
    value = value.replace("\r", " ").replace("\n", " ")
    # Common punctuation replacements before dropping non-ASCII characters.
    value = value.replace("“", '"').replace("”", '"').replace("’", "'").replace("—", "-").replace("–", "-")
    out = []
    for ch in value:
        n = ord(ch)
        if 32 <= n <= 126:
            out.append(ch)
        elif ch in "éèêëÉÈÊËáàâäÁÀÂÄíìîïÍÌÎÏóòôöÓÒÔÖúùûüÚÙÛÜñÑçÇ":
            # Deliberately conservative ASCII transliteration for common Latin letters.
            repl = {"é":"e","è":"e","ê":"e","ë":"e","É":"E","È":"E","Ê":"E","Ë":"E",
                    "á":"a","à":"a","â":"a","ä":"a","Á":"A","À":"A","Â":"A","Ä":"A",
                    "í":"i","ì":"i","î":"i","ï":"i","Í":"I","Ì":"I","Î":"I","Ï":"I",
                    "ó":"o","ò":"o","ô":"o","ö":"o","Ó":"O","Ò":"O","Ô":"O","Ö":"O",
                    "ú":"u","ù":"u","û":"u","ü":"u","Ú":"U","Ù":"U","Û":"U","Ü":"U",
                    "ñ":"n","Ñ":"N","ç":"c","Ç":"C"}
            out.append(repl.get(ch, ""))
        else:
            out.append(" ")
    value = " ".join("".join(out).split())
    if len(value) > max_len:
        value = value[:max(0, max_len - 3)].rstrip() + "..."
    return value


def decode_xml_text(value):
    # Small RSS-focused entity decoder; avoids importing a full XML parser.
    pairs = (("&amp;", "&"), ("&lt;", "<"), ("&gt;", ">"), ("&quot;", '"'), ("&apos;", "'"), ("&#39;", "'"), ("&#039;", "'"))
    for old, new in pairs:
        value = value.replace(old, new)
    # Decode common decimal/hex numeric entities; leave unsupported ones harmless.
    for _ in range(12):
        start = value.find("&#")
        if start < 0:
            break
        end = value.find(";", start + 2)
        if end < 0:
            break
        token = value[start + 2:end]
        try:
            if token.startswith(("x", "X")):
                code = int(token[1:], 16)
            else:
                code = int(token)
            repl = chr(code) if 0 < code < 127 else " "
            value = value[:start] + repl + value[end + 1:]
        except Exception:
            value = value[:start] + " " + value[end + 1:]
    return value


def fetch_text(url, headers=None):
    gc.collect()
    response = None
    try:
        response = urequests.get(url, headers=headers or {}, timeout=config.HTTP_TIMEOUT_SECONDS)
        if response.status_code < 200 or response.status_code >= 300:
            raise OSError("HTTP status " + str(response.status_code))
        return response.text
    finally:
        if response is not None:
            response.close()
        gc.collect()


def get_json(url, headers=None):
    text = fetch_text(url, headers)
    try:
        return ujson.loads(text)
    finally:
        del text
        gc.collect()


def fetch_weather():
    headers = {"User-Agent": config.WEATHER_USER_AGENT, "Accept": "application/geo+json"}
    try:
        point_url = "https://api.weather.gov/points/" + config.WEATHER_LAT + "," + config.WEATHER_LON
        point = get_json(point_url, headers)
        forecast_url = point["properties"]["forecast"]
        del point
        gc.collect()
        data = get_json(forecast_url, headers)
        periods = data.get("properties", {}).get("periods", [])
        if not periods or periods[0].get("temperature") is None:
            raise ValueError("No forecast periods/temperature")
        current = periods[0]
        unit = current.get("temperatureUnit", "F")
        high = None
        low = None
        for period in periods:
            if period.get("isDaytime") and high is None:
                high = period.get("temperature")
            elif not period.get("isDaytime") and low is None:
                low = period.get("temperature")
            if high is not None and low is not None:
                break
        conditions = sanitize_ascii(current.get("shortForecast", "Forecast unavailable"), 18)
        return "@WX|{}|{}{} {}|H:{}{}|L:{}{}".format(
            sanitize_ascii(config.WEATHER_LABEL, 28), current["temperature"], unit,
            conditions, high if high is not None else "--", unit,
            low if low is not None else "--", unit)
    except Exception as exc:
        log("weather refresh failed:", exc)
        return "@WX|{}|Weather unavailable|H:--|L:--".format(sanitize_ascii(config.WEATHER_LABEL, 28))


def fetch_stocks():
    parts = ["@ST"]
    headers = {"User-Agent": "Pocket386Dashboard/1.0"}
    for symbol, label in (("%5EDJI", "DOW"), ("%5EIXIC", "NASDAQ"), ("PTON", "PTON")):
        try:
            url = "https://query1.finance.yahoo.com/v8/finance/chart/{}?interval=1d".format(symbol)
            data = get_json(url, headers)
            results = data.get("chart", {}).get("result")
            if not results:
                raise ValueError("No chart result")
            meta = results[0]["meta"]
            price = float(meta["regularMarketPrice"])
            previous = float(meta.get("chartPreviousClose", price))
            change = (price - previous) / previous * 100.0 if previous else 0.0
            price_text = "{:.1f}".format(price) if price >= 1000 else "{:.2f}".format(price)
            parts.extend((label, price_text, "{:+.1f}%".format(change)))
            del data
        except Exception as exc:
            log(label, "quote unavailable:", exc)
            parts.extend((label, "--", "N/A"))
        gc.collect()
    return "|".join(parts)


def extract_tag(block, tag):
    low = block.lower()
    opening = "<" + tag.lower()
    a = low.find(opening)
    if a < 0:
        return ""
    a = low.find(">", a)
    if a < 0:
        return ""
    b = low.find("</" + tag.lower() + ">", a + 1)
    if b < 0:
        return ""
    value = block[a + 1:b]
    # Remove CDATA wrappers and simple markup around titles.
    if value.startswith("<![CDATA[") and value.endswith("]]>"):
        value = value[9:-3]
    while "<" in value and ">" in value:
        x = value.find("<")
        y = value.find(">", x)
        if y < 0:
            break
        value = value[:x] + " " + value[y + 1:]
    return sanitize_ascii(decode_xml_text(value), 70)


def fetch_headlines():
    headlines = []
    seen = set()
    headers = {"User-Agent": "Pocket386Dashboard/1.0"}
    for url in RSS_URLS:
        if len(headlines) >= 6:
            break
        try:
            xml = fetch_text(url, headers)
            # Most feeds are RSS; Atom feeds are supported by a fallback entry split.
            blocks = []
            marker = "<item"
            pos = 0
            lower = xml.lower()
            while len(headlines) < 6:
                a = lower.find(marker, pos)
                if a < 0:
                    break
                a = lower.find(">", a)
                if a < 0:
                    break
                b = lower.find("</item>", a)
                if b < 0:
                    break
                blocks.append(xml[a + 1:b])
                pos = b + 7
            if not blocks:
                pos = 0
                while len(headlines) < 6:
                    a = lower.find("<entry", pos)
                    if a < 0:
                        break
                    a = lower.find(">", a)
                    if a < 0:
                        break
                    b = lower.find("</entry>", a)
                    if b < 0:
                        break
                    blocks.append(xml[a + 1:b])
                    pos = b + 8
            for block in blocks:
                title = extract_tag(block, "title")
                if title and title not in seen:
                    seen.add(title)
                    headlines.append(title)
                    if len(headlines) >= 6:
                        break
            del xml, blocks
        except Exception as exc:
            log("RSS unavailable:", exc)
        gc.collect()
    if not headlines:
        headlines = ["Headlines unavailable"]
    while len(headlines) < 6:
        headlines.append("")
    return "@HL|" + "|".join(headlines[:6])


def format_game_status(league_code, status):
    status = status or {}
    status_type = status.get("type", {}) or {}
    if status_type.get("state") == "in":
        try:
            period = int(status.get("period", 0))
        except Exception:
            period = 0
        clock = sanitize_ascii(status.get("displayClock", ""), 5)
        if league_code == "nhl":
            prefix = "P{}".format(period) if 1 <= period <= 3 else "OT"
        else:
            prefix = "Q{}".format(period) if 1 <= period <= 4 else "OT"
        return sanitize_ascii((prefix + " " + clock) if clock else (prefix + " LIVE"), 8)
    return sanitize_ascii(status_type.get("shortDetail") or status_type.get("description") or "Status?", 8)


def fetch_sports():
    boston_games = []
    other_games = []
    headers = {"User-Agent": "Pocket386Dashboard/1.0"}
    boston_abbreviations = ("BOS", "NE", "NWE")
    boston_names = ("celtics", "patriots", "bruins")
    for league_code, sport, label in SPORTS:
        try:
            url = "https://site.api.espn.com/apis/site/v2/sports/{}/{}/scoreboard".format(sport, league_code)
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
                a1 = sanitize_ascii(team1.get("abbreviation", "?"), 4)
                a2 = sanitize_ascii(team2.get("abbreviation", "?"), 4)
                n1, n2 = team1.get("displayName", ""), team2.get("displayName", "")
                entry = [label, a1, sanitize_ascii(t1.get("score", "--"), 4), a2,
                         sanitize_ascii(t2.get("score", "--"), 4), format_game_status(league_code, comp.get("status", {}))]
                names = (n1 + " " + n2).lower()
                if a1 in boston_abbreviations or a2 in boston_abbreviations or any(n in names for n in boston_names):
                    boston_games.append(entry)
                else:
                    other_games.append(entry)
            del data
        except Exception as exc:
            log(label, "scoreboard refresh failed:", exc)
        gc.collect()
    games = (boston_games + other_games)[:10]
    parts = ["@SP"]
    for game in games:
        parts.extend(game)
    if not games:
        parts.extend(("INFO", "--", "--", "--", "--", "No games"))
    return "|".join(parts)


def fetch_time():
    try:
        t = time.gmtime()
        return "UTC {:04d}-{:02d}-{:02d} {:02d}:{:02d}:{:02d}".format(t[0], t[1], t[2], t[3], t[4], t[5])
    except Exception:
        return "UTC time unavailable"


def generate_payload():
    now = time.time()
    ages = []
    for key, short in (("weather", "W"), ("stocks", "S"), ("headlines", "H"), ("sports", "P")):
        stamp = state["updated"][key]
        age = str(max(0, int((now - stamp) / 60))) + "m" if stamp else "--"
        ages.append(short + age)
    lines = ["#DASHBOARD_V1|{}|{}|REFRESH=15".format(fetch_time(), " ".join(ages)),
             state["weather"], state["stocks"], state["headlines"], state["sports"], "@END"]
    return "\n".join(lines) + "\n"


def connect_wifi():
    wlan = network.WLAN(network.STA_IF)
    wlan.active(True)
    if not wlan.isconnected():
        log("connecting to Wi-Fi", config.WIFI_SSID)
        wlan.connect(config.WIFI_SSID, config.WIFI_PASSWORD)
        start = time.ticks_ms()
        while not wlan.isconnected() and time.ticks_diff(time.ticks_ms(), start) < 20000:
            time.sleep_ms(250)
    if wlan.isconnected():
        log("Wi-Fi connected:", wlan.ifconfig())
        if ntptime:
            try:
                ntptime.settime()
                log("UTC clock synchronized")
            except Exception as exc:
                log("NTP sync failed:", exc)
    else:
        log("Wi-Fi connection failed; will retry in main loop")
    return wlan


def refresh_one_due_source():
    # One source per loop iteration. Network calls are synchronous but bounded.
    now = time.time()
    tasks = (("weather", fetch_weather, config.WEATHER_INTERVAL),
             ("stocks", fetch_stocks, config.STOCKS_INTERVAL),
             ("headlines", fetch_headlines, config.HEADLINES_INTERVAL),
             ("sports", fetch_sports, config.SPORTS_INTERVAL))
    for key, fn, interval in tasks:
        if last_refresh[key] == 0 or now - last_refresh[key] >= interval:
            last_refresh[key] = now
            try:
                record = fn()
                state[key] = record
                state["updated"][key] = time.time()
            except Exception as exc:
                log(key, "unexpected refresh error:", exc)
            gc.collect()
            return


def process_command(command, writer):
    if command.strip() == "GET":
        payload = generate_payload()
        try:
            writer(payload.encode("ascii", "replace"))
        except Exception as exc:
            log("response write failed:", exc)


def start_tcp_server():
    if not config.ENABLE_TCP:
        return None
    addr = socket.getaddrinfo("0.0.0.0", config.TCP_PORT)[0][-1]
    server = socket.socket()
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind(addr)
    server.listen(config.MAX_TCP_CLIENTS)
    server.setblocking(False)
    log("TCP listener on port", config.TCP_PORT)
    return server


def main():
    uart = machine.UART(config.UART_ID, baudrate=config.UART_BAUD, bits=8, parity=None, stop=1,
                        tx=machine.Pin(config.UART_TX_PIN), rx=machine.Pin(config.UART_RX_PIN), timeout=0, timeout_char=20)
    log("UART{} ready: {} baud, TX GP{}, RX GP{}".format(config.UART_ID, config.UART_BAUD, config.UART_TX_PIN, config.UART_RX_PIN))
    wlan = connect_wifi()
    tcp_server = None
    try:
        tcp_server = start_tcp_server()
    except Exception as exc:
        log("TCP listener unavailable:", exc)

    clients = []
    uart_buffer = b""
    retry_wifi_at = time.ticks_add(time.ticks_ms(), 10000)

    while True:
        # UART command input; process complete newline-terminated commands.
        try:
            if uart.any():
                chunk = uart.read()
                if chunk:
                    uart_buffer += chunk
                    if len(uart_buffer) > 128:
                        uart_buffer = b""
                    while b"\n" in uart_buffer:
                        raw, uart_buffer = uart_buffer.split(b"\n", 1)
                        process_command(raw.decode("ascii", "ignore").strip(), uart.write)
        except Exception as exc:
            log("UART error:", exc)

        # Accept and service optional TCP clients. Nonblocking writes are queued.
        if tcp_server:
            try:
                client, remote = tcp_server.accept()
                client.setblocking(False)
                clients.append({"sock": client, "remote": remote, "buf": b"", "out": b"", "last": time.time()})
                log("TCP client connected:", remote)
            except OSError:
                pass
            keep = []
            now = time.time()
            for item in clients:
                sock = item["sock"]
                try:
                    if now - item["last"] > config.TCP_IDLE_TIMEOUT_SECONDS:
                        sock.close()
                        continue
                    try:
                        data = sock.recv(128)
                    except OSError:
                        data = None
                    if data == b"":
                        sock.close()
                        continue
                    if data:
                        item["last"] = now
                        item["buf"] += data
                        if len(item["buf"]) > 256:
                            item["buf"] = b""
                        while b"\n" in item["buf"]:
                            raw, item["buf"] = item["buf"].split(b"\n", 1)
                            if raw.strip() == b"GET":
                                item["out"] += generate_payload().encode("ascii", "replace")
                    if item["out"]:
                        try:
                            sent = sock.send(item["out"])
                            if sent > 0:
                                item["out"] = item["out"][sent:]
                        except OSError:
                            pass
                    keep.append(item)
                except Exception:
                    try:
                        sock.close()
                    except Exception:
                        pass
            clients = keep[:config.MAX_TCP_CLIENTS]

        # Retry Wi-Fi if it has dropped.
        if not wlan.isconnected() and time.ticks_diff(time.ticks_ms(), retry_wifi_at) >= 0:
            retry_wifi_at = time.ticks_add(time.ticks_ms(), 10000)
            try:
                wlan = connect_wifi()
            except Exception as exc:
                log("Wi-Fi reconnect failed:", exc)

        # Keep servicing requests between data refreshes. A refresh itself may
        # block for a few seconds, but HTTP calls have configured timeouts.
        if wlan.isconnected():
            refresh_one_due_source()
        time.sleep_ms(20)


try:
    main()
except KeyboardInterrupt:
    log("stopped")
