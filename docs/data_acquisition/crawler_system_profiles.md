# 多系统爬虫 Profile 管理规范

## 目标

爬虫引擎只管理浏览器生命周期、登录会话、安全策略、执行诊断和统一结果；每个外部系统单独管理自己的页面/API 契约、筛选遍历和行映射。新增或升级某个系统时，不修改 Playwright 传输层，也不影响其他系统。

## 目录与依赖方向

```text
backend/platform/crawler_engine/
├── engine.py                    # 统一执行入口和 Profile 查询
├── playwright_transport.py      # 通用浏览器 DSL，不依赖任何具体系统
├── profile_registry.py          # Profile 契约、注册、查询和分发
└── systems/
    ├── __init__.py              # 唯一内置 Profile 组装入口
    └── qifu_focuspro_sios/      # 企福系统独立维护单元
        ├── profile.py           # 系统身份、版本、能力和适配器
        └── collector.py         # API、筛选遍历、重试和 CSV 行映射
```

依赖只允许沿以下方向流动：

```text
CrawlerEngine → Transport → CrawlerProfileRegistry → System Profile → System Collector
```

系统包之间禁止相互 import。传输层禁止 import 任一 `systems/<system_id>` 包；所有内置系统仅在 `systems/__init__.py` 注册一次。

## 统一契约

每个 Profile 必须提供：

- 全局稳定的 `profile_id`，格式建议为 `<system_id>.<capability>.v<version>`；
- 独立的 `system_id`、显示名、版本、维护模块和支持的操作类型；
- `collect(context)`，返回 `CrawlerProfileCollection`；
- 扁平化数据行和非敏感元数据，不返回 Cookie、Token、密码或请求头。

浏览器脚本通过统一动作分发：

```json
{
  "action": "collect_system",
  "profile_id": "qifu_focuspro_sios.funnel_analysis.v1",
  "traversal_mode": "cartesian",
  "max_combinations": 2000,
  "timeout_ms": 900000
}
```

执行结果会自动补充 `metadata.crawler_profile`，包含系统、Profile、版本和维护模块信息，便于统一展示、审计和问题归属。可通过 `CrawlerEngine.list_crawler_profiles()` 查询已注册能力，也可按 `system_id` 过滤。

## 新增一个系统

1. 新建 `systems/<system_id>/`，将该系统的选择器、接口路径、筛选规则、重试策略和数据映射全部放在本目录。
2. 在 `profile.py` 声明 `CrawlerProfileDescriptor` 并实现 `collect()`。
3. 在 `systems/__init__.py` 的 `built_in_crawler_profiles()` 中注册；如需兼容旧动作，可在注册时声明 alias。
4. 业务脚本只使用 `collect_system + profile_id`，不得为新系统向 `PlaywrightCrawlerTransport._run_step()` 增加专用 action 分支。
5. 至少测试 Profile 注册冲突、操作类型门禁、系统采集结果、筛选边界、脱敏和错误分类。

## 版本和会话隔离

- 接口或输出契约不兼容时新增 `.v2` Profile，旧版本可并行保留到作业迁移完成。
- 数据接入中的每条连接只注册一个机构下的一个目标 URL；同一机构可注册多个 URL，每个 URL 都是独立的爬虫实例。
- 引擎基于规范化 URL 生成稳定 `crawlerKey`，登录状态默认按租户和 URL 隔离到 `.crawler-sessions/<tenant>/<crawler_key>.json`，权限固定为 `0600`，禁止提交仓库。
- 凭证由数据连接配置注入浏览器层，系统采集器只在已认证页面上下文内发起请求。
- 验证码、短信和 MFA 只允许人工完成并保存会话，不在 Profile 中实现绕过逻辑。

## URL 爬虫类型

数据接入明确区分两种页面爬虫，二者统一登记、独立执行：

- `page`：页面数据爬虫。进入目标页面后遍历页面筛选条件，优先复用已认证页面发出的接口请求，输出结构化行或 CSV。智运页面和企福漏斗属于此类型。
- `sql`：SQL 页面爬虫。进入 SQL 编辑页面，先校验单条只读 `SELECT/WITH`，再执行查询并采集结果；表、字段等元数据也通过页面交互采集，不直接绕过页面访问底层数据库。

数据连接保存 `crawlerMode`、`crawlerKey` 和可选 `crawlerProfileId`。已知企福漏斗 URL 会自动绑定 `qifu_focuspro_sios.funnel_analysis.v1`；其他系统仍由各自 Profile 管理选择器、接口契约、筛选遍历和结果映射。

连接测试与正式采集使用同一 URL 身份和会话边界。首次遇到验证码、短信或 MFA 时，操作员在可见浏览器中完成验证；验证后的会话按租户和 URL 复用，失效后重新人工验证。该机制解决持续自动采集问题，但不尝试识别、破解或规避验证码。

## 当前兼容策略

旧动作 `collect_funnel_analysis` 被注册为企福漏斗 Profile 的兼容别名，现有已发布脚本仍可运行；新脚本统一使用 `collect_system`。根目录的 `funnel_collector.py` 仅保留 import 兼容层，实际实现已经归入企福系统目录。
