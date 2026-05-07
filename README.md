# Feishu Group Task Listener

把飞书群聊里 @机器人 的工单消息写入多维表格，并向负责人发送可交互任务卡片。

## 功能

- 监听 `im.message.receive_v1` 和 `card.action.trigger`
- 自动提取执行人、车牌号、任务类型、发布时间
- 写入飞书多维表格
- 向执行人发送领取/已解决按钮卡片
- 异常消息发送“异常处理”卡片给机器人创建者
- 可选：卡片按钮跳转 H5 定位页，写入“出发位置 / 救援结束位置”
- 本地结构化日志、健康状态、启动/停止/状态脚本
- 任务类型和同义词配置化

## 配置

复制示例配置：

```cmd
copy feishu_config.example.json feishu_config.json
```

然后把 `feishu_config.json` 里的占位符替换成你的真实配置。`feishu_config.json` 已加入 `.gitignore`，不要提交真实配置。

任务类型和同义词在 `task_types.json` 中维护。

### 定位配置

如需点击卡片按钮采集位置，在 `feishu_config.json` 中配置：

```json
{
  "location_base_url": "https://your-domain.example.com",
  "location_signing_secret": "CHANGE_ME_TO_A_RANDOM_SECRET",
  "location_claim_field": "出发位置",
  "location_resolve_field": "救援结束位置",
  "location_value_mode": "location",
  "location_bind_host": "0.0.0.0",
  "location_port": 8000
}
```

`location_value_mode=location` 会按飞书多维表格地理位置字段格式写入：

```json
{"lng": 121.4737, "lat": 31.2304}
```

如果字段改成文本，可以设为 `text`。

## 运行

```cmd
start_listener.cmd
status_listener.cmd
stop_listener.cmd
```

也可以直接运行：

```cmd
python feishu_group_to_base.py
python feishu_group_to_base.py --status
```

定位服务本地启动：

```bash
python3.11 location_server.py --host 0.0.0.0 --port 8000 --lark-cli lark-cli
```

生产环境需要 HTTPS，否则手机浏览器通常无法获取定位。可以用 Nginx/Caddy 反代到 `8000` 端口。

## 安全

仓库只提交 `feishu_config.example.json`，不会提交真实 Base Token、Table ID、Open ID、日志和处理状态文件。
