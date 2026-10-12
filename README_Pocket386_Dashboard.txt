POCKET386 DASHBOARD - DUAL TRANSPORT REVISION
=============================================

FILES
-----
dos_serial_proxy_fixed.py  Linux Python data service; serial and TCP endpoints
dashbrd_fixed.c             Borland C / DOS dashboard client
screen_fixed.h       VGA text-mode helpers

WHAT CHANGED
------------
- The DOS client supports both the original direct serial transport and an
  ESP-01S running compatible factory ESP-AT firmware.
- Transport is selected on the DOS command line. The default remains direct
  serial, preserving the previous behavior:
      DASHBRD /SERIAL
      DASHBRD /ESP
- ESP-AT mode detects a module UART speed of either 115200 or 9600 baud,
  configures Wi-Fi, opens one TCP connection to the Linux host, and enters
  transparent UART-to-TCP mode. The DOS client then uses the same GET / @END
  protocol as direct serial.
- On normal exit, ESP-AT mode attempts to leave transparent mode and close the
  TCP connection so a later launch can initialize the module again.
- The Python TCP handler accepts repeated GET requests on the same connection
  and allows up to 180 seconds idle time, so the ESP-AT transparent connection
  survives the dashboard's approximately 15-second refresh interval.
- Live NBA/NFL status now includes the quarter, for example "Q2 05:32". Live NHL
  status includes the period, for example "P2 08:11". Overtime displays "OT"
  with the clock. Pregame/final status remains provider-supplied short detail.

ESP-AT CONFIGURATION
--------------------
Before compiling dashbrd_fixed.c for ESP mode, edit these definitions near the top:
  ESP_WIFI_SSID
  ESP_WIFI_PASSWORD
  ESP_HOST_IP       (numeric LAN IPv4 address of the Linux computer)
  ESP_HOST_PORT     (8765 unless you changed the Python service)

Use a simple SSID/password that do not contain literal double quotes. The
ESP module must be running ESP8266 AT firmware that supports AT+CWMODE,
AT+CWJAP, AT+CIPMUX, AT+CIPSTART, AT+CIPMODE, and transparent AT+CIPSEND.
The client probes 115200 and 9600 baud. If your module uses another baud rate,
change the probe list in try_at_baud() or configure the module to one of these
speeds before use.

The ESP's UART and the Pocket386 COM1 must use compatible 3.3 V signaling at
the ESP side, with proper power and common ground. The ESP-01S needs a stable
3.3 V supply able to handle Wi-Fi current bursts. Do not connect 5 V directly
to ESP VCC or ESP RX.

PYTHON HOST SETUP
-----------------
Edit SERIAL_PORT and BAUD_RATE if required. The service refreshes weather,
stocks, headlines, and sports in independent background workers. It serves
both the original serial interface and TCP port 8765 at the same time. If the
ESP-AT connection is used, allow TCP port 8765 only from your trusted LAN in
the Linux firewall; the endpoint has no application authentication or TLS.

Install dependencies:
  python3 -m pip install requests pyserial

Run:
  python3 dos_serial_proxy_fixed.py

Replace the example contact address in WEATHER_HEADERS with a real contact
address before deployment. Keep the Linux host clock synchronized.

DOS BUILD / TEST
----------------
Compile dashbrd_fixed.c with Borland C and keep screen_fixed.h in the same directory.
The source has not been compiled with Borland C or tested on Pocket386 hardware
in this environment. It has been checked with a host C89 syntax test using DOS
API stubs. Test direct serial mode first, then ESP mode. Keep the prior working
executable and sources until hardware tests pass. The screen expects 80x25
color text mode and COM1 at 9600 baud for direct serial mode.

ESP-AT NOTES
------------
Transparent mode is stateful. The client sends the AT setup commands on launch,
then leaves transparent mode with the documented +++ escape sequence on normal
quit. If the application or Pocket386 is reset unexpectedly while transparent
mode is active, the ESP may remain in data mode; power-cycle the ESP-01S before
relaunching if the client cannot get an AT response. Exact AT responses and
recovery behavior depend on the installed factory firmware version.
