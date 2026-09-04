"""Document versioning - track multiple versions of the same document."""

from __future__ import annotations

import difflib
import json
from pathlib import Path


class DocumentVersioner:
    """Track and compare versions of documents."""

    def __init__(self, data_dir: str = "./data/versions"):
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self._index_path = self.data_dir / "_index.json"
        self._index = self._load_index()

    def _load_index(self) -> dict:
        if self._index_path.exists():
            return json.loads(self._index_path.read_text())
        return {}

    def _save_index(self) -> None:
        self._index_path.write_text(json.dumps(self._index, indent=2))

    def _version_dir(self, filename: str) -> Path:
        safe_name = filename.replace("/", "_").replace("\\", "_")
        vdir = self.data_dir / safe_name
        vdir.mkdir(parents=True, exist_ok=True)
        return vdir

    def store_version(
        self, filename: str, content: str, metadata: dict | None = None
    ) -> int:
        vdir = self._version_dir(filename)
        versions = self._index.setdefault(filename, {"count": 0, "versions": []})
        version_num = versions["count"] + 1
        versions["count"] = version_num

        version_file = vdir / f"v{version_num}.txt"
        version_file.write_text(content, encoding="utf-8")

        versions["versions"].append({
            "version": version_num,
            "size": len(content),
            "metadata": metadata or {},
        })
        self._save_index()
        return version_num

    def get_versions(self, filename: str) -> list[dict]:
        entry = self._index.get(filename, {})
        return entry.get("versions", [])

    def get_version_content(self, filename: str, version: int) -> str:
        vdir = self._version_dir(filename)
        version_file = vdir / f"v{version}.txt"
        if version_file.exists():
            return version_file.read_text(encoding="utf-8")
        return ""

    def compare_versions(
        self, filename: str, v1: int, v2: int
    ) -> list[dict]:
        content1 = self.get_version_content(filename, v1)
        content2 = self.get_version_content(filename, v2)

        lines1 = content1.splitlines(keepends=True)
        lines2 = content2.splitlines(keepends=True)

        diff = list(difflib.unified_diff(
            lines1, lines2,
            fromfile=f"v{v1}", tofile=f"v{v2}",
            lineterm="",
        ))

        changes = []
        for line in diff:
            if line.startswith("+++") or line.startswith("---"):
                continue
            if line.startswith("+"):
                changes.append({"type": "added", "line": line[1:].strip()})
            elif line.startswith("-"):
                changes.append({"type": "removed", "line": line[1:].strip()})

        return changes
