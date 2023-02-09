from __future__ import annotations
from dotenv import dotenv_values, load_dotenv

from MeowerBot import Bot
from MeowerBot.context import CTX, Post
from revolt import Client, TextChannel,  Masquerade, Message
import revolt as revolt_pkg
import asyncio
import aiohttp
import pymongo
import threading

load_dotenv()

MEOWER_USERNAME = dotenv_values()["meower_username"]
MEOWER_PASSWORD = dotenv_values()["meower_password"]
REVOLT_TOKEN = dotenv_values()["revolt_token"]
DATABASE = pymongo.MongoClient(dotenv_values().get("mongo_url", "mongodb://localhost:27017"))["revolt-meower"]

# check if the environment variables are set
if not MEOWER_USERNAME or not MEOWER_PASSWORD or not REVOLT_TOKEN:
    raise ValueError("Environment variables not set")


MEOWER = Bot(autoreload=0)
LINKING_USERS = {}


async def send_revolt_message(message: Post, chat_id: str):
    # send the message to the revolt channel
    chat: TextChannel = await revolt.fetch_channel(chat_id)  # type: ignore

    if type(chat) is not TextChannel:
        return
    try:
        await chat.send(content=str(message), masquerade=Masquerade(name=message.user.username, avatar=f"https://assets.meower.org/PFP/{message.user.pfp}.svg"))
    except revolt_pkg.errors.HTTPError:
        MEOWER.send_msg("Failed to send message to revolt channel")


def on_message_meower(message: Post, bot=MEOWER):
    if message.user.username == MEOWER_USERNAME:
        return

    if str(message).startswith(f"@{MEOWER_USERNAME} link "):
        # check if the user is linking a revolt account
        args = str(message).split(" ")[2:]
        revolt_user = args.pop(0)

        if revolt_user not in LINKING_USERS:
            message.ctx.reply("You are not linking a revolt account")
            return

        # check if the revolt user is the same as the one that started the linking
        if LINKING_USERS[revolt_user]['meower_username'] != message.user.username:
            message.ctx.reply("You are not linking your revolt account")
            return

        # insert the user into the database
        DATABASE.users.insert_one(
            {"meower_username": message.user.username, "revolt_user": revolt_user, "pfp": message.user.pfp})
        message.ctx.reply("Successfully linked your revolt account")
        return

    # check if a message is in a known revolt channel
    chats = DATABASE.chats.find({"meower_chat": message.chat})

    if chats is None:
        return

    # send the message to the revolt channel
    for chat in chats:
        loop.create_task(send_revolt_message(message, chat["revolt_chat"]))


async def send_to_chat(chat: str, post: Message):
    channel = await revolt.fetch_channel(chat)
    if type(channel) is not TextChannel:
        return

    user = DATABASE.users.find_one({"revolt_user": post.author.id})
    if user is None:
        return

    await channel.send(content=str(post.content), masquerade=Masquerade(name=user["meower_username"], avatar=f"https://assets.meower.org/PFPS/{user['pfp']}"))


async def on_message(message: Message):
    print(str(message.content))

    # check if the message is sent by a bot
    if message.author.bot:
        return

    # check if the user has linked a meower account
    user = DATABASE.users.find_one({"revolt_user": message.author.id})

    # check if the message is a command
    if str(message.content).startswith(revolt.user.mention):
        args = str(message.content).split(" ")
        args.pop(0)
        command = args.pop(0)

        if command == "account":

            LINKING_USERS[message.author.id] = {
                "revolt_user": message.author.id,
                "meower_username": args.pop(0),
                "revolt_chat": message.channel.id
            }

            await message.channel.send(content=f"Please send @{MEOWER_USERNAME} link {message.author.id} to livechat")
            return
        elif command == "link":
            ALLOWED_CHATS = [
                "livechat",
                "home"
            ]

            chat = args.pop(0)
            if chat not in ALLOWED_CHATS:
                await message.channel.send(content=f"You can only link this channel to {','.join(ALLOWED_CHATS)}")
                return

            # add the chat to the database
            DATABASE.chats.insert_one(
                {"meower_chat": chat, "revolt_chat": message.channel.id})
            await message.channel.send(content=f"Successfully linked this channel to {chat}")
            return

    # check if the message is in a known revolt channel
    db_chat = DATABASE.chats.find_one({"revolt_chat": message.channel.id})

    if db_chat is None:
        return

    if user is None:
        await message.add_reaction("❌")
        return
    # send the message to the meower channel

    MEOWER.send_msg(
        f"{user['meower_username']}: {str(message.content)}", db_chat["meower_chat"])

    try:
        await message.add_reaction("✅")
    except revolt_pkg.errors.HTTPError:
        print("Failed to add reaction")

    chats = DATABASE.chats.find({"meower_chat": db_chat["meower_chat"]}) or []
    chats = list(chats)

    try:
        chats.remove(db_chat)  # remove the original chat from the list
    except ValueError:
        print("This somehow happened, this is a major red flag")

    # remove the original chat from the list

    tasks = []
    for chat in chats:  # type: ignore
        tasks.append(send_to_chat(chat["revolt_chat"], message))

    await asyncio.gather(*tasks)


async def on_revolt_ready():
    print("Revolt bot is ready")


class RevoltClient(Client):
    async def on_ready(self):
        await on_revolt_ready()

    async def on_message(self, message: Message):
        await on_message(message)


MEOWER.callback(on_message_meower, "message")


async def main():
    global revolt
    global loop
    loop = asyncio.get_event_loop()

    async with revolt_pkg.utils.client_session() as session:
        revolt = RevoltClient(session, REVOLT_TOKEN)
        threading.Thread(target=MEOWER.run, args=(
            MEOWER_USERNAME, MEOWER_PASSWORD)).start()
        await revolt.start()


asyncio.run(main())
