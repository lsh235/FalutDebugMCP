from __future__ import annotations
import hashlib, json, os, secrets, struct, time
from pathlib import Path

MAGIC = b"FDAR"; VERSION = 1
HEADER = struct.Struct("<4sHHQI32s")

class ArtifactError(ValueError): pass


_TEMP_PREFIX = ".faultdebug-artifact-"
_TEMP_SUFFIX = ".tmp"


def _fsync_directory(directory: Path) -> None:
    """Make an atomic rename/link durable on local POSIX filesystems."""
    flags = getattr(os, "O_DIRECTORY", 0) | os.O_RDONLY
    fd = os.open(directory, flags)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def recover_artifacts(directory: Path, *, stale_after: float = 300.0) -> int:
    """Remove stale temporary artifact files left by an interrupted writer.

    Only files with the private temporary prefix are touched.  Fresh files are
    retained so a concurrent writer cannot be mistaken for crash debris.
    """
    directory = Path(directory)
    if not directory.is_dir():
        return 0
    now = time.time()
    removed = 0
    for temporary in directory.glob(f"{_TEMP_PREFIX}*{_TEMP_SUFFIX}"):
        try:
            if stale_after >= 0 and now - temporary.stat().st_mtime < stale_after:
                continue
            temporary.unlink()
            removed += 1
        except FileNotFoundError:
            continue
    if removed:
        _fsync_directory(directory)
    return removed


def write_artifact(report: dict, directory: Path, pid: int, *, artifact_stem: str | None = None) -> Path:
    payload = json.dumps(report, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    digest = hashlib.sha256(payload).digest()
    directory.mkdir(parents=True, exist_ok=True)
    if artifact_stem is not None:
        if not artifact_stem or artifact_stem in {".", ".."} or "/" in artifact_stem or "\\" in artifact_stem:
            raise ArtifactError("artifact_stem must be one path component")
        stem = artifact_stem
    else:
        stem = f"fault-{pid}"
    recover_artifacts(directory)
    for serial in range(1000):
        suffix = f"-{serial}" if serial else ""
        final = directory / f"{stem}{suffix}.fault"
        temporary = directory / f"{_TEMP_PREFIX}{pid}-{secrets.token_hex(8)}{_TEMP_SUFFIX}"
        try:
            fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            continue
        try:
            with os.fdopen(fd, "wb") as stream:
                stream.write(HEADER.pack(MAGIC, VERSION, 0, len(payload), pid, digest)); stream.write(payload); stream.flush(); os.fsync(stream.fileno())
            # link() fails without replacing an existing artifact, so two
            # collectors using the same PID cannot corrupt one another.
            try:
                os.link(temporary, final)
            except FileExistsError:
                temporary.unlink(missing_ok=True)
                continue
            _fsync_directory(directory)
            temporary.unlink(missing_ok=True)
            _fsync_directory(directory)
            return final
        except Exception:
            try: temporary.unlink()
            except OSError: pass
            raise
    raise ArtifactError("could not reserve a unique artifact path")

def read_artifact(path: Path) -> dict:
    data = path.read_bytes()
    if len(data) < HEADER.size: raise ArtifactError("artifact is truncated")
    magic, version, flags, length, pid, digest = HEADER.unpack_from(data)
    payload = data[HEADER.size:]
    if magic != MAGIC or version != VERSION or length != len(payload): raise ArtifactError("artifact header/length mismatch")
    if not hashlib.sha256(payload).digest() == digest: raise ArtifactError("artifact checksum mismatch")
    return json.loads(payload)
