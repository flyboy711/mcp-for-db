import logging
from datetime import datetime
from typing import Dict, Any, List
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class DatabaseKnowledgeContext:
    """数据库知识上下文"""
    query: str
    search_method: str
    retrieved_segments: List[Dict[str, Any]] = field(default_factory=list)
    knowledge_sources: List[str] = field(default_factory=list)
    confidence_scores: List[float] = field(default_factory=list)
    keywords: List[str] = field(default_factory=list)


class DBAPromptTemplate:
    """通用RAG增强提示词模版生成器"""

    def generate_enhanced_prompt(self, user_query: str, rag_context: DatabaseKnowledgeContext) -> str:
        """
        生成RAG增强的通用提示词

        Args:
            user_query: 用户原始问题
            rag_context: RAG检索上下文
        """

        # 构建知识库上下文
        knowledge_context = self._build_knowledge_context(rag_context)

        # 构建搜索信息
        search_info = self._build_search_info(rag_context)

        # 构建置信度指标
        confidence_indicator = self._build_confidence_indicator(rag_context)

        # 生成最终提示词
        enhanced_prompt = f"""# 数据库专家助手
                ## 角色定义
                你是一位资深的数据库管理专家(DBA)，拥有丰富的数据库设计、管理、优化和故障处理经验。你精通多种数据库系统，包括MySQL、PostgreSQL、Oracle、SQL Server、MongoDB、Redis、OceanBase等关系型和NoSQL数据库技术。
                
                ## 知识库检索结果
                {knowledge_context}
                
                ## 检索信息
                {search_info}
                
                ## 置信度评估
                {confidence_indicator}
                
                ## 用户问题
                {user_query}
                
                ## 回答要求
                请基于上述知识库检索结果和你的专业经验，为用户提供准确、专业的数据库咨询建议：
                
                ### 核心回答原则
                1. **准确性优先**: 优先使用知识库中的权威信息，确保技术细节准确无误
                2. **实用性导向**: 提供具体可操作的建议、命令或配置示例
                3. **风险意识**: 对涉及数据安全、系统稳定性的操作明确提醒风险点
                4. **完整性考虑**: 提供多种解决方案时，对比分析各方案的优缺点
                5. **可追溯性**: 重要信息请明确引用知识库来源
                6. **结构化表达**: 使用清晰的层次结构组织答案内容，并使用标准 Markdown 格式进行回答
                
                ### 回答结构模版
                请按以下结构组织你的专业回答：
                
                #### 1. 问题理解
                - 简要重述和明确用户问题的核心要点
                - 识别问题类型(性能、故障、设计、选型、配置等)
                
                #### 2. 专业解答
                - 基于知识库内容提供权威的技术解决方案
                - 包含具体的操作步骤、SQL语句、配置参数等
                - 解释技术原理和实现机制
                
                #### 3. 最佳实践
                - 提供相关的行业最佳实践建议
                - 包含性能优化、安全配置、运维规范等方面
                
                #### 4. 注意事项
                - 明确指出操作风险和注意点
                - 提供备份、回滚等安全措施建议
                - 标识需要特别关注的环境依赖或版本要求
                
                #### 5. 扩展建议
                - 提供相关的优化建议或预防措施
                - 推荐进一步的学习资料或工具
                - 建议建立的监控和维护机制
                
                ## 回答格式说明
                - 使用 `代码块` 标识SQL语句、命令和配置
                - 使用 **加粗** 强调重要概念和关键点
                - 使用 ⚠️ 标识风险提醒
                - 使用 💡 标识最佳实践提示
                - 使用 📚 标识知识库引用来源
                
                请根据以上要求，为用户提供专业、准确、实用的数据库技术支持。
                ---
                *生成时间: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}*
                """

        return enhanced_prompt

    def _build_knowledge_context(self, rag_context: DatabaseKnowledgeContext) -> str:
        """构建知识库上下文"""
        if not rag_context.retrieved_segments:
            return """### ⚠️ 知识库检索状态
                      暂无相关知识库内容检索到，回答将主要基于通用数据库知识和最佳实践。建议用户提供更具体的问题描述以获得更精准的知识库匹配。"""

        context_parts = []
        context_parts.append("### 📚 相关知识库内容")

        for i, segment in enumerate(rag_context.retrieved_segments, 1):
            content = segment.get("内容", "").strip()
            source = segment.get("文档信息", {}).get("文档名称", "未知来源")
            score = segment.get("相似度分数", 0)

            # 限制显示内容长度，避免提示词过长
            if len(content) > 800:
                content = content[:800] + "..."

            context_parts.append(f"""
                    #### 知识片段 {i} (相关度: {score:.3f})
                    **📖 来源**: {source}
                    **📄 内容**:{content}
                    """)

        return "\n".join(context_parts)

    def _build_search_info(self, rag_context: DatabaseKnowledgeContext) -> str:
        """构建检索信息"""
        info_parts = [
            f"- **🔍 检索查询**: {rag_context.query}",
            f"- **📊 检索方法**: {rag_context.search_method}",
            f"- **📈 检索结果数**: {len(rag_context.retrieved_segments)} 个知识片段",
        ]

        if rag_context.keywords:
            # 限制关键词数量显示
            keywords_display = rag_context.keywords[:10]  # 只显示前10个关键词
            if len(rag_context.keywords) > 10:
                keywords_display.append("...")
            info_parts.append(f"- **🏷️ 相关关键词**: {', '.join(keywords_display)}")

        if rag_context.knowledge_sources:
            unique_sources = list(set(rag_context.knowledge_sources))
            info_parts.append(f"- **📚 涉及文档**: {', '.join(unique_sources)}")

        return "\n".join(info_parts)

    def _build_confidence_indicator(self, rag_context: DatabaseKnowledgeContext) -> str:
        """构建置信度指标"""
        if not rag_context.confidence_scores:
            return """### ⚠️ 知识可信度评估
                    无法评估知识库内容的可信度。建议：
                    - 结合实际环境进行验证
                    - 在非生产环境测试相关操作
                    - 必要时咨询相关技术文档"""

        avg_score = sum(rag_context.confidence_scores) / len(rag_context.confidence_scores)
        max_score = max(rag_context.confidence_scores)
        min_score = min(rag_context.confidence_scores)

        if avg_score >= 0.8:
            confidence_level = "🟢 高置信度"
            advice = "检索到的知识库内容与问题高度匹配，可作为权威技术参考。"
        elif avg_score >= 0.5:
            confidence_level = "🟡 中等置信度"
            advice = "检索到的知识库内容部分相关，建议结合具体业务场景判断适用性。"
        else:
            confidence_level = "🔴 低置信度"
            advice = "检索到的知识库内容相关性较低，将主要基于通用数据库知识回答。"

        return f"""### 📊 知识库内容可信度
                **{confidence_level}**
                - 平均匹配度: {avg_score:.3f}
                - 最高匹配度: {max_score:.3f}  
                - 最低匹配度: {min_score:.3f}
                - **建议**: {advice}"""
