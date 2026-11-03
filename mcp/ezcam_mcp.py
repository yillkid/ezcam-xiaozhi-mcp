"""EZ-CAM 拍照 MCP server（區網版）。

在老師的電腦上執行，透過區網跟 ESP32-CAM 拿照片，給小智當工具用。
通常不直接執行這支，而是由 xiaozhi_bridge.py 帶起來。

工具：
  capture_now      拍一張新照片，存到 photos/ 資料夾
  describe_photo   看最新的照片並回答問題（需要設定 OPENAI_API_KEY）
  camera_status    檢查相機有沒有連上
"""
import base64
import logging
import os
import sys
import time
from pathlib import Path

import httpx
from mcp.server.fastmcp import FastMCP

# 只印老師看得懂的訊息（stdout 留給 MCP 協定，訊息一律寫到 stderr）
for noisy in ("mcp", "httpx", "httpcore"):
    logging.getLogger(noisy).setLevel(logging.WARNING)


def say(msg: str) -> None:
    print(time.strftime("%H:%M:%S"), msg, file=sys.stderr, flush=True)

CAM_URL = os.environ.get("EZCAM_URL", "http://ezcam.local").rstrip("/")
CAM_KEY = os.environ.get("EZCAM_KEY", "")
OPENAI_KEY = os.environ.get("OPENAI_API_KEY", "")
VISION_MODEL = os.environ.get("VISION_MODEL", "gpt-4o-mini")
PHOTO_DIR = Path(os.environ.get("PHOTO_DIR", Path(__file__).with_name("photos")))
PHOTO_DIR.mkdir(parents=True, exist_ok=True)

mcp = FastMCP("ezcam")


def cam_params() -> dict:
    return {"key": CAM_KEY} if CAM_KEY else {}


def latest_photo() -> Path | None:
    photos = sorted(PHOTO_DIR.glob("*.jpg"))
    return photos[-1] if photos else None


@mcp.tool()
async def capture_now() -> str:
    """用 ESP32-CAM 立即拍一張新照片。使用者說「拍照」「拍一張」時使用。
    拍完只回報時間；想知道照片裡有什麼，請接著用 describe_photo。"""
    say("小智要求拍照…")
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            r = await client.get(f"{CAM_URL}/capture", params=cam_params())
    except httpx.HTTPError:
        say(f"連不到相機 {CAM_URL}，請檢查 .env 的 EZCAM_URL")
        return "連不到相機，請確認 ESP32-CAM 有開機，而且跟電腦在同一個 Wi-Fi。"
    if r.status_code != 200 or not r.content.startswith(b"\xff\xd8"):
        say(f"相機回應 {r.status_code}，沒有拿到照片")
        return f"相機沒有拍成功（{r.status_code}），請再試一次。"
    stamp = time.strftime("%Y%m%d-%H%M%S")
    path = PHOTO_DIR / f"{stamp}.jpg"
    path.write_bytes(r.content)
    say(f"拍好了，存成 photos/{path.name}（{len(r.content) // 1024} KB）")
    return f"拍照完成，時間 {time.strftime('%H:%M:%S')}。"


@mcp.tool()
async def describe_photo(question: str = "照片裡有什麼？") -> str:
    """看最新拍的照片並回答問題，例如「照片裡有什麼？」。不會拍新照片；要拍新照片請先用 capture_now。"""
    photo = latest_photo()
    if photo is None:
        return "還沒有照片，請先拍照。"
    say(f"小智要求看照片：{question}")
    if not OPENAI_KEY:
        say("沒有設定 OPENAI_API_KEY，只能拍照、不能描述")
        return f"照片已經存好（{photo.name}），但還沒設定看圖用的 OPENAI_API_KEY，所以沒辦法描述。"
    image = base64.b64encode(photo.read_bytes()).decode()
    body = {
        "model": VISION_MODEL,
        "max_tokens": 300,
        "messages": [{
            "role": "user",
            "content": [
                {"type": "text", "text": f"用繁體中文、兩三句話回答，對象是學生：{question}"},
                {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{image}"}},
            ],
        }],
    }
    try:
        async with httpx.AsyncClient(timeout=60) as client:
            r = await client.post("https://api.openai.com/v1/chat/completions", json=body,
                                  headers={"Authorization": f"Bearer {OPENAI_KEY}"})
            r.raise_for_status()
            answer = r.json()["choices"][0]["message"]["content"].strip()
    except (httpx.HTTPError, KeyError, IndexError) as e:
        say(f"看圖服務出錯：{type(e).__name__}（請檢查 OPENAI_API_KEY）")
        return "看圖服務暫時沒有回應，請稍後再試。"
    say(f"看圖結果：{answer}")
    return answer


@mcp.tool()
async def camera_status() -> str:
    """檢查相機有沒有連上、訊號好不好。相機好像壞掉時使用。"""
    say("小智要求檢查相機")
    try:
        async with httpx.AsyncClient(timeout=8) as client:
            r = await client.get(f"{CAM_URL}/status", params=cam_params())
            data = r.json()
    except (httpx.HTTPError, ValueError):
        return "連不到相機，請確認 ESP32-CAM 有開機，而且跟電腦在同一個 Wi-Fi。"
    return f"相機正常，IP {data.get('ip')}，訊號 {data.get('rssi')} dBm，已拍 {data.get('shots')} 張。"


if __name__ == "__main__":
    say(f"相機工具準備好了，相機網址 {CAM_URL}")
    mcp.run(transport="stdio")
