"""Generate a batch of unredeemed AppSumo-style lifetime-deal codes — see
app/models/ltd_code.py and app/services/ltd_redemption_service.py.

Run this against production the same way any other one-off operator script runs (see
docs/deployment/DEPLOYMENT.md's Railway SSH pattern):

    MSYS_NO_PATHCONV=1 railway ssh --service GrowthOS -- \\
        env PYTHONPATH=/app:/app/backend:/app/.pydeps/lib/python3.12/site-packages \\
        python3 backend/scripts/generate_ltd_codes.py --count 100 --source appsumo

Prints one code per line to stdout — nothing else — so the output can be piped straight into
a file to hand to AppSumo (or wherever the codes need to go). Each code is a short, random,
unambiguous string (no 0/O/1/I) rather than a UUID, since a human may need to type one in by
hand on the /redeem page.

`--source` tags every code in this batch with which marketplace it's for (e.g. "appsumo",
"dealmirror", "pitchground", "direct") — see app/models/ltd_code.py's `source` column.
Optional so old call sites/scripts keep working, but always pass it when launching on a new
channel: it's the only thing that lets you later tell "how many DealMirror codes actually
got redeemed" apart from AppSumo's.
"""

from __future__ import annotations

import argparse
import asyncio
import secrets
import sys

from app.core.config import get_settings
from app.core.db import create_engine, create_session_factory
from app.models.ltd_code import LtdCode

# Excludes visually ambiguous characters (0/O, 1/I/l) — these codes may be read off a screen
# and typed by hand.
_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
_CODE_LENGTH = 10


def _generate_code() -> str:
    return "".join(secrets.choice(_ALPHABET) for _ in range(_CODE_LENGTH))


async def main(count: int, source: str | None) -> None:
    settings = get_settings()
    engine = create_engine(settings.database_url)
    session_factory = create_session_factory(engine)

    async with session_factory() as session:
        codes: list[str] = []
        seen: set[str] = set()
        while len(codes) < count:
            code = _generate_code()
            if code in seen:  # astronomically unlikely, but a duplicate must never be issued
                continue
            seen.add(code)
            codes.append(code)
            session.add(LtdCode(code=code, source=source))
        await session.commit()

    for code in codes:
        print(code)

    await engine.dispose()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--count", type=int, required=True, help="How many codes to generate.")
    parser.add_argument(
        "--source",
        type=str,
        default=None,
        help="Which marketplace this batch is for (e.g. appsumo, dealmirror). Optional.",
    )
    args = parser.parse_args()
    if args.count <= 0:
        print("--count must be positive.", file=sys.stderr)
        sys.exit(1)
    asyncio.run(main(args.count, args.source))
