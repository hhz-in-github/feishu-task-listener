import json
import unittest
from unittest.mock import patch

from feishu_group_to_base import (
    BASE_HOST,
    BASE_TOKEN,
    BOT_CREATOR_OPEN_ID,
    TABLE_ID,
    alert_creator,
    extract_app_admin_open_ids,
    fetch_app_admin_open_ids,
    build_creator_alert_card,
    build_base_record_url,
    build_base_table_url,
    build_user_authorization_alert_reason,
    build_task_card,
    build_creator_alert_text,
    handle_card_action_event,
    handle_event,
    is_bot_availability_error,
    is_user_authorization_error,
    parse_card_action,
    parse_event,
    parse_record_id_from_output,
    send_task_card,
)


class ParseEventTests(unittest.TestCase):
    def test_parses_assignee_vehicle_task_types_and_times(self):
        event = {
            "event": {
                "message": {
                    "content": "{\"text\":\"@_user_1 @_user_2 0412救援，换电\"}",
                    "create_time": "1777917532650",
                    "mentions": [
                        {
                            "key": "@_user_1",
                            "mentioned_type": "bot",
                            "name": "救援工单",
                            "id": {"open_id": "test_bot_open_id"},
                        },
                        {
                            "key": "@_user_2",
                            "mentioned_type": "user",
                            "name": "陈福艳",
                            "id": {"open_id": "test_user_open_id"},
                        },
                    ],
                    "message_id": "om_1",
                }
            }
        }

        record = parse_event(event)

        self.assertEqual(record["消息原文"], "@救援工单 @陈福艳 0412救援，换电")
        self.assertEqual(record["执行人"], [{"id": "test_user_open_id"}])
        self.assertEqual(record["车牌号"], "0412")
        self.assertEqual(record["任务类型"], ["救援", "换电"])
        self.assertEqual(record["任务状态"], "待领取")
        self.assertEqual(record["任务发布时间"], "2026-05-05 01:58:52")
        self.assertEqual(record["日期"], "2026-05-05 00:00:00")

    def test_keeps_record_when_optional_parts_are_missing(self):
        event = {
            "event": {
                "message": {
                    "content": "{\"text\":\"@_user_1 需要人工看一下\"}",
                    "create_time": "1777917532650",
                    "mentions": [
                        {
                            "key": "@_user_1",
                            "mentioned_type": "bot",
                            "name": "救援工单",
                            "id": {"open_id": "test_bot_open_id"},
                        }
                    ],
                    "message_id": "om_2",
                }
            }
        }

        record = parse_event(event)

        self.assertEqual(record["消息原文"], "@救援工单 需要人工看一下")
        self.assertNotIn("执行人", record)
        self.assertNotIn("车牌号", record)
        self.assertNotIn("任务类型", record)
        self.assertIn("备注", record)

    def test_vehicle_number_is_optional_when_other_fields_exist(self):
        event = {
            "event": {
                "message": {
                    "content": "{\"text\":\"@_user_1 @_user_2 救援，换电\"}",
                    "create_time": "1777917532650",
                    "mentions": [
                        {
                            "key": "@_user_1",
                            "mentioned_type": "bot",
                            "name": "救援工单",
                            "id": {"open_id": "test_bot_open_id"},
                        },
                        {
                            "key": "@_user_2",
                            "mentioned_type": "user",
                            "name": "陈福艳",
                            "id": {"open_id": "test_user_open_id"},
                        },
                    ],
                    "message_id": "om_no_vehicle",
                }
            }
        }

        record = parse_event(event)

        self.assertNotIn("车牌号", record)
        self.assertEqual(record["执行人"], [{"id": "test_user_open_id"}])
        self.assertEqual(record["任务类型"], ["救援", "换电"])
        self.assertNotIn("备注", record)

    def test_maps_energy_task_type_to_existing_base_option(self):
        event = {
            "event": {
                "message": {
                    "content": "{\"text\":\"@_user_1 @_user_2 7757充换电\"}",
                    "create_time": "1777917532650",
                    "mentions": [
                        {
                            "key": "@_user_1",
                            "mentioned_type": "bot",
                            "name": "救援工单",
                            "id": {"open_id": "test_bot_open_id"},
                        },
                        {
                            "key": "@_user_2",
                            "mentioned_type": "user",
                            "name": "陈福艳",
                            "id": {"open_id": "test_user_open_id"},
                        },
                    ],
                    "message_id": "om_energy",
                }
            }
        }

        record = parse_event(event)

        self.assertEqual(record["任务类型"], ["充换电/带电/充电/换电"])

    def test_builds_interactive_card_with_record_actions(self):
        record = {
            "消息原文": "@救援工单 @陈福艳 0412救援，换电",
            "车牌号": "0412",
            "任务类型": ["救援", "换电"],
            "任务发布时间": "2026-05-05 01:58:52",
            "群聊ID": "test_chat_id",
        }

        card = build_task_card(record, "rec_123")

        self.assertEqual(card["config"]["wide_screen_mode"], True)
        self.assertIn("新增救援任务", card["header"]["title"]["content"])
        actions = card["elements"][1]["actions"]
        self.assertEqual(actions[0]["text"]["content"], "领取任务")
        self.assertEqual(actions[0]["value"]["action"], "claim")
        self.assertEqual(actions[0]["value"]["record_id"], "rec_123")
        self.assertEqual(actions[0]["value"]["群聊ID"], "test_chat_id")
        self.assertEqual(actions[1]["value"]["action"], "resolve")
        self.assertIn("**来源表格：** [查看表格](", card["elements"][0]["content"])
        self.assertIn(build_base_table_url(), card["elements"][0]["content"])
        self.assertNotIn("查看多维表格记录", card["elements"][0]["content"])
        self.assertNotIn("记录链接", actions[0]["value"])

    def test_builds_card_with_disabled_clicked_button(self):
        record = {
            "消息原文": "@救援工单 @陈福艳 0412救援，换电",
            "车牌号": "0412",
            "任务类型": ["救援", "换电"],
            "任务发布时间": "2026-05-05 01:58:52",
        }

        card = build_task_card(record, "rec_123", disabled_actions={"claim"})

        actions = card["elements"][1]["actions"]
        self.assertEqual(actions[0]["text"]["content"], "领取任务")
        self.assertEqual(actions[0]["disabled"], True)
        self.assertNotIn("disabled", actions[1])

    def test_builds_card_with_departure_location_link_after_claim(self):
        record = {
            "消息原文": "@救援工单 @陈福艳 0412救援，换电",
            "车牌号": "0412",
            "任务类型": ["救援", "换电"],
            "任务发布时间": "2026-05-05 01:58:52",
        }

        card = build_task_card(
            record,
            "rec_123",
            disabled_actions={"claim"},
            location_fill_action="claim",
        )

        actions = card["elements"][1]["actions"]
        self.assertEqual(actions[2]["text"]["content"], "填写出发位置")
        self.assertEqual(actions[2]["url"], build_base_record_url("rec_123"))
        self.assertIn("请打开对应记录填写出发位置", card["elements"][0]["content"])

    def test_builds_card_with_rescue_end_location_link_after_resolve(self):
        record = {
            "消息原文": "@救援工单 @陈福艳 0412救援，换电",
            "车牌号": "0412",
            "任务类型": ["救援", "换电"],
            "任务发布时间": "2026-05-05 01:58:52",
        }

        card = build_task_card(
            record,
            "rec_123",
            disabled_actions={"claim", "resolve"},
            location_fill_action="resolve",
        )

        actions = card["elements"][1]["actions"]
        self.assertEqual(actions[2]["text"]["content"], "填写救援结束位置")
        self.assertEqual(actions[2]["url"], build_base_record_url("rec_123"))
        self.assertIn("请打开对应记录填写救援结束位置", card["elements"][0]["content"])

    def test_parses_card_action_value(self):
        event = {
            "header": {"event_type": "card.action.trigger"},
            "event": {
                "context": {"open_message_id": "om_card_1"},
                "action": {
                    "value": {
                        "action": "claim",
                        "record_id": "rec_123",
                        "群聊ID": "test_chat_id",
                    }
                }
            },
        }

        action = parse_card_action(event)

        self.assertEqual(
            action,
            {
                "action": "claim",
                "群聊ID": "test_chat_id",
                "message_id": "om_card_1",
                "record_id": "rec_123",
            },
        )

    @patch("feishu_group_to_base.send_task_card")
    @patch("feishu_group_to_base.alert_creator")
    @patch("feishu_group_to_base.write_record_with_fallback")
    def test_missing_fields_alerts_creator_and_skips_card_send(
        self,
        write_record,
        alert_creator,
        send_task_card,
    ):
        write_record.return_value = "rec_123"
        event = {
            "header": {"event_type": "im.message.receive_v1"},
            "event": {
                "message": {
                    "chat_id": "test_chat_id",
                    "content": "{\"text\":\"@_user_1 @_user_2 11115545695842，测试异常情况\"}",
                    "create_time": "1777952509450",
                    "mentions": [
                        {
                            "id": {"open_id": "test_bot_open_id"},
                            "key": "@_user_1",
                            "mentioned_type": "bot",
                            "name": "救援工单",
                        },
                        {
                            "id": {"open_id": "test_user_open_id"},
                            "key": "@_user_2",
                            "mentioned_type": "user",
                            "name": "黄贵杰",
                        },
                    ],
                    "message_id": "om_missing",
                    "message_type": "text",
                }
            },
        }

        handle_event(event, set(), set(), "lark-cli.cmd")

        alert_creator.assert_called_once_with(
            "test_chat_id",
            "@救援工单 @黄贵杰 11115545695842，测试异常情况",
            "lark-cli.cmd",
            reason="未识别任务类型",
            dedupe_key="message:om_missing:incomplete",
        )
        send_task_card.assert_not_called()

    @patch("feishu_group_to_base.send_task_card")
    @patch("feishu_group_to_base.alert_creator")
    @patch("feishu_group_to_base.write_record_with_fallback")
    def test_missing_vehicle_still_sends_task_card(
        self,
        write_record,
        alert_creator,
        send_task_card,
    ):
        write_record.return_value = "rec_123"
        event = {
            "header": {"event_type": "im.message.receive_v1"},
            "event": {
                "message": {
                    "chat_id": "test_chat_id",
                    "content": "{\"text\":\"@_user_1 @_user_2 救援，换电\"}",
                    "create_time": "1777952509450",
                    "mentions": [
                        {
                            "id": {"open_id": "test_bot_open_id"},
                            "key": "@_user_1",
                            "mentioned_type": "bot",
                            "name": "救援工单",
                        },
                        {
                            "id": {"open_id": "test_user_open_id"},
                            "key": "@_user_2",
                            "mentioned_type": "user",
                            "name": "黄贵杰",
                        },
                    ],
                    "message_id": "om_no_vehicle_send",
                    "message_type": "text",
                }
            },
        }

        handle_event(event, set(), set(), "lark-cli.cmd")

        alert_creator.assert_not_called()
        send_task_card.assert_called_once()
        sent_record = send_task_card.call_args.kwargs["record"]
        self.assertNotIn("车牌号", sent_record)
        self.assertNotIn("备注", sent_record)

    @patch("feishu_group_to_base.send_task_card")
    @patch("feishu_group_to_base.alert_creator")
    @patch("feishu_group_to_base.write_record_with_fallback")
    def test_card_send_failure_alert_includes_assignee_identity(
        self,
        write_record,
        alert_creator,
        send_task_card,
    ):
        write_record.return_value = "rec_123"
        send_task_card.side_effect = RuntimeError("Bot has NO availability to this user.")
        event = {
            "header": {"event_type": "im.message.receive_v1"},
            "event": {
                "message": {
                    "chat_id": "test_chat_id",
                    "content": "{\"text\":\"@_user_1 @_user_2 7757救援\"}",
                    "create_time": "1777952509450",
                    "mentions": [
                        {
                            "id": {"open_id": "test_bot_open_id"},
                            "key": "@_user_1",
                            "mentioned_type": "bot",
                            "name": "救援工单",
                            "tenant_key": "tenant_app",
                        },
                        {
                            "id": {"open_id": "test_user_open_id"},
                            "key": "@_user_2",
                            "mentioned_type": "user",
                            "name": "外部执行人",
                            "tenant_key": "tenant_external",
                        },
                    ],
                    "message_id": "om_card_fail",
                    "message_type": "text",
                }
            },
        }

        with self.assertRaises(RuntimeError):
            handle_event(event, set(), set(), "lark-cli.cmd")

        self.assertIn("目标执行人：外部执行人", alert_creator.call_args.kwargs["reason"])
        self.assertIn("open_id=test_user_open_id", alert_creator.call_args.kwargs["reason"])
        self.assertIn("tenant_key=tenant_external", alert_creator.call_args.kwargs["reason"])

    @patch("feishu_group_to_base.send_task_card")
    @patch("feishu_group_to_base.alert_creator")
    @patch("feishu_group_to_base.write_record_with_fallback")
    def test_message_without_bot_mention_is_ignored(
        self,
        write_record,
        alert_creator,
        send_task_card,
    ):
        event = {
            "header": {"event_type": "im.message.receive_v1"},
            "event": {
                "message": {
                    "chat_id": "test_chat_id",
                    "content": "{\"text\":\"随便聊一下 0412 救援\"}",
                    "create_time": "1777952509450",
                    "mentions": [],
                    "message_id": "om_without_bot",
                    "message_type": "text",
                }
            },
        }
        processed_ids: set[str] = set()

        handle_event(event, processed_ids, set(), "lark-cli.cmd")

        write_record.assert_not_called()
        alert_creator.assert_not_called()
        send_task_card.assert_not_called()
        self.assertIn("om_without_bot", processed_ids)

    @patch("feishu_group_to_base.alert_creator")
    @patch("feishu_group_to_base.update_record")
    def test_alerts_creator_when_card_action_update_fails(self, update_record, alert_creator):
        update_record.side_effect = RuntimeError("base update failed")
        event = {
            "header": {
                "event_id": "evt_1",
                "event_type": "card.action.trigger",
            },
            "event": {
                "action": {
                    "value": {
                        "action": "resolve",
                        "record_id": "rec_123",
                        "群聊ID": "test_chat_id",
                        "消息原文": "@救援工单 @陈福艳 0412救援，换电",
                    }
                }
            },
        }

        with self.assertRaises(RuntimeError):
            handle_card_action_event(event, set(), "lark-cli.cmd")

        alert_creator.assert_called_once()
        args, kwargs = alert_creator.call_args
        self.assertEqual(args, ("test_chat_id", "@救援工单 @陈福艳 0412救援，换电", "lark-cli.cmd"))
        self.assertEqual(kwargs["dedupe_key"], "card_action:evt_1:resolve")
        self.assertIn("按钮回写失败：base update failed", kwargs["reason"])
        self.assertIn("record_id=rec_123", kwargs["reason"])
        self.assertIn("\"任务解决时间\":", kwargs["reason"])
        self.assertIn("\"任务状态\": \"已解决\"", kwargs["reason"])

    def test_parses_record_id_from_nested_upsert_output(self):
        output = """
        {
          "ok": true,
          "data": {
            "created": true,
            "record": {
              "fields": {"消息原文": "x"},
              "record_id": "rec_nested"
            }
          }
        }
        """

        self.assertEqual(parse_record_id_from_output(output), "rec_nested")

    def test_parses_record_id_recursively_when_shape_changes(self):
        output = """
        {
          "ok": true,
          "data": {
            "records": [
              {
                "id": "rec_list_shape",
                "fields": {}
              }
            ]
          }
        }
        """

        self.assertEqual(parse_record_id_from_output(output), "rec_list_shape")

    def test_parses_record_id_from_record_id_list(self):
        output = """
        {
          "ok": true,
          "data": {
            "created": true,
            "record": {
              "record_id_list": [
                "recviG5ZriYDq1"
              ],
              "fields": ["消息原文"]
            }
          }
        }
        """

        self.assertEqual(parse_record_id_from_output(output), "recviG5ZriYDq1")

    def test_detects_bot_availability_error(self):
        message = "HTTP 400: Bot has NO availability to this user."

        self.assertTrue(is_bot_availability_error(message))

    def test_detects_user_authorization_error(self):
        message = """
        Failed to write Base record
        STDERR:
        {"error": {"message": "API call failed: need_user_authorization (user: )"}}
        """

        self.assertTrue(is_user_authorization_error(message))

    @patch("feishu_group_to_base.alert_creator")
    @patch("feishu_group_to_base.write_record_with_fallback")
    def test_user_authorization_error_alerts_with_reauth_hint(
        self,
        write_record,
        alert_creator,
    ):
        write_record.side_effect = RuntimeError(
            "API call failed: need_user_authorization (user: )"
        )
        event = {
            "header": {"event_type": "im.message.receive_v1"},
            "event": {
                "message": {
                    "chat_id": "test_chat_id",
                    "content": "{\"text\":\"@_user_1 @_user_2 7757救援\"}",
                    "create_time": "1777952509450",
                    "mentions": [
                        {
                            "id": {"open_id": "test_bot_open_id"},
                            "key": "@_user_1",
                            "mentioned_type": "bot",
                            "name": "救援工单",
                        },
                        {
                            "id": {"open_id": "test_user_open_id"},
                            "key": "@_user_2",
                            "mentioned_type": "user",
                            "name": "黄贵杰",
                        },
                    ],
                    "message_id": "om_auth",
                    "message_type": "text",
                }
            },
        }

        with self.assertRaises(RuntimeError):
            handle_event(event, set(), set(), "lark-cli.cmd")

        alert_creator.assert_called_once_with(
            "test_chat_id",
            "@救援工单 @黄贵杰 7757救援",
            "lark-cli.cmd",
            reason=build_user_authorization_alert_reason(),
            dedupe_key="user_authorization:om_auth",
        )

    def test_builds_creator_alert_text_with_only_chat_and_original_message(self):
        text = build_creator_alert_text("救援群", "@救援工单 缺少车牌")

        self.assertEqual(
            text,
            "群聊名称：救援群\n"
            "消息原文：@救援工单 缺少车牌\n"
            f"来自表单：{build_base_table_url()}",
        )

    def test_builds_creator_alert_card_with_exception_title(self):
        card = build_creator_alert_card("救援群", "@救援工单 缺少车牌", "未识别车牌号")

        self.assertEqual(card["header"]["title"]["content"], "异常处理")
        self.assertIn("**异常原因：** 未识别车牌号", card["elements"][0]["content"])
        self.assertIn(build_base_table_url(), card["elements"][0]["content"])

    def test_parses_task_type_synonym_from_config(self):
        event = {
            "event": {
                "message": {
                    "content": "{\"text\":\"@_user_1 @_user_2 0412更换电池\"}",
                    "create_time": "1777917532650",
                    "mentions": [
                        {
                            "key": "@_user_1",
                            "mentioned_type": "bot",
                            "name": "救援工单",
                            "id": {"open_id": "test_bot_open_id"},
                        },
                        {
                            "key": "@_user_2",
                            "mentioned_type": "user",
                            "name": "陈福艳",
                            "id": {"open_id": "test_user_open_id"},
                        },
                    ],
                    "message_id": "om_synonym",
                }
            }
        }

        record = parse_event(event)

        self.assertIn("换电", record["任务类型"])

    def test_builds_base_table_url_from_write_target(self):
        self.assertEqual(
            build_base_table_url(),
            f"{BASE_HOST}/base/{BASE_TOKEN}?table={TABLE_ID}",
        )

    def test_builds_base_record_url_from_write_target(self):
        self.assertEqual(
            build_base_record_url("rec_123"),
            f"{BASE_HOST}/base/{BASE_TOKEN}?table={TABLE_ID}&record=rec_123",
        )

    @patch("feishu_group_to_base.cached_app_admin_open_ids", return_value=["admin_1"])
    @patch("feishu_group_to_base.subprocess.run")
    @patch("feishu_group_to_base.get_chat_name")
    def test_alert_creator_sends_exception_card_as_bot(self, get_chat_name, run, cached_admins):
        get_chat_name.return_value = "测试用"
        run.return_value.returncode = 0
        run.return_value.stdout = "{}"

        alert_creator("test_chat_id", "机器人发送测试", "lark-cli.cmd")

        args = run.call_args.args[0]
        self.assertEqual(
            args,
            [
                "lark-cli.cmd",
                "im",
                "+messages-send",
                "--as",
                "bot",
                "--user-id",
                "admin_1",
                "--msg-type",
                "interactive",
                "--content",
                run.call_args.args[0][run.call_args.args[0].index("--content") + 1],
            ],
        )
        content = run.call_args.args[0][run.call_args.args[0].index("--content") + 1]
        self.assertIn('"content": "异常处理"', content)
        self.assertIn("机器人发送测试", content)

    @patch("feishu_group_to_base.cached_app_admin_open_ids", return_value=["admin_1", "admin_2"])
    @patch("feishu_group_to_base.subprocess.run")
    @patch("feishu_group_to_base.get_chat_name")
    def test_alert_creator_sends_to_app_admins_without_duplicates(self, get_chat_name, run, cached_admins):
        get_chat_name.return_value = "测试用"
        run.return_value.returncode = 0
        run.return_value.stdout = "{}"

        alert_creator("test_chat_id", "管理员通知测试", "lark-cli.cmd")

        user_ids = [
            call.args[0][call.args[0].index("--user-id") + 1]
            for call in run.call_args_list
        ]
        self.assertEqual(user_ids, ["admin_1", "admin_2"])

    def test_extracts_app_admin_open_ids_from_api_payload(self):
        payload = {
            "code": 0,
            "data": {
                "user_list": [
                    {"open_id": "admin_1"},
                    {"open_id": "admin_2"},
                    {"open_id": "admin_1"},
                ]
            },
        }

        self.assertEqual(extract_app_admin_open_ids(payload), ["admin_1", "admin_2"])

    @patch("feishu_group_to_base.subprocess.run")
    def test_fetches_app_admin_open_ids(self, run):
        run.return_value.returncode = 0
        run.return_value.stdout = json.dumps(
            {"data": {"user_list": [{"open_id": "admin_1"}, {"open_id": "admin_2"}]}}
        )
        run.return_value.stderr = ""

        self.assertEqual(fetch_app_admin_open_ids("lark-cli.cmd"), ["admin_1", "admin_2"])
        self.assertIn("/open-apis/user/v4/app_admin_user/list", run.call_args.args[0])

    def test_send_task_card_does_not_fallback_to_group_chat(self):
        with patch("feishu_group_to_base.send_card_to_user") as send_user:
            send_user.side_effect = RuntimeError("Bot has NO availability to this user.")

            with self.assertRaises(RuntimeError):
                send_task_card(
                    assignee_open_id="test_user_open_id",
                    record={"消息原文": "x"},
                    record_id="rec_1",
                    lark_cli="lark-cli.cmd",
                )

    @patch("feishu_group_to_base.time.sleep")
    @patch("feishu_group_to_base.subprocess.run")
    def test_send_task_card_retries_transient_504(self, run, sleep):
        failed = unittest.mock.Mock()
        failed.returncode = 1
        failed.stdout = ""
        failed.stderr = (
            '{"ok": false, "error": {"type": "network", '
            '"subtype": "transport", '
            '"message": "API call failed: TAT API returned HTTP 504"}}'
        )
        succeeded = unittest.mock.Mock()
        succeeded.returncode = 0
        succeeded.stdout = "{}"
        succeeded.stderr = ""
        run.side_effect = [failed, succeeded]

        send_task_card(
            assignee_open_id="test_user_open_id",
            record={"消息原文": "x"},
            record_id="rec_1",
            lark_cli="lark-cli.cmd",
        )

        self.assertEqual(run.call_count, 2)
        sleep.assert_called_once()


if __name__ == "__main__":
    unittest.main()
