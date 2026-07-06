# Feishu Car Wash Notifier

飞书车辆清洗提醒接入：监听车辆清洗数据总表新增记录，用同一个飞书机器人向群内发送洗车任务卡片，并处理卡片按钮回写。

## Base

- Base URL: `https://atomdance.feishu.cn/base/LdiKbOgd7a5FSvsgNO5c0DNunTa?from=from_copylink`
- Base token: `LdiKbOgd7a5FSvsgNO5c0DNunTa`
- Table ID: `tblaTXQqJNNAzMSS`
- Table name: `车辆清洗数据总表`
- Target chat join link: `https://applink.feishu.cn/client/chat/chatter/add_by_link?link_token=382sa608-24f7-40ab-96df-3b498c555855`

## 配置

复制配置模板：

```cmd
copy car_wash_config.example.json car_wash_config.json
copy feishu_config.example.json feishu_config.json
copy .env.example .env
```

默认优先读取本目录的 `feishu_config.json`；如果作为父项目子目录运行，也会回退读取父目录的 `feishu_config.json`：

- `base_host`
- `bot_creator_open_id`
- `timezone`

新接入自己的信息放在 `car_wash_config.json`：

- `base_token`: 新 Base token，已预填
- `table_id`: `车辆清洗数据总表` 的表 ID，已预填
- `target_chat_id`: 消息卡片发送目标群，必须是 `oc_xxx`；入群链接不能直接用于发消息
- `field_mapping`: 洗车流程字段映射，已按当前表结构预填

运行时也会读取 `.env`，并优先用 `.env` 覆盖 JSON 配置。常用变量：

- `BASE_TOKEN`
- `TABLE_ID`
- `TARGET_CHAT_ID`
- `BASE_HOST`
- `BOT_CREATOR_OPEN_ID`
- `TIMEZONE`
- `EVENT_TYPES`
- `PLATE_LINK_TABLE_ID`
- `PLATE_LINK_DISPLAY_FIELD`
- `POLL_INTERVAL_SECONDS`
- `POLL_SEND_EXISTING_ON_START`

当前流程字段：

- `车牌号`: 卡片展示
- `清洗需求`: 卡片展示
- `到站时间`: 卡片展示为“车辆返回场站时间”
- `清洗人员`: 点击“接受任务”后写入点击用户
- `清洗完成时间`: 点击“完成任务”后写入当前时间
- `清洗照片`: 点击“上传清洗照片”后打开记录，由用户上传到该附件字段
- `任务状态`: 自动写入 `待接单` / `已接单` / `已完成`
- `群消息ID`: 群卡片发送成功后自动写入，用于重启后防重复发卡
- `私聊消息ID`: 接单后私聊卡片发送成功时自动写入

首次运行或新增字段前，执行一次：

```cmd
python car_wash_notifier.py --ensure-fields
```

该命令会补齐 `任务状态`、`群消息ID`、`私聊消息ID` 三个自动化字段。

## 常用命令

查看配置和健康状态：

```cmd
status_car_wash_notifier.cmd
```

查看 Base 下有哪些表：

```cmd
inspect_base.cmd
```

发送一张示例卡片到配置的 `target_chat_id` 或命令行指定的目标：

```cmd
python car_wash_notifier.py --send-sample-card --chat-id oc_xxx
python car_wash_notifier.py --send-sample-card --user-id ou_xxx
```

启动实时监听：

```cmd
start_car_wash_notifier.cmd
```

监听器会处理两类事件：

- Base 新增记录事件：读取记录详情并发送洗车提醒卡片
- `card.action.trigger`：处理“接受任务”“完成任务”按钮

交互规则：

- 新增记录先发群卡，并把 `任务状态=待接单`、`群消息ID` 写回表格。
- 群内点击“接受任务”后，群卡会显示“@xxx已接清洗任务”，并禁用群卡按钮。
- 接单人会收到一张私聊任务卡片，里面有“完成任务”和“上传清洗照片”两个按钮。
- 点击“完成任务”前会校验 `清洗照片`。如果没有照片，不写入完成时间，并私聊提醒先上传照片。
- 上传照片后再次点击“完成任务”，写入 `清洗完成时间` 和 `任务状态=已完成`，并把完成按钮改为“已清洗”且禁用。

默认 `EVENT_TYPES` 为：

```text
card.action.trigger,drive.file.bitable_record_changed_v1
```

如果飞书后台实际下发的 Base 新增记录事件名不同，先看 `runtime_events.ndjson` 和 `car_wash_notifier.err.log`，再调整 `.env` 里的 `EVENT_TYPES`。

`车牌号` 是关联字段时，脚本会用 `.env` 中的 `PLATE_LINK_TABLE_ID` 和 `PLATE_LINK_DISPLAY_FIELD` 读取关联车辆表，把卡片里的车牌号展示为可读文本。

脚本会保留 WebSocket 监听，同时用 `POLL_INTERVAL_SECONDS` 做轮询兜底。首次启动默认只把已有记录标记为已见过，不会批量补发；后续新增记录会被轮询发卡片。

手动补发某条记录：

```cmd
python car_wash_notifier.py --record-id rec_xxx
```

手动补发某条记录的接单人私聊任务卡：

```cmd
python car_wash_notifier.py --send-private-card --record-id rec_xxx --user-id ou_xxx
```

手动轮询一次：

```cmd
python car_wash_notifier.py --poll-once
```

异常兜底：发送卡片、读取记录、回写字段、更新卡片失败时，会给根目录 `feishu_config.json` 中的 `bot_creator_open_id` 发送异常卡片。

停止监听：

```cmd
stop_car_wash_notifier.cmd
```

## 后续接入点

1. 把真实群 `chat_id` 填入 `car_wash_config.json` 的 `target_chat_id`。
2. 启动监听后，在 Base 里新增一条测试记录，确认真实新增记录事件能被 WebSocket 下发。
3. 如果 Base 自动化能把记录 JSON 推给本地脚本，也可调用：

```cmd
python car_wash_notifier.py --record-json "{\"record_id\":\"rec_xxx\",\"fields\":{...}}"
```
