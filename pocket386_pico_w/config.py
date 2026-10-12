"""Pocket386 Dashboard Pico W configuration.

Edit Wi-Fi credentials and the weather contact string before deployment.
"""
WIFI_SSID = "YOUR_WIFI_SSID"
WIFI_PASSWORD = "YOUR_WIFI_PASSWORD"

# Waltham, MA; change coordinates and display label if desired.
WEATHER_LAT = "42.3765"
WEATHER_LON = "-71.2356"
WEATHER_LABEL = "Waltham, MA"
WEATHER_USER_AGENT = "Pocket386Dashboard (replace-with-your-contact-email@example.com)"

# Pocket386 serial protocol: 9600 baud, 8 data bits, no parity, 1 stop bit.
# Pico W UART0 default pins are GP0=TX and GP1=RX. Change if your wiring differs.
UART_ID = 0
UART_TX_PIN = 0
UART_RX_PIN = 1
UART_BAUD = 9600

# Optional TCP endpoint; the Pocket386 client itself remains unchanged and uses
# its existing serial path. TCP is useful for diagnostics or a future bridge.
ENABLE_TCP = True
TCP_PORT = 8765

WEATHER_INTERVAL = 600
STOCKS_INTERVAL = 60
HEADLINES_INTERVAL = 300
SPORTS_INTERVAL = 30

HTTP_TIMEOUT_SECONDS = 6
TCP_IDLE_TIMEOUT_SECONDS = 180
MAX_TCP_CLIENTS = 2
