"""Request schemas specific to the public API — see app/api/public/v1/content.py.

Distinct from app/schemas/content.py's RejectContentItemRequest: the dashboard requires the
caller to supply the `version` it last read (real optimistic-concurrency UX for a UI that
reads then writes across separate interactions). A public-API caller isn't expected to track
that — the server fetches the current version itself immediately before the atomic
version-guarded transition, which still gives the same correctness guarantee (a genuine race
still produces one winner and one 409, per ContentApprovalService._transition), just without
forcing an external caller to manage a version field it has no natural reason to hold onto.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class PublicRejectDraftRequest(BaseModel):
    reason: str = Field(min_length=1)
