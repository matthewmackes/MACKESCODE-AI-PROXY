import struct
import unittest

from src.console.services.websocket import WebSocketProtocolService


class FakeConn:
    def __init__(self, data=b""):
        self.data = bytearray(data)
        self.sent = b""

    def recv(self, size):
        chunk = self.data[:size]
        del self.data[:size]
        return bytes(chunk)

    def sendall(self, data):
        self.sent += data


class WebSocketProtocolServiceTests(unittest.TestCase):
    def service(self, ready=True, ioctl_calls=None):
        def select_func(reads, writes, errors, timeout):
            return (reads if ready else [], [], [])

        return WebSocketProtocolService(
            select_func=select_func,
            ioctl_func=lambda *args: ioctl_calls.append(args) if ioctl_calls is not None else None,
            clock=lambda: 1000,
        )

    def masked_frame(self, text, opcode=1):
        payload = text.encode("utf-8")
        mask = b"\x01\x02\x03\x04"
        masked = bytes(byte ^ mask[i % 4] for i, byte in enumerate(payload))
        return bytes([0x80 | opcode, 0x80 | len(payload)]) + mask + masked

    def test_accept_key_matches_websocket_spec_example(self):
        service = self.service()
        self.assertEqual(service.accept_key("dGhlIHNhbXBsZSBub25jZQ=="), "s3pPLMBiTxaQ9kYGzzhZRbK+xOo=")

    def test_recv_exact_reads_chunks_and_times_out_when_not_ready(self):
        service = self.service()
        self.assertEqual(service.recv_exact(FakeConn(b"hello"), 5), b"hello")

        timeout_service = self.service(ready=False)
        self.assertIsNone(timeout_service.recv_exact(FakeConn(b"hello"), 5))

    def test_read_frame_decodes_masked_text_and_extended_length(self):
        service = self.service()
        self.assertEqual(service.read_frame(FakeConn(self.masked_frame("hello"))), "hello")

        payload = b"a" * 130
        frame = bytes([0x81, 126]) + struct.pack("!H", len(payload)) + payload
        self.assertEqual(service.read_frame(FakeConn(frame)), "a" * 130)

    def test_read_frame_handles_ping_and_close(self):
        service = self.service()
        self.assertEqual(service.read_frame(FakeConn(self.masked_frame("ping", opcode=9))), {"ping": b"ping"})
        self.assertIsNone(service.read_frame(FakeConn(bytes([0x88, 0]))))

    def test_send_uses_short_and_extended_lengths(self):
        service = self.service()
        short = FakeConn()
        service.send(short, "hi")
        self.assertEqual(short.sent, b"\x81\x02hi")

        long = FakeConn()
        service.send(long, "a" * 130)
        self.assertEqual(long.sent[:4], b"\x81\x7e\x00\x82")
        self.assertEqual(long.sent[4:], b"a" * 130)

    def test_set_pty_size_swallows_bad_values_and_calls_ioctl_for_good_values(self):
        calls = []
        service = self.service(ioctl_calls=calls)
        service.set_pty_size(10, 24, 80)
        service.set_pty_size(10, "bad", 80)

        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][0], 10)
        self.assertEqual(len(calls[0][2]), 8)


if __name__ == "__main__":
    unittest.main()
