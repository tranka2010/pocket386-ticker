"""Small HTTPS-capable requests helper for Raspberry Pi Pico W MicroPython.

Supported subset: get(url, headers=None, timeout=None), response.status_code,
response.text, response.close(). Sends Connection: close and supports fixed-
length, connection-close, and chunked HTTP response bodies.

TLS behavior depends on the installed MicroPython firmware. This lightweight
helper does not perform CA certificate validation; use only trusted endpoints
and consider certificate validation if your firmware supports it reliably.
"""
import socket
import ssl


class Response:
    def __init__(self, status_code, headers, body, sock):
        self.status_code = status_code
        self.headers = headers
        self._body = body
        self._sock = sock
        self._closed = False

    @property
    def content(self):
        return self._body

    @property
    def text(self):
        body = self._body
        try:
            return body.decode("utf-8")
        except Exception:
            return body.decode("utf-8", "replace")

    def close(self):
        if not self._closed:
            self._closed = True
            try:
                self._sock.close()
            except Exception:
                pass
            self._body = b""


def _read_all(sock):
    out = bytearray()
    while True:
        chunk = sock.recv(1024)
        if not chunk:
            break
        out.extend(chunk)
    return bytes(out)


def _decode_chunked(body):
    out = bytearray()
    pos = 0
    length = len(body)
    while pos < length:
        end = body.find(b"\r\n", pos)
        if end < 0:
            break
        size_text = body[pos:end].split(b";", 1)[0].strip()
        try:
            size = int(size_text, 16)
        except Exception:
            break
        pos = end + 2
        if size <= 0:
            break
        if pos + size > length:
            break
        out.extend(body[pos:pos + size])
        pos += size
        if body[pos:pos + 2] == b"\r\n":
            pos += 2
    return bytes(out)


def get(url, headers=None, timeout=None, _redirects=0):
    if not (url.startswith("https://") or url.startswith("http://")):
        raise ValueError("Only HTTP and HTTPS URLs are supported")
    secure = url.startswith("https://")
    rest = url[8:] if secure else url[7:]
    slash = rest.find("/")
    if slash < 0:
        host, path = rest, "/"
    else:
        host, path = rest[:slash], rest[slash:]
    if not host:
        raise ValueError("Missing host")
    port = 443 if secure else 80
    if ":" in host:
        host, port_text = host.rsplit(":", 1)
        port = int(port_text)
    sock = None
    try:
        addr = socket.getaddrinfo(host, port, 0, socket.SOCK_STREAM)[0][-1]
        sock = socket.socket()
        if timeout is not None:
            try:
                sock.settimeout(timeout)
            except Exception:
                pass
        sock.connect(addr)
        if secure:
            try:
                sock = ssl.wrap_socket(sock, server_hostname=host)
            except TypeError:
                # Older MicroPython builds may not accept server_hostname.
                sock = ssl.wrap_socket(sock)
        request_headers = {
            "Host": host,
            "User-Agent": "MicroPython-Pocket386/1.0",
            "Connection": "close",
            "Accept": "*/*",
        }
        if headers:
            for key in headers:
                request_headers[key] = headers[key]
        request = "GET {} HTTP/1.0\r\n".format(path)
        for key, value in request_headers.items():
            request += "{}: {}\r\n".format(key, value)
        request += "\r\n"
        sock.send(request.encode())
        raw = _read_all(sock)
        marker = raw.find(b"\r\n\r\n")
        if marker < 0:
            raise OSError("Malformed HTTP response")
        header_bytes = raw[:marker]
        body = raw[marker + 4:]
        lines = header_bytes.split(b"\r\n")
        status_parts = lines[0].split()
        if len(status_parts) < 2:
            raise OSError("Malformed HTTP status line")
        status_code = int(status_parts[1])
        response_headers = {}
        for line in lines[1:]:
            colon = line.find(b":")
            if colon > 0:
                key = line[:colon].decode("ascii", "ignore").strip().lower()
                value = line[colon + 1:].decode("ascii", "ignore").strip()
                response_headers[key] = value
        if status_code in (301, 302, 303, 307, 308) and response_headers.get("location"):
            location = response_headers["location"]
            try:
                sock.close()
            except Exception:
                pass
            if _redirects >= 3:
                raise OSError("Too many HTTP redirects")
            if location.startswith("/"):
                scheme = "https://" if secure else "http://"
                location = scheme + host + location
            return get(location, headers, timeout, _redirects + 1)
        if response_headers.get("transfer-encoding", "").lower() == "chunked":
            body = _decode_chunked(body)
        # HTTP/1.0 Connection: close makes the received body complete at EOF.
        return Response(status_code, response_headers, body, sock)
    except Exception:
        if sock is not None:
            try:
                sock.close()
            except Exception:
                pass
        raise
