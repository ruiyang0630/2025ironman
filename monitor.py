import asyncio

import pandas as pd
from aiohttp import ClientSession

from ironman import (
    get_member_post_url,
    get_user_post_status,
)


async def get_user_post_df(session: ClientSession) -> pd.DataFrame:
    tasks = []
    async for member_post_url in get_member_post_url(session):
        tasks.append(get_user_post_status(session, member_post_url))

    user_post_statuses = [user.model_dump() for user in await asyncio.gather(*tasks)]
    df = pd.DataFrame(user_post_statuses, columns=user_post_statuses[0].keys())
    return df


async def main():
    async with ClientSession() as session:
        df = await get_user_post_df(session)
        df.to_markdown("user_post_status.md", index=False)


# Run the main function
if __name__ == "__main__":
    asyncio.run(main())
