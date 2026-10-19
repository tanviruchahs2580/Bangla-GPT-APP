"""A local fake SMTP server for the sandbox test of the mail path (H-11).

Mailpit is not available in this environment, so the sandbox is built from the
standard library plus ``cryptography`` (already a production dependency):
a threaded SMTP server on 127.0.0.1 with STARTTLS, optional AUTH, recipient
rejection and a captured-message list.

Why not ``aiosmtpd``: it would be a new dev dependency for a test-only need
(see ``.audit/handoffs/pyproject-h2.md``); the command surface the mailer uses
is six verbs, which this implements directly.

TLS is real, not stubbed: the server generates a self-signed certificate for
127.0.0.1 at startup and writes a temporary CA file, which the test points
``SSL_CERT_FILE`` at -- so ``mailer.send_mail``'s production path
(``ssl.create_default_context()`` + ``starttls()``) verifies a real chain
instead of a monkeypatched context.
"""

from __future__ import annotations

import base64
import datetime as dt
import ipaddress
import socket
import socketserver
import ssl
import tempfile
import threading
from dataclasses import dataclass, field
from email import message_from_bytes
from email.message import Message
from email.policy import default as default_policy
from email.utils import parseaddr
from pathlib import Path


@dataclass
class CapturedMessage:
    raw: bytes
    sender: str
    recipients: list[str]

    @property
    def parsed(self) -> Message:
        # EmailPolicy: RFC 2047 encoded words (any Bangla subject) come back
        # as decoded Unicode instead of "=?utf-8?b?...?=".
        return message_from_bytes(self.raw, policy=default_policy)

    @property
    def subject(self) -> str:
        return str(self.parsed.get("Subject") or "")

    @property
    def to(self) -> str:
        return str(self.parsed.get("To") or "")

    @property
    def body(self) -> str:
        """The decoded text body (CTE + charset applied, so Bangla round-trips)."""
        message = self.parsed
        if message.is_multipart():
            for part in message.walk():
                if part.get_content_type() == "text/plain":
                    return str(part.get_content())
            return ""
        return str(message.get_content())


def _self_signed(host: str = "127.0.0.1") -> tuple[str, str, bytes]:
    """(cert_pem_path, key_pem_path, cert_bytes) for 127.0.0.1, temp files."""
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, host)])
    now = dt.datetime.now(dt.UTC)
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - dt.timedelta(minutes=5))
        .not_valid_after(now + dt.timedelta(days=1))
        .add_extension(
            x509.SubjectAlternativeName([x509.IPAddress(ipaddress.ip_address(host))]),
            critical=False,
        )
        .sign(key, hashes.SHA256())
    )
    cert_bytes = cert.public_bytes(serialization.Encoding.PEM)
    key_bytes = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.TraditionalOpenSSL,
        serialization.NoEncryption(),
    )
    # SIM115 is deliberate: both files must outlive this function (ssl needs a
    # path on disk); stop()/the test that owns the server deletes them.
    cert_file = tempfile.NamedTemporaryFile(  # noqa: SIM115
        prefix="h2-fake-smtp-cert-", suffix=".pem", delete=False
    )
    cert_file.write(cert_bytes)
    cert_file.close()
    key_file = tempfile.NamedTemporaryFile(  # noqa: SIM115
        prefix="h2-fake-smtp-key-", suffix=".pem", delete=False
    )
    key_file.write(key_bytes)
    key_file.close()
    return cert_file.name, key_file.name, cert_bytes


