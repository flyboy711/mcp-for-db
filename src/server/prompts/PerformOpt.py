from typing import Dict, Any

from mcp.types import TextContent, Prompt, PromptArgument, GetPromptResult, PromptMessage
from server.prompts.BasePrompt import BasePrompt


class PerformanceOptimizationPrompt(BasePrompt):
    name = "performance-optimization-prompt"
    description = (
        "这是用于数据库性能优化与自动化功能的提示词"
    )

    def get_prompt(self) -> Prompt:
        return Prompt(
            name=self.name,
            description=self.description,
            arguments=[
                PromptArgument(
                    name="task",
                    description="请输入需要执行的任务，如慢查询分析、索引优化、性能压测等"
                )
            ],
        )

    async def run_prompt(self, arguments: Dict[str, Any]) -> GetPromptResult:
        task = arguments.get("task", "")

        prompt = f"""
        - Role: 数据库性能优化专家和自动化工程师
        - Background: 用户需要对 MySQL 数据库进行性能优化与自动化，包括慢查询治理、智能索引管理等功能。
        - Profile: 你是一位资深的数据库性能优化专家，熟悉 MySQL 数据库的性能调优机制和操作流程，能够运用专业的工具和方法进行数据库性能优化。
        - Skills: 你具备慢查询分析、索引优化、性能压测等关键能力，能够根据用户需求实现数据库性能优化与自动化功能。
        - Goals: 根据用户输入的任务，实现数据库性能优化与自动化功能，提升数据库的性能和稳定性。
        - Constrains: 在实现功能的过程中，应遵循最小干预原则，避免对现有数据造成不必要的影响，确保解决方案的可操作性和安全性。
        - OutputFormat: 以问题分析报告的形式输出，包括任务描述、实现步骤和注意事项。
        - Workflow:
          1. 解析用户输入的任务，确定需要实现的功能。
          2. 根据功能需求，调用相应的工具和方法进行实现。
          3. 测试验证功能的正确性和稳定性。
        - Initialization: 在第一次对话中，请直接输出以下：您好，作为数据库性能优化专家，我将协助您实现数据库性能优化与自动化功能。请详细描述您需要执行的任务，以便我更好地进行处理。
        - Task: {task}
        """

        return GetPromptResult(
            description="performance optimization prompt",
            messages=[
                PromptMessage(
                    role="user",
                    content=TextContent(type="text", text=prompt),
                )
            ],
        )
