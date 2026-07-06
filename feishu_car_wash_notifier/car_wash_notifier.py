import argparse
import json
import re
import subprocess
import sys
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo


MODULE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = MODULE_DIR
SHARED_CONFIG_PATHS = [
    PROJECT_ROOT / "feishu_config.json",
    PROJECT_ROOT.parent / "feishu_config.json",
]
CONFIG_PATH = MODULE_DIR / "car_wash_config.json"
ENV_PATH = MODULE_DIR / ".env"

DEFAULT_SHARED_CONFIG = {
    "base_host": "https://atomdance.feishu.cn",
    "bot_creator_open_id": "",
    "timezone": "Asia/Shanghai",
}
DEFAULT_CONFIG = {
    "base_token": "LdiKbOgd7a5FSvsgNO5c0DNunTa",
    "table_id": "tblaTXQqJNNAzMSS",
    "target_chat_join_link": "https://applink.feishu.cn/client/chat/chatter/add_by_link?link_token=382sa608-24f7-40ab-96df-3b498c555855",
    "target_chat_id": "",
    "card_title": "洗车任务提醒",
    "card_header_template": "blue",
    "field_mapping": {
        "plate_number": "车牌号",
        "cleaning_need": "清洗需求",
        "return_station_time": "到站时间",
        "cleaner": "清洗人员",
        "completed_at": "清洗完成时间",
        "photo": "清洗照片",
        "status": "任务状态",
        "group_message_id": "群消息ID",
        "private_message_id": "私聊消息ID",
    },
    "structured_log_path": "events/automation.jsonl",
    "health_path": "runtime_health.json",
    "processed_record_path": "processed_record_ids.txt",
    "processed_card_action_path": "processed_card_action_ids.txt",
    "card_cache_path": "card_cache.json",
    "raw_event_path": "runtime_events.ndjson",
    "event_types": "card.action.trigger,drive.file.bitable_record_changed_v1",
    "plate_link_table_id": "tblkx9E9JqKpxbJL",
    "plate_link_display_field": "车辆名称",
    "poll_interval_seconds": 3,
    "poll_send_existing_on_start": False,
}


def load_json_config(path: Path, defaults: dict[str, Any]) -> dict[str, Any]:
    config = dict(defaults)
    if path.exists():
        with path.open("r", encoding="utf-8") as file:
            loaded = json.load(file)
        if isinstance(loaded, dict):
            config.update(loaded)
    return config


def load_env_config(path: Path = ENV_PATH) -> dict[str, str]:
    if not path.exists():
        return {}
    env: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        env[key.strip()] = value.strip().strip('"').strip("'")
    return env


def apply_env_overrides(config: dict[str, Any], shared_config: dict[str, Any], env: dict[str, str]) -> None:
    config_key_map = {
        "BASE_TOKEN": "base_token",
        "TABLE_ID": "table_id",
        "TARGET_CHAT_ID": "target_chat_id",
        "CARD_TITLE": "card_title",
        "CARD_HEADER_TEMPLATE": "card_header_template",
        "EVENT_TYPES": "event_types",
        "PLATE_LINK_TABLE_ID": "plate_link_table_id",
        "PLATE_LINK_DISPLAY_FIELD": "plate_link_display_field",
        "POLL_INTERVAL_SECONDS": "poll_interval_seconds",
        "POLL_SEND_EXISTING_ON_START": "poll_send_existing_on_start",
    }
    shared_key_map = {
        "BASE_HOST": "base_host",
        "BOT_CREATOR_OPEN_ID": "bot_creator_open_id",
        "TIMEZONE": "timezone",
    }
    for env_key, config_key in config_key_map.items():
        if env.get(env_key):
            config[config_key] = env[env_key]
    for env_key, config_key in shared_key_map.items():
        if env.get(env_key):
            shared_config[config_key] = env[env_key]


def config_bool(key: str, default: bool = False) -> bool:
    value = CONFIG.get(key)
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    return str(value).strip().lower() in {"1", "true", "yes", "y", "on"}


def config_int(key: str, default: int = 0) -> int:
    try:
        return int(str(CONFIG.get(key, default)).strip())
    except ValueError:
        return default


def load_shared_config() -> dict[str, Any]:
    for path in SHARED_CONFIG_PATHS:
        if path.exists():
            return load_json_config(path, DEFAULT_SHARED_CONFIG)
    return dict(DEFAULT_SHARED_CONFIG)


CONFIG = load_json_config(CONFIG_PATH, DEFAULT_CONFIG)
SHARED_CONFIG = load_shared_config()
ENV_CONFIG = load_env_config()
apply_env_overrides(CONFIG, SHARED_CONFIG, ENV_CONFIG)

BASE_TOKEN = str(CONFIG["base_token"])
TABLE_ID = str(CONFIG["table_id"])
BASE_HOST = str(SHARED_CONFIG.get("base_host") or "https://atomdance.feishu.cn").rstrip("/")
TIMEZONE = ZoneInfo(str(SHARED_CONFIG.get("timezone") or "Asia/Shanghai"))
BOT_CREATOR_OPEN_ID = str(SHARED_CONFIG.get("bot_creator_open_id") or "")

STRUCTURED_LOG = PROJECT_ROOT / str(CONFIG["structured_log_path"])
HEALTH_PATH = PROJECT_ROOT / str(CONFIG["health_path"])
PROCESSED_RECORD_LOG = PROJECT_ROOT / str(CONFIG["processed_record_path"])
PROCESSED_CARD_ACTION_LOG = PROJECT_ROOT / str(CONFIG["processed_card_action_path"])
CARD_CACHE_PATH = PROJECT_ROOT / str(CONFIG["card_cache_path"])
RAW_EVENT_LOG = PROJECT_ROOT / str(CONFIG["raw_event_path"])


def now_iso() -> str:
    return datetime.now(TIMEZONE).isoformat(timespec="seconds")


