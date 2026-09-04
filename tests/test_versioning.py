"""Tests for document versioning."""

import tempfile

from src.ingestion.versioning import DocumentVersioner


def test_store_and_list_versions():
    with tempfile.TemporaryDirectory() as tmpdir:
        ver = DocumentVersioner(data_dir=tmpdir)
        ver.store_version("proposal.md", "Version 1 content", {"author": "test"})
        ver.store_version("proposal.md", "Version 2 content", {"author": "test"})
        versions = ver.get_versions("proposal.md")
        assert len(versions) == 2
        assert versions[0]["version"] == 1
        assert versions[1]["version"] == 2


def test_compare_versions():
    with tempfile.TemporaryDirectory() as tmpdir:
        ver = DocumentVersioner(data_dir=tmpdir)
        ver.store_version("proposal.md", "Revenue grew from $1M to $2M")
        ver.store_version("proposal.md", "Revenue grew from $1M to $3M")
        diff = ver.compare_versions("proposal.md", 1, 2)
        assert len(diff) > 0
        assert any(c["type"] == "removed" for c in diff)


def test_get_version_content():
    with tempfile.TemporaryDirectory() as tmpdir:
        ver = DocumentVersioner(data_dir=tmpdir)
        ver.store_version("doc.md", "First version")
        ver.store_version("doc.md", "Second version")
        v1 = ver.get_version_content("doc.md", 1)
        v2 = ver.get_version_content("doc.md", 2)
        assert v1 == "First version"
        assert v2 == "Second version"
