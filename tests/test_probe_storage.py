import os
from pathlib import Path
import stat

import pytest

from src.probe.storage import protect_evidence_path, write_evidence_file


def test_write_evidence_file_is_exclusive_and_round_trips(tmp_path):
    path = write_evidence_file(tmp_path / 'evidence', 'ev-1.json', '{"safe":true}')
    assert path.read_text(encoding='utf-8') == '{"safe":true}'
    with pytest.raises(FileExistsError):
        write_evidence_file(tmp_path / 'evidence', 'ev-1.json', '{}')
    if os.name != 'nt':
        assert stat.S_IMODE(path.stat().st_mode) == 0o600
        assert stat.S_IMODE(path.parent.stat().st_mode) == 0o700


def test_acl_failure_does_not_leave_new_evidence_file(tmp_path, monkeypatch):
    import src.probe.storage as storage
    calls = []

    def fail(path):
        calls.append(Path(path))
        if Path(path).is_file():
            raise PermissionError('test ACL failure')

    monkeypatch.setattr(storage, 'protect_evidence_path', fail)
    with pytest.raises(PermissionError):
        storage.write_evidence_file(tmp_path / 'evidence', 'ev-2.json', '{}')
    assert not (tmp_path / 'evidence' / 'ev-2.json').exists()
    assert len(calls) == 2


@pytest.mark.skipif(os.name != 'nt', reason='Windows ACL verification')
def test_windows_acl_contains_only_application_admin_and_system(tmp_path):
    import win32api
    import win32con
    import win32security as security

    root = tmp_path / 'evidence'
    root.mkdir()
    path = write_evidence_file(root, 'ev-3.json', '{}')
    token = security.OpenProcessToken(win32api.GetCurrentProcess(), win32con.TOKEN_QUERY)
    try:
        current_sid = security.ConvertSidToStringSid(
            security.GetTokenInformation(token, security.TokenUser)[0]
        )
    finally:
        token.Close()
    allowed = {current_sid, 'S-1-5-18', 'S-1-5-32-544'}
    for checked in (root, path):
        descriptor = security.GetNamedSecurityInfo(
            str(checked), security.SE_FILE_OBJECT, security.DACL_SECURITY_INFORMATION
        )
        acl = descriptor.GetSecurityDescriptorDacl()
        assert acl is not None
        for index in range(acl.GetAceCount()):
            ace = acl.GetAce(index)
            if ace[0][0] == security.ACCESS_ALLOWED_ACE_TYPE:
                sid = security.ConvertSidToStringSid(ace[-1])
                assert sid in allowed


@pytest.mark.skipif(os.name != 'nt', reason='Windows reparse-point verification')
def test_windows_reparse_point_is_rejected(tmp_path):
    import subprocess

    outside = tmp_path / 'outside'
    outside.mkdir()
    link = tmp_path / 'link'
    subprocess.run(['cmd.exe', '/c', 'mklink', '/J', str(link), str(outside)], check=True,
                   capture_output=True)
    try:
        with pytest.raises(PermissionError):
            write_evidence_file(link, 'ev-4.json', '{}')
    finally:
        os.rmdir(link)


@pytest.mark.skipif(os.name != 'nt', reason='Windows restricted-token verification')
def test_restricted_token_can_access_control_but_not_protected_evidence(tmp_path):
    import win32api
    import win32con
    import win32security as security

    control = tmp_path / 'control.json'
    control.write_text('{}', encoding='utf-8')
    users = security.ConvertStringSidToSid('S-1-5-32-545')
    acl = security.ACL()
    acl.AddAccessAllowedAceEx(security.ACL_REVISION, 0, 0x1F01FF, users)
    security.SetNamedSecurityInfo(str(control), security.SE_FILE_OBJECT,
        security.DACL_SECURITY_INFORMATION | security.PROTECTED_DACL_SECURITY_INFORMATION,
        None, None, acl, None)
    protected = write_evidence_file(tmp_path / 'protected', 'ev-token.json', '{"safe":true}')
    token = security.OpenProcessToken(win32api.GetCurrentProcess(), win32con.TOKEN_ALL_ACCESS)
    restricted = None
    try:
        restricted = security.CreateRestrictedToken(token, 1, [], [], [(users, 0)])
        security.ImpersonateLoggedOnUser(restricted)
        try:
            assert control.read_text(encoding='utf-8') == '{}'
            with control.open('a', encoding='utf-8') as handle:
                handle.write('control')
            for mode in ('r', 'a'):
                with pytest.raises(PermissionError):
                    with protected.open(mode, encoding='utf-8'):
                        pass
        finally:
            security.RevertToSelf()
    finally:
        if restricted is not None:
            restricted.Close()
        token.Close()
    assert protected.read_text(encoding='utf-8') == '{"safe":true}'
