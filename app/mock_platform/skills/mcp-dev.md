---
id: mcp-dev
name: MCP 开发 Skill
version: 1.0.0
description: 用于指导 MCP Server 和 MCP Client 开发
when_to_use:
  - 用户需要开发 MCP Server
  - 用户需要接入 MCP Client
  - 用户需要调试 MCP 工具调用
---

# MCP 开发 Skill

## 目标

帮助用户完成 MCP Server、MCP Client 和工具注册链路开发。

## 执行原则

1. 优先明确 MCP Server 暴露哪些工具。
2. 每个工具必须有明确的 name、description 和 input_schema。
3. 工具执行必须有超时控制。
4. 工具调用失败必须返回明确错误。
5. Agent 内部注册工具时需要加 serverName 前缀，避免重名。

## 输出要求

当用户要求设计 MCP 接入方案时，必须输出：

1. MCP 配置格式
2. MCP Server 启动方式
3. MCP Client 连接方式
4. tools/list 获取方式
5. tools/call 调用方式
6. 异常处理方式
