POCKET386 DASHBOARD - FEATURE-COMPLETE SOURCE REVISION
====================================================

FILES
-----
dos_serial_proxy_fixed.py  Python data service; serves serial and TCP requests
dashbrd_fixed.c             Borland C / DOS client
screen_fixed.h              VGA text-mode helpers

ARCHITECTURE
------------
The Linux process refreshes weather, stocks, headlines, and sports in four
independent background threads. The serial and TCP handlers return a snapshot
of the most recently refreshed records; they do not wait for upstream HTTP
requests. The line protocol remains ASCII and pipe-delimited, ending with @END.

The header includes host UTC time and the age in minutes of each source's most
recent refresh attempt (W=weather, S=stocks, H=headlines, P=sports). This age
indicates when the source was last checked; it does not guarantee the provider's
underlying data is current. Provider failures are logged and displayed as
unavailable rather than being replaced with fabricated live-looking values.

CONFIGURATION
-------------
Edit the configuration constants near the top of dos_serial_proxy_fixed.py:
  SERIAL_PORT = "/dev/ttyUSB0"
  BAUD_RATE = 9600
  TCP_BIND_HOST = "0.0.0.0"
  TCP_PORT = 8765

Replace the example contact address in WEATHER_HEADERS with a real contact
address before deployment. The Linux host clock should be synchronized with
NTP or an equivalent time service.

Install dependencies on Linux:
  python3 -m pip install requests pyserial

Run:
  python3 dos_serial_proxy_fixed.py

The service continues to provide the existing serial interface while also
listening for TCP clients on port 8765. Because the TCP listener has no
application-level authentication or TLS, allow that port only from the trusted
local network using the Linux firewall. Do not forward it from the Internet.

DOS BUILD / TEST
----------------
Compile dashbrd_fixed.c with the intended Borland C compiler and keep
screen_fixed.h in the same directory (the revised client includes that filename).
The source has not been compiled with Borland C or tested on Pocket386 hardware
in this environment. Keep the prior executable and source files until hardware
tests pass. Confirm that the system starts in 80x25 color text mode and that
COM1 is the intended UART at 9600 baud, 8N1.

ESP-01 OPTION (ASSESSMENT)
-------------------------
Recommended design: custom ESP8266 firmware acts as a small serial-to-TCP
bridge. The Pocket386 still sends GET<CR/LF> and receives the same newline-
terminated dashboard records. On GET, the ESP joins the configured Wi-Fi,
connects to the Linux host's TCP port 8765, sends GET followed by newline,
forwards bytes until @END, then closes the TCP connection (or reuses it with
careful framing). The C client and payload format need not change.

A transparent AT-command firmware setup is less attractive: it adds AT command
state handling and may not reliably provide the exact request/response bridge
behavior needed by this DOS client. A small custom firmware is more predictable.

The ESP-01's UART0 uses GPIO1/TX and GPIO3/RX. Its boot ROM can emit startup
text at a different baud rate before application firmware starts; the client
should tolerate and ignore non-protocol lines before the first #DASHBOARD line.
Use the ESP in normal flash boot mode and ensure GPIO0/GPIO2/CH_PD/RESET have
appropriate boot-state levels. The ESP8266 requires a stable supply capable of
handling Wi-Fi transmit current bursts; level shifting is assumed handled by
the project owner as specified.

ESP TCP connection settings should include the Linux host's LAN IP address,
TCP port 8765, Wi-Fi SSID/password, and bounded connection/read timeouts. On a
failed TCP connection, the ESP should return a short diagnostic line or simply
wait for the DOS client's timeout; it must not send fake dashboard records.
Avoid emitting diagnostics on the UART while a dashboard response is in flight.

LIMITATIONS / VERIFICATION
--------------------------
- Python syntax compilation and mocked data-source tests passed during revision.
- Borland C compilation and physical serial tests have not been performed here.
- Third-party API formats/availability can change.
- TCP port 8765 is unauthenticated; firewall it to the local trusted LAN.
- The ESP bridge firmware itself is not included in this source bundle; the
  existing Pocket386 serial protocol is deliberately preserved for it.
