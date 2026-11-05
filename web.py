# Python 3.10+ | Flask + Authlib
# env: DISCORD_CLIENT_ID, DISCORD_CLIENT_SECRET, DISCORD_BOT_TOKEN,
#       DISCORD_WEBHOOK_URL, WEB_BASE_URL

import os
import requests as req
from flask import Flask, request, redirect, jsonify
from authlib.integrations.requests_client import OAuth2Session
from dotenv import load_dotenv

load_dotenv()

CLIENT_ID     = os.environ["DISCORD_CLIENT_ID"]
CLIENT_SECRET = os.environ["DISCORD_CLIENT_SECRET"]
BOT_TOKEN     = os.environ["DISCORD_BOT_TOKEN"]
WEBHOOK_URL   = os.environ["DISCORD_WEBHOOK_URL"]
WEB_BASE_URL  = os.environ["WEB_BASE_URL"]

REDIRECT_URI       = f"{WEB_BASE_URL}/callback"
DISCORD_API        = "https://discord.com/api/v10"
DISCORD_TOKEN_URL  = f"{DISCORD_API}/oauth2/token"
DISCORD_USER_URL   = f"{DISCORD_API}/users/@me"

app = Flask(__name__)


def send_webhook(content: str):
    """Discordウェブフックにメッセージ送信"""
    req.post(WEBHOOK_URL, json={"content": content}, timeout=10)


def add_role_to_member(guild_id: str, user_id: str):
    """
    Bot権限でロールを付与。
    ロールIDはBot側で作成済みのものをサーバーから検索して取得。
    """
    # ギルドのロール一覧取得
    headers = {"Authorization": f"Bot {BOT_TOKEN}"}
    roles_resp = req.get(f"{DISCORD_API}/guilds/{guild_id}/roles", headers=headers, timeout=10)
    roles = roles_resp.json()

    role_id = None
    for role in roles:
        if role.get("name") == "認証済み":
            role_id = role["id"]
            break

    if role_id is None:
        send_webhook(f"⚠️ ロール「認証済み」が見つかりませんでした (guild: {guild_id})")
        return False

    put_resp = req.put(
        f"{DISCORD_API}/guilds/{guild_id}/members/{user_id}/roles/{role_id}",
        headers=headers,
        timeout=10,
    )
    return put_resp.status_code == 204


@app.route("/")
def index():
    return "auth server online", 200


@app.route("/ping")
def ping():
    """UptimeRobot用エンドポイント"""
    return "pong", 200


@app.route("/callback")
def callback():
    code  = request.args.get("code")
    state = request.args.get("state", "")

    if not code:
        return "認証がキャンセルされました。", 400

    # state から user_id と guild_id を復元
    try:
        user_id, guild_id = state.split(":")
    except ValueError:
        return "不正なstateパラメータです。", 400

    # ── IPアドレス取得 ──────────────────────────────────────────
    ip_address = (
        request.headers.get("X-Forwarded-For", "").split(",")[0].strip()
        or request.remote_addr
        or "unknown"
    )

    # ── OAuth2トークン取得 ───────────────────────────────────────
    oauth = OAuth2Session(CLIENT_ID, CLIENT_SECRET, redirect_uri=REDIRECT_URI)
    try:
        token = oauth.fetch_token(
            DISCORD_TOKEN_URL,
            grant_type="authorization_code",
            code=code,
        )
    except Exception as e:
        return f"トークン取得失敗: {e}", 500

    # ── Discordユーザー情報取得 ──────────────────────────────────
    user_resp = req.get(
        DISCORD_USER_URL,
        headers={"Authorization": f"Bearer {token['access_token']}"},
        timeout=10,
    )
    user_data = user_resp.json()

    discord_id    = user_data.get("id", "unknown")
    username      = user_data.get("username", "unknown")
    discriminator = user_data.get("discriminator", "0")
    email         = user_data.get("email", "取得不可")

    # ── Webhookでメール・IP送信 ──────────────────────────────────
    send_webhook(
        f"🔐 **新規認証**\n"
        f"👤 ユーザー: `{username}#{discriminator}` (ID: `{discord_id}`)\n"
        f"📧 メール: `{email}`\n"
        f"🌐 IP: `{ip_address}`\n"
        f"🏠 サーバーID: `{guild_id}`"
    )

    # ── ロール付与 ───────────────────────────────────────────────
    success = add_role_to_member(guild_id, discord_id)

    if success:
        return """
        <html><body style="font-family:sans-serif;text-align:center;margin-top:80px;background:#2c2f33;color:#fff">
            <h1>✅ 認証完了</h1>
            <p>認証済みロールが付与されました。Discordに戻ってください。</p>
        </body></html>
        """, 200
    else:
        return """
        <html><body style="font-family:sans-serif;text-align:center;margin-top:80px;background:#2c2f33;color:#fff">
            <h1>⚠️ ロール付与失敗</h1>
            <p>管理者にお問い合わせください。</p>
        </body></html>
        """, 500


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
