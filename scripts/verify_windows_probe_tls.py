"""Disposable loopback WSS/HTTPS verification; no system trust changes or models."""
import argparse
import asyncio
from datetime import datetime, timedelta, timezone
import ipaddress
import json
import os
from pathlib import Path
import ssl
import subprocess
import sys
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def certificates(output):
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID, ExtendedKeyUsageOID
    now = datetime.now(timezone.utc)
    ca_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, 'Disposable Probe Test CA')])
    ca = (x509.CertificateBuilder().subject_name(name).issuer_name(name)
        .public_key(ca_key.public_key()).serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(days=1)).not_valid_after(now + timedelta(days=1))
        .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
        .add_extension(x509.SubjectKeyIdentifier.from_public_key(ca_key.public_key()), critical=False)
        .add_extension(x509.AuthorityKeyIdentifier.from_issuer_public_key(ca_key.public_key()), critical=False)
        .add_extension(x509.KeyUsage(digital_signature=False, content_commitment=False,
            key_encipherment=False, data_encipherment=False, key_agreement=False,
            key_cert_sign=True, crl_sign=True, encipher_only=None, decipher_only=None), critical=True)
        .sign(ca_key, hashes.SHA256()))
    (output / 'ca.pem').write_bytes(ca.public_bytes(serialization.Encoding.PEM))
    for label, expired in [('server', False), ('expired', True)]:
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        certificate = (x509.CertificateBuilder().subject_name(x509.Name([
            x509.NameAttribute(NameOID.COMMON_NAME, 'Loopback Probe Test')]))
            .issuer_name(name).public_key(key.public_key()).serial_number(x509.random_serial_number())
            .not_valid_before(now - timedelta(days=2))
            .not_valid_after(now - timedelta(days=1) if expired else now + timedelta(hours=12))
            .add_extension(x509.SubjectAlternativeName([
                x509.IPAddress(ipaddress.ip_address('127.0.0.1'))]), critical=False)
            .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
            .add_extension(x509.SubjectKeyIdentifier.from_public_key(key.public_key()), critical=False)
            .add_extension(x509.AuthorityKeyIdentifier.from_issuer_public_key(ca_key.public_key()), critical=False)
            .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]), critical=False)
            .add_extension(x509.KeyUsage(digital_signature=True, content_commitment=False,
                key_encipherment=True, data_encipherment=False, key_agreement=False,
                key_cert_sign=False, crl_sign=False, encipher_only=None, decipher_only=None), critical=True)
            .sign(ca_key, hashes.SHA256()))
        (output / (label + '.pem')).write_bytes(certificate.public_bytes(serialization.Encoding.PEM))
        (output / (label + '.key')).write_bytes(key.private_bytes(serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))


