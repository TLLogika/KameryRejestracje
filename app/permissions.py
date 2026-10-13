"""Keep Unix permissions strict except on explicitly configured Windows mounts."""

import errno
import os


def private_mode(path, mode):
    try:
        os.chmod(path, mode)
    except OSError as exc:
        portable = os.name == "nt" or os.environ.get("PERMISSIONS_MODE") == "portable"
        if not portable or exc.errno not in {errno.EACCES, errno.EPERM, errno.EROFS, errno.ENOTSUP}:
            raise
