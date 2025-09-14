import asyncio
import json
from datetime import date, datetime, time, timedelta, timezone
from http import HTTPStatus
from pathlib import Path
from re import search
from textwrap import dedent

from aiohttp import ClientSession
from bs4 import BeautifulSoup
from pydantic import BaseModel, computed_field
from strenum import StrEnum

from config import (
    ITHOME_IRONMAN_TEAM_ID,
    TELEGRAM_BOT_TOKEN,
    TELEGRAM_CHAT_IDS
)

TZ = timezone(timedelta(hours=8))


class TeamMember(BaseModel):
    realname: str
    department: str
    grade: str


with open("users.json", "r", encoding="utf-8") as format_message:
    user_mappings = json.load(format_message)


class UserPostStatus(BaseModel):
    username: str
    post_count: int
    title: str
    url: str

    @computed_field
    @property
    def realname(self) -> str:
        nickname = search(r"(\w+) \((\w+)\)", self.username).group(1)
        if nickname not in user_mappings:
            return nickname

        return user_mappings[nickname]["realname"]

    @computed_field
    @property
    def message(self) -> str:
        # nickname, ID = search(r"(\w+) \((\w+)\)", user.username).groups()
        nickname = search(r"(\w+) \((\w+)\)", self.username).group(1)
        if nickname not in user_mappings:
            return f"- **{nickname}** {self.title}"

        department, grade, _ = user_mappings[nickname].values()
        return f"- **{self.realname}({department} Team, {grade})**: [{self.title}]({self.url})"


class SelectorEnum(StrEnum):
    HREF_SELECTOR = "body > section > div > div > div > div.col-md-10 > a"
    POST_COUNT_SELECTOR = "body > div.container.index-top > div > div > div.board.leftside.profile-main > div.ir-profile-content > div.ir-profile-series > div.qa-list__info.qa-list__info--ironman.subscription-group > span:nth-child(1)"
    USERNAME_SELECTOR = "body > div.container.index-top > div > div > div:nth-child(1) > div.profile-header.clearfix > div.profile-header__content > div.profile-header__name"


class URLEnum(StrEnum):
    TEAM_URL = (
        f"https://ithelp.ithome.com.tw/2025ironman/signup/team/{ITHOME_IRONMAN_TEAM_ID}"
    )


START_DATE = date(2025, 9, 14)
END_DATE = date(2025, 10, 14)
TARGET_POST_COUNT = 30

headers = {
    "referer": "https://ithelp.ithome.com.tw/notifications",
    "user-agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
}


async def get_team_status(session: ClientSession):
    async with session.get(URLEnum.TEAM_URL, headers=headers) as resp:
        if resp.status != HTTPStatus.OK:
            error_message = await resp.text()
            raise Exception(
                f"Failed to get team status: {resp.reason}\n{error_message}"
            )

        return await resp.text()


async def get_member_post_url(session: ClientSession):
    team_status = await get_team_status(session)
    soup = BeautifulSoup(team_status, "html.parser")
    for url in soup.select(SelectorEnum.HREF_SELECTOR):
        yield url["href"]


async def get_user_post_status(session: ClientSession, href: str) -> UserPostStatus:
    async with session.get(href, headers=headers) as user_posts_response:
        if user_posts_response.status != HTTPStatus.OK:
            error_message = await user_posts_response.text()
            raise Exception(
                f"Failed to get user posts: {user_posts_response.reason}\n{error_message}"
            )

        post_soup = BeautifulSoup(await user_posts_response.text(), "html.parser")
        post_count_element = post_soup.select_one(SelectorEnum.POST_COUNT_SELECTOR)

        return UserPostStatus(
            username=post_soup.select_one(SelectorEnum.USERNAME_SELECTOR)
            .text.replace("\n", "")
            .strip(),
            post_count=int(
                search(r"參賽天數 (\d+) 天", post_count_element.text).group(1)
            ),
            title=post_soup.title.text.split(" ::")[0],
            url=href,
        )

async def send_telegram_message(session: ClientSession, message: str):

    for chat_id in TELEGRAM_CHAT_IDS:
        resp = await session.post(
            f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
            json={"chat_id": chat_id, "text": message, "parse_mode": "Markdown"},
            headers={"Content-Type": "application/json"},
        )
        data = await resp.text()
        print("Telegram response:", resp.status, data)


async def get_today_not_posted_user(session: ClientSession, all_user: bool = False):
    tasks = []
    async for member_post_url in get_member_post_url(session):
        tasks.append(get_user_post_status(session, member_post_url))

    user_post_statuses = await asyncio.gather(*tasks)

    for user in user_post_statuses:
        if START_DATE + timedelta(days=user.post_count) != date.today() or all_user:
            yield user


async def main():
    async with ClientSession() as session:
        not_posted_users = [user async for user in get_today_not_posted_user(session)]
        now = datetime.now(TZ)
        current_day = (now.date() - START_DATE).days
        remain_day = (END_DATE - now.date()).days

        if not_posted_users:
            target_time = datetime.combine(now.date(), time(23, 59, 59), tzinfo=TZ)
            remain_delta = target_time - now
            remain_time = (
                (datetime.min + remain_delta).time().strftime(" %H 小時 %M 分 %S 秒")
            )

            # 發送主通知
            await send_telegram_message(
                session,
                dedent(
                    f"""
                    📢 *第 {current_day} 天*
                    今天還沒有發文的成員有 *{len(not_posted_users)}* 位  
                    ⏳ 距離截止時間還有 {remain_time}
                    """
                ),
            )

            # 逐一發送還沒發文的成員
            for user in not_posted_users:
                await send_telegram_message(session, user.message)

        else:
            done_file_path = Path(f"done_{current_day}.txt")
            if done_file_path.exists() is True:
                print("Already sent the message")
                return

            # 全部完成的通知
            await send_telegram_message(
                session,
                dedent(
                    f"""
                    🎉 *第 {current_day} 天*
                    今天所有成員都有發文了！  
                    目標是 *{TARGET_POST_COUNT}* 篇！  
                    (還剩下 {remain_day} 天)
                    """
                ),
            )

            # 建立檔案避免重複通知
            with done_file_path.open("w", encoding="utf-8") as done_file:
                done_file.write("done")


# Run the main function
if __name__ == "__main__":
    asyncio.run(main())
