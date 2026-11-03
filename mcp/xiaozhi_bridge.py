"""把 ezcam_mcp.py 接到小智。

小智控制台會給你一個「MCP 接入點」網址（wss://...）。這支程式從老師電腦
主動連出去，所以不需要網域、不需要開防火牆、不需要固定 IP。

用法：
  1. 把 .env.example 複製成 .env，填好 MCP_ENDPOINT 和 EZCAM_URL
  2. python xiaozhi_bridge.py
斷線會自動重連，視窗開著就一直有效。
"""
import asyncio
import logging
import os
import sys
from pathlib import Path

import websockets
from dotenv import load_dotenv

HERE = Path(__file__).resolve().parent
load_dotenv(HERE / ".env")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", datefmt="%H:%M:%S")
log = logging.getLogger("bridge")

ENDPOINT = os.environ.get("MCP_ENDPOINT", "").strip()
SERVER = [sys.executable, str(HERE / "ezcam_mcp.py")]


async def pump_ws_to_proc(ws, proc):
    async for message in ws:
        if isinstance(message, bytes):
            message = message.decode()
        proc.stdin.write(message.encode() + b"\n")
        await proc.stdin.drain()


async def pump_proc_to_ws(proc, ws):
    while line := await proc.stdout.readline():
        await ws.send(line.decode())


async def pump_stderr(proc):
    while line := await proc.stderr.readline():
        sys.stderr.write(line.decode())


async def session():
    async with websockets.connect(ENDPOINT, ping_interval=20, ping_timeout=20) as ws:
        log.info("已連上小智，相機工具上線（capture_now、describe_photo、camera_status）")
        proc = await asyncio.create_subprocess_exec(
            *SERVER, stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE, env=os.environ.copy())
        tasks = [asyncio.create_task(t) for t in
                 (pump_ws_to_proc(ws, proc), pump_proc_to_ws(proc, ws), pump_stderr(proc))]
        try:
            await asyncio.wait(tasks[:2], return_when=asyncio.FIRST_COMPLETED)
        finally:
            for t in tasks:
                t.cancel()
            if proc.returncode is None:
                proc.terminate()
                await proc.wait()


async def main():
    if not ENDPOINT.startswith("wss://"):
        sys.exit("請在 .env 設定 MCP_ENDPOINT（小智控制台的 MCP 接入點，wss:// 開頭）")
    wait = 1
    while True:
        try:
            await session()
            log.warning("小智那邊結束連線，重新連線中")
            wait = 1
        except Exception as e:  # 網路斷掉、小智重啟都會進來
            log.warning("連線中斷：%s，%d 秒後重連", type(e).__name__, wait)
        await asyncio.sleep(wait)
        wait = min(wait * 2, 60)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
