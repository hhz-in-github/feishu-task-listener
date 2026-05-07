import argparse
import json
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo


CONFIG_PATH = Path("feishu_config.json")
TASK_TYPES_PATH = Path("task_types.json")
DEFAULT_CONFIG = {
    "base_token": "YOUR_BASE_TOKEN",
    "table_id": "YOUR_TABLE_ID",
    "base_host": "https://your-tenant.feishu.cn",
    "bot_creator_open_id": "YOUR_BOT_CREATOR_OPEN_ID",
    "timezone": "Asia/Shanghai",
    "structured_log_path": "events/automation.jsonl",
    "health_path": "runtime_health.json",
    "processed_message_path": "processed_message_ids.txt",
    "processed_card_action_path": "processed_card_action_ids.txt",
    "processed_alert_path": "processed_alert_ids.txt",
    "raw_event_path": "runtime_events.ndjson",
}
DEFAULT_TASK_TYPE_SPECS = [
    {"name": "被堵住出不来（保安/警戒线/锥桶）", "keywords": ["被堵住出不来", "保安", "警戒线", "锥桶"]},
    {"name": "确认货物理赔信息", "keywords": ["确认货物理赔信息"]},
    {"name": "理赔信息确认", "keywords": ["理赔信息确认", "理赔"]},
    {"name": "充电/插拔枪", "keywords": ["充电/插拔枪", "插拔枪"]},
    {"name": "抬杆识别车牌", "keywords": ["抬杆识别车牌", "抬杆"]},
    {"name": "兜底送货", "keywords": ["兜底送货"]},
    {"name": "阻塞交通", "keywords": ["阻塞交通"]},
    {"name": "充换电", "keywords": ["充换电", "补能"]},
    {"name": "插拔电", "keywords": ["插拔电"]},
    {"name": "开关门", "keywords": ["开关门"]},
    {"name": "事故", "keywords": ["事故"]},
    {"name": "其他", "keywords": ["其他"]},
    {"name": "救援", "keywords": ["救援"]},
    {"name": "充电", "keywords": ["充电"]},
    {"name": "换电", "keywords": ["换电", "换电池", "更换电池"]},
    {"name": "故障", "keywords": ["故障"]},
    {"name": "轮胎", "keywords": ["轮胎"]},
]


def load_config(path: Path = CONFIG_PATH) -> dict[str, Any]:
    config = dict(DEFAULT_CONFIG)
    if path.exists():
        with path.open("r", encoding="utf-8") as file:
            loaded = json.load(file)
        if isinstance(loaded, dict):
            config.update(loaded)
    return config


def load_task_type_specs(path: Path = TASK_TYPES_PATH) -> list[dict[str, Any]]:
    if not path.exists():
        return DEFAULT_TASK_TYPE_SPECS
    with path.open("r", encoding="utf-8") as file:
        loaded = json.load(file)
    specs = []
    if not isinstance(loaded, list):
        return DEFAULT_TASK_TYPE_SPECS
    for item in loaded:
        if isinstance(item, str):
            specs.append({"name": item, "keywords": [item]})
        elif isinstance(item, dict) and item.get("name"):
            keywords = item.get("keywords") or [item["name"]]
            specs.append({"name": str(item["name"]), "keywords": [str(keyword) for keyword in keywords]})
    return specs or DEFAULT_TASK_TYPE_SPECS


CONFIG = load_config()
TASK_TYPE_SPECS = load_task_type_specs()
BASE_TOKEN = str(CONFIG["base_token"])
TABLE_ID = str(CONFIG["table_id"])
BASE_HOST = str(CONFIG["base_host"]).rstrip("/")
TIMEZONE = ZoneInfo(str(CONFIG["timezone"]))
BOT_CREATOR_OPEN_ID = str(CONFIG["bot_creator_open_id"])

PROCESSED_LOG = Path(str(CONFIG["processed_message_path"]))
PROCESSED_CARD_ACTION_LOG = Path(str(CONFIG["processed_card_action_path"]))
PROCESSED_ALERT_LOG = Path(str(CONFIG["processed_alert_path"]))
RAW_EVENT_LOG = Path(str(CONFIG["raw_event_path"]))
STRUCTURED_LOG = Path(str(CONFIG["structured_log_path"]))
HEALTH_PATH = Path(str(CONFIG["health_path"]))


