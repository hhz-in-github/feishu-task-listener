import argparse
import json
import subprocess
import sys
from typing import Any

import feishu_group_to_base as group_tasks
from feishu_car_wash_notifier import car_wash_notifier as car_wash


HUB_EVENT_TYPES = ",".join(
    [
        "im.message.receive_v1",
        "card.action.trigger",
        "drive.file.bitable_record_changed_v1",
    ]
)
GROUP_CARD_ACTIONS = {"claim", "resolve"}
CAR_WASH_CARD_ACTIONS = {"accept", "done"}


def run_listener(lark_cli: str, dry_run: bool = False) -> None:
    group_processed_ids = group_tasks._load_processed_ids()
    group_processed_card_action_ids = group_tasks._load_ids(group_tasks.PROCESSED_CARD_ACTION_LOG)
    car_processed_record_ids = car_wash.load_ids(car_wash.PROCESSED_RECORD_LOG)
    car_processed_card_action_ids = car_wash.load_ids(car_wash.PROCESSED_CARD_ACTION_LOG)

    if not dry_run:
        car_wash.ensure_required_fields(lark_cli)

    command = [
        lark_cli,
        "event",
        "+subscribe",
        "--event-types",
        HUB_EVENT_TYPES,
        "--as",
        "bot",
    ]
    group_tasks.update_health(status="running", started_at=group_tasks.now_iso(), lark_cli=lark_cli)
    group_tasks.log_event("hub_listener_started", event_types=HUB_EVENT_TYPES, dry_run=dry_run)
    car_wash.update_health(status="running", started_at=car_wash.now_iso(), lark_cli=lark_cli, hub=True)
    car_wash.log_event("hub_listener_started", event_types=HUB_EVENT_TYPES, dry_run=dry_run)

    print("Starting unified Feishu automation listener...", file=sys.stderr)
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
                group_tasks.log_event("hub_skip_non_json_output", line=line)
                car_wash.log_event("hub_skip_non_json_output", line=line)
                continue

            group_tasks._append_raw_event(event)
            car_wash.append_raw_event(event)
            try:
                route_event(
                    event,
                    group_processed_ids,
                    group_processed_card_action_ids,
                    car_processed_record_ids,
                    car_processed_card_action_ids,
                    lark_cli,
                    dry_run=dry_run,
                )
            except Exception as exc:  # noqa: BLE001 单条事件失败不得拖垮整条长连接
                # 记录错误但保持 status=running：进程仍在监听，只是这一条没处理成功。
                group_tasks.update_health(status="running", last_error=str(exc), last_error_at=group_tasks.now_iso())
                car_wash.update_health(status="running", last_error=str(exc), last_error_at=car_wash.now_iso())
                group_tasks.log_event("hub_event_processing_failed", error=str(exc), event=event)
                car_wash.log_event("hub_event_processing_failed", error=str(exc), event=event)
                event_type = str(event.get("header", {}).get("event_type") or "")
                group_tasks.alert_dev_group(
                    reason=str(exc),
                    lark_cli=lark_cli,
                    context=f"event_type={event_type}",
                )
                # 关键：不再 raise。跳过这一条，继续处理后续事件，长连接保持在线。
                continue


def route_event(
    event: dict[str, Any],
    group_processed_ids: set[str],
    group_processed_card_action_ids: set[str],
    car_processed_record_ids: set[str],
    car_processed_card_action_ids: set[str],
    lark_cli: str,
    dry_run: bool = False,
) -> None:
    event_type = str(event.get("header", {}).get("event_type") or "")
    if event_type == "card.action.trigger":
        action = parse_card_action_name(event)
        if action in CAR_WASH_CARD_ACTIONS:
            car_wash.handle_card_action_event(event, car_processed_card_action_ids, lark_cli, dry_run=dry_run)
            return
        if action in GROUP_CARD_ACTIONS:
            group_tasks.handle_card_action_event(event, group_processed_card_action_ids, lark_cli, dry_run)
            return
        group_tasks.log_event("hub_skip_unknown_card_action", action=action)
        car_wash.log_event("hub_skip_unknown_card_action", action=action)
        return

    if event_type == "im.message.receive_v1":
        group_tasks.handle_event(event, group_processed_ids, group_processed_card_action_ids, lark_cli, dry_run)
        return

    if car_wash.parse_new_record_event(event):
        car_wash.handle_event(event, car_processed_record_ids, car_processed_card_action_ids, lark_cli, dry_run=dry_run)
        return

    group_tasks.log_event("hub_skip_unrouted_event", event_type=event_type)
    car_wash.log_event("hub_skip_unrouted_event", event_type=event_type)


def parse_card_action_name(event: dict[str, Any]) -> str:
    value = event.get("event", {}).get("action", {}).get("value")
    if not isinstance(value, dict):
        return ""
    return str(value.get("action") or "")


def print_status() -> None:
    payload = {
        "event_types": HUB_EVENT_TYPES,
        "group_task_status": load_status_payload(group_tasks.HEALTH_PATH),
        "car_wash_status": load_status_payload(car_wash.HEALTH_PATH),
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def load_status_payload(path: Any) -> Any:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return path.read_text(encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--lark-cli", default="lark-cli")
    parser.add_argument("--status", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if args.status:
        print_status()
        return
    run_listener(args.lark_cli, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
