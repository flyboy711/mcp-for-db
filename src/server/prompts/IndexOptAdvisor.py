import logging
from typing import Dict, Any
from server.utils.logger import configure_logger, get_logger
from mcp import GetPromptResult
from mcp.types import Prompt, TextContent, PromptMessage, PromptArgument
from server.prompts.BasePrompt import BasePrompt

logger = get_logger(__name__)
configure_logger(log_level=logging.INFO, log_filename="index_advisor_prompt.log")


class IndexOptimizationAdvisorPrompt(BasePrompt):
    name = "mysql_index_optimization_advisor"
    description = (
        "MySQL索引优化顾问提示词，指导数据库专家分析查询性能并提供索引优化建议"
        "(MySQL index optimization advisor prompt for database experts to analyze query performance and provide index recommendations)"
    )

    def get_prompt(self) -> Prompt:
        return Prompt(
            name=self.name,
            description=self.description,
            arguments=[
                PromptArgument(
                    name="query",
                    description="需要优化的SQL查询语句",
                    required=True
                ),
                PromptArgument(
                    name="context",
                    description="附加上下文信息（可选）",
                    required=False
                )
            ],
        )

    async def run_prompt(self, arguments: Dict[str, Any]) -> GetPromptResult:
        """生成索引优化顾问提示词"""
        query = arguments.get("query", "")
        context = arguments.get("context", "")

        prompt = f"""
        # MySQL索引优化顾问提示词

        ## 角色定位
        - **角色**: 高级数据库性能优化专家
        - **专长**: MySQL查询优化、索引设计、性能调优
        - **目标**: 分析SQL查询性能瓶颈，提供最优索引优化方案

        ## 核心任务
        针对以下SQL查询语句进行深度性能分析，并提供专业的索引优化建议：
        ```sql
        {query}
        ```

        ## 分析框架
        请按照以下结构化方法进行分析：

        1. **查询解析与理解**:
           - 解析查询语义和执行逻辑
           - 识别关键操作（JOIN、WHERE、GROUP BY、ORDER BY等）
           - 评估查询复杂度（表数量、数据量估算）

        2. **性能瓶颈诊断**:
           - 识别潜在的全表扫描操作
           - 分析WHERE子句中的过滤条件
           - 评估JOIN操作的效率
           - 检查排序和分组操作的性能影响

        3. **索引策略设计**:
           - 基于查询模式设计最有效的单列索引
           - 创建高效的多列组合索引（考虑列顺序）
           - 评估覆盖索引的可能性
           - 建议删除冗余或低效索引

        4. **优化建议实施**:
           - 提供具体的索引创建语句
           - 预估优化后的性能提升
           - 给出实施步骤和验证方法

        ## 输出要求
        - 使用专业术语但保持解释清晰
        - 包含具体的优化建议和SQL语句
        - 评估优化前后的性能差异
        - 提供实施风险评估

        ## 专业指导原则
        - **索引选择原则**:
          1. 高选择性列优先
          2. 等值查询列优先于范围查询列
          3. 小数据类型列优先
          4. 避免在低选择性列上创建索引

        - **组合索引设计规则**:
          1. 最左前缀匹配原则
          2. 等值查询列在前，范围查询列在后
          3. 排序和分组列放在索引末尾
          4. 索引列总数不超过5个

        ## 案例分析示例

        ### 案例1: 简单查询优化
        **原始查询**:
        ```sql
        SELECT * FROM orders WHERE customer_id = 123 AND order_date > '2023-01-01';
        ```

        **优化建议**:
        1. 创建组合索引: `(customer_id, order_date)`
        2. 理由: 
           - customer_id 高选择性，适合作为前缀列
           - order_date 范围查询，适合作为第二列
        3. 预估性能提升: 查询时间从 1200ms → 15ms

        ### 案例2: JOIN查询优化
        **原始查询**:
        ```sql
        SELECT u.name, o.total 
        FROM users u
        JOIN orders o ON u.id = o.user_id
        WHERE u.country = 'US' AND o.status = 'completed'
        ORDER BY o.order_date DESC;
        ```

        **优化建议**:
        1. users表索引: `(country, id)`
        2. orders表索引: `(user_id, status, order_date)`
        3. 理由:
           - 覆盖WHERE条件和JOIN条件
           - 支持排序操作避免额外排序步骤
        4. 预估性能提升: 查询时间从 3500ms → 80ms

        ### 案例3: 复杂查询优化
        **原始查询**:
        ```sql
        SELECT product_id, COUNT(*) as order_count
        FROM order_items
        WHERE category = 'Electronics' 
          AND price > 1000
          AND order_date BETWEEN '2023-01-01' AND '2023-06-30'
        GROUP BY product_id
        HAVING order_count > 5
        ORDER BY order_count DESC;
        ```

        **优化建议**:
        1. 创建索引: `(category, price, order_date, product_id)`
        2. 理由:
           - 覆盖所有WHERE条件列
           - 包含GROUP BY列避免额外排序
           - 覆盖查询选择列
        3. 预估性能提升: 查询时间从 8500ms → 220ms

        ## 当前任务
        """

        # 添加用户提供的上下文信息
        if context:
            prompt += f"\n### 附加上下文信息:\n{context}\n"

        # 添加具体分析指令
        prompt += f"""
        请针对以下查询进行专业分析并提供优化建议:
        ```sql
        {query}
        ```

        **输出要求**:
        - 清晰的问题诊断
        - 具体的索引优化方案
        - 预估性能提升
        - 实施注意事项
        """

        logger.info(f"生成索引优化提示词，查询长度: {len(query)} 字符")
        logger.debug(f"提示词内容: {prompt[:500]}...")

        return GetPromptResult(
            description="MySQL索引优化顾问提示词",
            messages=[
                PromptMessage(
                    role="system",
                    content=TextContent(type="text", text="你是一位经验丰富的MySQL数据库性能优化专家"),
                ),
                PromptMessage(
                    role="user",
                    content=TextContent(type="text", text=prompt),
                )
            ],
        )