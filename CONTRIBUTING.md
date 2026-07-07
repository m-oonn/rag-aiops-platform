# 贡献指南

感谢你对本项目的关注!无论是报告问题、提出建议还是提交代码,都非常欢迎。

## 报告问题(Issue)

在提交 Issue 前:

1. 先搜索 [现有 Issue](../../issues),避免重复。
2. 使用对应的 Issue 模板(Bug 报告 / 功能请求)。
3. 提供尽量完整的信息:复现步骤、期望行为、实际行为、运行环境。

## 提交代码(Pull Request)

1. **Fork** 本仓库并从 `main` 拉出你的特性分支:

   ```bash
   git checkout -b feature/your-feature-name
   ```

2. 完成修改,并确保测试通过:

   ```bash
   # 后端测试
   pytest

   # 前端测试
   cd frontend && npm test
   ```

3. 遵循项目的提交信息规范(见下)。

4. 推送分支并发起 Pull Request,填写 PR 模板。

## 提交信息规范

采用 [Conventional Commits](https://www.conventionalcommits.org/) 风格:

```
<类型>(<可选范围>): <简短描述>
```

常用类型:

| 类型       | 说明                       |
| ---------- | -------------------------- |
| `feat`     | 新功能                     |
| `fix`      | 修复 bug                   |
| `docs`     | 文档变更                   |
| `refactor` | 重构(非新功能非修 bug)  |
| `test`     | 测试相关                   |
| `chore`    | 构建 / 工具 / 依赖等杂项   |

示例:

```
feat(chat): 支持前端手动切换模型
fix(retrieval): 修复混合检索温度参数丢弃
```

## 代码风格

- **Python**: 遵循 PEP 8,函数保持短小、单一职责。
- **前端**: 遵循项目现有的 Vue 3 组合式 API 风格。
- 优先编写小而聚焦的文件,避免超大文件。
- 处理错误要显式,不要静默吞掉异常。

## 行为准则

请保持友善、尊重与建设性。我们希望这里是一个欢迎所有人的社区。
