---
description: 将当前分析或配置结果同步到 Universal Bridge 精确匹配的后台系统
---

遵循 `smart-data-agent-report` Skill：先通过 `systems` 精确识别用户所说的后台系统，再按四模块契约读取、分析同步、配置动作和学习回收。不得使用第一项或默认系统；成功读取或配置后必须以相同 operation ID 回传有界证据。不要读取或上传完整对话、原始文件、凭据、未使用材料或原始数据行。