def log_event(event_type: str, **fields: Any) -> None:
    entry = {"time": now_iso(), "event_type": event_type, **fields}
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
    HEALTH_PATH.parent.mkdir(parents=True, exist_ok=True)
    HEALTH_PATH.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def print_status() -> None:
    payload = {
        "base_token": BASE_TOKEN,
        "table_id": TABLE_ID,
        "target_chat_id": str(CONFIG.get("target_chat_id") or ""),
        "base_host": BASE_HOST,
        "config_path": str(CONFIG_PATH),
        "env_path": str(ENV_PATH),
        "health_path": str(HEALTH_PATH),
    }
    if HEALTH_PATH.exists():
        try:
            payload["health"] = json.loads(HEALTH_PATH.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            payload["health"] = HEALTH_PATH.read_text(encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def inspect_base(lark_cli: str) -> None:
    result = subprocess.run(
        [
            lark_cli,
            "base",
            "+table-list",
            "--base-token",
            BASE_TOKEN,
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
            "Failed to inspect Base tables\n"
            f"STDOUT:\n{result.stdout}\n"
            f"STDERR:\n{result.stderr}"
        )
    print(result.stdout)


def ensure_required_fields(lark_cli: str) -> None:
    existing = set(list_field_names(lark_cli))
    mapping = field_mapping()
    required_fields = [
        {
            "name": mapping["status"],
            "type": "select",
            "multiple": False,
            "options": [
                {"name": "待接单", "hue": "Blue", "lightness": "Lighter"},
                {"name": "已接单", "hue": "Orange", "lightness": "Light"},
                {"name": "已完成", "hue": "Green", "lightness": "Light"},
                {"name": "异常", "hue": "Red", "lightness": "Light"},
            ],
        },
        {"name": mapping["group_message_id"], "type": "text", "style": {"type": "plain"}},
        {"name": mapping["private_message_id"], "type": "text", "style": {"type": "plain"}},
    ]
    for field in required_fields:
        if field["name"] in existing:
            continue
        create_field(field, lark_cli)
        existing.add(str(field["name"]))
    log_event("required_fields_ensured", fields=[field["name"] for field in required_fields])


def list_field_names(lark_cli: str) -> list[str]:
    result = subprocess.run(
        [
            lark_cli,
            "base",
            "+field-list",
            "--base-token",
            BASE_TOKEN,
            "--table-id",
            TABLE_ID,
            "--offset",
            "0",
            "--limit",
            "100",
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
            "Failed to list Base fields\n"
            f"STDOUT:\n{result.stdout}\n"
            f"STDERR:\n{result.stderr}"
        )
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Failed to parse field-list output: {exc}") from exc
    fields = payload.get("data", {}).get("fields") or payload.get("fields") or []
    names: list[str] = []
    for field in fields:
        if isinstance(field, dict):
            name = (
                field.get("field_name")
                or field.get("name")
                or field.get("fieldName")
                or field.get("field_alias")
            )
            if name:
                names.append(str(name))
        elif isinstance(field, str):
            names.append(field)
    return names


def create_field(field: dict[str, Any], lark_cli: str) -> None:
    result = subprocess.run(
        [
            lark_cli,
            "base",
            "+field-create",
            "--base-token",
            BASE_TOKEN,
            "--table-id",
            TABLE_ID,
            "--json",
            json.dumps(field, ensure_ascii=False),
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
        if is_duplicate_field_error(result.stderr, str(field.get("name") or "")):
            log_event("base_field_already_exists", field=field)
            return
        raise RuntimeError(
            "Failed to create Base field\n"
            f"FIELD:\n{json.dumps(field, ensure_ascii=False)}\n"
            f"STDOUT:\n{result.stdout}\n"
            f"STDERR:\n{result.stderr}"
        )
    log_event("base_field_created", field=field)


def is_duplicate_field_error(stderr: str, field_name: str) -> bool:
    if not field_name:
        return False
    lowered = stderr.lower()
    return (
        "validation_error" in lowered
        and "unique field name" in lowered
        and field_name in stderr
    )


def run_listener(lark_cli: str, dry_run: bool = False) -> None:
    processed_record_ids = load_ids(PROCESSED_RECORD_LOG)
    processed_action_ids = load_ids(PROCESSED_CARD_ACTION_LOG)
    if not dry_run:
        ensure_required_fields(lark_cli)
    start_polling_thread(processed_record_ids, lark_cli, dry_run=dry_run)
    command = [
        lark_cli,
        "event",
        "+subscribe",
        "--event-types",
        str(CONFIG.get("event_types") or "card.action.trigger"),
        "--as",
        "bot",
    ]
    update_health(status="running", started_at=now_iso(), lark_cli=lark_cli)
    log_event("listener_started", dry_run=dry_run)
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
                log_event("skip_non_json_output", line=line)
                continue
            append_raw_event(event)
            try:
                handle_event(event, processed_record_ids, processed_action_ids, lark_cli, dry_run=dry_run)
            except RuntimeError as exc:
                alert_creator(
                    lark_cli,
                    "洗车自动化异常",
                    f"{exc}",
                    dedupe_key=f"runtime:{event.get('header', {}).get('event_id') or now_iso()}",
                )
                update_health(status="error", last_error=str(exc), last_error_at=now_iso())
                log_event("event_processing_failed", error=str(exc), event=event)


def start_polling_thread(processed_record_ids: set[str], lark_cli: str, dry_run: bool = False) -> None:
    interval = config_int("poll_interval_seconds", 0)
    if interval <= 0:
        return
    thread = threading.Thread(
        target=poll_records_forever,
        args=(processed_record_ids, lark_cli, interval, dry_run),
        daemon=True,
    )
    thread.start()
    log_event("polling_started", interval_seconds=interval)


def poll_records_forever(
    processed_record_ids: set[str],
    lark_cli: str,
    interval: int,
    dry_run: bool = False,
) -> None:
    baseline_done = False
    while True:
        try:
            poll_pending_records(processed_record_ids, lark_cli, baseline=not baseline_done, dry_run=dry_run)
            baseline_done = True
        except RuntimeError as exc:
            alert_creator(
                lark_cli,
                "洗车任务轮询失败",
                str(exc),
                dedupe_key=f"poll:{now_iso()}",
            )
            update_health(status="error", last_error=str(exc), last_error_at=now_iso())
            log_event("polling_failed", error=str(exc))
        time.sleep(interval)


def poll_pending_records(
    processed_record_ids: set[str],
    lark_cli: str,
    baseline: bool = False,
    dry_run: bool = False,
) -> None:
    records = list_records(lark_cli)
    send_existing = config_bool("poll_send_existing_on_start", False)
    for record in records:
        record_id = record["record_id"]
        if record_id in processed_record_ids:
            continue
        if baseline and not send_existing:
            processed_record_ids.add(record_id)
            append_id(PROCESSED_RECORD_LOG, record_id)
            log_event("polling_baseline_record_marked", record_id=record_id)
            continue
        process_record_payload(
            {"record_id": record_id, "fields": record["fields"]},
            lark_cli,
            dry_run=dry_run,
        )
        processed_record_ids.add(record_id)
        append_id(PROCESSED_RECORD_LOG, record_id)
        update_health(last_polled_record_at=now_iso(), last_record_id=record_id)
        log_event("polling_record_processed", record_id=record_id)


def list_records(lark_cli: str) -> list[dict[str, Any]]:
    result = subprocess.run(
        [
            lark_cli,
            "base",
            "+record-list",
            "--base-token",
            BASE_TOKEN,
            "--table-id",
            TABLE_ID,
            "--offset",
            "0",
            "--limit",
            "200",
            "--format",
            "json",
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
            "Failed to list Base records\n"
            f"STDOUT:\n{result.stdout}\n"
            f"STDERR:\n{result.stderr}"
        )
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError as stdout_exc:
        try:
            payload = json.loads(result.stderr)
        except json.JSONDecodeError:
            raise RuntimeError(
                "Failed to parse record-list output\n"
                f"STDOUT:\n{result.stdout}\n"
                f"STDERR:\n{result.stderr}\n"
                f"JSON error: {stdout_exc}"
            ) from stdout_exc
    data = payload.get("data", {})
    fields = data.get("fields") or []
    rows = data.get("data") or []
    record_ids = data.get("record_id_list") or []
    records: list[dict[str, Any]] = []
    for index, record_id in enumerate(record_ids):
        values = rows[index] if index < len(rows) and isinstance(rows[index], list) else []
        record_fields = {
            str(field): values[field_index] if field_index < len(values) else None
            for field_index, field in enumerate(fields)
        }
        if should_notify_record(record_fields):
            records.append({"record_id": str(record_id), "fields": record_fields})
    return records


def should_notify_record(fields: dict[str, Any]) -> bool:
    mapping = field_mapping()
    return bool(
        fields.get(mapping["plate_number"])
        and fields.get(mapping["cleaning_need"])
        and not has_sent_group_message(fields)
    )


def has_sent_group_message(fields: dict[str, Any]) -> bool:
    mapping = field_mapping()
    return bool(fields.get(mapping["group_message_id"]))


def record_has_photo(fields: dict[str, Any]) -> bool:
    mapping = field_mapping()
    value = fields.get(mapping["photo"])
    if isinstance(value, list):
        return bool(value)
    return bool(value)


def handle_event(
    event: dict[str, Any],
    processed_record_ids: set[str],
    processed_action_ids: set[str],
    lark_cli: str,
    dry_run: bool = False,
) -> None:
    event_type = str(event.get("header", {}).get("event_type") or "")
    if event_type == "card.action.trigger":
        handle_card_action_event(event, processed_action_ids, lark_cli, dry_run=dry_run)
        return
    record_id = parse_new_record_event(event)
    if not record_id:
        log_event("skip_unrelated_event", event_type=event_type)
        return
    if record_id in processed_record_ids:
        log_event("skip_duplicate_record_event", record_id=record_id, event_type=event_type)
        return
    fields = fetch_record_fields(record_id, lark_cli)
    process_record_payload({"record_id": record_id, "fields": fields}, lark_cli, dry_run=dry_run)
    processed_record_ids.add(record_id)
    append_id(PROCESSED_RECORD_LOG, record_id)
    update_health(last_record_event_at=now_iso(), last_record_id=record_id)
    log_event("new_record_processed", record_id=record_id, event_type=event_type)


def process_record_payload(
    payload: dict[str, Any],
    lark_cli: str,
    chat_id: str | None = None,
    user_id: str | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    record_id = str(payload.get("record_id") or payload.get("recordId") or "")
    fields = payload.get("fields") if isinstance(payload.get("fields"), dict) else payload
    fields = enrich_record_fields(dict(fields), lark_cli) if isinstance(fields, dict) else {}
    if record_id and has_sent_group_message(fields):
        log_event("skip_record_with_group_message_id", record_id=record_id)
        return build_car_wash_card(fields, record_id)
    card = build_car_wash_card(fields, record_id)
    target_chat_id = chat_id or str(CONFIG.get("target_chat_id") or "")
    target_user_id = user_id or ""
    if dry_run:
        print(json.dumps({"target_chat_id": target_chat_id, "target_user_id": target_user_id, "card": card}, ensure_ascii=False))
        return card
    try:
        message_id = send_card(card, lark_cli, record_id=record_id, chat_id=target_chat_id, user_id=target_user_id)
        if record_id and message_id and target_chat_id:
            mapping = field_mapping()
            update_record(
                record_id,
                {
                    mapping["status"]: "待接单",
                    mapping["group_message_id"]: message_id,
                },
                lark_cli,
            )
    except RuntimeError as exc:
        alert_creator(
            lark_cli,
            "洗车任务卡片发送失败",
            f"记录：{record_id or '未知'}\n原因：{exc}",
            dedupe_key=f"send_card:{record_id or now_iso()}",
        )
        raise
    return card


def send_private_work_card_for_record(record_id: str, user_id: str, lark_cli: str, dry_run: bool = False) -> dict[str, Any]:
    fields = enrich_record_fields(fetch_record_fields(record_id, lark_cli), lark_cli)
    card = build_private_work_card(fields, record_id)
    if dry_run:
        print(json.dumps({"target_user_id": user_id, "card": card}, ensure_ascii=False))
        return card
    message_id = send_card(
        card,
        lark_cli,
        record_id=private_card_idempotency_key(record_id, unique=True),
        user_id=user_id,
    )
    if message_id:
        update_record(record_id, {field_mapping()["private_message_id"]: message_id}, lark_cli)
    cache_card(f"{record_id}:private:{user_id}", card)
    return card


def handle_card_action_event(
    event: dict[str, Any],
    processed_action_ids: set[str],
    lark_cli: str,
    dry_run: bool = False,
) -> None:
    if event.get("header", {}).get("event_type") != "card.action.trigger":
        return
    event_id = str(event.get("header", {}).get("event_id") or "")
    if event_id and event_id in processed_action_ids:
        log_event("skip_duplicate_card_action", event_id=event_id)
        return
    action = parse_card_action(event)
    if not action:
        log_event("skip_unparsed_card_action", event_id=event_id)
        return
    record_fields: dict[str, Any] | None = None
    if action["action"] == "done" and action["record_id"] and not dry_run:
        record_fields = fetch_record_fields(action["record_id"], lark_cli)
    update = build_action_update(action["action"], event, record_fields=record_fields)
    if dry_run:
        print(json.dumps({"record_id": action["record_id"], "update": update}, ensure_ascii=False))
    elif action["record_id"] and action["action"] == "done" and not update:
        actor_open_id = find_actor_open_id(event)
        if actor_open_id:
            fields = enrich_record_fields(record_fields or fetch_record_fields(action["record_id"], lark_cli), lark_cli)
            reminder_card = build_photo_required_card(fields, action["record_id"])
            send_card(
                reminder_card,
                lark_cli,
                record_id=f"{action['record_id']}-photo-required",
                user_id=actor_open_id,
            )
        log_event("skip_done_without_photo", event_id=event_id, record_id=action["record_id"])
    elif action["record_id"] and update:
        try:
            message_id = find_message_id(event)
            actor_open_id = find_actor_open_id(event) or ""
            if message_id and action["action"] == "accept":
                card = load_cached_card(action["record_id"]) or find_card_payload(event)
                if card:
                    updated_card = mark_group_card_accepted(card, actor_open_id)
                else:
                    fields = enrich_record_fields(fetch_record_fields(action["record_id"], lark_cli), lark_cli)
                    updated_card = mark_group_card_accepted(build_car_wash_card(fields, action["record_id"]), actor_open_id)
                update_card_message(
                    message_id,
                    updated_card,
                    lark_cli,
                )
                cache_card(action["record_id"], updated_card)
            update_record(action["record_id"], update, lark_cli)
            if action["action"] == "accept":
                if actor_open_id:
                    fields = enrich_record_fields(fetch_record_fields(action["record_id"], lark_cli), lark_cli)
                    private_card = build_private_work_card(fields, action["record_id"])
                    private_message_id = send_card(
                        private_card,
                        lark_cli,
                        record_id=private_card_idempotency_key(action["record_id"], unique=True),
                        user_id=actor_open_id,
                    )
                    if private_message_id:
                        update_record(
                            action["record_id"],
                            {field_mapping()["private_message_id"]: private_message_id},
                            lark_cli,
                        )
                    cache_card(f"{action['record_id']}:private:{actor_open_id}", private_card)
            elif message_id and action["action"] == "done":
                card = find_card_payload(event)
                if card:
                    updated_card = mark_done_button_cleaned(card)
                else:
                    fields = enrich_record_fields(record_fields or fetch_record_fields(action["record_id"], lark_cli), lark_cli)
                    updated_card = mark_done_button_cleaned(build_private_work_card(fields, action["record_id"]))
                update_card_message(
                    message_id,
                    updated_card,
                    lark_cli,
                )
                actor_open_id = find_actor_open_id(event) or ""
                if actor_open_id:
                    cache_card(f"{action['record_id']}:private:{actor_open_id}", updated_card)
        except RuntimeError as exc:
            alert_creator(
                lark_cli,
                "洗车任务按钮回写失败",
                f"动作：{action['action']}\n记录：{action['record_id']}\n原因：{exc}",
                dedupe_key=f"card_action:{event_id or action['record_id']}:{action['action']}",
            )
            raise
    if event_id:
        processed_action_ids.add(event_id)
        append_id(PROCESSED_CARD_ACTION_LOG, event_id)
    update_health(last_card_action_at=now_iso(), last_card_action=action)
    log_event("card_action_processed", event_id=event_id, action=action)


def parse_card_action(event: dict[str, Any]) -> dict[str, str] | None:
    value = event.get("event", {}).get("action", {}).get("value")
    if not isinstance(value, dict):
        return None
    action = str(value.get("action") or "")
    record_id = str(value.get("record_id") or find_record_id_from_event(event) or "")
    if not action:
        return None
    return {"action": action, "record_id": record_id}


def find_record_id_from_event(event: dict[str, Any]) -> str | None:
    direct = find_first_value(event, {"record_id", "recordId"})
    if direct:
        return direct
    return find_record_id_in_strings(event)


def find_record_id_in_strings(node: Any) -> str | None:
    if isinstance(node, dict):
        for value in node.values():
            found = find_record_id_in_strings(value)
            if found:
                return found
    elif isinstance(node, list):
        for item in node:
            found = find_record_id_in_strings(item)
            if found:
                return found
    elif isinstance(node, str):
        match = re.search(r"(?:[?&]|%3F|%26)record(?:=|%3D)(rec[A-Za-z0-9_]+)", node)
        if match:
            return match.group(1)
    return None


def build_action_update(
    action: str,
    event: dict[str, Any] | None = None,
    record_fields: dict[str, Any] | None = None,
) -> dict[str, Any]:
    mapping = field_mapping()
    if action == "accept":
        open_id = find_actor_open_id(event or {})
        if not open_id:
            raise RuntimeError("未能从卡片点击事件中识别点击用户 open_id")
        return {mapping["cleaner"]: [{"id": open_id}], mapping["status"]: "已接单"}
    if action == "done":
        if record_fields is not None and not record_has_photo(record_fields):
            return {}
        return {
            mapping["completed_at"]: datetime.now(TIMEZONE).strftime("%Y-%m-%d %H:%M:%S"),
            mapping["status"]: "已完成",
        }
    return {}


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
    update_health(last_update_success_at=now_iso(), last_record_id=record_id)
    log_event("base_record_updated", record_id=record_id, update=update)


def fetch_record_fields(record_id: str, lark_cli: str) -> dict[str, Any]:
    result = subprocess.run(
        [
            lark_cli,
            "base",
            "+record-get",
            "--base-token",
            BASE_TOKEN,
            "--table-id",
            TABLE_ID,
            "--record-id",
            record_id,
            "--format",
            "json",
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
            "Failed to fetch Base record\n"
            f"STDOUT:\n{result.stdout}\n"
            f"STDERR:\n{result.stderr}"
        )
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError as stdout_exc:
        try:
            payload = json.loads(result.stderr)
        except json.JSONDecodeError:
            raise RuntimeError(
                "Failed to parse record-get output\n"
                f"STDOUT:\n{result.stdout}\n"
                f"STDERR:\n{result.stderr}\n"
                f"JSON error: {stdout_exc}"
            ) from stdout_exc
    fields = extract_record_fields(payload)
    if fields:
        return fields
    fallback_fields = fetch_record_fields_from_record_list(record_id, lark_cli)
    if fallback_fields:
        log_event("record_get_fallback_to_record_list", record_id=record_id)
        return fallback_fields
    return {}


def extract_record_fields(payload: dict[str, Any]) -> dict[str, Any]:
    candidates = [
        payload.get("data", {}).get("record") if isinstance(payload.get("data"), dict) else None,
        payload.get("record"),
        payload.get("data") if isinstance(payload.get("data"), dict) else None,
        payload.get("raw", {}).get("data", {}).get("record") if isinstance(payload.get("raw"), dict) else None,
        payload.get("raw", {}).get("record") if isinstance(payload.get("raw"), dict) else None,
    ]
    data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
    if isinstance(data.get("raw"), dict):
        candidates.extend(
            [
                data["raw"].get("data", {}).get("record") if isinstance(data["raw"].get("data"), dict) else None,
                data["raw"].get("record"),
            ]
        )
    candidates.append(payload)
    for candidate in candidates:
        if not isinstance(candidate, dict):
            continue
        fields = candidate.get("fields")
        if isinstance(fields, dict):
            return fields
        if looks_like_fields(candidate):
            return candidate
    return {}


def fetch_record_fields_from_record_list(record_id: str, lark_cli: str) -> dict[str, Any]:
    result = subprocess.run(
        [
            lark_cli,
            "base",
            "+record-list",
            "--base-token",
            BASE_TOKEN,
            "--table-id",
            TABLE_ID,
            "--offset",
            "0",
            "--limit",
            "200",
            "--format",
            "json",
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
        log_event(
            "record_list_fallback_failed",
            record_id=record_id,
            stdout=result.stdout,
            stderr=result.stderr,
        )
        return {}
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError as stdout_exc:
        try:
            payload = json.loads(result.stderr)
        except json.JSONDecodeError:
            log_event(
                "record_list_fallback_parse_failed",
                record_id=record_id,
                stdout=result.stdout,
                stderr=result.stderr,
                error=str(stdout_exc),
            )
            return {}
    data = payload.get("data", {})
    fields = data.get("fields") or []
    rows = data.get("data") or []
    record_ids = data.get("record_id_list") or []
    for index, current_record_id in enumerate(record_ids):
        if str(current_record_id) != record_id:
            continue
        values = rows[index] if index < len(rows) and isinstance(rows[index], list) else []
        return {
            str(field): values[field_index] if field_index < len(values) else None
            for field_index, field in enumerate(fields)
        }
    return {}


def looks_like_fields(value: dict[str, Any]) -> bool:
    metadata_keys = {
        "record_id",
        "recordId",
        "_record_id",
        "id",
        "created_time",
        "last_modified_time",
        "fields",
        "raw",
        "record",
        "data",
        "ok",
        "error",
        "identity",
        "_notice",
    }
    mapped_fields = set(field_mapping().values())
    return any(
        key in mapped_fields
        or any("\u4e00" <= char <= "\u9fff" for char in key)
        for key in value
        if isinstance(key, str) and key not in metadata_keys
    )


def enrich_record_fields(fields: dict[str, Any], lark_cli: str) -> dict[str, Any]:
    mapping = field_mapping()
    plate_field = mapping["plate_number"]
    plate_value = fields.get(plate_field)
    if not needs_link_display_resolution(plate_value):
        return fields
    linked_record_id = str(plate_value[0].get("id") or "")
    link_table_id = str(CONFIG.get("plate_link_table_id") or "")
    display_field = str(CONFIG.get("plate_link_display_field") or "")
    if not linked_record_id or not link_table_id or not display_field:
        return fields
    display_value = fetch_linked_record_display(link_table_id, linked_record_id, display_field, lark_cli)
    if display_value:
        enriched = dict(fields)
        enriched[plate_field] = display_value
        return enriched
    return fields


def needs_link_display_resolution(value: Any) -> bool:
    return (
        isinstance(value, list)
        and len(value) == 1
        and isinstance(value[0], dict)
        and bool(value[0].get("id"))
        and not (value[0].get("text") or value[0].get("name"))
    )


def fetch_linked_record_display(table_id: str, record_id: str, display_field: str, lark_cli: str) -> str:
    result = subprocess.run(
        [
            lark_cli,
            "base",
            "+record-get",
            "--base-token",
            BASE_TOKEN,
            "--table-id",
            table_id,
            "--record-id",
            record_id,
            "--format",
            "json",
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
        log_event("linked_record_fetch_failed", table_id=table_id, record_id=record_id, stderr=result.stderr)
        return ""
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError as stdout_exc:
        try:
            payload = json.loads(result.stderr)
        except json.JSONDecodeError:
            log_event(
                "linked_record_parse_failed",
                table_id=table_id,
                record_id=record_id,
                stdout=result.stdout,
                stderr=result.stderr,
                error=str(stdout_exc),
            )
            return ""
    fields = extract_record_fields(payload)
    if fields.get(display_field):
        return stringify_field(fields.get(display_field))
    tabular_value = extract_tabular_record_value(payload, record_id, display_field)
    return stringify_field(tabular_value)


def extract_tabular_record_value(payload: dict[str, Any], record_id: str, field_name: str) -> Any:
    data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
    fields = data.get("fields") or []
    rows = data.get("data") or []
    record_ids = data.get("record_id_list") or []
    if field_name not in fields:
        return None
    field_index = fields.index(field_name)
    for row_index, current_record_id in enumerate(record_ids):
        if str(current_record_id) != record_id:
            continue
        row = rows[row_index] if row_index < len(rows) and isinstance(rows[row_index], list) else []
        return row[field_index] if field_index < len(row) else None
    return None


def build_car_wash_card(fields: dict[str, Any], record_id: str = "", accepted: bool = False) -> dict[str, Any]:
    mapping = field_mapping()
    title = str(CONFIG.get("card_title") or "洗车任务提醒")
    plate_number = stringify_field(fields.get(mapping["plate_number"])) or "未填写"
    cleaning_need = stringify_field(fields.get(mapping["cleaning_need"])) or "未填写"
    return_station_time = stringify_field(fields.get(mapping["return_station_time"])) or "未填写"
    cleaner = stringify_field(fields.get(mapping["cleaner"]))
    completed_at = stringify_field(fields.get(mapping["completed_at"]))
    rows = [
        ("车牌号", plate_number),
        ("清洗需求", cleaning_need),
        ("车辆返回场站时间", return_station_time),
        ("清洗人员", cleaner),
        ("清洗完成时间", completed_at),
    ]
    content_lines = [f"**{label}：** {stringify_field(value)}" for label, value in rows if stringify_field(value)]
    if record_id:
        content_lines.append(f"**来源记录：** [查看记录]({build_base_record_url(record_id)})")
    else:
        content_lines.append(f"**来源表格：** [查看表格]({build_base_table_url()})")
    return {
        "config": {"wide_screen_mode": True},
        "header": {
            "template": str(CONFIG.get("card_header_template") or "blue"),
            "title": {"tag": "plain_text", "content": title},
        },
        "elements": [
            {"tag": "markdown", "content": "\n".join(content_lines)},
            {
                "tag": "action",
                "actions": build_card_actions(record_id, accepted=accepted),
            },
        ],
    }


def build_private_work_card(fields: dict[str, Any], record_id: str = "") -> dict[str, Any]:
    card = build_car_wash_card(fields, record_id, accepted=False)
    card["elements"][1]["actions"] = [
        {
            "tag": "button",
            "text": {"tag": "plain_text", "content": "完成任务"},
            "type": "primary",
            "value": {"action": "done", "record_id": record_id},
        },
        {
            "tag": "button",
            "text": {"tag": "plain_text", "content": "上传清洗照片"},
            "type": "default",
            "url": build_base_record_url(record_id),
        },
    ]
    return card


def build_photo_required_card(fields: dict[str, Any], record_id: str = "") -> dict[str, Any]:
    card = build_private_work_card(fields, record_id)
    card["header"]["template"] = "orange"
    card["header"]["title"]["content"] = "请先上传清洗照片"
    card["elements"].insert(
        1,
        {
            "tag": "markdown",
            "content": "检测到这条记录还没有清洗照片。请先上传照片，再点击完成任务。",
        },
    )
    return card


def build_card_actions(record_id: str, accepted: bool = False) -> list[dict[str, Any]]:
    actions: list[dict[str, Any]] = [
        {
            "tag": "button",
            "text": {"tag": "plain_text", "content": "接受任务"},
            "type": "primary",
            "value": {"action": "accept", "record_id": record_id},
        },
        {
            "tag": "button",
            "text": {"tag": "plain_text", "content": "完成任务"},
            "type": "default",
            "value": {"action": "done", "record_id": record_id},
        },
    ]
    if accepted and record_id:
        actions.append(
            {
                "tag": "button",
                "text": {"tag": "plain_text", "content": "上传清洗照片"},
                "type": "default",
                "url": build_base_record_url(record_id),
            }
        )
    return actions


def add_upload_button_to_card(card: dict[str, Any], record_id: str) -> dict[str, Any]:
    result = dict(card)
    elements = list(result.get("elements") or [])
    for element in elements:
        if not isinstance(element, dict) or element.get("tag") != "action":
            continue
        actions = list(element.get("actions") or [])
        if any(isinstance(action, dict) and action.get("value", {}).get("action") == "upload_photo" for action in actions):
            return result
        actions.append(
            {
                "tag": "button",
                "text": {"tag": "plain_text", "content": "上传清洗照片"},
                "type": "default",
                "url": build_base_record_url(record_id),
            }
        )
        element["actions"] = actions
        result["elements"] = elements
        return result
    result["elements"] = elements + [{"tag": "action", "actions": build_card_actions(record_id, accepted=True)}]
    return result


def mark_group_card_accepted(card: dict[str, Any], actor_open_id: str) -> dict[str, Any]:
    result = dict(card)
    elements = list(result.get("elements") or [])
    mention = f"<at id={actor_open_id}></at>已接清洗任务" if actor_open_id else "已接清洗任务"
    for element in elements:
        if isinstance(element, dict) and element.get("tag") == "markdown":
            content = str(element.get("content") or "")
            if mention not in content and "已接清洗任务" not in content:
                element["content"] = f"{content}\n**任务状态：** {mention}" if content else f"**任务状态：** {mention}"
            break
    for element in elements:
        if not isinstance(element, dict) or element.get("tag") != "action":
            continue
        disabled_actions = []
        for action in element.get("actions") or []:
            if isinstance(action, dict):
                updated_action = dict(action)
                updated_action["disabled"] = True
                disabled_actions.append(updated_action)
            else:
                disabled_actions.append(action)
        element["actions"] = disabled_actions
    result["elements"] = elements
    return result


def mark_done_button_cleaned(card: dict[str, Any]) -> dict[str, Any]:
    result = dict(card)
    elements = list(result.get("elements") or [])
    for element in elements:
        if not isinstance(element, dict) or element.get("tag") != "action":
            continue
        actions = []
        changed = False
        for action in element.get("actions") or []:
            if not isinstance(action, dict):
                actions.append(action)
                continue
            updated_action = dict(action)
            value = updated_action.get("value")
            if isinstance(value, dict) and value.get("action") == "done":
                updated_action["text"] = {"tag": "plain_text", "content": "已清洗"}
                updated_action["disabled"] = True
                changed = True
            actions.append(updated_action)
        if changed:
            element["actions"] = actions
            result["elements"] = elements
            return result
    return result


def add_upload_button_to_card_event(event: dict[str, Any], record_id: str) -> dict[str, Any]:
    card = find_card_payload(event)
    if not card:
        return build_car_wash_card({}, record_id, accepted=True)
    return add_upload_button_to_card(card, record_id)


def find_card_payload(event: dict[str, Any]) -> dict[str, Any] | None:
    action = event.get("event", {}).get("action", {})
    if isinstance(action, dict):
        for key in ("card", "context_card"):
            value = action.get(key)
            if isinstance(value, dict) and isinstance(value.get("elements"), list):
                return value
    return None


def stringify_field(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, list):
        parts = []
        for item in value:
            if isinstance(item, dict):
                parts.append(str(item.get("name") or item.get("text") or item.get("id") or item))
            else:
                parts.append(str(item))
        return "、".join(parts)
    if isinstance(value, dict):
        return str(value.get("text") or value.get("name") or value.get("link") or value)
    return str(value)


def alert_creator(lark_cli: str, title: str, detail: str, dedupe_key: str | None = None) -> None:
    if not BOT_CREATOR_OPEN_ID:
        log_event("skip_creator_alert_without_open_id", title=title, detail=detail)
        return
    if dedupe_key and dedupe_key in load_ids(PROCESSED_CARD_ACTION_LOG):
        log_event("skip_duplicate_creator_alert", dedupe_key=dedupe_key)
        return
    card = {
        "config": {"wide_screen_mode": True},
        "header": {
            "template": "red",
            "title": {"tag": "plain_text", "content": title},
        },
        "elements": [
            {
                "tag": "markdown",
                "content": (
                    f"**异常时间：** {now_iso()}\n"
                    f"**详情：** {detail}\n"
                    f"**来源表格：** [查看表格]({build_base_table_url()})"
                ),
            }
        ],
    }
    result = subprocess.run(
        [
            lark_cli,
            "im",
            "+messages-send",
            "--user-id",
            BOT_CREATOR_OPEN_ID,
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
        log_event("creator_alert_failed", stdout=result.stdout, stderr=result.stderr)
        return
    if dedupe_key:
        append_id(PROCESSED_CARD_ACTION_LOG, dedupe_key)
    update_health(last_alert_success_at=now_iso())
    log_event("creator_alert_sent", title=title, detail=detail)


def send_card(
    card: dict[str, Any],
    lark_cli: str,
    record_id: str = "",
    chat_id: str = "",
    user_id: str = "",
) -> str:
    if not chat_id and not user_id:
        raise RuntimeError("No card target configured. Set target_chat_id, target_user_open_id, or pass --chat-id/--user-id.")
    target_args = ["--chat-id", chat_id] if chat_id else ["--user-id", user_id]
    idempotency_key = build_idempotency_key(record_id)
    result = subprocess.run(
        [
            lark_cli,
            "im",
            "+messages-send",
            *target_args,
            "--idempotency-key",
            idempotency_key,
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
            "Failed to send car wash card\n"
            f"STDOUT:\n{result.stdout}\n"
            f"STDERR:\n{result.stderr}"
        )
    message_id = parse_sent_message_id(result.stdout)
    update_health(last_card_send_success_at=now_iso(), last_record_id=record_id, last_message_id=message_id)
    if record_id:
        cache_card(record_id, card)
    log_event("car_wash_card_sent", record_id=record_id, chat_id=chat_id, user_id=user_id, message_id=message_id)
    return message_id


def build_idempotency_key(record_id: str = "") -> str:
    raw_key = f"car-wash-card-{record_id}" if record_id else f"car-wash-card-{datetime.now(TIMEZONE).timestamp()}"
    safe_key = re.sub(r"[^A-Za-z0-9-]+", "-", raw_key).strip("-")
    return safe_key[:50] or "car-wash-card"


def private_card_idempotency_key(record_id: str, unique: bool = False) -> str:
    suffix = f"-{int(time.time() * 1000)}" if unique else ""
    return f"{record_id}-private{suffix}"


def parse_sent_message_id(output: str) -> str:
    try:
        payload = json.loads(output)
    except json.JSONDecodeError:
        return ""
    value = find_first_value(payload, {"open_message_id", "message_id", "messageId"})
    return value or ""


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
            "Failed to update car wash card\n"
            f"STDOUT:\n{result.stdout}\n"
            f"STDERR:\n{result.stderr}"
        )
    update_health(last_card_update_success_at=now_iso())
    log_event("car_wash_card_updated", message_id=message_id)


def load_card_cache() -> dict[str, Any]:
    if not CARD_CACHE_PATH.exists():
        return {}
    try:
        cache = json.loads(CARD_CACHE_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return cache if isinstance(cache, dict) else {}


def cache_card(record_id: str, card: dict[str, Any]) -> None:
    cache = load_card_cache()
    cache[record_id] = card
    CARD_CACHE_PATH.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8")


def load_cached_card(record_id: str) -> dict[str, Any] | None:
    card = load_card_cache().get(record_id)
    return card if isinstance(card, dict) else None


def build_base_table_url() -> str:
    return f"{BASE_HOST}/base/{BASE_TOKEN}?table={TABLE_ID}"


def build_base_record_url(record_id: str) -> str:
    return f"{build_base_table_url()}&record={record_id}"


def field_mapping() -> dict[str, str]:
    mapping = CONFIG.get("field_mapping") if isinstance(CONFIG.get("field_mapping"), dict) else {}
    return {
        "plate_number": str(mapping.get("plate_number") or "车牌号"),
        "cleaning_need": str(mapping.get("cleaning_need") or "清洗需求"),
        "return_station_time": str(mapping.get("return_station_time") or "到站时间"),
        "cleaner": str(mapping.get("cleaner") or "清洗人员"),
        "completed_at": str(mapping.get("completed_at") or "清洗完成时间"),
        "photo": str(mapping.get("photo") or "清洗照片"),
        "status": str(mapping.get("status") or "任务状态"),
        "group_message_id": str(mapping.get("group_message_id") or "群消息ID"),
        "private_message_id": str(mapping.get("private_message_id") or "私聊消息ID"),
    }


def parse_new_record_event(event: dict[str, Any]) -> str | None:
    event_type = str(event.get("header", {}).get("event_type") or "")
    lowered = event_type.lower()
    if "card.action" in lowered:
        return None
    if event_type == "drive.file.bitable_record_changed_v1":
        return parse_bitable_record_added_event(event)
    if not any(marker in lowered for marker in ("base", "bitable", "record")):
        return None
    if not any(marker in lowered for marker in ("create", "created", "add", "added", "change", "changed")):
        return None
    base_token = find_first_value(event, {"base_token", "app_token", "baseToken", "appToken"})
    table_id = find_first_value(event, {"table_id", "tableId"})
    record_id = find_first_value(event, {"record_id", "recordId"})
    if base_token and str(base_token) != BASE_TOKEN:
        return None
    if table_id and str(table_id) != TABLE_ID:
        return None
    return str(record_id) if record_id else None


def parse_bitable_record_added_event(event: dict[str, Any]) -> str | None:
    event_body = event.get("event") if isinstance(event.get("event"), dict) else {}
    file_token = find_first_value(event_body, {"file_token", "app_token", "base_token", "appToken", "baseToken"})
    table_id = find_first_value(event_body, {"table_id", "tableId"})
    if file_token and str(file_token) != BASE_TOKEN:
        return None
    if table_id and str(table_id) != TABLE_ID:
        return None
    action_list = event_body.get("action_list")
    if not isinstance(action_list, list):
        return None
    for action in action_list:
        if not isinstance(action, dict):
            continue
        if action.get("action") == "record_added" and action.get("record_id"):
            return str(action["record_id"])
    return None


def find_actor_open_id(event: dict[str, Any]) -> str | None:
    return find_first_value(
        event,
        {
            "open_id",
            "openId",
            "operator_open_id",
            "operatorOpenId",
            "user_open_id",
            "userOpenId",
        },
    )


def find_message_id(event: dict[str, Any]) -> str | None:
    value = find_first_value(event, {"open_message_id", "message_id", "messageId"})
    return str(value) if value else None


def find_first_value(node: Any, keys: set[str]) -> str | None:
    if isinstance(node, dict):
        for key, value in node.items():
            if key in keys and value:
                return str(value)
        for value in node.values():
            found = find_first_value(value, keys)
            if found:
                return found
    elif isinstance(node, list):
        for item in node:
            found = find_first_value(item, keys)
            if found:
                return found
    return None


def load_ids(path: Path) -> set[str]:
    if not path.exists():
        return set()
    return {line.strip() for line in path.read_text(encoding="utf-8").splitlines() if line.strip()}


def append_id(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as file:
        file.write(value + "\n")


def append_raw_event(event: dict[str, Any]) -> None:
    RAW_EVENT_LOG.parent.mkdir(parents=True, exist_ok=True)
    with RAW_EVENT_LOG.open("a", encoding="utf-8") as file:
        file.write(json.dumps(event, ensure_ascii=False) + "\n")


def sample_record() -> dict[str, Any]:
    mapping = field_mapping()
    return {
        "record_id": "sample_record_id",
        "fields": {
            mapping["plate_number"]: [{"text": "沪A12345"}],
            mapping["cleaning_need"]: "内外清洗",
            mapping["return_station_time"]: "2026-05-08 16:30:00",
            mapping["cleaner"]: "",
            mapping["completed_at"]: "",
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--lark-cli", default="lark-cli")
    parser.add_argument("--status", action="store_true")
    parser.add_argument("--inspect-base", action="store_true")
    parser.add_argument("--ensure-fields", action="store_true")
    parser.add_argument("--send-sample-card", action="store_true")
    parser.add_argument("--send-private-card", action="store_true")
    parser.add_argument("--record-json", default="")
    parser.add_argument("--record-id", default="")
    parser.add_argument("--poll-once", action="store_true")
    parser.add_argument("--send-existing", action="store_true")
    parser.add_argument("--chat-id", default="")
    parser.add_argument("--user-id", default="")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if args.status:
        print_status()
        return
    if args.inspect_base:
        inspect_base(args.lark_cli)
        return
    if args.ensure_fields:
        ensure_required_fields(args.lark_cli)
        return
    if args.send_sample_card:
        process_record_payload(sample_record(), args.lark_cli, args.chat_id, args.user_id, dry_run=args.dry_run)
        return
    if args.send_private_card:
        if not args.record_id or not args.user_id:
            raise RuntimeError("--send-private-card requires --record-id and --user-id")
        send_private_work_card_for_record(args.record_id, args.user_id, args.lark_cli, dry_run=args.dry_run)
        return
    if args.record_id:
        process_record_payload(
            {"record_id": args.record_id, "fields": fetch_record_fields(args.record_id, args.lark_cli)},
            args.lark_cli,
            args.chat_id,
            args.user_id,
            dry_run=args.dry_run,
        )
        return
    if args.record_json:
        process_record_payload(json.loads(args.record_json), args.lark_cli, args.chat_id, args.user_id, dry_run=args.dry_run)
        return
    if args.poll_once:
        processed_record_ids = load_ids(PROCESSED_RECORD_LOG)
        if args.send_existing:
            CONFIG["poll_send_existing_on_start"] = True
        poll_pending_records(processed_record_ids, args.lark_cli, baseline=not args.send_existing, dry_run=args.dry_run)
        return
    run_listener(args.lark_cli, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
