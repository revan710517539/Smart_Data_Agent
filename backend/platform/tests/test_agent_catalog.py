import unittest

from backend.platform.agents import AgentCatalog
from backend.platform.skills import SkillConfigCatalog


class AgentCatalogTest(unittest.TestCase):
    def test_loads_engineering_and_algorithm_groups(self) -> None:
        catalog = AgentCatalog.from_config_dir("configs/agent_groups")
        groups = {group.group_id: group for group in catalog.list_groups()}

        self.assertIn("engineering", groups)
        self.assertIn("algorithm_engineering", groups)
        self.assertEqual(groups["engineering"].controller_agent, "engineering_controller")
        self.assertEqual(groups["algorithm_engineering"].controller_agent, "algorithm_controller")
        self.assertGreaterEqual(len(groups["engineering"].agents), 14)
        self.assertGreaterEqual(len(groups["algorithm_engineering"].agents), 16)

    def test_agent_groups_include_required_governance_agents(self) -> None:
        catalog = AgentCatalog.from_config_dir("configs/agent_groups")
        engineering_agent_ids = {agent.agent_id for agent in catalog.get_group("engineering").agents}
        algorithm_agent_ids = {agent.agent_id for agent in catalog.get_group("algorithm_engineering").agents}

        self.assertIn("security_permission", engineering_agent_ids)
        self.assertIn("mcp_tool_engineering", engineering_agent_ids)
        self.assertIn("completion_check", engineering_agent_ids)
        self.assertIn("algorithm_risk_compliance", algorithm_agent_ids)
        self.assertIn("drift_monitoring", algorithm_agent_ids)
        self.assertIn("algorithm_review", algorithm_agent_ids)

    def test_agent_group_stage_gates_prevent_demo_delivery(self) -> None:
        catalog = AgentCatalog.from_config_dir("configs/agent_groups")
        engineering_gates = " ".join(catalog.get_group("engineering").stage_gates)
        algorithm_gates = " ".join(catalog.get_group("algorithm_engineering").stage_gates)

        self.assertIn("数据库", engineering_gates)
        self.assertIn("权限", engineering_gates)
        self.assertIn("测试", engineering_gates)
        self.assertIn("数据权限", algorithm_gates)
        self.assertIn("风控合规", algorithm_gates)

    def test_all_agent_allowed_skills_are_registered_in_skill_config(self) -> None:
        catalog = AgentCatalog.from_config_dir("configs/agent_groups")
        skill_catalog = SkillConfigCatalog.from_config_dir("configs/skills")
        missing = sorted(
            {
                skill_id
                for agent in catalog.list_agents()
                for skill_id in agent.allowed_skills
                if not skill_catalog.has(skill_id)
            }
        )

        self.assertEqual(missing, [])


if __name__ == "__main__":
    unittest.main()
