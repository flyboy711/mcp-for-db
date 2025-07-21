from typing import Dict, Any

from mcp.types import TextContent, Prompt, PromptArgument, GetPromptResult, PromptMessage
from server.prompts.BasePrompt import BasePrompt

class EnhancedSecurityPrompt(BasePrompt):
    name = "enhanced-security-prompt"
    description = (
        "这是用于数据库安全与管理增强功能的提示词"
    )

    def get_prompt(self) -> Prompt:
        return Prompt(
            name=self.name,
            description=self.description,
            arguments=[
                PromptArgument(
                    name="task", description="请输入需要执行的任务，如字段级权限管理、动态权限审批、敏感数据脱敏、操作审计等"
                )
            ],
        )

    async def run_prompt(self, arguments: Dict[str, Any]) -> GetPromptResult:
        task = arguments.get("task", "")

        logger.info(f"当前执行任务是：{task}")

        prompt = f"""
        - Role: 数据库安全专家和运维工程师
        - Background: 用户需要对 MySQL 数据库进行安全与管理增强，包括细粒度权限控制、操作审计与追溯等功能。
        - Profile: 你是一位资深的数据库安全专家，熟悉 MySQL 数据库的安全机制和操作流程，能够运用专业的工具和方法进行数据库安全管理。
        - Skills: 你具备数据库权限管理、操作审计、数据脱敏等关键能力，能够根据用户需求实现数据库安全与管理增强功能。
        - Goals: 根据用户输入的任务，实现数据库安全与管理增强功能，确保数据库的安全性和稳定性。
        - Constrains: 在实现功能的过程中，应遵循最小干预原则，避免对现有数据造成不必要的影响，确保解决方案的可操作性和安全性。
        - OutputFormat: 以问题分析报告的形式输出，包括任务描述、实现步骤和注意事项。
        - Workflow:
          1. 解析用户输入的任务，确定需要实现的功能。
          2. 根据功能需求，调用相应的工具和方法进行实现。
          3. 测试验证功能的正确性和稳定性。
        - Initialization: 在第一次对话中，请直接输出以下：您好，作为数据库安全专家，我将协助您实现数据库安全与管理增强功能。请详细描述您需要执行的任务，以便我更好地进行处理。
        - Task: {task}
        """

        logger.info(f"当前提示词内容：{prompt}")

        return GetPromptResult(
            description="enhanced security prompt",
            messages=[
                PromptMessage(
                    role="user",
                    content=TextContent(type="text", text=prompt),
                )
            ],
        )
