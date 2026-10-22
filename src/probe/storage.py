"""Filesystem protection for local diagnostic evidence."""
import os
from pathlib import Path
import stat


def protect_evidence_path(path: Path) -> None:
    """Allow only the writer, administrators and SYSTEM; fail on unsafe links."""
    info = path.lstat()
    if stat.S_ISLNK(info.st_mode) or getattr(info, 'st_file_attributes', 0) & 0x400:
        raise PermissionError('Evidence storage cannot use links or reparse points')
    if not (stat.S_ISDIR(info.st_mode) or stat.S_ISREG(info.st_mode)):
        raise PermissionError('Evidence storage must be a directory or regular file')
    if os.name == 'nt':
        import win32api
        import win32con
        import win32security as security
        token = security.OpenProcessToken(win32api.GetCurrentProcess(), win32con.TOKEN_QUERY)
        try:
            user = security.GetTokenInformation(token, security.TokenUser)[0]
        finally:
            token.Close()
        acl = security.ACL()
        flags = 3 if stat.S_ISDIR(info.st_mode) else 0
        # win32con does not expose FILE_ALL_ACCESS on all pywin32 builds.
        file_all_access = 0x1F01FF
        for sid in {security.ConvertSidToStringSid(user), 'S-1-5-18', 'S-1-5-32-544'}:
            acl.AddAccessAllowedAceEx(security.ACL_REVISION, flags, file_all_access,
                                     security.ConvertStringSidToSid(sid))
        security.SetNamedSecurityInfo(str(path), security.SE_FILE_OBJECT,
            security.DACL_SECURITY_INFORMATION | security.PROTECTED_DACL_SECURITY_INFORMATION,
            None, None, acl, None)
    else:
        if info.st_uid != os.geteuid():
            raise PermissionError('Evidence storage must be owned by the application account')
        path.chmod(0o700 if stat.S_ISDIR(info.st_mode) else 0o600)


def write_evidence_file(root: Path, filename: str, content: str) -> Path:
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    protect_evidence_path(root)
    path = root / filename
    # Exclusive creation prevents following a pre-existing file or hard link.
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as handle:
            protect_evidence_path(path)
            handle.write(content)
    except Exception:
        try:
            path.unlink()
        except OSError:
            pass
        raise
    return path
