import logging
from typing import Dict, Any
from server.utils.logger import configure_logger, get_logger
from mcp.types import TextContent, Prompt, PromptArgument, GetPromptResult, PromptMessage
from server.prompts.BasePrompt import BasePrompt

logger = get_logger(__name__)
configure_logger(log_level=logging.INFO, log_filename="prompts.log")


class DevelopmentEfficiencyPrompt(BasePrompt):
    name = "development-efficiency-prompt"
    description = (
        "这是用于数据库开发提效工具的提示词"
    )

    def get_prompt(self) -> Prompt:
        return Prompt(
            name=self.name,
            description=self.description,
            arguments=[
                PromptArgument(
                    name="task",
                    description="请输入需要执行的任务，如元数据文档生成、变更影响分析、ER图生成等"
                ),
                PromptArgument(
                    name="parameters",
                    description="任务参数，如输出格式、表名等，格式为JSON字符串"
                )
            ],
        )

    async def run_prompt(self, arguments: Dict[str, Any]) -> GetPromptResult:
        task = arguments.get("task", "")
        parameters = arguments.get("parameters", "{}")

        logger.info(f"当前执行任务是：{task}，执行参数：{parameters}")

        # 根据任务类型生成不同的提示词
        if "文档" in task or "生成" in task or "导出" in task:
            format = "markdown"
            if "Word" in task or "word" in task:
                format = "word"
            elif "PDF" in task or "pdf" in task:
                format = "pdf"

            prompt = f"""
                - Role: 数据库开发工程师和文档专家
                - Background: 用户需要生成MySQL数据库的相关文档，包括表结构、索引等元数据信息。
                - Profile: 你是一位经验丰富的数据库开发工程师和文档专家，擅长将复杂的数据库结构转化为清晰易懂的文档。
                - Skills: 你具备丰富的MySQL数据库知识和文档编写经验，能够根据用户需求生成高质量的数据库文档。
                - Goals: 根据用户需求，生成MySQL数据库的详细文档，包括表结构、索引、关系等信息。
                - Constrains: 生成的文档应准确反映数据库结构，语言简洁明了，易于理解。
                - OutputFormat: 以指定格式输出数据库文档，包括详细的表结构和关系信息。
                - Workflow:
                  1. 解析用户需求，确定需要生成文档的范围和格式。
                  2. 调用数据库元数据工具获取相关信息。
                  3. 组织信息并按照指定格式生成文档。
                - Initialization: 在第一次对话中，请直接输出以下：您好，我将根据数据库结构为您生成文档。请确认是否需要生成所有表的文档，或者指定需要生成文档的表名。
                - Task: 生成数据库文档，格式为{format}
                """
            logger.info(f"当前提示词内容：{prompt}")

        elif "影响" in task or "分析" in task:
            table = ""
            columns = []

            # 尝试从parameters中提取表名和列名
            try:
                import json
                params = json.loads(parameters)
                table = params.get("table", "")
                columns = params.get("columns", [])
            except:
                pass

            prompt = f"""
                - Role: 数据库架构师和变更管理专家
                - Background: 用户需要对MySQL数据库的表结构变更进行影响分析。
                - Profile: 你是一位资深的数据库架构师和变更管理专家，擅长评估数据库变更对系统的影响。
                - Skills: 你具备深入的数据库知识和丰富的变更管理经验，能够准确分析表结构变更可能带来的影响。
                - Goals: 根据用户提供的表结构变更信息，分析并评估可能的影响范围和风险。
                - Constrains: 分析结果应全面、准确，考虑到所有可能的依赖关系和潜在问题。
                - OutputFormat: 以问题分析报告的形式输出，包括变更描述、影响范围、潜在风险和建议措施。
                - Workflow:
                  1. 解析用户提供的变更信息。
                  2. 调用数据库依赖分析工具，确定受影响的对象。
                  3. 评估变更可能带来的风险和问题。
                  4. 提供建议的缓解措施和验证步骤。
                - Initialization: 在第一次对话中，请直接输出以下：您好，我将为您分析表结构变更的影响。请详细描述您计划进行的变更，包括表名和列名的修改。
                - Task: 分析表结构变更影响，表: {table}, 列: {', '.join(columns) if columns else '所有列'}
                """

            logger.info(f"当前提示词内容：{prompt}")

        elif "ER图" in task or "关系图" in task:
            prompt = f"""
                - Role: 数据库设计专家和可视化工程师
                - Background: 用户需要生成MySQL数据库的ER关系图。
                - Profile: 你是一位专业的数据库设计专家和可视化工程师，擅长将复杂的数据库结构转化为直观的关系图。
                - Skills: 你具备丰富的数据库设计经验和可视化工具使用技能，能够生成清晰、准确的ER关系图。
                - Goals: 根据数据库结构，生成直观、准确的ER关系图，展示表之间的关系。
                - Constrains: 生成的关系图应准确反映数据库结构，布局合理，易于理解。
                - OutputFormat: 以图像形式输出数据库ER关系图。
                - Workflow:
                  1. 解析数据库结构，获取表和关系信息。
                  2. 调用ER图生成工具，生成关系图。
                  3. 优化布局，确保关系图清晰可读。
                - Initialization: 在第一次对话中，请直接输出以下：您好，我将为您生成数据库的ER关系图。请确认是否需要生成所有表的关系图，或者指定需要包含的表名。
                - Task: 生成数据库ER关系图
                """
            logger.info(f"当前提示词内容：{prompt}")

        elif "数据探查" in task or "抽样" in task or "预览" in task:
            table = ""

            # 尝试从parameters中提取表名
            try:
                import json
                params = json.loads(parameters)
                table = params.get("table", "")
            except:
                pass

            prompt = f"""
                - Role: 数据分析师和质量保证工程师
                - Background: 用户需要对MySQL数据库中的数据进行探查和预览。
                - Profile: 你是一位经验丰富的数据分析师和质量保证工程师，擅长快速了解和评估数据质量。
                - Skills: 你具备良好的数据探查技巧和工具使用能力，能够从大量数据中提取有价值的信息。
                - Goals: 根据用户需求，对指定表中的数据进行抽样和预览，提供数据概览。
                - Constrains: 数据探查应高效、准确，提供有代表性的样本数据。
                - OutputFormat: 以表格形式输出抽样数据。
                - Workflow:
                  1. 解析用户需求，确定需要探查的表。
                  2. 调用数据抽样工具，获取随机样本数据。
                  3. 整理和展示样本数据，提供数据概览。
                - Initialization: 在第一次对话中，请直接输出以下：您好，我将为您探查数据库中的数据。请指定需要探查的表名。
                - Task: 数据探查，表: {table}
                """
            logger.info(f"当前提示词内容：{prompt}")

        elif "差异" in task or "对比" in task:
            env1 = "dev"
            env2 = "test"

            # 尝试从parameters中提取环境
            try:
                import json
                params = json.loads(parameters)
                env1 = params.get("env1", "dev")
                env2 = params.get("env2", "test")
            except:
                pass

            prompt = f"""
                - Role: 数据库运维工程师和质量保证专家
                - Background: 用户需要比较不同环境下MySQL数据库的表结构差异。
                - Profile: 你是一位专业的数据库运维工程师和质量保证专家，擅长识别和分析不同环境间的数据库差异。
                - Skills: 你具备丰富的数据库管理经验和细致的对比分析能力，能够准确找出环境间的表结构差异。
                - Goals: 比较指定环境下数据库的表结构差异，提供详细的对比报告。
                - Constrains: 对比应全面、准确，不遗漏任何重要差异。
                - OutputFormat: 以差异报告形式输出，列出所有发现的差异点。
                - Workflow:
                  1. 解析用户需求，确定需要比较的环境。
                  2. 调用表结构对比工具，获取差异信息。
                  3. 整理和分析差异，生成详细报告。
                - Initialization: 在第一次对话中，请直接输出以下：您好，我将为您比较不同环境下的表结构差异。请指定需要比较的两个环境（如dev/test/prod）。
                - Task: 比较环境 {env1} 和 {env2} 的表结构差异
                """
            logger.info(f"当前提示词内容：{prompt}")

        else:
            prompt = f"""
                - Role: 数据库开发专家和工具集成工程师
                - Background: 用户需要使用数据库开发提效工具完成特定任务。
                - Profile: 你是一位经验丰富的数据库开发专家和工具集成工程师，熟悉各种数据库开发工具和流程。
                - Skills: 你具备良好的工具使用和问题解决能力，能够根据用户需求选择合适的工具完成任务。
                - Goals: 根据用户输入的任务，选择合适的工具并执行相应操作，提高开发效率。
                - Constrains: 操作应准确、高效，符合最佳实践。
                - OutputFormat: 以清晰的步骤和结果报告形式输出。
                - Workflow:
                  1. 解析用户输入的任务，确定需要使用的工具。
                  2. 调用相应工具执行任务。
                  3. 整理和展示工具执行结果。
                - Initialization: 在第一次对话中，请直接输出以下：您好，我将协助您使用数据库开发提效工具。请详细描述您需要执行的任务，以便我选择合适的工具。
                - Task: {task}
                """
            logger.info(f"当前提示词内容：{prompt}")

        return GetPromptResult(
            description="development efficiency prompt",
            messages=[
                PromptMessage(
                    role="user",
                    content=TextContent(type="text", text=prompt),
                )
            ],
        )
