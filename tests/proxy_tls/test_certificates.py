import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
import re
import shutil
import ssl
import subprocess

import pytest

from foghttp_benchmark.proxy_connect.proxy_server import generate_localhost_certificate


HANDSHAKE_TIMEOUT_S = 5
TLS_PAYLOAD = b"verified TLS response"
UNTRUSTED_ISSUER_CODE = 20
HOSTNAME_MISMATCH_CODE = 62


@dataclass(frozen=True)
class CertificateChain:
    ca: Path
    leaf: Path
    key: Path


@pytest.fixture(scope="module")
def certificate_chains(tmp_path_factory: pytest.TempPathFactory) -> tuple[CertificateChain, CertificateChain]:
    chains = []
    for name in ("trusted", "untrusted"):
        directory = tmp_path_factory.mktemp(name)
        chain = CertificateChain(directory / "ca.crt", directory / "localhost.crt", directory / "localhost.key")
        generate_localhost_certificate(ca_cert_path=chain.ca, cert_path=chain.leaf, key_path=chain.key)
        chains.append(chain)
    return chains[0], chains[1]


def strict_context(chain: CertificateChain) -> ssl.SSLContext:
    context = ssl.create_default_context(cafile=chain.ca)
    context.verify_flags |= ssl.VERIFY_X509_STRICT
    assert context.check_hostname
    assert context.verify_mode == ssl.CERT_REQUIRED
    assert context.verify_flags & ssl.VERIFY_X509_STRICT
    return context


async def serve_payload(_reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    try:
        writer.write(TLS_PAYLOAD)
        await writer.drain()
    finally:
        writer.close()
        await asyncio.wait_for(writer.wait_closed(), timeout=HANDSHAKE_TIMEOUT_S)


@asynccontextmanager
async def tls_endpoint(chain: CertificateChain) -> AsyncIterator[int]:
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(certfile=chain.leaf, keyfile=chain.key)
    server = await asyncio.start_server(
        serve_payload,
        host="127.0.0.1",
        port=0,
        ssl=context,
        ssl_handshake_timeout=HANDSHAKE_TIMEOUT_S,
    )
    async with server:
        yield int(server.sockets[0].getsockname()[1])


async def receive_payload(chain: CertificateChain, context: ssl.SSLContext, hostname: str) -> bytes:
    async with tls_endpoint(chain) as port:
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection("127.0.0.1", port, ssl=context, server_hostname=hostname),
            timeout=HANDSHAKE_TIMEOUT_S,
        )
        try:
            return await asyncio.wait_for(reader.readexactly(len(TLS_PAYLOAD)), timeout=HANDSHAKE_TIMEOUT_S)
        finally:
            writer.close()
            await asyncio.wait_for(writer.wait_closed(), timeout=HANDSHAKE_TIMEOUT_S)


@pytest.mark.parametrize("hostname", ["localhost", "127.0.0.1"])
def test_generated_chain_is_trusted_under_strict_tls_for_dns_and_ip(
    certificate_chains: tuple[CertificateChain, CertificateChain],
    hostname: str,
) -> None:
    trusted, _untrusted = certificate_chains

    assert asyncio.run(receive_payload(trusted, strict_context(trusted), hostname)) == TLS_PAYLOAD


def test_generated_chain_rejects_an_unrelated_ca(
    certificate_chains: tuple[CertificateChain, CertificateChain],
) -> None:
    trusted, unrelated = certificate_chains

    with pytest.raises(ssl.SSLCertVerificationError) as error:
        asyncio.run(receive_payload(trusted, strict_context(unrelated), "localhost"))

    assert error.value.verify_code == UNTRUSTED_ISSUER_CODE


def test_generated_chain_rejects_a_mismatched_hostname(
    certificate_chains: tuple[CertificateChain, CertificateChain],
) -> None:
    trusted, _untrusted = certificate_chains

    with pytest.raises(ssl.SSLCertVerificationError) as error:
        asyncio.run(receive_payload(trusted, strict_context(trusted), "unrelated.invalid"))

    assert error.value.verify_code == HOSTNAME_MISMATCH_CODE


def certificate_extensions(path: Path, extensions: str) -> str:
    openssl = shutil.which("openssl")
    assert openssl is not None
    result = subprocess.run(  # noqa: S603 - fixed openssl inspection of generated temporary certificates.
        [openssl, "x509", "-in", str(path), "-noout", "-ext", extensions],
        capture_output=True,
        check=True,
        text=True,
        timeout=HANDSHAKE_TIMEOUT_S,
    )
    return result.stdout


def key_identifier(path: Path, extension: str) -> str:
    output = certificate_extensions(path, extension)
    match = re.search(r"^\s*(?:keyid:)?([0-9A-F]{2}(?::[0-9A-F]{2})+)\s*$", output, re.MULTILINE)
    assert match is not None, output
    return match[1]


def test_generated_root_is_a_constrained_signing_ca(
    certificate_chains: tuple[CertificateChain, CertificateChain],
) -> None:
    trusted, _untrusted = certificate_chains
    extensions = certificate_extensions(trusted.ca, "basicConstraints,keyUsage")

    assert "X509v3 Basic Constraints: critical" in extensions
    assert "CA:TRUE" in extensions
    assert "X509v3 Key Usage: critical" in extensions
    assert "Certificate Sign" in extensions
    assert "CRL Sign" in extensions
    assert "Digital Signature" not in extensions


def test_generated_leaf_has_linked_key_identifiers_and_local_server_purpose(
    certificate_chains: tuple[CertificateChain, CertificateChain],
) -> None:
    trusted, _untrusted = certificate_chains
    extensions = certificate_extensions(trusted.leaf, "basicConstraints,keyUsage,extendedKeyUsage,subjectAltName")

    assert key_identifier(trusted.ca, "subjectKeyIdentifier") == key_identifier(trusted.leaf, "authorityKeyIdentifier")
    assert key_identifier(trusted.leaf, "subjectKeyIdentifier") != key_identifier(trusted.ca, "subjectKeyIdentifier")
    assert "X509v3 Basic Constraints: critical" in extensions
    assert "CA:FALSE" in extensions
    assert "X509v3 Key Usage: critical" in extensions
    assert "Digital Signature, Key Encipherment" in extensions
    assert "TLS Web Server Authentication" in extensions
    assert "DNS:localhost, IP Address:127.0.0.1" in extensions
    assert "Certificate Sign" not in extensions
