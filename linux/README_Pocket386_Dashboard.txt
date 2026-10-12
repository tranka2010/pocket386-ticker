POCKET386 DASHBOARD - DUAL TRANSPORT / LINUX CLIENT REVISION
===========================================================

FILES
-----
dos_serial_proxy_fixed.py  Linux Python data service; serial and TCP endpoints
dashbrd_fixed.c             Shared Borland C / DOS and Linux client source
screen_fixed.h              VGA text-mode / ANSI terminal screen helpers

WHAT CHANGED
------------
- The same C client source can be compiled for Borland C / DOS or for Linux.
- The DOS build uses VGA text memory, BIOS ticks, keyboard functions, and COM1
  hardware access as before.
- The Linux build uses a POSIX serial device, monotonic time, terminal ANSI
  drawing, and single-key input. It expects an 80-column by 25-row terminal.
- The client supports direct serial and ESP-01S factory ESP-AT firmware.
- Transport is selected on the client command line. Direct serial remains the
  default:
      DASHBRD /SERIAL
      DASHBRD /ESP
  On Linux, the generated executable can be invoked with the same arguments.
- Linux terminal keys are R to refresh and Q or Esc to quit. On DOS, F5 refreshes.
- ESP-AT mode detects a module UART speed of either 115200 or 9600 baud,
  configures Wi-Fi, opens one TCP connection to the Linux host, and enters
  transparent UART-to-TCP mode. The client then uses the same GET / @END
  protocol as direct serial.
- On normal exit, ESP-AT mode attempts to leave transparent mode and close the
  TCP connection so a later launch can initialize the module again.
- The Python TCP handler accepts repeated GET requests on the same connection
  and allows up to 180 seconds idle time, so the ESP-AT transparent connection
  survives the dashboard's approximately 15-second refresh interval.
- Live NBA/NFL status includes the quarter, for example "Q2 05:32". Live NHL
  status includes the period, for example "P2 08:11". Overtime displays "OT"
  with the clock. Pregame/final status remains provider-supplied short detail.

LINUX BUILD
-----------
Install GCC (for example, package build-essential on Debian/Ubuntu). From the
source directory, compile the shared client with:

  gcc -DPOCKET386_LINUX -D_DEFAULT_SOURCE -O2 -Wall -Wextra \
      -o dashbrd_linux dashbrd_fixed.c

The code also detects Linux automatically via __linux__, but the explicit
-DPOCKET386_LINUX flag documents the intended build target. The -D_DEFAULT_SOURCE
flag enables the POSIX/Linux declarations used by the serial and terminal layer.

By default, the Linux client opens /dev/ttyUSB0. To use a different device,
compile with a quoted macro, for example:

  gcc -DPOCKET386_LINUX -D_DEFAULT_SOURCE \
      -DPOCKET386_SERIAL_DEVICE='"/dev/ttyUSB1"' \
      -O2 -Wall -Wextra -o dashbrd_linux dashbrd_fixed.c

Run it from a terminal:
  ./dashbrd_linux /SERIAL
  ./dashbrd_linux /ESP

For direct serial mode, the client opens the configured device at 9600 baud.
For ESP-AT mode, it opens that device while probing 115200 and 9600 baud. Make
sure your Linux user has permission to access the serial device (often via the
dialout group), and close any terminal program using it.

LINUX ESP-AT TESTING WITH THE PYTHON SERVER ON THE SAME COMPUTER
----------------------------------------------------------------
If the ESP-01S is attached to the same Linux computer through /dev/ttyUSB0,
the Python server must not also open that serial device. In
 dos_serial_proxy_fixed.py, set:

  SERIAL_PORT = ""

An empty SERIAL_PORT disables only the Python serial endpoint; the TCP server
continues to run on port 8765. Restore SERIAL_PORT to the appropriate device
when you want the Python service to provide the original direct serial endpoint.

ESP-AT CONFIGURATION
--------------------
Before compiling the client for ESP mode, edit these definitions near the top
of dashbrd_fixed.c:
  ESP_WIFI_SSID
  ESP_WIFI_PASSWORD
  ESP_HOST_IP       (numeric LAN IPv4 address of the Linux computer)
  ESP_HOST_PORT     (8765 unless you changed the Python service)

Use an SSID/password that do not contain literal double quotes. The ESP module
must be running ESP8266 AT firmware that supports AT+CWMODE, AT+CWJAP,
AT+CIPMUX, AT+CIPSTART, AT+CIPMODE, and transparent AT+CIPSEND. The client
probes 115200 and 9600 baud. If your module uses another baud rate, change the
probe list in try_at_baud() or configure the module to one of these speeds.

The ESP's UART and the Pocket386 COM1 must use compatible 3.3 V signaling at
the ESP side, with proper power and common ground. The ESP-01S needs a stable
3.3 V supply able to handle Wi-Fi current bursts. Do not connect 5 V directly
to ESP VCC or ESP RX.

PYTHON HOST SETUP
-----------------
Edit SERIAL_PORT and BAUD_RATE if required. The service refreshes weather,
stocks, headlines, and sports in independent background workers. It serves
both the original serial interface and TCP port 8765 at the same time unless
SERIAL_PORT is set to an empty string. If the ESP-AT connection is used, allow
TCP port 8765 only from your trusted LAN in the Linux firewall; the endpoint
has no application authentication or TLS.

Install dependencies:
  python3 -m pip install requests pyserial

Run:
  python3 dos_serial_proxy_fixed.py

Replace the example contact address in WEATHER_HEADERS with a real contact
address before deployment. Keep the Linux host clock synchronized.

DOS BUILD / TEST
----------------
Compile dashbrd_fixed.c with Borland C and keep screen_fixed.h in the same
directory. The DOS version has not been compiled with Borland C or tested on
Pocket386 hardware in this environment. The Linux build has been compiled with
GCC and checked with C89/C99 syntax tests. Test direct serial mode first, then
ESP mode. Keep the prior working executable and sources until hardware tests
pass. The DOS screen expects 80x25 color text mode and COM1 at 9600 baud for
direct serial mode.

ESP-AT NOTES
------------
Transparent mode is stateful. The client sends the AT setup commands on launch,
then leaves transparent mode with the documented +++ escape sequence on normal
quit. If the application or Pocket386 is reset unexpectedly while transparent
mode is active, the ESP may remain in data mode; power-cycle the ESP-01S before
relaunching if the client cannot get an AT response. Exact AT responses and
recovery behavior depend on the installed factory firmware version.
