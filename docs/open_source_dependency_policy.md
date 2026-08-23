# 开源依赖许可证策略

Smart Data Agent 当前是内部私有项目，仓库未声明对外分发许可证；这不等于项目使用了
商业许可证。项目所有第三方依赖必须通过
`uv run python scripts/check_open_source_licenses.py --write-sbom` 审计。

门禁拒绝商业闭源、Proprietary、BUSL、SSPL、Elastic License、PolyForm、Commons
Clause 和仓库内企业版源码目录；每个前端锁定依赖和 Python 直接运行依赖都必须声明并
匹配经评审的开源许可证。当前允许的 LGPL/MPL 属于开源许可证，不是收费商业组件；
若后续决定采用“仅 MIT/Apache/BSD”策略，必须先替换对应依赖并完成回归，不能直接
删除而破坏现有数据连接、安全证书或前端构建能力。

项目自身如需对外分发，必须由项目所有者和法务明确选择许可证后再新增 `LICENSE`；
开发人员和 Agent 不得自行把内部代码改成 MIT、Apache 或其他对外授权。
