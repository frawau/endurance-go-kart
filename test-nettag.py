#!/usr/bin/env python3
"""
Test whether a Lantronix/NetTag decoder sends data to multiple
independent UDP endpoints (different local IPs, same port).

Each client binds to a distinct local IP on port 2009, sends an ACK
to register with the decoder, then enters the data/ACK cycle.
Configure a Lantronix endpoint for each local IP.

Usage:
    python3 test-nettag.py <local_ip> [local_ip ...] [--decoder HOST] [--port PORT]

Examples:
    # Single client
    python3 test-nettag.py 192.168.0.100

    # Two clients on different IPs
    python3 test-nettag.py 192.168.0.100 192.168.0.101

    # Custom decoder address
    python3 test-nettag.py 192.168.0.100 192.168.0.101 --decoder 192.168.0.11 --port 2009
"""

import argparse
import socket
import select
import sys
import time

ACK = b"\x1b\x11"

parser = argparse.ArgumentParser(description="Test NetTag multi-endpoint connectivity")
parser.add_argument("local_ips", nargs="+", help="Local IP(s) to bind to")
parser.add_argument(
    "--decoder", default="192.168.0.11", help="Decoder IP (default: 192.168.0.11)"
)
parser.add_argument("--port", type=int, default=2009, help="UDP port (default: 2009)")
args = parser.parse_args()

print(f"Decoder: {args.decoder}:{args.port}")
print(f"Clients: {len(args.local_ips)}")
print(f"Ctrl+C to stop.\n")

sockets = []
for i, ip in enumerate(args.local_ips):
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setblocking(False)
    try:
        sock.bind((ip, args.port))
    except OSError as e:
        print(f"Client {i+1}: failed to bind to {ip}:{args.port}: {e}")
        sys.exit(1)
    print(f"Client {i+1}: bound to {ip}:{args.port}, waiting for data")
    sockets.append(sock)

counts = [0] * len(args.local_ips)
frames = [[] for _ in args.local_ips]
start = time.time()

try:
    while True:
        readable, _, _ = select.select(sockets, [], [], 1.0)
        if not readable:
            continue

        for sock in readable:
            idx = sockets.index(sock)
            data, addr = sock.recvfrom(4096)
            counts[idx] += 1
            elapsed = time.time() - start
            frames[idx].append(data)
            print(
                f"[{elapsed:7.2f}s] Client {idx+1} ({args.local_ips[idx]}): "
                f"{len(data)}B from {addr}: {data[:80]}"
            )
            sock.sendto(ACK, (args.decoder, args.port))

except KeyboardInterrupt:
    pass

elapsed = time.time() - start
print(f"\n\nStopped after {elapsed:.1f}s")
print("Summary:")
for i, c in enumerate(counts):
    print(f"  Client {i+1} ({args.local_ips[i]}): {c} frames received")

if len(args.local_ips) > 1:
    if all(c > 0 for c in counts):
        print("\nAll clients received data - decoder sends to multiple endpoints.")
        if frames[0] == frames[1]:
            print("Frames are identical across clients 1 and 2.")
        else:
            common = len(set(map(bytes, frames[0])) & set(map(bytes, frames[1])))
            print(f"Frames differ. {common} frames in common between client 1 and 2.")
    elif any(c > 0 for c in counts):
        active = [f"{i+1} ({args.local_ips[i]})" for i, c in enumerate(counts) if c > 0]
        inactive = [
            f"{i+1} ({args.local_ips[i]})" for i, c in enumerate(counts) if c == 0
        ]
        print(f"\nOnly client(s) {', '.join(active)} received data.")
        print(f"Client(s) {', '.join(inactive)} got nothing.")
        print("Decoder only responds to one configured endpoint.")
    else:
        print("\nNo client received data.")

for sock in sockets:
    sock.close()
