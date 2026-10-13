import errno
import pytest
from app.permissions import private_mode


@pytest.mark.parametrize("code", [errno.EPERM, errno.EACCES, errno.EROFS, errno.ENOTSUP])
def test_portable_windows_mounts_do_not_crash_on_unsupported_permissions(monkeypatch, code):
    monkeypatch.setenv("PERMISSIONS_MODE", "portable")

    def chmod(*args):
        raise OSError(code, "unsupported permission change")

    monkeypatch.setattr("app.permissions.os.chmod", chmod)
    private_mode("test-directory", 0o700)


def test_strict_linux_errors_and_actual_io_errors_are_not_suppressed(monkeypatch):
    def chmod(*args):
        raise OSError(errno.EROFS, "read-only")

    monkeypatch.setattr("app.permissions.os.chmod", chmod)
    monkeypatch.setenv("PERMISSIONS_MODE", "strict")
    with pytest.raises(OSError):
        private_mode("test", 0o600)
    monkeypatch.setenv("PERMISSIONS_MODE", "portable")

    def broken(*args):
        raise OSError(errno.EIO, "broken filesystem")

    monkeypatch.setattr("app.permissions.os.chmod", broken)
    with pytest.raises(OSError):
        private_mode("test", 0o600)
