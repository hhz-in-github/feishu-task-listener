import argparse
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qs, urlparse

from feishu_group_to_base import (
    LOCATION_BIND_HOST,
    LOCATION_PORT,
    build_location_update,
    log_event,
    update_record,
    verify_location_action,
)


LOCATION_PAGE = """<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>任务位置确认</title>
  <style>
    body { margin: 0; font-family: system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; background: #f6f7f9; color: #111827; }
    main { min-height: 100vh; display: flex; align-items: center; justify-content: center; padding: 24px; box-sizing: border-box; }
    section { width: 100%; max-width: 560px; background: #fff; border: 1px solid #e5e7eb; border-radius: 8px; padding: 28px; box-shadow: 0 8px 24px rgba(15, 23, 42, 0.08); }
    h1 { margin: 0 0 16px; font-size: 26px; line-height: 1.25; }
    p { margin: 0 0 16px; color: #4b5563; font-size: 16px; line-height: 1.7; }
    .status { color: #1f2937; }
    .error { color: #b42318; }
    button { width: 100%; border: 0; border-radius: 6px; background: #111827; color: #fff; cursor: pointer; font-size: 16px; font-weight: 600; padding: 12px 16px; }
    button:disabled { background: #9ca3af; cursor: default; }
  </style>
</head>
<body>
  <main>
    <section>
      <h1>任务位置确认</h1>
      <p id="description">本页面将请求获取您的地理位置，用于记录任务处理位置和点击时间。</p>
      <p id="status" class="status">正在准备定位。</p>
      <button id="retry" type="button" style="display:none">重新获取位置</button>
    </section>
  </main>
  <script>
    const params = new URLSearchParams(window.location.search);
    const action = params.get("action");
    const recordId = params.get("record_id");
    const token = params.get("token");
    const statusEl = document.getElementById("status");
    const retryButton = document.getElementById("retry");
    const description = document.getElementById("description");

    const actionText = action === "resolve" ? "救援结束位置" : "出发位置";
    description.textContent = `本页面将请求获取您的地理位置，用于写入${actionText}。`;

    function setStatus(message, isError = false) {
      statusEl.textContent = message;
      statusEl.className = isError ? "error" : "status";
      retryButton.style.display = isError ? "block" : "none";
    }

    async function submitPosition(position) {
      setStatus("定位成功，正在写入多维表格。");
      const body = {
        action,
        record_id: recordId,
        token,
        latitude: position.coords.latitude,
        longitude: position.coords.longitude,
        accuracy: position.coords.accuracy,
        clicked_at: new Date().toISOString(),
      };
      const response = await fetch("/api/location-submit", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      if (!response.ok) {
        const payload = await response.json().catch(() => ({}));
        throw new Error(payload.error || "位置写入失败");
      }
      setStatus("位置已写入，可以关闭本页面。");
      retryButton.style.display = "none";
    }

    function requestLocation() {
      if (!action || !recordId || !token) {
        setStatus("链接缺少必要参数，请回到飞书卡片重新点击。", true);
        return;
      }
      if (!navigator.geolocation) {
        setStatus("当前浏览器不支持定位。", true);
        return;
      }
      setStatus("正在请求定位，请在浏览器弹窗中允许位置访问。");
      navigator.geolocation.getCurrentPosition(
        (position) => submitPosition(position).catch((error) => setStatus(error.message, true)),
        (error) => {
          if (error.code === error.PERMISSION_DENIED) {
            setStatus("定位权限被拒绝，请在浏览器设置中允许位置访问后重试。", true);
          } else if (error.code === error.TIMEOUT) {
            setStatus("定位超时，请确认网络和定位权限后重试。", true);
          } else {
            setStatus("定位失败，请稍后重试。", true);
          }
        },
        { enableHighAccuracy: true, timeout: 12000, maximumAge: 0 },
      );
    }

    retryButton.addEventListener("click", requestLocation);
    requestLocation();
  </script>
</body>
</html>
"""


class LocationRequestHandler(BaseHTTPRequestHandler):
    server_version = "FeishuLocationServer/1.0"

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/location":
            self._send_html(LOCATION_PAGE)
            return
        if parsed.path == "/health":
            self._send_json({"ok": True})
            return
        self.send_error(404)

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path != "/api/location-submit":
            self.send_error(404)
            return
        try:
            payload = self._read_json()
            action = str(payload.get("action") or "")
            record_id = str(payload.get("record_id") or "")
            token = str(payload.get("token") or "")
            latitude = float(payload["latitude"])
            longitude = float(payload["longitude"])
            accuracy = payload.get("accuracy")
            accuracy_value = float(accuracy) if accuracy is not None else None
        except (ValueError, TypeError, KeyError, json.JSONDecodeError):
            self._send_json({"error": "Invalid location payload"}, status=400)
            return

        if not verify_location_action(action, record_id, token):
            self._send_json({"error": "Invalid location token"}, status=403)
            return

        try:
            update = build_location_update(action, latitude, longitude, accuracy_value)
            update_record(record_id, update, self.server.lark_cli)  # type: ignore[attr-defined]
            log_event(
                "location_submitted",
                action=action,
                record_id=record_id,
                latitude=latitude,
                longitude=longitude,
                accuracy=accuracy_value,
            )
        except Exception as exc:
            self._send_json({"error": f"Failed to write location: {exc}"}, status=500)
            return

        self._send_json({"ok": True})

    def log_message(self, format: str, *args: Any) -> None:
        log_event("location_server_access", message=format % args)

    def _read_json(self) -> dict[str, Any]:
        length = int(self.headers.get("content-length") or 0)
        raw = self.rfile.read(length)
        payload = json.loads(raw.decode("utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("JSON body must be an object")
        return payload

    def _send_html(self, html: str, status: int = 200) -> None:
        body = html.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_json(self, payload: dict[str, Any], status: int = 200) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def run_server(host: str, port: int, lark_cli: str) -> None:
    server = ThreadingHTTPServer((host, port), LocationRequestHandler)
    server.lark_cli = lark_cli  # type: ignore[attr-defined]
    print(f"Location server listening on http://{host}:{port}", flush=True)
    server.serve_forever()


def main() -> None:
    parser = argparse.ArgumentParser(description="Serve task location capture page.")
    parser.add_argument("--host", default=LOCATION_BIND_HOST)
    parser.add_argument("--port", type=int, default=LOCATION_PORT)
    parser.add_argument("--lark-cli", default="lark-cli")
    args = parser.parse_args()
    run_server(args.host, args.port, args.lark_cli)


if __name__ == "__main__":
    main()
