"""
Docker TLS certificate generation and management

Generates and manages TLS certificates for secure Docker Remote API communication.
"""

import subprocess
from pathlib import Path
from typing import Tuple

from loguru import logger


class DockerTLSSetup:
    """
    Docker TLS certificate setup and management

    Generates CA, server, and client certificates for secure Docker daemon communication.
    """

    def __init__(self, cert_dir: str = "~/.docker"):
        """
        Initialize TLS setup

        Args:
            cert_dir: Directory to store certificates (default ~/.docker)
        """
        self.cert_dir = Path(cert_dir).expanduser()
        self.cert_dir.mkdir(parents=True, exist_ok=True)
        logger.info(f"TLS setup initialized with cert_dir: {self.cert_dir}")

    @staticmethod
    def check_openssl() -> bool:
        """Check if OpenSSL is installed"""
        try:
            result = subprocess.run(["openssl", "version"], capture_output=True, timeout=5)
            return result.returncode == 0
        except (FileNotFoundError, subprocess.TimeoutExpired) as e:
            logger.debug(f"OpenSSL check failed: {e}")
            return False

    def generate_ca_cert(
        self,
        ca_name: str = "ca",
        days: int = 3650,
    ) -> Tuple[bool, str]:
        """
        Generate CA certificate

        Args:
            ca_name: CA certificate name (without extension)
            days: Certificate validity days (default 10 years)

        Returns:
            Tuple of (success, message)
        """
        try:
            if not self.check_openssl():
                return False, "OpenSSL not installed"

            ca_key = self.cert_dir / f"{ca_name}-key.pem"
            ca_cert = self.cert_dir / f"{ca_name}.pem"

            # Generate CA private key
            cmd = ["openssl", "genrsa", "-out", str(ca_key), "2048"]
            result = subprocess.run(cmd, capture_output=True, timeout=30)
            if result.returncode != 0:
                return False, f"Failed to generate CA key: {result.stderr.decode()}"

            # Generate CA certificate
            cmd = [
                "openssl",
                "req",
                "-new",
                "-x509",
                "-days",
                str(days),
                "-key",
                str(ca_key),
                "-out",
                str(ca_cert),
                "-subj",
                "/CN=Docker-CA",
            ]
            result = subprocess.run(cmd, capture_output=True, timeout=30)
            if result.returncode != 0:
                return False, f"Failed to generate CA cert: {result.stderr.decode()}"

            logger.info(f"CA certificate generated: {ca_cert}")
            return True, f"CA certificate generated: {ca_cert}"

        except Exception as e:
            return False, f"Error generating CA cert: {str(e)}"

    def generate_server_cert(
        self,
        server_name: str,
        ca_name: str = "ca",
        days: int = 365,
    ) -> Tuple[bool, str]:
        """
        Generate server certificate

        Args:
            server_name: Server name or IP (e.g., 192.168.1.10 or docker.example.com)
            ca_name: CA certificate name
            days: Certificate validity days (default 1 year)

        Returns:
            Tuple of (success, message)
        """
        try:
            if not self.check_openssl():
                return False, "OpenSSL not installed"

            ca_key = self.cert_dir / f"{ca_name}-key.pem"
            ca_cert = self.cert_dir / f"{ca_name}.pem"

            if not ca_key.exists() or not ca_cert.exists():
                return False, "CA certificate not found. Generate CA first."

            server_key = self.cert_dir / f"{server_name}-key.pem"
            server_csr = self.cert_dir / f"{server_name}.csr"
            server_cert = self.cert_dir / f"{server_name}.pem"

            # Generate server private key
            cmd = ["openssl", "genrsa", "-out", str(server_key), "2048"]
            result = subprocess.run(cmd, capture_output=True, timeout=30)
            if result.returncode != 0:
                return False, f"Failed to generate server key: {result.stderr.decode()}"

            # Generate server CSR (Certificate Signing Request)
            cmd = [
                "openssl",
                "req",
                "-new",
                "-key",
                str(server_key),
                "-out",
                str(server_csr),
                "-subj",
                f"/CN={server_name}",
            ]
            result = subprocess.run(cmd, capture_output=True, timeout=30)
            if result.returncode != 0:
                return False, f"Failed to generate server CSR: {result.stderr.decode()}"

            # Create extensions file for SAN (Subject Alternative Name)
            ext_file = self.cert_dir / f"{server_name}.ext"
            ext_content = f"""subjectAltName = IP:{server_name},DNS:{server_name}
extendedKeyUsage = serverAuth
"""
            ext_file.write_text(ext_content)

            # Sign server certificate with CA
            cmd = [
                "openssl",
                "x509",
                "-req",
                "-days",
                str(days),
                "-in",
                str(server_csr),
                "-CA",
                str(ca_cert),
                "-CAkey",
                str(ca_key),
                "-CAcreateserial",
                "-out",
                str(server_cert),
                "-extfile",
                str(ext_file),
            ]
            result = subprocess.run(cmd, capture_output=True, timeout=30)
            if result.returncode != 0:
                return False, f"Failed to sign server cert: {result.stderr.decode()}"

            # Clean up CSR and ext file
            server_csr.unlink()
            ext_file.unlink()

            logger.info(f"Server certificate generated: {server_cert}")
            return True, f"Server certificate generated: {server_cert}"

        except Exception as e:
            return False, f"Error generating server cert: {str(e)}"

    def generate_client_cert(
        self,
        client_name: str,
        ca_name: str = "ca",
        days: int = 365,
    ) -> Tuple[bool, str]:
        """
        Generate client certificate

        Args:
            client_name: Client name (e.g., client, admin)
            ca_name: CA certificate name
            days: Certificate validity days (default 1 year)

        Returns:
            Tuple of (success, message)
        """
        try:
            if not self.check_openssl():
                return False, "OpenSSL not installed"

            ca_key = self.cert_dir / f"{ca_name}-key.pem"
            ca_cert = self.cert_dir / f"{ca_name}.pem"

            if not ca_key.exists() or not ca_cert.exists():
                return False, "CA certificate not found. Generate CA first."

            client_key = self.cert_dir / f"{client_name}-key.pem"
            client_csr = self.cert_dir / f"{client_name}.csr"
            client_cert = self.cert_dir / f"{client_name}.pem"

            # Generate client private key
            cmd = ["openssl", "genrsa", "-out", str(client_key), "2048"]
            result = subprocess.run(cmd, capture_output=True, timeout=30)
            if result.returncode != 0:
                return False, f"Failed to generate client key: {result.stderr.decode()}"

            # Generate client CSR
            cmd = [
                "openssl",
                "req",
                "-new",
                "-key",
                str(client_key),
                "-out",
                str(client_csr),
                "-subj",
                f"/CN={client_name}",
            ]
            result = subprocess.run(cmd, capture_output=True, timeout=30)
            if result.returncode != 0:
                return False, f"Failed to generate client CSR: {result.stderr.decode()}"

            # Create extensions file for client auth
            ext_file = self.cert_dir / f"{client_name}.ext"
            ext_content = "extendedKeyUsage = clientAuth\n"
            ext_file.write_text(ext_content)

            # Sign client certificate with CA
            cmd = [
                "openssl",
                "x509",
                "-req",
                "-days",
                str(days),
                "-in",
                str(client_csr),
                "-CA",
                str(ca_cert),
                "-CAkey",
                str(ca_key),
                "-CAcreateserial",
                "-out",
                str(client_cert),
                "-extfile",
                str(ext_file),
            ]
            result = subprocess.run(cmd, capture_output=True, timeout=30)
            if result.returncode != 0:
                return False, f"Failed to sign client cert: {result.stderr.decode()}"

            # Clean up CSR and ext file
            client_csr.unlink()
            ext_file.unlink()

            logger.info(f"Client certificate generated: {client_cert}")
            return True, f"Client certificate generated: {client_cert}"

        except Exception as e:
            return False, f"Error generating client cert: {str(e)}"

    def setup_complete_tls(
        self,
        server_name: str,
        client_name: str = "client",
        ca_name: str = "ca",
    ) -> Tuple[bool, str]:
        """
        Setup complete TLS infrastructure (CA + Server + Client certs)

        Args:
            server_name: Server name or IP
            client_name: Client name
            ca_name: CA name

        Returns:
            Tuple of (success, message)
        """
        try:
            # Generate CA
            success, msg = self.generate_ca_cert(ca_name)
            if not success:
                return False, f"CA generation failed: {msg}"
            print(f"✓ {msg}")

            # Generate server cert
            success, msg = self.generate_server_cert(server_name, ca_name)
            if not success:
                return False, f"Server cert generation failed: {msg}"
            print(f"✓ {msg}")

            # Generate client cert
            success, msg = self.generate_client_cert(client_name, ca_name)
            if not success:
                return False, f"Client cert generation failed: {msg}"
            print(f"✓ {msg}")

            return True, "TLS setup complete"

        except Exception as e:
            return False, f"Error in TLS setup: {str(e)}"

    def get_cert_paths(
        self,
        server_name: str,
        client_name: str = "client",
        ca_name: str = "ca",
    ) -> dict:
        """
        Get paths to all certificates

        Args:
            server_name: Server name
            client_name: Client name
            ca_name: CA name

        Returns:
            Dict with certificate paths
        """
        return {
            "ca_cert": str(self.cert_dir / f"{ca_name}.pem"),
            "ca_key": str(self.cert_dir / f"{ca_name}-key.pem"),
            "server_cert": str(self.cert_dir / f"{server_name}.pem"),
            "server_key": str(self.cert_dir / f"{server_name}-key.pem"),
            "client_cert": str(self.cert_dir / f"{client_name}.pem"),
            "client_key": str(self.cert_dir / f"{client_name}-key.pem"),
        }

    def verify_cert(self, cert_path: str) -> Tuple[bool, str]:
        """
        Verify certificate validity

        Args:
            cert_path: Path to certificate file

        Returns:
            Tuple of (valid, message)
        """
        try:
            if not Path(cert_path).exists():
                return False, f"Certificate not found: {cert_path}"

            cmd = ["openssl", "x509", "-in", cert_path, "-text", "-noout"]
            result = subprocess.run(cmd, capture_output=True, timeout=10)

            if result.returncode != 0:
                return False, f"Invalid certificate: {result.stderr.decode()}"

            # Extract expiration date
            output = result.stdout.decode()
            if "Not After" in output:
                for line in output.split("\n"):
                    if "Not After" in line:
                        return True, f"Certificate valid: {line.strip()}"

            return True, "Certificate is valid"

        except Exception as e:
            return False, f"Error verifying certificate: {str(e)}"

    def list_certificates(self) -> dict:
        """List all certificates in cert directory"""
        certs = {}
        for cert_file in self.cert_dir.glob("*.pem"):
            certs[cert_file.name] = str(cert_file)
        return certs
