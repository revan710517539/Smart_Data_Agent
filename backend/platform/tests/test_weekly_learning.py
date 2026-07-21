import unittest

from backend.platform.bootstrap import build_local_platform
from backend.platform.reports.weekly_learning import WeeklyReportLearningEngine


class WeeklyReportLearningTest(unittest.TestCase):
    def setUp(self) -> None:
        self.services = build_local_platform()
        self.tenant_id = "tenant_demo"
        self.user_id = "u_admin"

    def tearDown(self) -> None:
        self.services.close()

    def test_saved_weekly_version_generates_learning_outputs(self) -> None:
        version = self.services.report_store.save_weekly_report_version(
            self.tenant_id,
            _sample_weekly_version(),
            updated_by=self.user_id,
        )

        task = WeeklyReportLearningEngine(
            self.services.report_store,
            self.services.data_asset_store,
            self.services.application_store,
        ).analyze_version(self.tenant_id, version["id"], self.user_id, force=True)

        self.assertEqual(task["status"], "已完成")
        self.assertEqual(task["version_id"], version["id"])
        self.assertIn("rounds", task["debate_result"])
        self.assertEqual(len(task["debate_result"]["rounds"]), 3)
        self.assertTrue(task["final_result"]["data_analysis_methods"])
        self.assertTrue(task["final_result"]["user_behavior_habits"])
        self.assertTrue(task["final_result"]["todo_tasks"])

        candidates = self.services.report_store.list_learning_candidates(self.tenant_id)
        self.assertTrue(candidates)
        self.assertTrue(all(item["status"] == "candidate" for item in candidates))
        self.assertEqual(
            {item["candidate_type"] for item in candidates},
            {"analysis_method", "behavior_habit", "todo"},
        )
        assets = self.services.data_asset_store.list_bundle(self.tenant_id)
        self.assertFalse(
            [item for item in assets["analysis_experiences"] if item.get("sourceVersionId") == version["id"]]
        )
        todos = self.services.application_store.get_module(
            self.tenant_id, "agent_workspace", actor_user_id=self.user_id
        )["state"]["todos"]
        self.assertFalse([todo for todo in todos if todo.get("sourceVersionId") == version["id"]])

    def test_reanalysis_compresses_existing_method_frequency(self) -> None:
        version = self.services.report_store.save_weekly_report_version(
            self.tenant_id,
            _sample_weekly_version(),
            updated_by=self.user_id,
        )
        engine = WeeklyReportLearningEngine(
            self.services.report_store,
            self.services.data_asset_store,
            self.services.application_store,
        )

        first = engine.analyze_version(self.tenant_id, version["id"], self.user_id, force=True)
        second = engine.analyze_version(self.tenant_id, version["id"], self.user_id, force=True)

        self.assertEqual(first["status"], "已完成")
        self.assertEqual(second["status"], "已完成")
        candidates = self.services.report_store.list_learning_candidates(self.tenant_id)
        generated_methods = [item for item in candidates if item["candidate_type"] == "analysis_method"]
        self.assertEqual(len(generated_methods), 1)
        self.assertEqual(generated_methods[0]["status"], "candidate")

    def test_pending_scan_analyzes_unprocessed_versions(self) -> None:
        version = self.services.report_store.save_weekly_report_version(
            self.tenant_id,
            {**_sample_weekly_version(), "id": "weekly_report_pending_w27"},
            updated_by=self.user_id,
        )
        engine = WeeklyReportLearningEngine(
            self.services.report_store,
            self.services.data_asset_store,
            self.services.application_store,
        )

        self.assertIsNone(self.services.report_store.get_weekly_ai_task(self.tenant_id, version["id"]))
        tasks = engine.analyze_pending_versions(self.tenant_id, self.user_id)

        self.assertEqual(len(tasks), 1)
        self.assertEqual(tasks[0]["status"], "已完成")
        self.assertIsNotNone(self.services.report_store.get_weekly_ai_task(self.tenant_id, version["id"]))


def _sample_weekly_version() -> dict:
    return {
        "id": "weekly_report_2026_w27",
        "name": "上海分行经营周报：2026-06-29 ~ 2026-07-03",
        "savedAt": "2026/07/07 20:30",
        "tenantId": "tenant_demo",
        "reportId": "shanghai",
        "comments": [
            {
                "id": "comment_1",
                "targetId": "shanghai_next_text",
                "targetLabel": "下一步计划",
                "text": "请下周补充客户经理跟进结果。",
            }
        ],
        "report": {
            "id": "shanghai",
            "institutionName": "上海分行",
            "projectNo": "经营周报",
            "meetingTime": "7月3日 周五",
            "reporters": "陆凯亮",
            "period": "2026-06-29 ~ 2026-07-03",
            "status": "已编辑",
            "owner": "陆凯亮",
            "sections": [
                {
                    "id": "shanghai_performance",
                    "name": "一、业绩与业务波动",
                    "blocks": [
                        {
                            "id": "shanghai_balance",
                            "type": "table",
                            "title": "余额达成情况",
                            "dataSource": "dw_finance.weekly_balance_progress",
                            "fields": ["项目", "周目标", "当前余额", "达成率", "本周净增", "时间进度"],
                            "rows": [
                                {
                                    "项目": "上海分行",
                                    "周目标": "18.00亿",
                                    "当前余额": "13.42亿",
                                    "达成率": "74.6%",
                                    "本周净增": "+0.82亿",
                                    "时间进度": "72.0%",
                                }
                            ],
                            "analysis": {
                                "status": "待确认",
                                "conclusion": "上海分行本周余额达成率为74.6%，整体略高于当前时间进度；建议将未动支名单按客户经理拆分，形成下周一复核清单。",
                            },
                        }
                    ],
                },
                {
                    "id": "shanghai_next",
                    "name": "四、下一步计划",
                    "blocks": [
                        {
                            "id": "shanghai_next_text",
                            "type": "text",
                            "title": "计划说明",
                            "content": "围绕余额缺口、重点客户、渠道转化三条线形成下周推进清单；周一补齐客户经理跟进结果，周三复核动支与风险变化。",
                        }
                    ],
                },
            ],
        },
    }
