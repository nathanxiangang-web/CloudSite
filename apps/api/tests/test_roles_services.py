"""T1 roles service tests.

Covers: role validation, permission mapping, role hierarchy,
admin backward compatibility.
"""
from __future__ import annotations

import pytest

from cloudsite.modules.users.contracts import public as roles


def test_list_roles():
    result = roles.list_roles()
    assert result == ["viewer", "editor", "reviewer", "operator", "owner"]


def test_validate_role_valid():
    for r in ["viewer", "editor", "reviewer", "operator", "owner"]:
        assert roles.validate_role(r) == r


def test_validate_role_invalid():
    with pytest.raises(roles.RoleError):
        roles.validate_role("superadmin")


def test_get_permissions_viewer():
    p = roles.get_permissions("viewer")
    assert not p.can_edit_content
    assert not p.can_publish
    assert not p.can_view_admin_dashboard


def test_get_permissions_editor():
    p = roles.get_permissions("editor")
    assert p.can_edit_content
    assert not p.can_publish
    assert p.can_manage_collections
    assert not p.can_manage_users


def test_get_permissions_reviewer():
    p = roles.get_permissions("reviewer")
    assert p.can_edit_content
    assert p.can_publish
    assert p.can_review_submissions
    assert not p.can_manage_system


def test_get_permissions_operator():
    p = roles.get_permissions("operator")
    assert p.can_manage_system
    assert not p.can_manage_users


def test_get_permissions_owner():
    p = roles.get_permissions("owner")
    assert p.can_manage_users
    assert p.can_manage_system


def test_has_permission():
    assert roles.has_permission("editor", "can_edit_content") is True
    assert roles.has_permission("editor", "can_publish") is False
    assert roles.has_permission("owner", "can_manage_users") is True


def test_role_at_least():
    assert roles.role_at_least("owner", "viewer") is True
    assert roles.role_at_least("viewer", "owner") is False
    assert roles.role_at_least("editor", "editor") is True
    assert roles.role_at_least("reviewer", "editor") is True
    assert roles.role_at_least("editor", "reviewer") is False


def test_is_admin_role():
    assert roles.is_admin_role("editor") is True
    assert roles.is_admin_role("viewer") is False
    assert roles.is_admin_role("owner") is True


def test_get_admin_permissions():
    p = roles.get_admin_permissions()
    assert p.can_manage_users is True
    assert p.can_manage_system is True
    assert p.can_publish is True


def test_get_permissions_invalid_role():
    with pytest.raises(roles.RoleError):
        roles.get_permissions("invalid")