def now_iso() -> str:
    return datetime.now(TIMEZONE).isoformat(timespec="seconds")


def log_event(event_type: str, **fields: Any) -> None:
    entry = {
        "time": now_iso(),
        "event_type": event_type,
        **fields,
    }
    STRUCTURED_LOG.parent.mkdir(parents=True, exist_ok=True)
    with STRUCTURED_LOG.open("a", encoding="utf-8") as file:
        file.write(json.dumps(entry, ensure_ascii=False) + "\n")


def update_health(**fields: Any) -> None:
    state: dict[str, Any] = {}
    if HEALTH_PATH.exists():
        try:
            state = json.loads(HEALTH_PATH.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            state = {}
    state.update(fields)
    state["updated_at"] = now_iso()
    HEALTH_PATH.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def print_status() -> None:
    if not HEALTH_PATH.exists():
        print(json.dumps({"status": "unknown", "message": "No health file yet."}, ensure_ascii=False, indent=2))
        return
    print(HEALTH_PATH.read_text(encoding="utf-8"))


def parse_event(raw_event: dict[str, Any]) -> dict[str, Any]:
    message = raw_event.get("event", {}).get("message", {})
    text = _extract_text(message.get("content", ""))
    mentions = message.get("mentions") or []
    original_text = _replace_mentions(text, mentions)
    body_text = _remove_mentions(text)
    created_at = _format_event_time(message.get("create_time"))

    record: dict[str, Any] = {
        "消息原文": original_text,
        "任务发布时间": created_at.strftime("%Y-%m-%d %H:%M:%S"),
        "日期": created_at.strftime("%Y-%m-%d 00:00:00"),
        "任务状态": "待领取",
    }

    assignee_open_id = _first_user_mention_open_id(mentions)
    if assignee_open_id:
        record["执行人"] = [{"id": assignee_open_id}]

    vehicle = _extract_vehicle_number(body_text)
    if vehicle:
        record["车牌号"] = vehicle

    task_types = _extract_task_types(body_text)
    if task_types:
        record["任务类型"] = task_types

    notes = []
    if not assignee_open_id:
        notes.append("未识别执行人")
    if not vehicle:
        notes.append("未识别车牌号")
    if not task_types:
        notes.append("未识别任务类型")
    if notes:
        record["备注"] = "；".join(notes)

    return record


def run_listener(lark_cli: str, dry_run: bool = False) -> None:
    processed_ids = _load_processed_ids()
    processed_card_action_ids = _load_ids(PROCESSED_CARD_ACTION_LOG)
    update_health(
        status="starting",
        started_at=now_iso(),
        lark_cli=lark_cli,
        last_error="",
        last_error_at="",
    )
    log_event("listener_starting", lark_cli=lark_cli, dry_run=dry_run)
    command = [
        lark_cli,
        "event",
        "+subscribe",
        "--event-types",
        "im.message.receive_v1,card.action.trigger",
        "--as",
        "bot",
    ]

    print("Starting Feishu event listener...", file=sys.stderr)
    update_health(status="running")
    with subprocess.Popen(
        command,
        stdout=subprocess.PIPE,
        stderr=sys.stderr,
        text=True,
        encoding="utf-8",
        errors="replace",
    ) as process:
        assert process.stdout is not None
        for line in process.stdout:
            line = line.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                print(f"Skip non-JSON output: {line}", file=sys.stderr)
                log_event("skip_non_json_output", line=line)
                continue
            _append_raw_event(event)
            update_health(
                status="running",
                last_event_at=now_iso(),
                last_event_type=event.get("header", {}).get("event_type"),
            )
            handle_event(
                event,
                processed_ids,
                processed_card_action_ids,
                lark_cli,
                dry_run=dry_run,
            )


def handle_event(
    event: dict[str, Any],
    processed_ids: set[str],
    processed_card_action_ids: set[str],
    lark_cli: str,
    dry_run: bool = False,
) -> None:
    event_type = event.get("header", {}).get("event_type")
    if event_type == "card.action.trigger":
        handle_card_action_event(event, processed_card_action_ids, lark_cli, dry_run)
        return
    if event_type != "im.message.receive_v1":
        print(f"Skip unsupported event type: {event_type}", file=sys.stderr)
        log_event("skip_unsupported_event", event_type=event_type)
        return

    message = event.get("event", {}).get("message", {})
    message_id = message.get("message_id")
    chat_id = message.get("chat_id")
    if not message_id:
        print("Skip event without message_id", file=sys.stderr)
        log_event("skip_message_without_id", chat_id=chat_id)
        return
    if message_id in processed_ids:
        print(f"Skip duplicate message: {message_id}", file=sys.stderr)
        log_event("skip_duplicate_message", message_id=message_id, chat_id=chat_id)
        return
    mentions = message.get("mentions") or []
    if not _mentions_bot(mentions):
        print(f"Skip message without bot mention: {message_id}", file=sys.stderr)
        log_event("skip_message_without_bot_mention", message_id=message_id, chat_id=chat_id)
        processed_ids.add(message_id)
        _append_processed_id(message_id)
        return

    record = parse_event(event)
    assignee_open_id = _first_user_mention_open_id(mentions)
    original_message = str(record.get("消息原文") or _replace_mentions(
        _extract_text(message.get("content", "")),
        mentions,
    ))
    if dry_run:
        print(json.dumps(record, ensure_ascii=False), flush=True)
        if assignee_open_id:
            print(
                json.dumps(build_task_card(record, "dry_run_record_id"), ensure_ascii=False),
                flush=True,
            )
    else:
        alerted = False
        try:
            record_id = write_record_with_fallback(record, lark_cli)
            if "备注" in record:
                alert_creator(
                    chat_id,
                    original_message,
                    lark_cli,
                    reason=str(record["备注"]),
                    dedupe_key=f"message:{message_id}:incomplete",
                )
                alerted = True
                print("Skip card send: record has missing required fields", file=sys.stderr)
                log_event(
                    "incomplete_record_alerted",
                    message_id=message_id,
                    chat_id=chat_id,
                    record_id=record_id,
                    reason=record["备注"],
                )
            elif assignee_open_id:
                try:
                    card_record = dict(record)
                    if chat_id:
                        card_record["群聊ID"] = str(chat_id)
                    send_task_card(
                        assignee_open_id=assignee_open_id,
                        record=card_record,
                        record_id=record_id,
                        lark_cli=lark_cli,
                    )
                except RuntimeError as exc:
                    if not alerted:
                        alert_creator(
                            chat_id,
                            original_message,
                            lark_cli,
                            reason=f"消息卡片发送失败：{exc}",
                            dedupe_key=f"message:{message_id}:card_send",
                        )
                        alerted = True
                    raise
            else:
                print("Skip card send: no assignee open_id", file=sys.stderr)
        except RuntimeError as exc:
            if not alerted:
                reason = (
                    build_user_authorization_alert_reason()
                    if is_user_authorization_error(str(exc))
                    else f"多维表格处理失败：{exc}"
                )
                alert_creator(
                    chat_id,
                    original_message,
                    lark_cli,
                    reason=reason,
                    dedupe_key=(
                        f"user_authorization:{message_id}"
                        if is_user_authorization_error(str(exc))
                        else f"message:{message_id}:runtime"
                    ),
                )
            update_health(status="error", last_error=str(exc), last_error_at=now_iso())
            log_event("message_processing_failed", message_id=message_id, chat_id=chat_id, error=str(exc))
            raise

    processed_ids.add(message_id)
    _append_processed_id(message_id)
    update_health(last_message_id=message_id, last_message_processed_at=now_iso())
    log_event("message_processed", message_id=message_id, chat_id=chat_id)
    print(f"Processed message: {message_id}", file=sys.stderr)


def handle_card_action_event(
    event: dict[str, Any],
    processed_card_action_ids: set[str],
    lark_cli: str,
    dry_run: bool = False,
) -> None:
    event_id = event.get("header", {}).get("event_id")
    if event_id and event_id in processed_card_action_ids:
        print(f"Skip duplicate card action: {event_id}", file=sys.stderr)
        log_event("skip_duplicate_card_action", event_id=event_id)
        return

    action = parse_card_action(event)
    if not action:
        print(
            "Raw card action event could not be parsed:\n"
            + json.dumps(event, ensure_ascii=False, indent=2),
            file=sys.stderr,
        )
        print("Skip card action without supported value", file=sys.stderr)
        log_event("skip_unparsed_card_action", event_id=event_id)
        return

    update = build_action_update(action["action"])
    if dry_run:
        print(
            json.dumps(
                {"record_id": action["record_id"], "update": update},
                ensure_ascii=False,
            ),
            flush=True,
        )
    else:
        try:
            update_record(action["record_id"], update, lark_cli)
            message_id = action.get("message_id")
            if message_id:
                disabled_actions = disabled_actions_for(action["action"])
                update_card_message(
                    message_id=message_id,
                    card=build_task_card(
                        action,
                        action["record_id"],
                        disabled_actions=disabled_actions,
                        location_fill_action=action["action"],
                    ),
                    lark_cli=lark_cli,
                )
            else:
                print("Skip card disable update: no message_id in action event", file=sys.stderr)
        except RuntimeError as exc:
            reason = (
                build_user_authorization_alert_reason()
                if is_user_authorization_error(str(exc))
                else f"按钮回写失败：{exc}"
            )
            alert_creator(
                action.get("群聊ID"),
                action.get("消息原文", f"卡片动作：{action['action']}"),
                lark_cli,
                reason=reason,
                dedupe_key=(
                    f"user_authorization:{event_id or action['record_id']}"
                    if is_user_authorization_error(str(exc))
                    else f"card_action:{event_id or action['record_id']}:{action['action']}"
                ),
            )
            update_health(status="error", last_error=str(exc), last_error_at=now_iso())
            log_event("card_action_failed", event_id=event_id, action=action, error=str(exc))
            raise

    if event_id:
        processed_card_action_ids.add(event_id)
        _append_id(PROCESSED_CARD_ACTION_LOG, event_id)
    update_health(last_card_action_at=now_iso(), last_card_action=action["action"])
    log_event("card_action_processed", event_id=event_id, action=action)
    print(f"Processed card action: {action}", file=sys.stderr)


def write_record(record: dict[str, Any], lark_cli: str) -> str:
    result = subprocess.run(
        [
            lark_cli,
            "base",
            "+record-upsert",
            "--base-token",
            BASE_TOKEN,
            "--table-id",
            TABLE_ID,
            "--json",
            json.dumps(record, ensure_ascii=False),
            "--as",
            "user",
        ],
        text=True,
        capture_output=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(
            "Failed to write Base record\n"
            f"STDOUT:\n{result.stdout}\n"
            f"STDERR:\n{result.stderr}"
        )
    print(result.stdout.strip(), file=sys.stderr)
    record_id = parse_record_id_from_output(result.stdout)
    update_health(last_write_success_at=now_iso(), last_record_id=record_id)
    log_event("base_record_written", record_id=record_id, fields=sorted(record.keys()))
    return record_id


def write_record_with_fallback(record: dict[str, Any], lark_cli: str) -> str:
    try:
        return write_record(record, lark_cli)
    except RuntimeError as exc:
        if is_user_authorization_error(str(exc)):
            raise
        if "执行人" not in record:
            raise

    fallback = dict(record)
    fallback.pop("执行人", None)
    note = fallback.get("备注")
    fallback["备注"] = (
        f"{note}；执行人字段写入失败，已保留在消息原文"
        if note
        else "执行人字段写入失败，已保留在消息原文"
    )
    return write_record(fallback, lark_cli)


def update_record(record_id: str, update: dict[str, Any], lark_cli: str) -> None:
    result = subprocess.run(
        [
            lark_cli,
            "base",
            "+record-upsert",
            "--base-token",
            BASE_TOKEN,
            "--table-id",
            TABLE_ID,
            "--record-id",
            record_id,
            "--json",
            json.dumps(update, ensure_ascii=False),
            "--as",
            "user",
        ],
        text=True,
        capture_output=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(
            "Failed to update Base record\n"
            f"STDOUT:\n{result.stdout}\n"
            f"STDERR:\n{result.stderr}"
        )
    print(result.stdout.strip(), file=sys.stderr)
    update_health(last_update_success_at=now_iso(), last_record_id=record_id)
    log_event("base_record_updated", record_id=record_id, update=update)


def send_task_card(
    assignee_open_id: str,
    record: dict[str, Any],
    record_id: str,
    lark_cli: str,
) -> None:
    card = build_task_card(record, record_id)
    send_card_to_user(assignee_open_id, card, record_id, lark_cli)


def alert_creator(
    chat_id: str | None,
    original_message: str,
    lark_cli: str,
    reason: str = "信息有缺漏或处理失败",
    dedupe_key: str | None = None,
) -> None:
    if dedupe_key and dedupe_key in _load_ids(PROCESSED_ALERT_LOG):
        print(f"Skip duplicate creator alert: {dedupe_key}", file=sys.stderr)
        log_event("skip_duplicate_creator_alert", dedupe_key=dedupe_key)
        return
    chat_name = get_chat_name(chat_id, lark_cli) if chat_id else "未知群聊"
    card = build_creator_alert_card(chat_name, original_message, reason)
    result = subprocess.run(
        [
            lark_cli,
            "im",
            "+messages-send",
            "--as",
            "bot",
            "--user-id",
            BOT_CREATOR_OPEN_ID,
            "--msg-type",
            "interactive",
            "--content",
            json.dumps(card, ensure_ascii=False),
        ],
        text=True,
        capture_output=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if result.returncode != 0:
        print(
            "Failed to alert bot creator\n"
            f"STDOUT:\n{result.stdout}\n"
            f"STDERR:\n{result.stderr}",
            file=sys.stderr,
        )
        return
    if dedupe_key:
        _append_id(PROCESSED_ALERT_LOG, dedupe_key)
    update_health(last_alert_success_at=now_iso())
    log_event("creator_alert_sent", chat_id=chat_id, chat_name=chat_name, reason=reason)
    print(result.stdout.strip(), file=sys.stderr)


def build_creator_alert_text(chat_name: str, original_message: str) -> str:
    return (
        f"群聊名称：{chat_name}\n"
        f"消息原文：{original_message}\n"
        f"来自表单：{build_base_table_url()}"
    )


def build_creator_alert_card(
    chat_name: str,
    original_message: str,
    reason: str,
) -> dict[str, Any]:
    return {
        "config": {"wide_screen_mode": True},
        "header": {
            "template": "red",
            "title": {
                "tag": "plain_text",
                "content": "异常处理",
            },
        },
        "elements": [
            {
                "tag": "markdown",
                "content": (
                    f"**群聊名称：** {chat_name}\n"
                    f"**异常原因：** {reason}\n"
                    f"**消息原文：** {original_message}\n"
                    f"**来自表单：** [查看表格]({build_base_table_url()})"
                ),
            }
        ],
    }


def get_chat_name(chat_id: str, lark_cli: str) -> str:
    result = subprocess.run(
        [
            lark_cli,
            "im",
            "chats",
            "get",
            "--params",
            json.dumps({"chat_id": chat_id}, ensure_ascii=False),
            "--as",
            "bot",
        ],
        text=True,
        capture_output=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if result.returncode != 0:
        print(
            "Failed to get chat name; falling back to chat_id\n"
            f"STDOUT:\n{result.stdout}\n"
            f"STDERR:\n{result.stderr}",
            file=sys.stderr,
        )
        return chat_id
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError:
        return chat_id
    name = _find_chat_name(payload)
    return name or chat_id


def send_card_to_user(
    user_open_id: str,
    card: dict[str, Any],
    record_id: str,
    lark_cli: str,
) -> None:
    _send_card(
        [
            "--user-id",
            user_open_id,
            "--idempotency-key",
            f"task-card-user-{record_id}",
        ],
        card,
        lark_cli,
    )


def _send_card(target_args: list[str], card: dict[str, Any], lark_cli: str) -> None:
    result = subprocess.run(
        [
            lark_cli,
            "im",
            "+messages-send",
            *target_args,
            "--msg-type",
            "interactive",
            "--content",
            json.dumps(card, ensure_ascii=False),
            "--as",
            "bot",
        ],
        text=True,
        capture_output=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(
            "Failed to send task card\n"
            f"STDOUT:\n{result.stdout}\n"
            f"STDERR:\n{result.stderr}"
        )
    print(result.stdout.strip(), file=sys.stderr)
    update_health(last_card_send_success_at=now_iso())
    log_event("task_card_sent")


def is_bot_availability_error(message: str) -> bool:
    return "Bot has NO availability to this user" in message


def is_user_authorization_error(message: str) -> bool:
    markers = (
        "need_user_authorization",
        "user authorization",
        "user_access_token",
        "refresh token",
        "token expired",
        "invalid access token",
        "Access token is invalid",
    )
    lowered = message.lower()
    return any(marker.lower() in lowered for marker in markers)


def build_user_authorization_alert_reason() -> str:
    return (
        "服务器飞书用户授权已失效，请在服务器项目目录重新执行："
        "lark-cli auth login --scope "
        "\"base:record:create base:record:update base:record:read "
        "base:field:read base:table:read offline_access\""
    )


def build_task_card(
    record: dict[str, Any],
    record_id: str,
    disabled_actions: set[str] | None = None,
    location_fill_action: str | None = None,
) -> dict[str, Any]:
    disabled_actions = disabled_actions or set()
    task_types = record.get("任务类型") or []
    if isinstance(task_types, list):
        task_type_text = "、".join(str(item) for item in task_types)
    else:
        task_type_text = str(task_types)
    vehicle = record.get("车牌号") or "未识别"
    published_at = record.get("任务发布时间") or ""
    original = record.get("消息原文") or ""
    source_table_url = build_base_table_url()
    chat_id = record.get("群聊ID")

    claim_button = {
        "tag": "button",
        "text": {"tag": "plain_text", "content": "领取任务"},
        "type": "primary",
        "value": _button_value(
            action="claim",
            record_id=record_id,
            vehicle=vehicle,
            task_type_text=task_type_text,
            published_at=published_at,
            original=original,
            chat_id=chat_id,
        ),
    }
    resolve_button = {
        "tag": "button",
        "text": {"tag": "plain_text", "content": "已解决"},
        "type": "danger",
        "value": _button_value(
            action="resolve",
            record_id=record_id,
            vehicle=vehicle,
            task_type_text=task_type_text,
            published_at=published_at,
            original=original,
            chat_id=chat_id,
        ),
    }
    if "claim" in disabled_actions:
        claim_button["disabled"] = True
    if "resolve" in disabled_actions:
        resolve_button["disabled"] = True
    actions = [
        claim_button,
        resolve_button,
    ]

    location_hint = ""
    if location_fill_action:
        location_label = location_fill_label(location_fill_action)
        location_hint = f"\n**位置填写：** 请打开对应记录填写{location_label}"
        actions.append(
            {
                "tag": "button",
                "text": {"tag": "plain_text", "content": f"填写{location_label}"},
                "type": "default",
                "url": build_base_record_url(record_id),
            }
        )

    return {
        "config": {"wide_screen_mode": True, "update_multi": True},
        "header": {
            "template": "orange",
            "title": {
                "tag": "plain_text",
                "content": f"新增救援任务【{vehicle}】【{task_type_text or '未识别'}】",
            },
        },
        "elements": [
            {
                "tag": "markdown",
                "content": (
                    f"**派发时间：** {published_at}\n"
                    f"**任务类型：** {task_type_text or '未识别'}\n"
                    f"**车牌号：** {vehicle}\n"
                    f"**消息原文：** {original}\n"
                    f"**来源表格：** [查看表格]({source_table_url})"
                    f"{location_hint}"
                ),
            },
            {
                "tag": "action",
                "actions": actions,
            },
        ],
    }


def _button_value(
    action: str,
    record_id: str,
    vehicle: str,
    task_type_text: str,
    published_at: str,
    original: str,
    chat_id: Any = None,
) -> dict[str, str]:
    value = {
        "action": action,
        "record_id": record_id,
        "车牌号": vehicle,
        "任务类型": task_type_text,
        "任务发布时间": published_at,
        "消息原文": original,
    }
    if chat_id:
        value["群聊ID"] = str(chat_id)
    return value


def build_base_table_url() -> str:
    return f"{BASE_HOST}/base/{BASE_TOKEN}?table={TABLE_ID}"


def build_base_record_url(record_id: str) -> str:
    return f"{build_base_table_url()}&record={record_id}"


def location_fill_label(action: str) -> str:
    if action == "claim":
        return "出发位置"
    if action == "resolve":
        return "救援结束位置"
    raise ValueError(f"Unsupported location fill action: {action}")


def parse_card_action(event: dict[str, Any]) -> dict[str, str] | None:
    value = _find_action_value(event)
    if not isinstance(value, dict):
        return None
    action = value.get("action")
    record_id = value.get("record_id")
    if action not in {"claim", "resolve"} or not record_id:
        return None
    parsed = {"action": str(action), "record_id": str(record_id)}
    message_id = _find_message_id(event)
    if message_id:
        parsed["message_id"] = message_id
    for key in ("车牌号", "任务类型", "任务发布时间", "消息原文", "群聊ID"):
        if key in value:
            parsed[key] = str(value[key])
    return parsed


def build_action_update(action: str) -> dict[str, Any]:
    now = datetime.now(TIMEZONE).strftime("%Y-%m-%d %H:%M:%S")
    if action == "claim":
        return {"任务领取时间": now, "任务状态": "处理中"}
    if action == "resolve":
        return {"任务解决时间": now, "任务状态": "已解决"}
    raise ValueError(f"Unsupported action: {action}")


def disabled_actions_for(action: str) -> set[str]:
    if action == "claim":
        return {"claim"}
    if action == "resolve":
        return {"claim", "resolve"}
    return set()


def update_card_message(message_id: str, card: dict[str, Any], lark_cli: str) -> None:
    body = {
        "msg_type": "interactive",
        "content": json.dumps(card, ensure_ascii=False),
    }
    result = subprocess.run(
        [
            lark_cli,
            "api",
            "PATCH",
            f"/open-apis/im/v1/messages/{message_id}",
            "--data",
            json.dumps(body, ensure_ascii=False),
            "--as",
            "bot",
        ],
        text=True,
        capture_output=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(
            "Failed to update task card\n"
            f"STDOUT:\n{result.stdout}\n"
            f"STDERR:\n{result.stderr}"
        )
    print(result.stdout.strip(), file=sys.stderr)


def _extract_text(content: str) -> str:
    if not content:
        return ""
    try:
        parsed = json.loads(content)
    except json.JSONDecodeError:
        return content
    return str(parsed.get("text") or "")


def _replace_mentions(text: str, mentions: list[dict[str, Any]]) -> str:
    result = text
    for mention in mentions:
        key = mention.get("key")
        name = mention.get("name")
        if key and name:
            result = result.replace(key, f"@{name}")
    return _normalize_spaces(result)


def _remove_mentions(text: str) -> str:
    return _normalize_spaces(re.sub(r"@_user_\d+", " ", text))


def _normalize_spaces(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _first_user_mention_open_id(mentions: list[dict[str, Any]]) -> str | None:
    for mention in mentions:
        if mention.get("mentioned_type") != "user":
            continue
        open_id = mention.get("id", {}).get("open_id")
        if open_id:
            return str(open_id)
    return None


def _mentions_bot(mentions: list[dict[str, Any]]) -> bool:
    return any(mention.get("mentioned_type") == "bot" for mention in mentions)


def _extract_vehicle_number(text: str) -> str | None:
    match = re.search(r"(?<!\d)(\d{3,6})(?!\d)", text)
    if match:
        return match.group(1)
    return None


def _extract_task_types(text: str) -> list[str]:
    matched = []
    for spec in TASK_TYPE_SPECS:
        name = str(spec["name"])
        keywords = spec.get("keywords") or [name]
        if name in matched:
            continue
        if any(str(keyword) and str(keyword) in text for keyword in keywords):
            matched.append(name)
    return matched


def _format_event_time(value: Any) -> datetime:
    try:
        timestamp_ms = int(value)
    except (TypeError, ValueError):
        return datetime.now(TIMEZONE)
    return datetime.fromtimestamp(timestamp_ms / 1000, tz=TIMEZONE)


def parse_record_id_from_output(output: str) -> str:
    try:
        payload = json.loads(output)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Unable to parse record-upsert output: {output}") from exc

    candidate = _find_record_id(payload)
    if candidate:
        return candidate
    raise RuntimeError(f"Unable to find record_id in output: {output}")


def _find_record_id(node: Any) -> str | None:
    if isinstance(node, str) and node.startswith("rec"):
        return node
    if isinstance(node, dict):
        record_id = node.get("record_id")
        if isinstance(record_id, str) and record_id.startswith("rec"):
            return record_id
        node_id = node.get("id")
        if isinstance(node_id, str) and node_id.startswith("rec"):
            return node_id
        for value in node.values():
            found = _find_record_id(value)
            if found:
                return found
    elif isinstance(node, list):
        for item in node:
            found = _find_record_id(item)
            if found:
                return found
    return None


def _find_action_value(node: Any) -> Any:
    if isinstance(node, dict):
        action = node.get("action")
        if isinstance(action, dict) and "value" in action:
            return action.get("value")
        if "value" in node and isinstance(node["value"], dict):
            value = node["value"]
            if "action" in value and "record_id" in value:
                return value
        for value in node.values():
            found = _find_action_value(value)
            if found is not None:
                return found
    elif isinstance(node, list):
        for item in node:
            found = _find_action_value(item)
            if found is not None:
                return found
    return None


def _find_message_id(node: Any) -> str | None:
    if isinstance(node, dict):
        for key in ("open_message_id", "message_id"):
            value = node.get(key)
            if isinstance(value, str) and value.startswith("om"):
                return value
        for value in node.values():
            found = _find_message_id(value)
            if found:
                return found
    elif isinstance(node, list):
        for item in node:
            found = _find_message_id(item)
            if found:
                return found
    return None


def _find_chat_name(node: Any) -> str | None:
    if isinstance(node, dict):
        name = node.get("name")
        if isinstance(name, str) and name:
            return name
        for value in node.values():
            found = _find_chat_name(value)
            if found:
                return found
    elif isinstance(node, list):
        for item in node:
            found = _find_chat_name(item)
            if found:
                return found
    return None


def _load_processed_ids() -> set[str]:
    return _load_ids(PROCESSED_LOG)


def _load_ids(path: Path) -> set[str]:
    if not path.exists():
        return set()
    return {
        line.strip()
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    }


def _append_processed_id(message_id: str) -> None:
    _append_id(PROCESSED_LOG, message_id)


def _append_id(path: Path, value: str) -> None:
    with path.open("a", encoding="utf-8") as file:
        file.write(value + "\n")


def _append_raw_event(event: dict[str, Any]) -> None:
    with RAW_EVENT_LOG.open("a", encoding="utf-8") as file:
        file.write(json.dumps(event, ensure_ascii=False) + "\n")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Listen for Feishu group bot mentions and write task records to Base."
    )
    parser.add_argument("--lark-cli", default="lark-cli.cmd")
    parser.add_argument(
        "--status",
        action="store_true",
        help="Print the latest local health status and exit.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Parse events and print records without writing to Base.",
    )
    args = parser.parse_args()
    if args.status:
        print_status()
        return
    run_listener(args.lark_cli, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
