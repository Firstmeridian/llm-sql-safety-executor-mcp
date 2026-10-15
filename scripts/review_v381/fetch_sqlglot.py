"""Fetch a verified public wheel for an isolated experiment, never runtime."""
from pathlib import Path
import hashlib
import io
import json
import urllib.request
import zipfile

root = Path(__file__).resolve().parents[2]
target = Path("/tmp/v381-sqlglot-probe")
target.mkdir(exist_ok=True)
with urllib.request.urlopen("https://pypi.org/pypi/sqlglot/30.22.0/json", timeout=15) as response:
    metadata = json.load(response)
wheel = next(row for row in metadata["urls"] if row["filename"].endswith("py3-none-any.whl"))
with urllib.request.urlopen(wheel["url"], timeout=20) as response:
    raw = response.read()
assert hashlib.sha256(raw).hexdigest() == wheel["digests"]["sha256"]
with zipfile.ZipFile(io.BytesIO(raw)) as archive:
    assert all(not Path(name).is_absolute() and ".." not in Path(name).parts for name in archive.namelist())
    archive.extractall(target)
record = {"version": metadata["info"]["version"], "wheel": wheel["filename"],
          "sha256": wheel["digests"]["sha256"], "url": wheel["url"],
          "upload_time": wheel["upload_time_iso_8601"],
          "installation": "Isolated /tmp extraction; project runtime dependencies/lock unchanged"}
out = root / "docs/validation/v3.8/phase123_2026_10_14"
(out / "sqlglot_dependency.json").write_text(json.dumps(record, indent=2) + "\n")
print("Verified isolated SQLGlot", record["version"])
