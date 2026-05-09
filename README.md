# Feishu Group Task Listener

把飞书群聊里 @机器人 的工单消息写入多维表格，并向负责人发送可交互任务卡片。

## 功能

- 监听 `im.message.receive_v1` 和 `card.action.trigger`
- 自动提取执行人、车牌号、任务类型、发布时间
- 写入飞书多维表格
- 向执行人发送领取/已解决按钮卡片
- 异常消息发送“异常处理”卡片给机器人创建者
- 本地结构化日志、健康状态、启动/停止/状态脚本
- 任务类型和同义词配置化

## 配置

复制示例配置：

```cmd
copy feishu_config.example.json feishu_config.json
```

然后把 `feishu_config.json` 里的占位符替换成你的真实配置。`feishu_config.json` 已加入 `.gitignore`，不要提交真实配置。

任务类型和同义词在 `task_types.json` 中维护。

## 运行

如果同一个飞书机器人同时负责群工单和洗车提醒，只能启动统一入口，不能同时启动两个独立监听脚本：

```cmd
python feishu_automation_hub.py
python feishu_automation_hub.py --status
```

统一入口会监听：

- `im.message.receive_v1`：转给群工单逻辑
- `drive.file.bitable_record_changed_v1`：转给洗车新增记录逻辑
- `card.action.trigger`：按按钮 action 分流，`claim/resolve` 走群工单，`accept/done` 走洗车

旧的独立启动方式只适合单独运行群工单业务：

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

## 安全

仓库只提交 `feishu_config.example.json`，不会提交真实 Base Token、Table ID、Open ID、日志和处理状态文件。
