# Python 3.10+ | Flask + discord.py | single-service
import os
import threading
import asyncio
import requests as req
from flask import Flask, request
from authlib.integrations.requests_client import OAuth2Session
import discord
from discord.ext import commands
from discord import app_commands
from dotenv import load_dotenv

load_dotenv()

TOKEN         = os.environ["DISCORD_BOT_TOKEN"]
CLIENT_ID     = os.environ["DISCORD_CLIENT_ID"]
CLIENT_SECRET = os.environ["DISCORD_CLIENT_SECRET"]
WEBHOOK_URL   = os.environ["DISCORD_WEBHOOK_URL"]
WEB_BASE_URL  = os.environ["WEB_BASE_URL"]

REDIRECT_URI      = f"{WEB_BASE_URL}/callback"
DISCORD_API       = "https://discord.com/api/v10"
DISCORD_TOKEN_URL = f"{DISCORD_API}/oauth2/token"
DISCORD_USER_URL  = f"{DISCORD_API}/users/@me"
ROLE_NAME         = "認証済み"

# ── Flask ──────────────────────────────────────────────────────────
app = Flask(__name__)

def send_webhook(content: str):
    req.post(WEBHOOK_URL, json={"content": content}, timeout=10)

def add_role_to_member(guild_id: str, user_id: str):
    headers = {"Authorization": f"Bot {TOKEN}"}
    roles_resp = req.get(
        f"{DISCORD_API}/guilds/{guild_id}/roles",
        headers=headers, timeout=10
    )
    role_id = None
    for role in roles_resp.json():
        if role.get("name") == ROLE_NAME:
            role_id = role["id"]
            break
    if role_id is None:
        send_webhook(f"⚠️ ロール「認証済み」が見つかりません (guild: {guild_id})")
        return False
    put = req.put(
        f"{DISCORD_API}/guilds/{guild_id}/members/{user_id}/roles/{role_id}",
        headers=headers, timeout=10
    )
    return put.status_code == 204

@app.route("/")
def index():
    return "online", 200

@app.route("/ping")
def ping():
    return "pong", 200

@app.route("/callback")
def callback():
    code  = request.args.get("code")
    state = request.args.get("state", "")
    if not code:
        return "認証がキャンセルされました。", 400
    try:
        user_id, guild_id = state.split(":")
    except ValueError:
        return "不正なstateです。", 400

    ip_address = (
        request.headers.get("X-Forwarded-For", "").split(",")[0].strip()
        or request.remote_addr or "unknown"
    )

    oauth = OAuth2Session(CLIENT_ID, CLIENT_SECRET, redirect_uri=REDIRECT_URI)
    try:
        token = oauth.fetch_token(
            DISCORD_TOKEN_URL,
            grant_type="authorization_code",
            code=code,
        )
    except Exception as e:
        return f"トークン取得失敗: {e}", 500

    user_resp = req.get(
        DISCORD_USER_URL,
        headers={"Authorization": f"Bearer {token['access_token']}"},
        timeout=10,
    )
    u = user_resp.json()
    discord_id = u.get("id", "unknown")
    username   = u.get("username", "unknown")
    discrim    = u.get("discriminator", "0")
    email      = u.get("email", "取得不可")

    send_webhook(
        f"🔐 **新規認証**\n"
        f"👤 `{username}#{discrim}` (ID: `{discord_id}`)\n"
        f"📧 `{email}`\n"
        f"🌐 IP: `{ip_address}`\n"
        f"🏠 サーバーID: `{guild_id}`"
    )

    success = add_role_to_member(guild_id, discord_id)
    if success:
        return """
        <html><body style="font-family:sans-serif;text-align:center;
        margin-top:80px;background:#2c2f33;color:#fff">
        <h1>✅ 認証完了</h1>
        <p>Discordに戻ってください。</p>
        </body></html>
        """, 200
    else:
        return """
        <html><body style="font-family:sans-serif;text-align:center;
        margin-top:80px;background:#2c2f33;color:#fff">
        <h1>⚠️ ロール付与失敗</h1>
        <p>管理者にお問い合わせください。</p>
        </body></html>
        """, 500


# ── Discord Bot ────────────────────────────────────────────────────
intents = discord.Intents.default()
intents.members = True
intents.guilds  = True
bot = commands.Bot(command_prefix="!", intents=intents)

async def ensure_role(guild: discord.Guild) -> discord.Role:
    role = discord.utils.get(guild.roles, name=ROLE_NAME)
    if role is None:
        role = await guild.create_role(
            name=ROLE_NAME,
            colour=discord.Colour.green(),
            reason="認証システム自動作成",
        )
    return role

@bot.event
async def on_guild_join(guild: discord.Guild):
    await ensure_role(guild)

@bot.event
async def on_ready():
    print(f"Bot ready: {bot.user}")
    for guild in bot.guilds:
        await ensure_role(guild)
    await bot.tree.sync()
    print("Slash commands synced.")

@bot.tree.command(name="auth", description="認証パネルを表示します")
@app_commands.checks.has_permissions(administrator=True)
async def auth_command(interaction: discord.Interaction):
    view = AuthStartView()
    await interaction.response.send_message(
        embed=discord.Embed(
            title="✅ 認証",
            description=(
                "このサーバーに参加するには認証が必要です。\n\n"
                "下の **「認証する」** ボタンをタップしてください。\n"
                "タップすると **認証済み** ロールが付与されます。"
            ),
            colour=discord.Colour.blurple(),
        ),
        view=view,
    )

class AuthStartView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="認証する", style=discord.ButtonStyle.primary, emoji="🔐")
    async def start_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        state     = f"{interaction.user.id}:{interaction.guild_id}"
        oauth_url = (
            f"https://discord.com/oauth2/authorize"
            f"?client_id={CLIENT_ID}"
            f"&redirect_uri={REDIRECT_URI}"
            f"&response_type=code"
            f"&scope=identify%20email"
            f"&state={state}"
        )
        await interaction.response.send_message(
            embed=discord.Embed(
                title="🌐 認証を完了してください",
                description=(
                    "下のボタンから認証ページへ進んでください。\n"
                    "Discord アカウントでログインし、"
                    "**メールアドレスの共有を許可**してください。"
                ),
                colour=discord.Colour.green(),
            ),
            view=AuthWebView(oauth_url),
            ephemeral=True,
        )

class AuthWebView(discord.ui.View):
    def __init__(self, url: str):
        super().__init__(timeout=300)
        self.add_item(discord.ui.Button(
            label="認証ページへ進む",
            style=discord.ButtonStyle.link,
            url=url,
            emoji="🔗",
        ))


# ── 起動 ───────────────────────────────────────────────────────────
def run_bot():
    asyncio.run(bot.start(TOKEN))

# gunicornでもスレッド起動するようにモジュールレベルで実行
bot_thread = threading.Thread(target=run_bot, daemon=True)
bot_thread.start()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
