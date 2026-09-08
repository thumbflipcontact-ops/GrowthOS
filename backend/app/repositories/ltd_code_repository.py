from __future__ import annotations

from sqlalchemy import select

from app.models.ltd_code import LtdCode
from app.repositories.base import Repository


class LtdCodeRepository(Repository[LtdCode]):
    model = LtdCode

    async def get_by_code(self, code: str) -> LtdCode | None:
        result = await self.session.execute(select(LtdCode).where(LtdCode.code == code))
        return result.scalar_one_or_none()
