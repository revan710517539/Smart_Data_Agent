from __future__ import annotations

from typing import Any


def _field(
    name: str,
    label: str,
    data_type: str,
    explanation: str,
    *,
    metric: str = "",
    logic: str = "",
) -> dict[str, Any]:
    return {
        "fieldNameEn": name,
        "fieldNameCn": label,
        "type": data_type,
        "explanation": explanation,
        "isMetric": bool(metric),
        "metricCode": metric,
        "metricLogic": logic,
        "exampleUsage": "智能分析、指标核对、可视化报告",
    }


COMMON_ORG_FIELDS = [
    _field("institution_id", "机构ID", "string", "机构主键，关联客户和贷款订单。"),
    _field("institution_name", "机构名称", "string", "客户或订单归属的具体分支机构名称。"),
    _field("branch_name", "分行名称", "string", "统一汇总到一级分行的机构维度。"),
]

INSTITUTION_FIELDS = [
    _field("tenant_id", "租户ID", "string", "租户隔离字段；模板值星号在查询时替换为当前租户。"),
    _field("institution_id", "机构ID", "string", "机构唯一主键。"),
    _field("institution_code", "机构编码", "string", "机构业务编码。"),
    _field("institution_name", "机构名称", "string", "分行或支行名称。"),
    _field("institution_level", "机构层级", "string", "分行或支行层级。"),
    _field("parent_institution_id", "上级机构ID", "string", "支行指向所属分行的自关联外键。"),
    _field("branch_name", "分行名称", "string", "机构统一归属的一级分行。"),
    _field("province", "省份", "string", "机构所在省级行政区。"),
    _field("city", "城市", "string", "机构所在城市。"),
    _field("institution_type", "机构类型", "string", "一级分行、综合支行或小微专营支行。"),
    _field("opening_date", "开业日期", "date", "机构开业日期。"),
    _field("employee_count", "员工人数", "integer", "机构员工数量。", metric="employee_count", logic="sum(employee_count)"),
    _field("customer_manager_count", "客户经理人数", "integer", "机构客户经理数量。", metric="customer_manager_count", logic="sum(customer_manager_count)"),
    _field("target_application_count", "目标进件笔数", "integer", "机构考核期目标进件笔数。"),
    _field("target_credit_amount", "授信目标金额", "decimal", "机构考核期授信目标金额，单位元。", metric="target_credit_amount", logic="sum(target_credit_amount)"),
    _field("target_drawdown_amount", "动支目标金额", "decimal", "机构考核期动支目标金额，单位元。", metric="target_drawdown_amount", logic="sum(target_drawdown_amount)"),
    _field("status", "机构状态", "string", "机构是否正常经营。"),
]

CUSTOMER_FIELDS = [
    _field("tenant_id", "租户ID", "string", "租户隔离字段。"),
    _field("customer_id", "客户ID", "string", "客户唯一主键。"),
    _field("customer_name", "客户名称", "string", "仅用于演示的合成客户名称。"),
    _field("gender", "性别", "string", "客户性别。"),
    _field("age", "年龄", "integer", "客户周岁年龄。"),
    _field("province", "省份", "string", "客户归属机构所在省份。"),
    _field("city", "城市", "string", "客户归属机构所在城市。"),
    _field("customer_segment", "客户客群", "string", "小微商户、存量经营户、年轻白领、代发客群或新市民。"),
    _field("industry", "行业", "string", "客户所属行业。"),
    *COMMON_ORG_FIELDS,
    _field("customer_manager_id", "客户经理ID", "string", "服务客户的客户经理编号。"),
    _field("customer_manager_name", "客户经理名称", "string", "服务客户的合成客户经理名称。"),
    _field("registration_date", "注册日期", "date", "客户首次注册日期。"),
    _field("annual_income", "年收入", "decimal", "个人口径年收入，单位元。"),
    _field("annual_revenue", "年营业收入", "decimal", "经营口径年营业收入，单位元。"),
    _field("credit_score", "信用评分", "integer", "模拟信用评分，范围 560 至 809。", metric="average_credit_score", logic="avg(credit_score)"),
    _field("risk_level", "风险等级", "string", "由信用评分映射的低、中、高风险等级。"),
    _field("is_active", "活跃客户标记", "integer", "活跃为1，否则为0。", metric="active_customer_count", logic="sum(is_active)"),
    _field("has_credit", "授信成功标记", "integer", "存在授信成功订单为1。", metric="credit_customer_count", logic="sum(has_credit)"),
    _field("has_drawdown", "动支成功标记", "integer", "存在动支成功订单为1。", metric="drawdown_customer_count", logic="sum(has_drawdown)"),
    _field("current_loan_balance", "当前贷款余额", "decimal", "客户成功动支后尚未归还的本金余额。", metric="customer_loan_balance", logic="sum(current_loan_balance)"),
]

