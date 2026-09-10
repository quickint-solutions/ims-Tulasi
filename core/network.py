"""LAN address helpers for on-premise hosting.

The QR code on every printed label encodes an absolute URL. When the system is
hosted inside the plant on a private IP, that IP becomes part of the physical
sticker - so it must be stable. See docs/LOCAL_HOSTING.md.
"""
import socket


def detect_lan_ip(default="127.0.0.1"):
    """Best-effort private IPv4 address of this machine.

    Opens a UDP socket towards a public address - no packet is actually sent -
    and reads back which local interface the OS would route through. This is
    more reliable than gethostbyname(hostname), which returns 127.0.1.1 on many
    Linux setups and the wrong adapter on multi-homed Windows boxes.
    """
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.settimeout(0.4)
        sock.connect(("10.255.255.255", 1))
        return sock.getsockname()[0]
    except OSError:
        try:
            return socket.gethostbyname(socket.gethostname())
        except OSError:
            return default
    finally:
        sock.close()


def is_private(address):
    import ipaddress
    try:
        return ipaddress.ip_address(address).is_private
    except ValueError:
        return False
