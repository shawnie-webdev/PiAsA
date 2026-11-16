#!/usr/bin/env python3
"""Small UDP/TCP DNS forwarder used by PiAsA's piasa-router mode."""
from __future__ import annotations

import argparse
import socket
import socketserver
import struct
import threading


class DNSForwarder:
    def __init__(self, upstream: str, timeout: float = 4.0):
        self.upstream = upstream
        self.timeout = timeout

    def forward(self, packet: bytes, tcp: bool = False) -> bytes:
        if len(packet) < 12:
            raise ValueError("invalid DNS packet")
        if tcp:
            with socket.create_connection((self.upstream, 53), self.timeout) as conn:
                conn.settimeout(self.timeout)
                conn.sendall(struct.pack("!H", len(packet)) + packet)
                size = struct.unpack("!H", self.read_exact(conn, 2))[0]
                response = self.read_exact(conn, size)
        else:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
                sock.settimeout(self.timeout)
                sock.sendto(packet, (self.upstream, 53))
                response, _ = sock.recvfrom(65535)
        if len(response) < 12 or response[:2] != packet[:2]:
            raise ValueError("invalid upstream DNS response")
        return response

    @staticmethod
    def read_exact(conn, count: int) -> bytes:
        data = bytearray()
        while len(data) < count:
            chunk = conn.recv(count - len(data))
            if not chunk:
                raise ConnectionError("DNS TCP connection closed")
            data.extend(chunk)
        return bytes(data)


class UDPHandler(socketserver.BaseRequestHandler):
    def handle(self):
        packet, sock = self.request
        try:
            response = self.server.forwarder.forward(packet)
        except Exception:
            if len(packet) < 12:
                return
            response = bytearray(packet)
            flags = struct.unpack("!H", response[2:4])[0]
            response[2:4] = struct.pack("!H", flags | 0x8002)
            response = bytes(response)
        sock.sendto(response, self.client_address)


class TCPHandler(socketserver.BaseRequestHandler):
    def handle(self):
        try:
            size = struct.unpack("!H", DNSForwarder.read_exact(self.request, 2))[0]
            packet = DNSForwarder.read_exact(self.request, size)
            response = self.server.forwarder.forward(packet, tcp=True)
            self.request.sendall(struct.pack("!H", len(response)) + response)
        except Exception:
            return


class ThreadedUDP(socketserver.ThreadingMixIn, socketserver.UDPServer):
    allow_reuse_address = True
    daemon_threads = True


class ThreadedTCP(socketserver.ThreadingMixIn, socketserver.TCPServer):
    allow_reuse_address = True
    daemon_threads = True


def main():
    parser = argparse.ArgumentParser(description="PiAsA DNS forwarder")
    parser.add_argument("--listen", default="192.168.7.1")
    parser.add_argument("--upstream", default="1.1.1.1")
    args = parser.parse_args()
    forwarder = DNSForwarder(args.upstream)
    udp = ThreadedUDP((args.listen, 53), UDPHandler)
    tcp = ThreadedTCP((args.listen, 53), TCPHandler)
    udp.forwarder = forwarder
    tcp.forwarder = forwarder
    threading.Thread(target=tcp.serve_forever, daemon=True).start()
    try:
        udp.serve_forever()
    finally:
        udp.server_close()
        tcp.shutdown()
        tcp.server_close()


if __name__ == "__main__":
    main()
