"""Transactional mail through Resend's HTTP API (https://resend.com/docs/api-reference/emails/send-email)."""
import httpx

from . import config


class MailError(Exception):
    pass


def send(to, subject, html, text):
    if config.DEV_MODE:
        print(f"[mail:dev] to={to} subject={subject}\n{text}\n", flush=True)
        return {"dev": True}
    r = httpx.post(
        "https://api.resend.com/emails",
        headers={"Authorization": f"Bearer {config.RESEND_API_KEY}"},
        json={"from": config.MAIL_FROM, "to": [to], "subject": subject, "html": html, "text": text},
        timeout=20,
    )
    if r.status_code >= 300:
        raise MailError(f"resend {r.status_code}: {r.text[:300]}")
    return r.json()


def magic_link_mail(link, code, minutes):
    subject = "karaoke.rodeo ログインリンク / sign-in link"
    text = (
        f"karaoke.rodeo にログインするには、次のリンクを開いてください（{minutes}分間有効、1回のみ）:\n\n{link}\n\n"
        f"ホーム画面に追加したアプリや別の端末で開いている場合は、ログイン画面にこのコードを入力してください: {code}\n\n"
        f"Open this link to sign in to karaoke.rodeo (valid {minutes} minutes, single use).\n"
        f"Opened as an installed app or on another device? Enter this code on the login screen instead: {code}\n"
        "このメールに覚えがない場合は無視してください。/ If you didn't request this, ignore this mail.\n"
    )
    html = f"""<!doctype html><html><body style="font-family:-apple-system,Segoe UI,Hiragino Sans,Meiryo,sans-serif;background:#0b0e1a;color:#eef2ff;padding:32px">
<div style="max-width:520px;margin:0 auto;background:#131a2e;border:1px solid #232d4d;border-radius:16px;padding:28px 32px">
<div style="font-size:22px;letter-spacing:2px;color:#35d6f0;margin-bottom:18px">karaoke<span style="color:#ff4d8f">.</span>rodeo</div>
<p style="font-size:16px;line-height:1.6">ログインリンクです。ボタンを押すとログインします（{minutes}分間有効、1回のみ）。</p>
<p style="margin:26px 0"><a href="{link}" style="background:#ff4d8f;color:#fff;text-decoration:none;font-weight:800;padding:12px 28px;border-radius:999px;display:inline-block">ログイン / Sign in</a></p>
<p style="font-size:14px;line-height:1.6;color:#c9d1f0">ホーム画面に追加したアプリや別の端末で開いている場合は、ログイン画面にこのコードを入力してください:<br>
<span style="display:inline-block;margin-top:8px;font-size:30px;letter-spacing:8px;font-weight:800;color:#ffc64b;font-family:Consolas,Menlo,monospace">{code}</span></p>
<p style="color:#8b93b8;font-size:13px;line-height:1.6">Open this link to sign in to karaoke.rodeo (valid {minutes} minutes, single use).<br>
ボタンが動かない場合はこのURLを開いてください:<br><a href="{link}" style="color:#35d6f0;word-break:break-all">{link}</a></p>
<p style="color:#8b93b8;font-size:12px">このメールに覚えがない場合は無視してください。/ If you didn't request this, ignore this mail.</p>
</div></body></html>"""
    return subject, html, text