ORDER_FIELDS = [
    _field("tenant_id", "租户ID", "string", "租户隔离字段。"),
    _field("order_id", "贷款订单ID", "string", "贷款申请订单唯一主键。"),
    _field("customer_id", "客户ID", "string", "关联客户主数据的外键。"),
    *COMMON_ORG_FIELDS,
    _field("product_line", "产品线", "string", "经营贷、消费贷或综合授信。"),
    _field("channel", "渠道", "string", "客户经理、手机银行、联合运营或线上渠道。"),
    _field("customer_segment", "客户客群", "string", "订单申请人所属客群。"),
    _field("application_date", "申请日期", "date", "贷款申请发起日期。"),
    _field("completion_date", "完件日期", "date", "资料完整并提交审批的日期。"),
    _field("decision_date", "审批决策日期", "date", "授信通过或拒绝的决策日期；审批中为空。"),
    _field("credit_approved_date", "授信成功日期", "date", "最终获得额度建档成功日期。"),
    _field("drawdown_application_date", "动支申请日期", "date", "客户提交动支申请的日期。"),
    _field("drawdown_date", "动支成功日期", "date", "借款成功并放款的日期。"),
    _field("month", "申请月份", "string", "申请日期对应的自然月。"),
    _field("current_stage", "当前阶段", "string", "完件、授信或动支阶段。"),
    _field("application_status", "订单状态", "string", "审批中、授信拒绝、授信成功待动支、动支处理中或动支成功。"),
    _field("application_amount", "申请金额", "decimal", "客户申请授信金额，单位元。"),
    _field("approved_amount", "授信金额", "decimal", "授信通过总金额，且不大于申请金额。", metric="approved_amount", logic="sum(approved_amount)"),
    _field("drawdown_apply_amount", "动支申请金额", "decimal", "客户申请动支金额，且不大于授信金额。"),
    _field("drawdown_amount", "动支成功金额", "decimal", "实际放款成功金额，且不大于授信金额。", metric="drawdown_amount", logic="sum(drawdown_amount)"),
    _field("loan_balance", "贷款余额", "decimal", "在贷本金余额，且不大于动支成功金额。", metric="loan_balance", logic="sum(loan_balance)"),
    _field("m1_overdue_balance", "M1逾期余额", "decimal", "逾期30至59天的在贷本金余额，且不大于贷款余额。"),
    _field("overdue_days", "逾期天数", "integer", "当前逾期天数，未逾期为0。"),
    _field("annual_interest_rate", "年利率", "decimal", "订单执行年利率。"),
    _field("term_months", "期限月数", "integer", "贷款合同期限月数。"),
    _field("application_order_count", "进件笔数分子", "integer", "每条申请订单记1。", metric="application_order_count", logic="sum(application_order_count)"),
    _field("completion_order_count", "完件笔数分子", "integer", "已提交审批的订单记1。", metric="completion_order_count", logic="sum(completion_order_count)"),
    _field("completed_customer_count", "完件人数分母", "integer", "一客一单模拟下完件客户记1，用于授信通过率。"),
    _field("credit_approved_order_count", "授信成功笔数分子", "integer", "最终获得额度的订单记1。", metric="credit_approved_order_count", logic="sum(credit_approved_order_count)"),
    _field("credit_approved_customer_count", "授信成功人数", "integer", "授信成功客户记1，是动支率分母。"),
    _field("drawdown_application_order_count", "动支申请笔数分子", "integer", "提交动支申请的订单记1。", metric="drawdown_application_order_count", logic="sum(drawdown_application_order_count)"),
    _field("drawdown_success_order_count", "动支成功笔数分子", "integer", "实际放款成功订单记1。", metric="drawdown_success_order_count", logic="sum(drawdown_success_order_count)"),
    _field("drawdown_success_customer_count", "动支成功人数分子", "integer", "动支成功客户记1，是动支率分子。"),
    _field("credit_rate_weighted_amount", "授信利率加权分子", "decimal", "单笔授信金额乘年利率，用于授信加权利率。"),
    _field("drawdown_rate_weighted_amount", "动支利率加权分子", "decimal", "单笔动支金额乘年利率，用于动支加权利率。"),
]


def _raw_table(
    item_id: str,
    code: str,
    name: str,
    csv_path: str,
    primary_key: str,
    date_field: str,
    org_field: str,
    customer_field: str,
    description: str,
    fields: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "id": item_id, "tableNameEn": code, "tableNameCn": name, "source": f"Origin_Data/mock/{csv_path}",
        "tableType": "mock_csv", "primaryKey": primary_key, "dateField": date_field, "orgField": org_field,
        "customerField": customer_field, "description": description, "updateFrequency": "确定性生成",
        "restrictions": "仅限本地演示；查询必须绑定 tenant_id。",
        "exampleSql": f"select * from {code} where tenant_id = :tenant_id limit 100",
        "fields": fields, "updatedAt": "2026-07-11", "rowCount": 100, "qualityReport": "Origin_Data/mock/mock_data_quality_report.json",
    }


