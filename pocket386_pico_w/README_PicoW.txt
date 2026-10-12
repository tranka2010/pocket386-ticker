POCKET386 DASHBOARD — RASPBERRY PI PICO W SERVER
================================================

GOAL
----
This is an Option A implementation: the Pico W connects to Wi-Fi, fetches the
four data sources itself, caches the results, and answers the Pocket386 over
TTL UART. The existing Pocket386 C client and its protocol are not changed.

FILES
-----
main.py      MicroPython server
config.py    Wi-Fi, UART, location, and refresh configuration
urequests.py MicroPython HTTPS helper (install separately; see below)

PROTOCOL COMPATIBILITY
----------------------
The server accepts GET followed by newline and returns ASCII lines in this
existing order:
  #DASHBOARD_V1|UTC timestamp|source ages|REFRESH=15
  @WX|...
  @ST|...
  @HL|six pipe-separated headlines
  @SP|six fields per game (up to ten games)
  @END

The Pocket386 client should remain unchanged. The Pico UART defaults to 9600,
8N1, UART0, TX=GP0 and RX=GP1. These are configurable in config.py. The code
also provides an optional TCP endpoint on port 8765; the direct UART endpoint
is the intended Pocket386 connection for this setup.

IMPORTANT: urequests dependency
------------------------------
MicroPython does not include urequests in every firmware build. Install a
MicroPython-compatible urequests.py (and any dependency it requires) onto the
Pico W filesystem, or copy a compatible implementation from the official
MicroPython/micropython-lib collection. It must support HTTPS, a timeout
argument, response.status_code, response.text, and response.close(). Verify
TLS behavior with the exact firmware/library version you install.

INSTALL
-------
1. Install current Raspberry Pi Pico W MicroPython firmware.
2. Connect to the Pico W over USB using Thonny or another MicroPython tool.
3. Edit config.py: set WIFI_SSID, WIFI_PASSWORD, and a real contact address in
   WEATHER_USER_AGENT. The weather API expects an identifying User-Agent.
4. Copy config.py, main.py, and a compatible urequests.py to the Pico filesystem.
5. Reboot the Pico. Watch the serial console for Wi-Fi, NTP, and refresh logs.
6. Wire UART TX/RX crossed and connect grounds as described below.

ELECTRICAL CONNECTION
---------------------
Pico W GPIO pins are 3.3 V logic and are NOT 5 V tolerant. You said the
Pocket386's signals are TTL-level and will pass through a level shifter. Ensure
the shifter is suitable for UART push-pull signals, supports the direction of
both TX and RX, and provides a common ground. Cross TX-to-RX and RX-to-TX:

  Pocket386 TX -> appropriate level shifter -> Pico GP1 (UART0 RX)
  Pocket386 RX <- appropriate level shifter <- Pico GP0 (UART0 TX)
  Pocket386 GND ---------------------------- Pico GND

Do not feed 5 V into a Pico GPIO pin. Confirm the Pocket386 GPIO output voltage
and the shifter's logic-side voltage before powering the circuit. This is for
TTL UART pins, not a DB9 RS-232 port; RS-232 needs a dedicated transceiver.
Power the Pico W via its normal USB/VBUS supply, not from a UART signal pin.

CURRENT LIMITATIONS / HONEST EXPECTATIONS
-----------------------------------------
- MicroPython has far less RAM than desktop Linux. ESPN JSON and RSS feed sizes
  may cause memory pressure depending on current upstream responses and the
  urequests implementation. The code fetches one source at a time and calls
  gc.collect(), but this must be tested on the actual board.
- The server uses cooperative, sequential refreshes rather than Linux threads.
  A network refresh can briefly delay serial/TCP processing. HTTP timeouts are
  finite; the Pocket386 client's existing response timeout is 100 seconds.
- RSS parsing is intentionally lightweight and handles common RSS <item>/<title>
  and Atom <entry>/<title> forms, not every possible XML variant.
- HTTPS provider endpoints and their response formats can change. Yahoo Finance,
  ESPN, and the three RSS feeds are public endpoints and are not guaranteed APIs.
- NTP is attempted on Wi-Fi connection. If unavailable, the header still works
  but its UTC timestamp may not be correct until the Pico clock is synchronized.
- The TCP endpoint is unauthenticated and should only be used on a trusted LAN.
- This implementation has not been run on physical Pico W hardware here. Test
  one source at a time and inspect memory/network errors before relying on it.

SUGGESTED FIRST TEST
--------------------
First test UART with Wi-Fi credentials entered but data refresh temporarily
stubbed to known records. Verify GET -> complete response -> @END. Then enable
weather, stocks, headlines, and sports incrementally. If memory becomes tight,
the first optimization should be to reduce ESPN response handling and/or replace
RSS parsing with a smaller single-feed headline source.
