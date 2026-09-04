"""Tests for role-based access control."""

import tempfile
from src.compliance.rbac import RBACManager


def test_create_role():
    with tempfile.TemporaryDirectory() as tmpdir:
        rbac = RBACManager(db_path=f"{tmpdir}/rbac.db")
        rbac.create_role("junior_analyst", permissions=["read_limited"])
        roles = rbac.list_roles()
        assert "junior_analyst" in roles


def test_assign_and_check_permission():
    with tempfile.TemporaryDirectory() as tmpdir:
        rbac = RBACManager(db_path=f"{tmpdir}/rbac.db")
        rbac.create_role("analyst", permissions=["read_all", "query"])
        rbac.assign_role("user_001", "analyst")
        assert rbac.check_permission("user_001", "query") is True
        assert rbac.check_permission("user_001", "delete") is False


def test_document_level_access():
    with tempfile.TemporaryDirectory() as tmpdir:
        rbac = RBACManager(db_path=f"{tmpdir}/rbac.db")
        rbac.create_role("junior", permissions=["read_limited"])
        rbac.assign_role("user_002", "junior")
        rbac.grant_document_access("user_002", "cv.pdf")
        accessible = rbac.list_accessible_documents("user_002")
        assert "cv.pdf" in accessible
        # Can't access other docs
        assert rbac.check_document_access("user_002", "financial_model.md") is False


def test_admin_full_access():
    with tempfile.TemporaryDirectory() as tmpdir:
        rbac = RBACManager(db_path=f"{tmpdir}/rbac.db")
        rbac.create_role("admin", permissions=["read_all", "query", "upload", "delete", "manage_users"])
        rbac.assign_role("admin_001", "admin")
        assert rbac.check_permission("admin_001", "delete") is True
        assert rbac.check_permission("admin_001", "manage_users") is True
