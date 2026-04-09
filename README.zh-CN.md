[English](./README.md) | [简体中文](./README.zh-CN.md)

# codex-session-transfer

`codex-session-transfer` 是 `codex-session-transfer` 这个 Codex 技能的公开 GitHub 仓库。

随着 AI 越来越深地集成进传统工作流，与 AI agent 的会话正在逐渐变成一种新型资产。它们沉淀了任务历史、运行上下文、调试路径、中间决策，以及可复用的过程性知识。从工程实践上看，这些会话历史正在演化成一种新的业务数据或操作数据。

问题在于，这类数据往往与创建它的本地主机环境深度绑定。会话 transcript、本地索引、SQLite 元数据、可写根目录、技能依赖以及项目路径，都会和某一台机器上的 Codex 状态纠缠在一起。因此，不同宿主机之间迁移会话资产时，往往会遇到很大的摩擦。

`codex-session-transfer` 正是为降低这种迁移摩擦而开发的。它会打包会话可移植所需的最小工作集，在目标端完成与机器相关路径的本地化，并保留足够的支撑状态，使导入后的会话能够在 Codex Desktop 中正常显示、打开，并继续工作。

这种能力在不少实际场景中都会越来越有价值，比如团队协作中跨机器交接 AI 辅助工作、个人对长期积累的 AI 历史会话进行整合、硬件升级或工作站更擢、需要可复现上下文的科研与工程流程，以及更广义上的上下文迁移场景。在这些场景里，真正有价值的往往不只是文件本身，还包括围绕文件产生的决策轨迹与工作历史。

## 它能做什么

- 为指定 Codex 会话打包第一阶段“最小可工作集”
- 把会话技能包安装到另一套 Codex Desktop 环境
- 按目标机器环境对工作目录路径进行本地化
- 记录事务日志和备份，以支持安全回滚
- 列出迁移事务，并在需要时执行回滚

## 技能名与仓库名

GitHub 仓库名与可安装的技能名统一为 `codex-session-transfer`，这个名字定义在 [SKILL.md](./SKILL.md) 中。安装到 Codex 时，目标目录应为：

```text
~/.codex/skills/codex-session-transfer/
```

## 仓库结构

```text
codex-session-transfer/
  SKILL.md
  agents/
    openai.yaml
  references/
    package-format.md
  scripts/
    install_session_skill_package.py
  README.md
  README.zh-CN.md
  PUBLISHING.md
  LICENSE
  .gitignore
```

## 主要工作流

这个技能围绕同一条迁移生命周期提供四个动作：

- `packup`
- `install`
- `list-transactions`
- `rollback`

核心实现位于 [scripts/install_session_skill_package.py](./scripts/install_session_skill_package.py)。

## 当前范围

当前仓库聚焦第一阶段的“最小可工作集”：

- rollout `jsonl` 文件
- `threads`
- `session_index`
- `thread_dynamic_tools`
- 用户自定义技能
- 所需的空目录骨架

暂时还不迁移：

- `logs_1.sqlite`
- `state_5.sqlite.logs`
- `state_5.sqlite.stage1_outputs`
- `.codex-global-state.json`

## 许可证

本仓库采用 [MIT License](./LICENSE)。
