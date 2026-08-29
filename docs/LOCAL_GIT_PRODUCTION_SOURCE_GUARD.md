# 本地代码与 Gitea 生产源码保护及融合操作指南

## 目的

本指南用于完成两件事：

1. 在 Mac 本地安装 Git 上传保护钩子；
2. 将 Gitea 最新 `main` 与现有本地开发内容安全融合。

当前受保护生产源码基线：

```text
2c423c0d8ca505d503c7fb6286d7f54357c9b22b
```

最近一次实际生产修复提交：

```text
2138fd0df1534d76fadb51a63909b03c1c0c0e01
```

首批保护文件：

```text
backend/platform/bootstrap.py
backend/platform/metrics/postgresql_store.py
backend/platform/tests/test_bootstrap_metric_seed.py
```

保护不是永久禁止修改。修改这些文件并上传时，系统会提示选择：

- **保留 Git 版本**：阻止上传；你先把受保护文件恢复成 Git/远端版本，再重新融合；
- **保留本地版本**：明确批准本地修改覆盖这些文件，然后继续上传。

> 注意：Git hook 只对已经安装它的本地仓库生效。首次拉取最新代码后必须执行安装命令。不要使用 `git push --no-verify` 绕过保护。

---

## 第一部分：安装本地上传保护

在 Mac 的项目目录中执行：

```bash
git fetch origin
git switch main
git pull --ff-only origin main
sh scripts/install-production-source-guard.sh
```

验证安装：

```bash
git config --get core.hooksPath
```

应输出：

```text
.githooks
```

再验证基线文件：

```bash
python3 scripts/production_source_guard.py check \
  --remote-ref 2c423c0d8ca505d503c7fb6286d7f54357c9b22b \
  --local-ref HEAD \
  --non-interactive
```

未修改保护文件时应输出：

```text
PRODUCTION_SOURCE_GUARD_OK protected files unchanged
```

---

## 第二部分：先保存现有本地开发内容

不要直接拉取并覆盖有未提交修改的目录。先检查：

```bash
git status
```

如果存在本地修改，建立备份分支并提交：

```bash
git switch -c backup/local-before-production-sync-20260829
git add -A
git commit -m "backup: preserve local work before production baseline sync"
```

记录备份提交：

```bash
git rev-parse HEAD
```

将输出的 SHA 保存下来，以下以 `<LOCAL_BACKUP_SHA>` 表示。

如果本地修改不适合形成正式提交，也必须先复制整个项目目录到独立备份位置；但推荐形成 Git 提交，因为更容易审计和恢复。

---

## 第三部分：同步 Gitea 最新 main

```bash
git fetch origin
git switch main
git pull --ff-only origin main
git rev-parse HEAD
```

同步时，`HEAD` 应等于 Gitea 当前最新 `main`。首次执行本指南时至少应包含：

```text
2c423c0d8ca505d503c7fb6286d7f54357c9b22b
```

验证当前分支继承生产基线：

```bash
git merge-base --is-ancestor \
  2c423c0d8ca505d503c7fb6286d7f54357c9b22b HEAD
echo $?
```

必须输出：

```text
0
```

然后安装保护钩子：

```bash
sh scripts/install-production-source-guard.sh
```

---

## 第四部分：融合本地开发内容

从最新 `main` 创建整合分支：

```bash
git switch -c integration/local-development-20260829
```

推荐按提交叠加本地开发内容：

```bash
git cherry-pick <LOCAL_BACKUP_SHA>
```

如果本地开发分成多个提交，应按开发顺序逐个 `cherry-pick`。

### 出现 Git 冲突时

先查看冲突：

```bash
git status
git diff --name-only --diff-filter=U
```

如果冲突文件属于首批保护文件，不要批量使用 `--ours` 或 `--theirs`。逐个检查：

```bash
git diff -- backend/platform/bootstrap.py
git diff -- backend/platform/metrics/postgresql_store.py
git diff -- backend/platform/tests/test_bootstrap_metric_seed.py
```

处理完成后：

```bash
git add <已处理文件>
git cherry-pick --continue
```

---

## 第五部分：上传时的选择

正常上传整合分支：

```bash
git push -u origin integration/local-development-20260829
```

如果没有影响保护文件，上传直接继续。

如果影响保护文件，会看到文件清单和以下选择：

```text
1) 保留 Git/生产基线版本
2) 保留本地版本
```

### 选择 1：保留 Git 版本

上传会被阻止。按提示恢复受保护文件，例如：

```bash
git restore --source origin/main -- \
  backend/platform/bootstrap.py \
  backend/platform/metrics/postgresql_store.py \
  backend/platform/tests/test_bootstrap_metric_seed.py

git add -A
git commit -m "fix: preserve protected production source during local integration"
git push -u origin integration/local-development-20260829
```

这会保留其他本地开发改动，只恢复列出的受保护文件。

### 选择 2：保留本地版本

表示你明确批准当前本地版本修改这些生产保护文件，上传继续。但这不代表可以直接上线；合并和发布前仍必须执行相关专项回归和完整发布门禁。

---

## 第六部分：融合后核验

确认新版本仍继承生产基线：

```bash
git merge-base --is-ancestor \
  2c423c0d8ca505d503c7fb6286d7f54357c9b22b HEAD
echo $?
```

必须为 `0`。

查看整合版本对生产基线的修改：

```bash
git diff --stat \
  2c423c0d8ca505d503c7fb6286d7f54357c9b22b..HEAD

git diff \
  2c423c0d8ca505d503c7fb6286d7f54357c9b22b..HEAD -- \
  backend/platform/bootstrap.py \
  backend/platform/metrics/postgresql_store.py \
  backend/platform/tests/test_bootstrap_metric_seed.py
```

运行首批专项回归：

```bash
uv run python -m unittest \
  backend.platform.tests.test_bootstrap_metric_seed
```

准备合并或上线前，还必须运行项目规定的完整候选发布门禁；Git 上传成功不等于生产发布成功。

---

## 禁止操作

不要执行：

```bash
git push --force
git push -f
git push --no-verify
```

不要用旧项目目录整体覆盖同步后的目录，也不要对冲突文件批量执行：

```bash
git checkout --ours .
git checkout --theirs .
```

这些操作可能绕过逐文件判断或撤销生产修复。

---

## 日常开发标准流程

以后每次开发：

```bash
git fetch origin
git switch main
git pull --ff-only origin main
sh scripts/install-production-source-guard.sh
git switch -c feature/<功能名称>
```

开发完成后：

```bash
git add -A
git commit -m "feat: <修改说明>"
git push -u origin feature/<功能名称>
```

如涉及保护文件，上传时进行明确选择；随后通过 Pull Request、测试和发布门禁进入生产。
