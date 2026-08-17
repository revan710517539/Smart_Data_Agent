# Smart Data Agent 商业许可证门禁

SDA 默认自主实现 Data Formulator、DB-GPT、WrenAI、Lightdash、SuperSonic、JimuReport、Vanna 和 SQLCoder 的产品能力，不复制其页面、源码、模型权重或素材。

- 允许 MIT、Apache-2.0、BSD、ISC、MPL-2.0、0BSD、BlueOak 和明确可商业使用且履行署名要求的 CC-BY-4.0 依赖。
- 禁止 AGPL、GPL、SSPL、BUSL、Commons Clause、Elastic License、PolyForm、附加商业限制及许可证不明的依赖进入运行代码。
- 禁止引入 Lightdash EE、JimuReport、SuperSonic 源码和 SQLCoder CC BY-SA 模型权重；Apache/MIT 子目录也必须保留来源提交、NOTICE 和局部审查证据后才能引用。
- `python3 scripts/check_commercial_licenses.py --write-sbom` 是提交与发布质量门，未知许可证、未复核 Python 直接依赖或受限源码路径会失败关闭。

生成的 `artifacts/sbom/smart-data-agent.cdx.json` 是交付证据，不代表对依赖作者许可证声明的替代。新增依赖时必须先更新复核清单及归属材料，再更新锁文件。
