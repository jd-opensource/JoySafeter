"""Local TLS material for the HTTPS cells.

``trustme`` is not installed in the backend venv, so we mint a CA + leaf cert
directly with ``cryptography``. The leaf SAN covers every name/IP a cell might
use to reach an https server (see ``matrix.CERT_SAN_HOSTS`` / ``CERT_SAN_IPS``)
so TLS validation succeeds regardless of the host form.
"""

from __future__ import annotations

import datetime as _dt
import ipaddress
import tempfile
from dataclasses import dataclass
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID


@dataclass(frozen=True)
class TlsMaterial:
    """Filesystem paths to the generated PEM material."""

    ca_cert_path: str
    server_cert_path: str
    server_key_path: str
    dir: str


def _san_entries(hosts: list[str], ips: list[str]) -> list[x509.GeneralName]:
    entries: list[x509.GeneralName] = [x509.DNSName(h) for h in hosts]
    for ip in ips:
        try:
            entries.append(x509.IPAddress(ipaddress.ip_address(ip)))
        except ValueError:
            # Not a literal IP — treat as a DNS name instead of dropping it.
            entries.append(x509.DNSName(ip))
    return entries


def generate_tls_material(hosts: list[str], ips: list[str]) -> TlsMaterial:
    """Generate a CA and a leaf cert (SAN = hosts + ips), written as PEM files."""
    out_dir = Path(tempfile.mkdtemp(prefix="jsf-mcp-tls-"))
    now = _dt.datetime.now(_dt.timezone.utc)
    not_before = now - _dt.timedelta(minutes=5)
    not_after = now + _dt.timedelta(days=2)

    # --- CA ---
    ca_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    ca_name = x509.Name(
        [x509.NameAttribute(NameOID.COMMON_NAME, "JoySafeter MCP Test CA")]
    )
    ca_cert = (
        x509.CertificateBuilder()
        .subject_name(ca_name)
        .issuer_name(ca_name)
        .public_key(ca_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(not_before)
        .not_valid_after(not_after)
        .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
        .add_extension(
            x509.KeyUsage(
                digital_signature=True,
                key_cert_sign=True,
                crl_sign=True,
                key_encipherment=False,
                content_commitment=False,
                data_encipherment=False,
                key_agreement=False,
                encipher_only=False,
                decipher_only=False,
            ),
            critical=True,
        )
        .add_extension(
            x509.SubjectKeyIdentifier.from_public_key(ca_key.public_key()),
            critical=False,
        )
        .sign(ca_key, hashes.SHA256())
    )

    # --- leaf ---
    leaf_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    leaf_name = x509.Name(
        [x509.NameAttribute(NameOID.COMMON_NAME, hosts[0] if hosts else "localhost")]
    )
    leaf_cert = (
        x509.CertificateBuilder()
        .subject_name(leaf_name)
        .issuer_name(ca_name)
        .public_key(leaf_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(not_before)
        .not_valid_after(not_after)
        .add_extension(
            x509.SubjectAlternativeName(_san_entries(hosts, ips)), critical=False
        )
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .add_extension(
            x509.ExtendedKeyUsage(
                [x509.ObjectIdentifier("1.3.6.1.5.5.7.3.1")]
            ),  # serverAuth
            critical=False,
        )
        .add_extension(
            x509.SubjectKeyIdentifier.from_public_key(leaf_key.public_key()),
            critical=False,
        )
        .add_extension(
            x509.AuthorityKeyIdentifier.from_issuer_public_key(ca_key.public_key()),
            critical=False,
        )
        .sign(ca_key, hashes.SHA256())
    )

    ca_cert_path = out_dir / "ca.pem"
    server_cert_path = out_dir / "server.pem"
    server_key_path = out_dir / "server.key"

    ca_cert_path.write_bytes(ca_cert.public_bytes(serialization.Encoding.PEM))
    server_cert_path.write_bytes(leaf_cert.public_bytes(serialization.Encoding.PEM))
    server_key_path.write_bytes(
        leaf_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.TraditionalOpenSSL,
            encryption_algorithm=serialization.NoEncryption(),
        )
    )

    return TlsMaterial(
        ca_cert_path=str(ca_cert_path),
        server_cert_path=str(server_cert_path),
        server_key_path=str(server_key_path),
        dir=str(out_dir),
    )
