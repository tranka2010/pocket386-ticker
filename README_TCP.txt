POCKET386 DASHBOARD — DIRECT TCP / mTCP VARIANT
================================================

FILES
-----
dashbrd_tcp.c       New Borland C 3.0 client variant with /TCP transport
screen_fixed.h      Existing VGA text-mode helper header
README_TCP.txt      This file

WHAT THIS VARIANT DOES
----------------------
The dashboard display and GET / @END data protocol are preserved. Run:

    DASHBRD /TCP

The client launches the mTCP Netcat utility (NC.EXE) for each refresh, sends
"GET" through redirected standard input, captures the server response in
DASHRSP.TXT, and renders the existing dashboard records. This uses Ethernet
and mTCP directly; there is no serial cable or ESP module in the data path.

IMPORTANT COMPILER / mTCP COMPATIBILITY NOTE
--------------------------------------------
This is intentionally an external-NC transport bridge rather than a direct
in-process socket implementation. mTCP networking is normally compiled into
each mTCP application; it is not a resident TCP socket service that a random
Borland C program can call. Current official mTCP sources are built with Open
Watcom, so linking their TCP stack into Borland C 3.0 is not a straightforward
or verified combination. Using the installed NC.EXE avoids that toolchain
mismatch while allowing this client to be built with Borland C 3.0.

REQUIREMENTS
------------
1. The Pocket386 Ethernet card's packet driver is loaded.
2. mTCP is configured as it is for your working mTCP applications (MTCPCFG /
   TCP.CFG as appropriate).
3. NC.EXE from mTCP is in the current directory or on PATH.
4. The Python server is running on the LAN and listening on TCP port 8765.
5. TCP_HOST_IP in dashbrd_tcp.c is changed to the numeric LAN IPv4 address of
   the Linux/Python server. TCP_HOST_PORT defaults to 8765.
6. Allow that port through the server's LAN firewall, restricted to your
   trusted local network.

BUILD WITH BORLAND C 3.0
-----------------------
Keep dashbrd_tcp.c and screen_fixed.h in the same directory. Edit TCP_HOST_IP
near the top of dashbrd_tcp.c, then compile from the Borland C directory, for
example:

    BCC DASHBRD_TCP.C

Use the output executable name DASHBRD.EXE (rename it if Borland produces a
name based on the source file). Keep the original DASHBRD.EXE and original
source files as backups. If your Borland setup requires explicit include or
library paths, use the same options as your working build of the existing
client.

TESTING
-------
1. From DOS, verify NC itself works with the server before testing the UI.
   A simple mTCP Netcat command uses this form:

       NC -target 192.168.1.100 8765 -w 3 < DASHGET.TXT > DASHRSP.TXT

   DASHGET.TXT should contain GET followed by a newline. Substitute the real
   server IP. DASHRSP.TXT should end with @END.
2. Run DASHBRD /TCP.
3. Press F5 to refresh; press Q or Esc to exit.
4. If it reports an incomplete response, verify the server IP, TCP port,
   mTCP packet driver/configuration, NC.EXE location, and firewall.

NOTES / LIMITATIONS
-------------------
- NC.EXE is launched for each refresh, so TCP refreshes are not as seamless as
  a persistent in-process socket. The -w 3 option allows the server response
  to arrive after GET input reaches EOF; each refresh may take a few seconds.
- The client requires numeric IPv4 in TCP_HOST_IP (no DNS dependency).
- The existing Python server's TCP endpoint has no authentication or TLS;
  keep it restricted to a trusted LAN.
- Source was adapted from the existing client, but Borland C 3.0 compilation
  and real Pocket386/mTCP hardware behavior have not been tested here.