class _Handler(socketserver.StreamRequestHandler):
    """One SMTP conversation: EHLO/HELO, STARTTLS, AUTH, MAIL, RCPT, DATA, QUIT.

    ``rbufsize = 0`` is load-bearing: a buffered reader can consume the
    client's TLS ClientHello into its own buffer before ``STARTTLS`` is
    wrapped, and the handshake then deadlocks on bytes the socket never sees
    (the classic STARTTLS buffering bug). Unbuffered reads cost a syscall per
    byte and buy a correct handshake.
    """

    rbufsize = 0
    wbufsize = 0

    def _send(self, line: str) -> None:
        self.wfile.write((line + "\r\n").encode("ascii"))

    def handle(self) -> None:  # noqa: C901 - a state machine reads as one unit
        server: FakeSMTPServer = self.server.fake  # type: ignore[attr-defined]
        self.tls_active = False
        self._send("220 fake-smtp ready")
        authenticated = not server.require_auth
        in_data = False
        data_lines: list[bytes] = []
        sender = ""
        recipients: list[str] = []
        while True:
            raw = self.rfile.readline()
            if not raw:
                return
            line = raw.decode("utf-8", "replace").rstrip("\r\n")
            if in_data:
                if line == ".":
                    in_data = False
                    message = CapturedMessage(
                        raw=b"\r\n".join(data_lines), sender=sender, recipients=recipients
                    )
                    server.messages.append(message)
                    self._send("250 OK queued")
                    sender, recipients = "", []
                else:
                    data_lines.append(raw.rstrip(b"\r\n"))
                continue
            verb, _, rest = line.partition(" ")
            verb = verb.upper()
            if verb in {"EHLO", "HELO"}:
                self._send("250-fake-smtp")
                if not server.require_starttls or self.tls_active:
                    self._send("250-AUTH PLAIN LOGIN")
                # The final line MUST be "250 <feature>" (space, not hyphen):
                # smtplib treats a trailing "250-..." as a continuation and
                # waits forever for the rest of the multiline reply.
                self._send("250 8BITMIME" if self.tls_active else "250 STARTTLS")
            elif verb == "STARTTLS":
                if self.tls_active:
                    self._send("503 already TLS")
                    continue
                if server.tls_context is None:
                    self._send("502 STARTTLS not supported")
                    continue
                self._send("220 go ahead")
                self._tls_wrap(server)
            elif verb == "AUTH":
                if authenticated:
                    self._send("503 already authenticated")
                    continue
                authenticated = self._do_auth(server, rest.strip())
            elif verb == "MAIL":
                sender = parseaddr(rest.split(":", 1)[-1].strip())[1] if ":" in rest else ""
                self._send("250 sender ok")
            elif verb == "RCPT":
                address = parseaddr(rest.split(":", 1)[-1].strip())[1] if ":" in rest else ""
                if address in server.reject_recipients:
                    self._send("550 5.1.1 mailbox unavailable")
                    continue
                recipients.append(address)
                self._send("250 recipient ok")
            elif verb == "DATA":
                if not authenticated:
                    self._send("530 authentication required")
                    continue
                if not recipients:
                    self._send("554 5.5.1 no valid recipients")
                    continue
                in_data = True
                data_lines = []
                self._send("354 end with .")
            elif verb == "RSET":
                sender, recipients = "", []
                self._send("250 reset")
            elif verb == "NOOP":
                self._send("250 ok")
            elif verb == "QUIT":
                self._send("221 bye")
                return
            else:
                self._send("502 command not implemented")

    def _tls_wrap(self, server: FakeSMTPServer) -> None:
        assert server.tls_context is not None
        self.wfile.flush()
        self.connection = server.tls_context.wrap_socket(self.connection, server_side=True)
        # Unbuffered again, for the same reason as rbufsize/wbufsize above: a
        # buffered writer would hold the reply until the conversation ends.
        self.rfile = self.connection.makefile("rb", 0)
        self.wfile = self.connection.makefile("wb", 0)
        self.tls_active = True

    def _do_auth(self, server: FakeSMTPServer, rest: str) -> bool:
        mechanism, _, payload = rest.partition(" ")
        mechanism = mechanism.upper()
        if mechanism == "PLAIN":
            blob = payload.strip()
            if not blob:
                self._send("334 ")
                blob = self.rfile.readline().decode("ascii", "replace").strip()
            try:
                decoded = base64.b64decode(blob).decode("utf-8", "replace")
            except (ValueError, UnicodeError):
                self._send("501 bad base64")
                return False
            parts = decoded.split("\x00")
            _authz, user, password = ([*parts, "", ""])[:3]
        elif mechanism == "LOGIN":
            self._send("334 " + base64.b64encode(b"Username:").decode("ascii"))
            user = base64.b64decode(self.rfile.readline().strip()).decode("utf-8", "replace")
            self._send("334 " + base64.b64encode(b"Password:").decode("ascii"))
            password = base64.b64decode(self.rfile.readline().strip()).decode("utf-8", "replace")
        else:
            self._send("504 mechanism not supported")
            return False
        if user == server.username and password == server.password:
            self._send("235 authenticated")
            return True
        self._send("535 5.7.8 authentication failed")
        return False