MOCK_RAW_TABLES = [
    _raw_table("raw_mock_institution_100", "mock_institution_master", "模拟机构主数据（100条）", "institution_master_100.csv", "institution_id", "opening_date", "institution_id", "", "包含10家分行和90家支行的机构层级、人员和经营目标。", INSTITUTION_FIELDS),
    _raw_table("raw_mock_customer_100", "mock_customer_master", "模拟客户主数据（100条）", "customer_master_100.csv", "customer_id", "registration_date", "institution_id", "customer_id", "与机构和贷款订单主外键一致的客户画像、风险与余额数据。", CUSTOMER_FIELDS),
    _raw_table("raw_mock_loan_order_100", "mock_loan_transaction_order", "模拟贷款交易订单（100条）", "loan_transaction_order_100.csv", "order_id", "application_date", "institution_id", "customer_id", "覆盖完件、授信、动支、余额和M1逾期的贷款漏斗订单。", ORDER_FIELDS),
]


def _topic(
    item_id: str,
    name: str,
    dataset_id: str,
    source_table: str,
    csv_path: str,
    description: str,
    fields: list[dict[str, Any]],
    metric_codes: list[str],
    default_metrics: list[str],
    dimensions: list[str],
    default_dimensions: list[str],
) -> dict[str, Any]:
    return {
        "id": item_id, "name": name, "code": dataset_id, "datasetId": dataset_id, "description": description,
        "csvPath": f"Origin_Data/mock/{csv_path}",
        "sql": f"select * from {source_table} where tenant_id = :tenant_id",
        "fields": fields, "fieldExplanations": "字段级中文名、类型、口径、分子分母和示例用途均已登记。",
        "metricCodes": metric_codes, "defaultMetrics": default_metrics, "dimensionCodes": dimensions,
        "defaultDimensions": default_dimensions, "chartTypes": ["column", "line", "table"],
        "analysisAngles": ["先核对总体分子分母", "再按机构、客群、产品和月份交叉拆解", "最后检查金额、余额和风险约束"],
        "applicableScene": "智能分析、漏斗分析、机构经营、客户画像、可视化报告",
        "relatedIntent": "模拟数据严谨分析", "relatedExperience": "exp_weekly_growth_quality",
        "quickDisplay": True, "reportReference": "模拟数据端到端验证", "source": "mock_csv",
        "updatedAt": "2026-07-11", "rowCount": 100, "qualityReport": "Origin_Data/mock/mock_data_quality_report.json",
    }


MOCK_TOPIC_TABLES = [
    _topic(
        "topic_mock_institution_operation", "模拟机构经营主题表（100条）", "institution_operation_mock_mart",
        "mock_institution_master", "institution_master_100.csv", "按机构层级、区域和类型分析人员配置及授信、动支目标。", INSTITUTION_FIELDS,
        ["institution_count", "employee_count", "customer_manager_count", "target_credit_amount", "target_drawdown_amount"],
        ["institution_count", "target_credit_amount", "target_drawdown_amount"],
        ["branch_name", "institution_name", "institution_level", "province", "city", "institution_type", "status"],
        ["branch_name", "institution_level"],
    ),
    _topic(
        "topic_mock_customer_profile", "模拟客户画像主题表（100条）", "customer_profile_mock_mart",
        "mock_customer_master", "customer_master_100.csv", "按机构、客群、行业和风险等级分析客户规模、授信、动支与余额。", CUSTOMER_FIELDS,
        ["customer_count", "active_customer_count", "credit_customer_count", "drawdown_customer_count", "customer_loan_balance", "average_credit_score"],
        ["customer_count", "credit_customer_count", "drawdown_customer_count"],
        ["branch_name", "institution_name", "province", "city", "customer_segment", "industry", "risk_level", "gender"],
        ["customer_segment", "branch_name"],
    ),
    _topic(
        "topic_mock_loan_funnel", "模拟贷款申请授信动支主题表（100条）", "loan_funnel_mock_mart",
        "mock_loan_transaction_order", "loan_transaction_order_100.csv", "严格按指标字典口径分析完件、授信、动支、金额、余额和M1风险。", ORDER_FIELDS,
        ["application_order_count", "completion_order_count", "credit_approved_order_count", "drawdown_application_order_count", "drawdown_success_order_count", "credit_approval_rate", "drawdown_rate", "approved_amount", "drawdown_amount", "loan_balance", "m1_overdue_rate", "credit_weighted_rate", "drawdown_weighted_rate"],
        ["completion_order_count", "credit_approval_rate", "drawdown_rate", "approved_amount", "drawdown_amount"],
        ["branch_name", "institution_name", "product_line", "month", "channel", "customer_segment", "current_stage", "application_status"],
        ["branch_name", "product_line"],
    ),
]
