from __future__ import annotations

"""
Tenant and storage helpers.

This module introduces a light-weight abstraction for tenant-scoped
paths without changing existing single-tenant behavior. All helpers
default to the implicit 'default' tenant, which maps to the existing
project-root data/log layout.
"""

from dataclasses import dataclass
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent


@dataclass
class TenantContext:
    tenant_id: str = "default"

    @property
    def data_dir(self) -> Path:
        # Backwards-compatible: existing data/ directory
        return PROJECT_ROOT / "data"

    @property
    def logs_dir(self) -> Path:
        # Backwards-compatible: existing logs/ directory
        return PROJECT_ROOT / "logs"

    @property
    def config_dir(self) -> Path:
        return PROJECT_ROOT / "config"


def get_tenant(tenant_id: str | None = None) -> TenantContext:
    """
    Return a TenantContext for the given tenant_id.

    For now, all tenants share the same underlying directories; future
    productization can map tenant_id into subdirectories.
    """
    return TenantContext(tenant_id or "default")