class FakeSMTPServer:
    """Threaded fake SMTP server bound to 127.0.0.1 on an ephemeral port."""

    def __init__(
        self,
        *,
        require_starttls: bool = True,
        require_auth: bool = False,
        username: str = "",
        password: str = "",
        reject_recipients: tuple[str, ...] = (),
    ) -> None:
        self.require_starttls = require_starttls
        self.require_auth = require_auth
        self.username = username
        self.password = password
        self.reject_recipients = set(reject_recipients)
        self.messages: list[CapturedMessage] = []
        self.ca_pem: bytes | None = None
        self._cert_file: str | None = None
        self._key_file: str | None = None
        self._httpd: socketserver.ThreadingTCPServer | None = None
        self._thread: threading.Thread | None = None

    @property
    def port(self) -> int:
        assert self._httpd is not None
        return int(self._httpd.server_address[1])

    @property
    def host(self) -> str:
        return "127.0.0.1"

    @property
    def ca_file(self) -> str:
        """Path of the temporary PEM the tests point their trust anchor at."""
        assert self._cert_file is not None, "start() the server first"
        return self._cert_file

    @property
    def tls_context(self) -> ssl.SSLContext | None:
        return self._context

    def start(self) -> FakeSMTPServer:
        self._context: ssl.SSLContext | None = None
        if self.require_starttls:
            self._cert_file, self._key_file, self.ca_pem = _self_signed(self.host)
            context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            context.load_cert_chain(self._cert_file, self._key_file)
            self._context = context
        server = socketserver.ThreadingTCPServer((self.host, 0), _Handler)
        server.daemon_threads = True
        server.fake = self  # type: ignore[attr-defined]
        self._httpd = server
        self._thread = threading.Thread(target=server.serve_forever, daemon=True)
        self._thread.start()
        return self

    def stop(self) -> None:
        if self._httpd is not None:
            self._httpd.shutdown()
            self._httpd.server_close()
        if self._thread is not None:
            self._thread.join(timeout=5)
        for path in (self._cert_file, self._key_file):
            if path:
                Path(path).unlink(missing_ok=True)

    def __enter__(self) -> FakeSMTPServer:
        return self.start()

    def __exit__(self, *_exc: object) -> None:
        self.stop()


@dataclass
class FakeIMAP:
    """A scripted imaplib stand-in: the network boundary is replaced (I3)."""

    script: dict[str, list[bytes]] = field(default_factory=dict)
    logged_in: bool = False
    selected: str = ""
    seen: list[str] = field(default_factory=list)

    def login(self, user: str, password: str) -> tuple[str, list[bytes]]:
        self.logged_in = True
        self.credentials = (user, password)  # type: ignore[attr-defined]
        return "OK", [b"logged in"]

    def select(self, folder: str) -> tuple[str, list[bytes]]:
        self.selected = folder
        return "OK", [b"1"]

    def search(self, _charset: str, criterion: str) -> tuple[str, list[bytes]]:
        return "OK", [b" ".join(key.encode("ascii") for key in self.script)]

    def fetch(self, num: str, _spec: str) -> tuple[str, list[object]]:
        return "OK", [(b"1 (BODY[])", self.script[num][0])]

    def store(self, num: str, _op: str, flag: str) -> tuple[str, list[bytes]]:
        self.seen.append(num)
        return "OK", [flag.encode("ascii")]

    def logout(self) -> tuple[str, list[bytes]]:
        return "BYE", [b"bye"]


def assert_port_free(host: str, port: int) -> None:
    """Small helper used by the tests to prove stop() released the socket."""
    with socket.socket() as probe:
        probe.settimeout(0.5)
        assert probe.connect_ex((host, port)) != 0, f"port {port} still open"
