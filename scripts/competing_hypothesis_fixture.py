"""Local-only competing-fault fixture used by free scenario checks."""

from __future__ import annotations

import os
import errno
import json
import socket
from pathlib import Path
import subprocess
import sys
import time
import psutil
from tempfile import TemporaryDirectory
from urllib.error import URLError
from scripts.evaluation_record import utc_now

from scripts.verify_windows_local_faults import (
    ROOT, cleanup_owned, free_port, get_local, stop, wait_listener,
)


UNAVAILABLE_BODY = b"temporarily unavailable"


def _request(port: int, *, path='/health') -> tuple[int, bytes]:
    status, body = get_local(port, path=path)
    return status, body.encode('utf-8')


class CompetingFaultFixture:
    """Start independent processes with a controller-only fault selection."""

    def __init__(self, fault: str, output: Path | None = None, *, stop_mode: str = 'terminate',
                 startup_configuration: bool = False):
        if fault not in {"normal", "localapp_unavailable", "downstream_unreachable", "downstream_bind_failed",
                         "localapp_wrong_endpoint", "downstream_slow"}:
            raise ValueError("unsupported competing fault")
        if stop_mode not in {'terminate', 'request'}:
            raise ValueError('unsupported stop mode')
        self.fault = fault
        self.stop_mode = stop_mode
        ports = set()
        while len(ports) < 3:
            ports.add(free_port())
        self.edge_port, self.localapp_port, self.downstream_port = ports
        self._temporary = None
        self.output = output
        self.owned = []
        self.processes = {}
        self.process_pids = {}
        self._handles = []
        self._reservation = None
        self.startup_configuration = startup_configuration or fault == 'localapp_wrong_endpoint'
        self.obsolete_port = free_port()
        while self.obsolete_port in ports:
            self.obsolete_port = free_port()
        self._obsolete_reservation = None

    @property
    def connection_config(self):
        return self.output / 'localapp.connection.json'

    def process_identity(self, name):
        return ('--mode-file', str(self.output / (name + '.mode')))

    def _start(self, name, *, expect_bind_failure=False):
        ports = {'edge': self.edge_port, 'localapp': self.localapp_port, 'downstream': self.downstream_port}
        args = [sys.executable, str(ROOT / 'scripts/verify_windows_local_faults.py'),
            '--serve', str(ports[name]), '--log', str(self.output / (name + '.log')),
            *self.process_identity(name)]
        if self.stop_mode == 'request':
            stop_file = self.output / (name + '.stop')
            stop_file.unlink(missing_ok=True)
            args += ['--stop-file', str(stop_file)]
        if name != 'downstream':
            args += ['--downstream', str(self.localapp_port if name == 'edge' else self.downstream_port)]
        if self.startup_configuration:
            args += ['--runtime-config', str(self.output / (name + '.connection.json'))]
        handle = (self.output / (name + '.stderr')).open('ab')
        self._handles.append(handle)
        process = subprocess.Popen(args, cwd=ROOT, stdout=handle, stderr=subprocess.STDOUT,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
        self.owned.append(process)
        self.processes[name] = process
        if expect_bind_failure:
            # Capture the launcher/worker identity before it exits; do not use
            # the log's own PID as independent proof of where that log came from.
            pids, deadline = {process.pid}, time.monotonic() + 5
            while process.poll() is None:
                try:
                    pids.update(child.pid for child in psutil.Process(process.pid).children(recursive=True))
                except psutil.NoSuchProcess:
                    pass
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise subprocess.TimeoutExpired(args, 5)
                try:
                    process.wait(timeout=min(0.01, remaining))
                except subprocess.TimeoutExpired:
                    pass
            events = [json.loads(line) for line in (self.output / (name + '.log')).read_text(encoding='utf-8').splitlines()]
            if (process.returncode == 0 or len(events) != 1 or events[0].get('error') != 'bind_failed'
                    or events[0].get('port') != ports[name]
                    or events[0].get('errno') not in {errno.EADDRINUSE, errno.EACCES, 10013, 10048}
                    or events[0].get('pid') not in pids):
                raise RuntimeError('reserved port did not produce the expected application bind failure')
            self.process_pids[name] = pids
            return
        wait_listener(ports[name], process)
        # Windows venv launchers can own a separate Python worker PID.
        self.process_pids[name] = {process.pid, *[child.pid for child in psutil.Process(process.pid).children(recursive=True)]}

    def __enter__(self):
        if self.output is None:
            runtime = ROOT / 'runtime'
            runtime.mkdir(exist_ok=True)
            self._temporary = TemporaryDirectory(prefix='competing-fixture-', dir=runtime)
            self.output = Path(self._temporary.name)
        self.output.mkdir(parents=True, exist_ok=True)
        for name in ('edge', 'localapp', 'downstream'):
            (self.output / (name + '.mode')).write_text('normal', encoding='utf-8')
            (self.output / (name + '.log')).touch()
        try:
            self.reset(self.fault)
            self._start('edge')
            return self
        except BaseException:
            self.__exit__()
            raise

    def reset(self, fault):
        if fault not in {'normal', 'localapp_unavailable', 'downstream_unreachable', 'downstream_bind_failed',
                         'localapp_wrong_endpoint', 'downstream_slow'}:
            raise ValueError('unsupported competing fault')
        if fault == 'localapp_wrong_endpoint' and not self.startup_configuration:
            raise ValueError('wrong endpoint requires a startup-configuration fixture')
        for name in ('localapp', 'downstream'):
            if name in self.processes:
                stop(self.processes[name])
        if getattr(self, '_reservation', None) is not None:
            self._reservation.close()
            self._reservation = None
        for name in ('edge', 'localapp', 'downstream'):
            (self.output / (name + '.log')).write_text('', encoding='utf-8')
        boundary = utc_now()
        self.boundary = boundary
        if self.startup_configuration:
            # Reserve without listening: no unrelated process may turn the obsolete endpoint healthy.
            if self._obsolete_reservation is None:
                self._obsolete_reservation = socket.socket()
                if os.name == 'nt':
                    self._obsolete_reservation.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
                self._obsolete_reservation.bind(('127.0.0.1', self.obsolete_port))
            for name, dependency in (('edge', self.localapp_port), ('downstream', None),
                    ('localapp', self.obsolete_port if fault == 'localapp_wrong_endpoint' else self.downstream_port)):
                (self.output / (name + '.connection.json')).write_text(
                    json.dumps({'downstream_port': dependency,
                        'upstream_timeout_seconds': 1.5 if name == 'edge' else 0.5}), encoding='utf-8')
        if fault == 'downstream_bind_failed':
            # A real bound socket prevents startup without adding a listener.
            self._reservation = socket.socket()
            if os.name == 'nt':
                self._reservation.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
            self._reservation.bind(('127.0.0.1', self.downstream_port))
            self._start('downstream', expect_bind_failure=True)
        else:
            self._start('downstream')
        self._start('localapp')
        if fault == 'downstream_slow':
            # Latency fault: the dependency keeps running and listening, but answers
            # only after a delay longer than the application's upstream timeout.
            (self.output / 'downstream.mode').write_text(
                json.dumps({'mode': 'slow_response', 'delay_ms': 1200}), encoding='utf-8')
        if fault in {'localapp_unavailable', 'downstream_unreachable'}:
            name = 'localapp' if fault == 'localapp_unavailable' else 'downstream'
            process = self.processes[name]
            if self.stop_mode == 'request':
                (self.output / (name + '.stop')).touch()
                # A failed request must fail the fixture, not silently become an abrupt-stop sample.
                process.wait(timeout=5)
                if process.returncode != 0:
                    raise RuntimeError('requested stop did not exit normally')
            else:
                stop(process)
        self.fault = fault
        return boundary

    def repair_endpoint(self, *, restart):
        if not self.startup_configuration:
            raise ValueError('fixture has no startup connection configuration')
        configuration = json.loads(self.connection_config.read_text(encoding='utf-8'))
        configuration['downstream_port'] = self.downstream_port
        self.connection_config.write_text(json.dumps(configuration), encoding='utf-8')
        if restart:
            process = self.processes['localapp']
            if self.stop_mode == 'request':
                (self.output / 'localapp.stop').touch()
                process.wait(timeout=5)
                if process.returncode != 0:
                    raise RuntimeError('application restart did not stop normally')
            else:
                stop(process)
            self._start('localapp')

    def trigger_business_request(self):
        """Create a real edge request after reset, before any Agent observation."""
        import uuid
        request_id = uuid.uuid4().hex
        started_at = utc_now()
        status, _ = get_local(self.edge_port, path='/api/availability', request_id=request_id)
        if status != (200 if self.fault == 'normal' else 503):
            raise RuntimeError('business request did not reproduce the selected condition')
        events = {}
        if self.startup_configuration:
            for name in ('edge', 'localapp'):
                rows = [json.loads(line) for line in (self.output / (name + '.log')).read_text(encoding='utf-8').splitlines()]
                matches = [row for row in rows if row.get('request_id') == request_id]
                if len(matches) != 1 or matches[0]['status'] != status or matches[0]['at'] < self.boundary:
                    raise RuntimeError('current business request is missing from the application logs')
                events[name] = matches[0]['at']
        return {'request_id': request_id, 'started_at': started_at, 'completed_at': utc_now(),
                'http_status': status, 'log_times': events}

    def observe_controller_side(self) -> dict:
        """Return direct fixture checks; these are never Agent evidence."""
        checks = {}
        for name, port in (("edge", self.edge_port), ("localapp", self.localapp_port),
                           ("downstream", self.downstream_port)):
            try:
                status, body = _request(port, path='/api/availability' if self.startup_configuration else '/health')
                checks[name] = {"tcp": "ok", "http_status": status, "body": body.decode("utf-8")}
            except (OSError, URLError, TimeoutError):
                checks[name] = {"tcp": "failed", "http_status": None, "body": None}
        checks["source"] = "controller_fixture_check_not_agent_evidence"
        checks["hidden_fault"] = self.fault
        return checks

    def __exit__(self, *_):
        if self._obsolete_reservation is not None:
            self._obsolete_reservation.close()
            self._obsolete_reservation = None
        if self._reservation is not None:
            self._reservation.close()
            self._reservation = None
        result = cleanup_owned(self.owned, (self.edge_port, self.localapp_port, self.downstream_port, self.obsolete_port))
        self.cleanup_result = {
            "remaining_listener_ports": ([row['port'] for row in result['remaining_listeners']]
                if result['remaining_listeners'] is not None else None),
            "cleanup_errors": result['cleanup_errors'],
        }
        for handle in self._handles:
            handle.close()
        if self._temporary and result['owned_processes_stopped'] and result['ports_released']:
            self._temporary.cleanup()
