# WorkBuddy Universal Bridge 兼容入口

此文件只保留旧链接兼容，不再包含源码目录或本地开发端点。请按接收者操作系统使用：

- macOS：`docs/integrations/workbuddy-smart-data-agent-install-macos.md`
- Windows：`docs/integrations/workbuddy-smart-data-agent-install-windows.md`

终端用户安装必须从其组织真实 SDA HTTPS 服务的公开分发接口取得固定白名单包并校验 SHA-256：

- `/api/integrations/bridge/distribution/manifest`
- `/api/integrations/bridge/distribution/package`
- `/api/integrations/bridge/distribution/package.sha256`

不要让终端用户克隆 SDA 仓库、使用维护者绝对路径、连接 `127.0.0.1`，或从聊天/网盘运行未经校验的脚本。正式服务尚未放行上述接口时应停止并由 SDA 管理员完成网关与部署验收，不能用本地开发地址替代。
