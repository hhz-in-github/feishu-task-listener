import unittest
from unittest.mock import MagicMock
from unittest.mock import patch

import feishu_automation_hub as hub


class FeishuAutomationHubTests(unittest.TestCase):
    def test_routes_group_card_actions_to_group_task_handler(self):
        event = {
            "header": {"event_type": "card.action.trigger"},
            "event": {"action": {"value": {"action": "claim", "record_id": "rec_1"}}},
        }

        with patch.object(hub.group_tasks, "handle_card_action_event") as group_handler, \
            patch.object(hub.car_wash, "handle_card_action_event") as car_handler:
            hub.route_event(event, set(), set(), set(), set(), "lark-cli")

        group_handler.assert_called_once()
        car_handler.assert_not_called()

    def test_routes_car_wash_card_actions_to_car_wash_handler(self):
        event = {
            "header": {"event_type": "card.action.trigger"},
            "event": {"action": {"value": {"action": "accept", "record_id": "rec_1"}}},
        }

        with patch.object(hub.group_tasks, "handle_card_action_event") as group_handler, \
            patch.object(hub.car_wash, "handle_card_action_event") as car_handler:
            hub.route_event(event, set(), set(), set(), set(), "lark-cli")

        car_handler.assert_called_once()
        group_handler.assert_not_called()

    def test_routes_group_messages_to_group_task_handler(self):
        event = {"header": {"event_type": "im.message.receive_v1"}}

        with patch.object(hub.group_tasks, "handle_event") as group_handler, \
            patch.object(hub.car_wash, "handle_event") as car_handler:
            hub.route_event(event, set(), set(), set(), set(), "lark-cli")

        group_handler.assert_called_once()
        car_handler.assert_not_called()

    def test_routes_bitable_record_events_to_car_wash_handler(self):
        event = {
            "header": {"event_type": "drive.file.bitable_record_changed_v1"},
            "event": {
                "file_token": hub.car_wash.BASE_TOKEN,
                "table_id": hub.car_wash.TABLE_ID,
                "action_list": [{"action": "record_added", "record_id": "rec_1"}],
            },
        }

        with patch.object(hub.group_tasks, "handle_event") as group_handler, \
            patch.object(hub.car_wash, "handle_event") as car_handler:
            hub.route_event(event, set(), set(), set(), set(), "lark-cli")

        car_handler.assert_called_once()
        group_handler.assert_not_called()

    def test_run_listener_does_not_start_car_wash_polling(self):
        process = MagicMock()
        process.stdout = []
        process.__enter__.return_value = process
        process.__exit__.return_value = None

        with patch.object(hub.group_tasks, "_load_processed_ids", return_value=set()), \
            patch.object(hub.group_tasks, "_load_ids", return_value=set()), \
            patch.object(hub.car_wash, "load_ids", return_value=set()), \
            patch.object(hub.car_wash, "ensure_required_fields"), \
            patch.object(hub.car_wash, "start_polling_thread") as start_polling, \
            patch.object(hub.subprocess, "Popen", return_value=process):
            hub.run_listener("lark-cli", dry_run=False)

        start_polling.assert_not_called()


if __name__ == "__main__":
    unittest.main()
