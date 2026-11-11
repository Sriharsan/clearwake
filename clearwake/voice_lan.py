"""Serve the console over https on this laptop's private LAN address, so a phone on the same Wi-Fi can use the microphone.

Browsers allow the microphone only on https or localhost. This makes a short lived self signed certificate on this machine
(data/voice-tls/, git ignored), binds only to the private LAN address, and keeps every console protection: the session
cookie, the CSRF token, the host check (the LAN address and loopback are the only hosts accepted), and no cross site writes.

    set CLEARWAKE_VOICE_LAN=1        (PowerShell: $env:CLEARWAKE_VOICE_LAN = "1")
    python -m clearwake --voice-lan
"""
import argparse
from datetime import datetime, timedelta, timezone
import ipaddress
import os
from pathlib import Path
import socket
import ssl
import sys

ROOT = Path(__file__).resolve().parent.parent
TLS_DIR = ROOT / "data" / "voice-tls"
DEFAULT_PORT = 8863
CERT_DAYS = 30


def lan_address(preferred=None):
    """The private IPv4 address of this machine on its LAN. Refuses loopback, link local and public addresses."""
    if preferred:
        found = preferred
    else:
        probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            probe.connect(("10.255.255.255", 1))     # a UDP connect sends nothing; it only picks the outgoing interface
            found = probe.getsockname()[0]
        except OSError:
            raise SystemExit("No LAN address found. Connect to Wi-Fi or Ethernet and run again.")
        finally:
            probe.close()
    ip = ipaddress.ip_address(found)
    if ip.version != 4 or not ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_unspecified or ip.is_multicast:
        raise SystemExit(f"{found} is not a private LAN address. Voice over LAN binds to private addresses only.")
    return str(ip)


def make_certificate(ip, folder=TLS_DIR, days=CERT_DAYS):
    """A self signed certificate for this LAN address, loopback and localhost. Reused while it is valid and names this address."""
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.x509.oid import NameOID
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    cert_path, key_path = folder / "voice.crt", folder / "voice.key"
    if cert_path.exists() and key_path.exists():
        try:
            current = x509.load_pem_x509_certificate(cert_path.read_bytes())
            names = current.extensions.get_extension_for_class(x509.SubjectAlternativeName).value.get_values_for_type(x509.IPAddress)
            if ipaddress.ip_address(ip) in names and current.not_valid_after_utc > datetime.now(timezone.utc) + timedelta(days=2):
                return cert_path, key_path, current.fingerprint(hashes.SHA256()).hex()
        except Exception:
            pass
    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Clearwake voice on this laptop")])
    now = datetime.now(timezone.utc)
    cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
            .serial_number(x509.random_serial_number()).not_valid_before(now - timedelta(minutes=5)).not_valid_after(now + timedelta(days=days))
            .add_extension(x509.SubjectAlternativeName([x509.IPAddress(ipaddress.ip_address(ip)), x509.IPAddress(ipaddress.ip_address("127.0.0.1")),
                                                        x509.DNSName("localhost")]), critical=False)
            .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
            .add_extension(x509.ExtendedKeyUsage([x509.oid.ExtendedKeyUsageOID.SERVER_AUTH]), critical=False)
            .sign(key, hashes.SHA256()))
    key_path.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
    try:
        os.chmod(key_path, 0o600)
    except OSError:
        pass
    cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    return cert_path, key_path, cert.fingerprint(hashes.SHA256()).hex()


def qr_ascii(url):
    """The URL as an ASCII QR code if a QR library is already installed, else None."""
    try:
        import qrcode
        code = qrcode.QRCode(border=1)
        code.add_data(url)
        code.make(fit=True)
        rows = code.get_matrix()
        return "\n".join("".join("##" if cell else "  " for cell in row) for row in rows)
    except Exception:
        pass
    try:
        import segno
        import io
        out = io.StringIO()
        segno.make(url).terminal(out=out, compact=True)
        return out.getvalue()
    except Exception:
        return None


def build_server(controller, console, ip, port, cert, key, hosted_limits=True):
    """A ClearwakeServer bound to ip only, wrapped in TLS, accepting only this LAN host and loopback."""
    from .server import ClearwakeServer, RateLimiter
    server = ClearwakeServer((ip, port), controller, console, hosted=True)    # hosted=True only lets the socket bind beyond loopback
    server.hosted = False                                                    # not a hosted deployment: no wipe on reset, plain local data
    console.hosted = False
    server.allowed_hosts = set()
    server.lan_hosts = {f"{ip}:{port}", f"127.0.0.1:{port}", f"localhost:{port}"}
    if hosted_limits:
        server.limiter = RateLimiter({"read": 240, "write": 40, "voice": 12})
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    context.load_cert_chain(str(cert), str(key))
    # Handshake per connection in its own thread, so one stalled phone cannot block the accept loop.
    server.socket = context.wrap_socket(server.socket, server_side=True, do_handshake_on_connect=False)
    original_handle_error = server.handle_error

    def quiet(request, client_address):
        if isinstance(sys.exc_info()[1], (ssl.SSLError, ConnectionError, TimeoutError, OSError)):
            return    # a phone that has not yet accepted the certificate, or a dropped connection
        original_handle_error(request, client_address)
    server.handle_error = quiet
    plain_finish = server.finish_request

    def finish(request, client_address):
        request.settimeout(10)
        request.do_handshake()
        plain_finish(request, client_address)
    server.finish_request = finish
    return server


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--lan-ip", default=None, help="Use this private address instead of the detected one")
    parser.add_argument("--database", type=Path, default=ROOT / "data" / "clearwake.sqlite3")
    parser.add_argument("--console-model", choices=("scripted", "ollama"), default="scripted")
    args = parser.parse_args(argv)
    if os.environ.get("CLEARWAKE_VOICE_LAN") != "1":
        raise SystemExit("Voice over the LAN is off. Set CLEARWAKE_VOICE_LAN=1 to serve this laptop's console to your phone on your own Wi-Fi.")
    if not 1024 <= args.port <= 65535:
        raise SystemExit("port must be between 1024 and 65535")
    from .console import Console
    from .controller import RefundController
    from .paypal import LocalGateway
    ip = lan_address(args.lan_ip)
    cert, key, fingerprint = make_certificate(ip)
    database = args.database.resolve()
    database.parent.mkdir(parents=True, exist_ok=True)
    controller = RefundController(database, gateway=LocalGateway(database.with_name("local-provider.sqlite3"), "completed"))
    console = Console(database.parent / "console", args.console_model)
    server = build_server(controller, console, ip, args.port, cert, key)
    url = f"https://{ip}:{args.port}/voice"
    print(f"Clearwake voice on your LAN, https only, bound to {ip} (not 0.0.0.0).")
    print(f"Open on the phone (same Wi-Fi): {url}")
    qr = qr_ascii(url)
    if qr:
        print(qr)
    print(f"Certificate: {cert} (self signed, valid {CERT_DAYS} days). SHA-256 {fingerprint[:32]}")
    print("The phone shows a one time certificate warning because the certificate is made here. Continue past it once.")
    print("Speech to text runs on this laptop. Press Ctrl+C here to stop.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        controller.close()


if __name__ == "__main__":
    main()
