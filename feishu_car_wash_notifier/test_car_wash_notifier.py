import unittest
from unittest.mock import patch
from types import SimpleNamespace

try:
    from feishu_car_wash_notifier import car_wash_notifier
except ModuleNotFoundError:
    import car_wash_notifier


class CarWashNotifierTests(unittest.TestCase):
    def test_builds_card_from_configured_fields(self):
        payload = car_wash_notifier.sample_record()
        card = car_wash_notifier.build_car_wash_card(payload["fields"], payload["record_id"])

        self.assertEqual(card["config"]["wide_screen_mode"], True)
        self.assertEqual(card["header"]["title"]["content"], "洗车任务提醒")
        self.assertIn("沪A12345", card["elements"][0]["content"])
        self.assertIn("内外清洗", card["elements"][0]["content"])
        self.assertIn("车辆返回场站时间", card["elements"][0]["content"])
        self.assertIn("2026-05-08 16:30:00", card["elements"][0]["content"])
        self.assertIn("sample_record_id", card["elements"][0]["content"])
        self.assertEqual(card["elements"][1]["actions"][0]["value"]["action"], "accept")
        self.assertEqual(card["elements"][1]["actions"][1]["value"]["action"], "done")
        self.assertEqual(card["elements"][1]["actions"][0]["text"]["content"], "接受任务")
        self.assertEqual(card["elements"][1]["actions"][1]["text"]["content"], "完成任务")

    def test_adds_upload_photo_button_after_accept(self):
        payload = car_wash_notifier.sample_record()
        card = car_wash_notifier.build_car_wash_card(payload["fields"], payload["record_id"], accepted=True)

        actions = card["elements"][1]["actions"]
        self.assertEqual(actions[2]["text"]["content"], "上传清洗照片")
        self.assertIn("record=sample_record_id", actions[2]["url"])
        self.assertNotIn("value", actions[2])

    def test_adds_upload_button_to_existing_card_without_refetch(self):
        card = car_wash_notifier.build_car_wash_card(car_wash_notifier.sample_record()["fields"], "rec_1")
        event = {"event": {"action": {"card": card}}}

        updated = car_wash_notifier.add_upload_button_to_card_event(event, "rec_1")

        actions = updated["elements"][1]["actions"]
        self.assertEqual(actions[2]["text"]["content"], "上传清洗照片")
        self.assertIn("record=rec_1", actions[2]["url"])
        self.assertNotIn("value", actions[2])

    def test_adds_upload_button_to_cached_card_without_losing_fields(self):
        card = car_wash_notifier.build_car_wash_card(car_wash_notifier.sample_record()["fields"], "rec_1")

        updated = car_wash_notifier.add_upload_button_to_card(card, "rec_1")

        content = updated["elements"][0]["content"]
        self.assertIn("沪A12345", content)
        self.assertIn("内外清洗", content)
        self.assertIn("2026-05-08 16:30:00", content)
        self.assertIn("record=rec_1", updated["elements"][1]["actions"][2]["url"])
        self.assertNotIn("value", updated["elements"][1]["actions"][2])

    def test_marks_done_button_cleaned_and_disabled(self):
        card = car_wash_notifier.build_car_wash_card(car_wash_notifier.sample_record()["fields"], "rec_1")

        updated = car_wash_notifier.mark_done_button_cleaned(card)

        done_button = updated["elements"][1]["actions"][1]
        self.assertEqual(done_button["text"]["content"], "已清洗")
        self.assertEqual(done_button["disabled"], True)
        self.assertIn("沪A12345", updated["elements"][0]["content"])

    def test_marks_group_card_accepted_and_disabled(self):
        card = car_wash_notifier.build_car_wash_card(car_wash_notifier.sample_record()["fields"], "rec_1")

        updated = car_wash_notifier.mark_group_card_accepted(card, "ou_cleaner")

        self.assertIn("<at id=ou_cleaner></at>已接清洗任务", updated["elements"][0]["content"])
        for action in updated["elements"][1]["actions"]:
            self.assertEqual(action["disabled"], True)

    def test_builds_private_work_card_after_accept(self):
        card = car_wash_notifier.build_private_work_card(car_wash_notifier.sample_record()["fields"], "rec_1")

        actions = card["elements"][1]["actions"]
        self.assertEqual(actions[0]["value"]["action"], "done")
        self.assertEqual(actions[1]["text"]["content"], "上传清洗照片")
        self.assertIn("record=rec_1", actions[1]["url"])
        self.assertNotIn("value", actions[1])
        self.assertNotIn("接受任务", str(actions))

    def test_private_work_card_upload_button_is_url_only(self):
        card = car_wash_notifier.build_private_work_card(car_wash_notifier.sample_record()["fields"], "rec_1")

        upload_button = card["elements"][1]["actions"][1]
        self.assertEqual(upload_button["text"]["content"], "上传清洗照片")
        self.assertIn("url", upload_button)
        self.assertNotIn("value", upload_button)

    def test_parse_sent_message_id_from_cli_output(self):
        output = '{"data":{"message_id":"om_123"}}'

        self.assertEqual(car_wash_notifier.parse_sent_message_id(output), "om_123")

    def test_sanitizes_idempotency_key_for_lark(self):
        key = car_wash_notifier.build_idempotency_key("rec_1-private-ou_abc")

        self.assertEqual(key, "car-wash-card-rec-1-private-ou-abc")
        self.assertNotIn("_", key)

    def test_private_card_idempotency_key_excludes_user_id(self):
        key = car_wash_notifier.build_idempotency_key(
            car_wash_notifier.private_card_idempotency_key("rec27mC8vFuew2")
        )

        self.assertEqual(key, "car-wash-card-rec27mC8vFuew2-private")
        self.assertLessEqual(len(key), 50)

    def test_private_card_idempotency_key_can_be_unique(self):
        with patch.object(car_wash_notifier.time, "time", return_value=1778317000.123):
            key = car_wash_notifier.private_card_idempotency_key("rec27mC8vFuew2", unique=True)

        self.assertEqual(key, "rec27mC8vFuew2-private-1778317000123")

    def test_accept_updates_group_card_before_base_write_and_private_send(self):
        calls = []
        event = {
            "header": {"event_type": "card.action.trigger"},
            "event": {
                "operator": {"open_id": "ou_cleaner"},
                "action": {"value": {"action": "accept", "record_id": "rec_1"}},
                "context": {"open_message_id": "om_1"},
            },
        }

        def update_card_message(*_args):
            calls.append("update_card")

        def update_record(*_args):
            calls.append("update_record")

        def fetch_record_fields(*_args):
            calls.append("fetch_record")
            return car_wash_notifier.sample_record()["fields"]

        def send_card(*_args, **_kwargs):
            calls.append("send_private")
            return "om_private"

        with patch.object(car_wash_notifier, "load_cached_card", return_value=car_wash_notifier.build_car_wash_card(car_wash_notifier.sample_record()["fields"], "rec_1")), \
            patch.object(car_wash_notifier, "update_card_message", side_effect=update_card_message), \
            patch.object(car_wash_notifier, "update_record", side_effect=update_record), \
            patch.object(car_wash_notifier, "fetch_record_fields", side_effect=fetch_record_fields), \
            patch.object(car_wash_notifier, "send_card", side_effect=send_card), \
            patch.object(car_wash_notifier, "cache_card"), \
            patch.object(car_wash_notifier, "update_health"), \
            patch.object(car_wash_notifier, "log_event"):
            car_wash_notifier.handle_card_action_event(event, set(), "lark-cli")

        self.assertEqual(calls[:4], ["update_card", "update_record", "fetch_record", "send_private"])

    def test_duplicate_field_error_is_treated_as_existing_field(self):
        stderr = 'validation_error Use a unique field name. Existing field: fldwoFyAra("任务状态"). Requested field name: "任务状态".'

        self.assertTrue(car_wash_notifier.is_duplicate_field_error(stderr, "任务状态"))

    def test_should_not_notify_record_with_group_message_id(self):
        self.assertFalse(
            car_wash_notifier.should_notify_record(
                {
                    "车牌号": [{"id": "rec_vehicle"}],
                    "清洗需求": ["需要小清洗"],
                    "群消息ID": "om_sent",
                }
            )
        )

    def test_done_requires_photo_before_update(self):
        update = car_wash_notifier.build_action_update(
            "done",
            record_fields={"清洗照片": None},
        )

        self.assertEqual(update, {})

    def test_parses_card_action(self):
        event = {
            "header": {"event_type": "card.action.trigger", "event_id": "evt_1"},
            "event": {
                "action": {
                    "value": {
                        "action": "done",
                        "record_id": "rec_1",
                    }
                }
            },
        }

        self.assertEqual(
            car_wash_notifier.parse_card_action(event),
            {"action": "done", "record_id": "rec_1"},
        )

    def test_parses_card_action_record_id_from_card_url(self):
        event = {
            "header": {"event_type": "card.action.trigger", "event_id": "evt_1"},
            "event": {
                "action": {"value": {"action": "done"}},
                "context": {
                    "card": {
                        "elements": [
                            {
                                "tag": "button",
                                "url": "https://atomdance.feishu.cn/base/app_xxx?table=tbl_xxx&record=rec27mDuSUwbVu",
                            }
                        ]
                    }
                },
            },
        }

        self.assertEqual(
            car_wash_notifier.parse_card_action(event),
            {"action": "done", "record_id": "rec27mDuSUwbVu"},
        )

    def test_builds_accept_update_from_click_user(self):
        event = {"event": {"operator": {"open_id": "ou_cleaner"}}}
        self.assertEqual(
            car_wash_notifier.build_action_update("accept", event),
            {"清洗人员": [{"id": "ou_cleaner"}], "任务状态": "已接单"},
        )

    def test_builds_done_update_with_completion_time(self):
        update = car_wash_notifier.build_action_update("done")
        self.assertIn("清洗完成时间", update)
        self.assertRegex(update["清洗完成时间"], r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$")

    def test_ignores_unknown_action(self):
        self.assertEqual(car_wash_notifier.build_action_update("unknown"), {})

    def test_parses_new_record_event(self):
        event = {
            "header": {"event_type": "bitable.record.created_v1"},
            "event": {
                "base_token": "LdiKbOgd7a5FSvsgNO5c0DNunTa",
                "table_id": "tblaTXQqJNNAzMSS",
                "record_id": "rec_1",
            },
        }

        self.assertEqual(car_wash_notifier.parse_new_record_event(event), "rec_1")

    def test_parses_drive_bitable_record_added_event(self):
        event = {
            "header": {"event_type": "drive.file.bitable_record_changed_v1"},
            "event": {
                "file_token": "LdiKbOgd7a5FSvsgNO5c0DNunTa",
                "table_id": "tblaTXQqJNNAzMSS",
                "action_list": [
                    {"action": "record_edited", "record_id": "rec_ignore"},
                    {"action": "record_added", "record_id": "rec_added"},
                ],
            },
        }

        self.assertEqual(car_wash_notifier.parse_new_record_event(event), "rec_added")

    def test_detects_link_value_that_needs_display_resolution(self):
        self.assertTrue(car_wash_notifier.needs_link_display_resolution([{"id": "rec_vehicle"}]))
        self.assertFalse(car_wash_notifier.needs_link_display_resolution([{"id": "rec_vehicle", "text": "沪A12345"}]))

    def test_should_notify_record_requires_plate_and_need(self):
        self.assertTrue(
            car_wash_notifier.should_notify_record(
                {"车牌号": [{"id": "rec_vehicle"}], "清洗需求": ["需要小清洗"]}
            )
        )
        self.assertFalse(car_wash_notifier.should_notify_record({"车牌号": [{"id": "rec_vehicle"}]}))

    def test_record_list_parse_error_includes_raw_output(self):
        result = SimpleNamespace(returncode=0, stdout="", stderr="not-json")

        with patch.object(car_wash_notifier.subprocess, "run", return_value=result):
            with self.assertRaisesRegex(RuntimeError, "STDOUT"):
                car_wash_notifier.list_records("lark-cli")

    def test_record_list_requests_json_format(self):
        result = SimpleNamespace(
            returncode=0,
            stdout='{"data":{"fields":[],"data":[],"record_id_list":[]}}',
            stderr="",
        )

        with patch.object(car_wash_notifier.subprocess, "run", return_value=result) as run:
            car_wash_notifier.list_records("lark-cli")

        command = run.call_args.args[0]
        self.assertIn("--format", command)
        self.assertEqual(command[command.index("--format") + 1], "json")

    def test_record_get_requests_json_format(self):
        result = SimpleNamespace(
            returncode=0,
            stdout='{"data":{"record":{"fields":{"车牌号":"沪A12345"}}}}',
            stderr="",
        )

        with patch.object(car_wash_notifier.subprocess, "run", return_value=result) as run:
            fields = car_wash_notifier.fetch_record_fields("rec_1", "lark-cli")

        self.assertEqual(fields["车牌号"], "沪A12345")
        command = run.call_args.args[0]
        self.assertIn("--format", command)
        self.assertEqual(command[command.index("--format") + 1], "json")

    def test_record_get_reads_data_fields_shape(self):
        result = SimpleNamespace(
            returncode=0,
            stdout='{"data":{"fields":{"车牌号":"沪A12345","清洗需求":"小清洗"}}}',
            stderr="",
        )

        with patch.object(car_wash_notifier.subprocess, "run", return_value=result):
            fields = car_wash_notifier.fetch_record_fields("rec_1", "lark-cli")

        self.assertEqual(fields["车牌号"], "沪A12345")
        self.assertEqual(fields["清洗需求"], "小清洗")

    def test_record_get_reads_raw_record_fields_shape(self):
        result = SimpleNamespace(
            returncode=0,
            stdout='{"record":{},"raw":{"data":{"record":{"fields":{"车牌号":"沪A12345"}}}}}',
            stderr="",
        )

        with patch.object(car_wash_notifier.subprocess, "run", return_value=result):
            fields = car_wash_notifier.fetch_record_fields("rec_1", "lark-cli")

        self.assertEqual(fields["车牌号"], "沪A12345")

    def test_record_get_falls_back_to_record_list_when_empty(self):
        record_get_result = SimpleNamespace(returncode=0, stdout='{"ok":true,"data":{}}', stderr="")
        record_list_result = SimpleNamespace(
            returncode=0,
            stdout='{"data":{"fields":["车牌号","清洗需求"],"data":[["沪A12345","小清洗"]],"record_id_list":["rec_1"]}}',
            stderr="",
        )

        with patch.object(
            car_wash_notifier.subprocess,
            "run",
            side_effect=[record_get_result, record_list_result],
        ):
            fields = car_wash_notifier.fetch_record_fields("rec_1", "lark-cli")

        self.assertEqual(fields["车牌号"], "沪A12345")
        self.assertEqual(fields["清洗需求"], "小清洗")

    def test_linked_record_get_requests_json_format(self):
        result = SimpleNamespace(
            returncode=0,
            stdout='{"data":{"record":{"fields":{"车辆名称":"X6S7715"}}}}',
            stderr="",
        )

        with patch.object(car_wash_notifier.subprocess, "run", return_value=result) as run:
            display = car_wash_notifier.fetch_linked_record_display("tbl_vehicle", "rec_vehicle", "车辆名称", "lark-cli")

        self.assertEqual(display, "X6S7715")
        command = run.call_args.args[0]
        self.assertIn("--format", command)
        self.assertEqual(command[command.index("--format") + 1], "json")

    def test_linked_record_get_reads_top_level_fields_shape(self):
        result = SimpleNamespace(
            returncode=0,
            stdout='{"fields":{"车辆名称":"X6S7715"}}',
            stderr="",
        )

        with patch.object(car_wash_notifier.subprocess, "run", return_value=result):
            display = car_wash_notifier.fetch_linked_record_display("tbl_vehicle", "rec_vehicle", "车辆名称", "lark-cli")

        self.assertEqual(display, "X6S7715")

    def test_linked_record_get_reads_tabular_shape(self):
        result = SimpleNamespace(
            returncode=0,
            stdout='{"data":{"data":[["X6S7715"]],"fields":["车辆名称"],"record_id_list":["recvj0p6oofGEz"]}}',
            stderr="",
        )

        with patch.object(car_wash_notifier.subprocess, "run", return_value=result):
            display = car_wash_notifier.fetch_linked_record_display(
                "tbl_vehicle",
                "recvj0p6oofGEz",
                "车辆名称",
                "lark-cli",
            )

        self.assertEqual(display, "X6S7715")

    def test_record_get_parse_error_includes_raw_output(self):
        result = SimpleNamespace(returncode=0, stdout="", stderr="not-json")

        with patch.object(car_wash_notifier.subprocess, "run", return_value=result):
            with self.assertRaisesRegex(RuntimeError, "STDOUT"):
                car_wash_notifier.fetch_record_fields("rec_1", "lark-cli")


if __name__ == "__main__":
    unittest.main()
