"""Small WebSocket protocol helpers for terminal bridges."""
import base64
import hashlib
import struct
import time


class WebSocketProtocolService:
    """Owns WebSocket accept-key, frame parsing, sending, and PTY sizing."""

    def __init__(self, select_func, ioctl_func, clock=None):
        self.select_func = select_func
        self.ioctl_func = ioctl_func
        self.clock = clock or time.time

    def accept_key(self, key):
        raw = (key + "258EAFA5-E914-47DA-95CA-C5AB0DC85B11").encode("ascii")
        return base64.b64encode(hashlib.sha1(raw).digest()).decode("ascii")

    def recv_exact(self, conn, size, timeout=2.0):
        chunks = []
        remaining = size
        deadline = self.clock() + timeout
        while remaining > 0:
            wait = deadline - self.clock()
            if wait <= 0:
                return None
            ready, _, _ = self.select_func([conn], [], [], wait)
            if not ready:
                return None
            try:
                chunk = conn.recv(remaining)
            except BlockingIOError:
                continue
            if not chunk:
                return None
            chunks.append(chunk)
            remaining -= len(chunk)
        return b"".join(chunks)

    def read_frame(self, conn):
        header = self.recv_exact(conn, 2)
        if not header:
            return None
        first, second = header
        opcode = first & 0x0F
        masked = second & 0x80
        length = second & 0x7F
        if length == 126:
            data = self.recv_exact(conn, 2)
            if not data:
                return None
            length = struct.unpack("!H", data)[0]
        elif length == 127:
            data = self.recv_exact(conn, 8)
            if not data:
                return None
            length = struct.unpack("!Q", data)[0]
        mask = self.recv_exact(conn, 4) if masked else b""
        if masked and mask is None:
            return None
        payload = self.recv_exact(conn, length) if length else b""
        if payload is None:
            return None
        if masked:
            payload = bytes(byte ^ mask[i % 4] for i, byte in enumerate(payload))
        if opcode == 8:
            return None
        if opcode == 9:
            return {"ping": payload}
        return payload.decode("utf-8", errors="replace")

    def send(self, conn, text):
        payload = text.encode("utf-8", errors="replace")
        header = bytearray([0x81])
        length = len(payload)
        if length < 126:
            header.append(length)
        elif length < 65536:
            header.append(126)
            header.extend(struct.pack("!H", length))
        else:
            header.append(127)
            header.extend(struct.pack("!Q", length))
        conn.sendall(bytes(header) + payload)

    def set_pty_size(self, fd, rows, cols):
        try:
            import termios
            self.ioctl_func(fd, termios.TIOCSWINSZ, struct.pack("HHHH", int(rows), int(cols), 0, 0))
        except Exception:
            pass