async def verify(output):
    from contextlib import ExitStack
    from scripts.windows_probe import _set_acl
    from scripts.verify_windows_local_faults import free_port, wait_listener, stop, listening_rows
    import httpx
    import websockets
    output.mkdir(parents=True, exist_ok=False)
    if os.name == 'nt':
        _set_acl(output)
    certificates(output)
    target, token = 'windows-local-01', uuid4().hex + uuid4().hex
    (output / 'token').write_text(token, encoding='utf-8')
    port = free_port()
    env = os.environ.copy()
    env.update(PROBE_TARGET_ID=target, PROBE_TOKEN=token,
        DATABASE_URL='sqlite:///' + (output / 'tls.sqlite').as_posix(),
        RAG_AIOPS_PROBE_CONFIG=str(output / 'config.toml'),
        SSL_CERT_FILE=str(output / 'ca.pem'))
    (output / 'config.toml').write_text('\n'.join([
        f"target_id = '{target}'", f"gateway_url = 'wss://127.0.0.1:{port}/probe/ws'",
        f"token_file = '{(output / 'token').as_posix()}'",
        f"tls_ca_file = '{(output / 'ca.pem').as_posix()}'", 'baseline_interval_seconds = 60']), encoding='utf-8')
    result = {'ok': False, 'model_calls': 0, 'system_trust_modified': False,
        'installed_service_modified': False, 'checks': []}
    owned = []
    with ExitStack() as stack:
        def launch(args, name):
            log = stack.enter_context((output / (name + '.log')).open('wb'))
            process = subprocess.Popen([sys.executable, *args], cwd=ROOT, env=env,
                stdout=log, stderr=subprocess.STDOUT,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
            owned.append(process)
            return process

        def gateway(label):
            process = launch(['-m', 'uvicorn', 'mcp_servers.probe_gateway:app',
                '--host', '127.0.0.1', '--port', str(port),
                '--ssl-certfile', str(output / (label + '.pem')),
                '--ssl-keyfile', str(output / (label + '.key'))], label + '-gateway')
            wait_listener(port, process)
            return process

        async def rejected_wss(label, context, expected_code, **kwargs):
            try:
                async with websockets.connect(f'wss://127.0.0.1:{port}/probe/ws', ssl=context,
                    additional_headers={'Authorization': 'Bearer ' + token}, open_timeout=3, **kwargs):
                    raise AssertionError(label + ' unexpectedly connected')
            except ssl.SSLCertVerificationError as exc:
                assert exc.verify_code == expected_code, (
                    f'{label}: expected verification code {expected_code}, '
                    f'got {exc.verify_code}: {exc.verify_message}')
                result['checks'].append({'case': label, 'status': 'passed',
                    'verify_code': exc.verify_code, 'verify_message': exc.verify_message})

        try:
            server = gateway('server')
            # An empty trust store proves rejection independently of developer-machine trust.
            await rejected_wss('untrusted_ca_rejected', ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT), 20)
            trusted = ssl.create_default_context(cafile=str(output / 'ca.pem'))
            await rejected_wss('hostname_mismatch_rejected', trusted, 62,
                server_hostname='unconfigured.example.invalid')
            with httpx.Client(verify=ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT), trust_env=False) as client:
                try:
                    client.get(f'https://127.0.0.1:{port}/mcp', timeout=3)
                    raise AssertionError('HTTPS accepted untrusted certificate')
                except httpx.ConnectError as exc:
                    assert 'CERTIFICATE_VERIFY_FAILED' in str(exc)
                    result['checks'].append({'case': 'https_untrusted_ca_rejected', 'status': 'passed'})
            probe = launch(['-c', 'import asyncio; from pathlib import Path; '
                'from scripts.windows_probe import run_probe; '
                f'asyncio.run(run_probe(lambda: Path({str(output / "stop")!r}).exists()))'], 'probe')
            # Only this test process uses this CA; system certificate stores are unchanged.
            os.environ['SSL_CERT_FILE'] = str(output / 'ca.pem')
            from src.agent.mcp_client import load_tools_for_config, close_client_for_config
            from src.probe.evidence import validate_tool_evidence, EvidenceValidationError
            config = {'probe': {'transport': 'streamable_http',
                'url': f'https://127.0.0.1:{port}/mcp', 'tls_verify': True,
                'headers': {'Authorization': 'Bearer ' + token}}}
            tools, error = await load_tools_for_config(config)
            assert error is None and len(tools) == 9, 'TLS MCP tool loading failed'
            inventory = next(tool for tool in tools if tool.name == 'probe_inventory')
            raw = None
            for attempt in range(30):
                try:
                    raw = validate_tool_evidence(await inventory.ainvoke({}),
                        tool_name=inventory.name, target_id=target)
                    break
                except EvidenceValidationError:
                    if probe.poll() is not None:
                        raise RuntimeError('temporary Probe exited')
                    await asyncio.sleep(0.5)
            assert raw, 'WSS Probe did not provide inventory'
            (output / 'inventory.json').write_text(json.dumps(raw, ensure_ascii=False, indent=2), encoding='utf-8')
            result['checks'].append({'case': 'real_probe_wss_https_mcp_inventory', 'status': 'passed',
                'target_id': raw['target_id'], 'collected_at': raw['collected_at'], 'raw_hash': raw['raw_hash'],
                'tls_verify': True, 'tool_count': len(tools), 'probe_identity': 'foreground current account'})
            close_client_for_config(config)
            (output / 'stop').touch()
            await asyncio.to_thread(probe.wait, timeout=15)
            stop(server)
            expired_server = gateway('expired')
            await rejected_wss('expired_certificate_rejected', trusted, 10)
            stop(expired_server)
            result['ok'] = True
        except Exception as exc:
            result['error'] = type(exc).__name__ + ': ' + str(exc)
            raise
        finally:
            for process in reversed(owned):
                stop(process)
            result['remaining_listeners'] = listening_rows([port])
            result['ports_released'] = not result['remaining_listeners']
            result['owned_processes_stopped'] = all(process.poll() is not None for process in owned)
            result['ok'] = result['ok'] and result['ports_released'] and result['owned_processes_stopped']
            (output / 'summary.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
            print(json.dumps({'output': str(output), **result}, ensure_ascii=False))
    assert result['ok']


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args()
    asyncio.run(verify(ROOT / 'runtime' / ('probe-tls-' + uuid4().hex)))
