import logging
import re
from datetime import datetime
from typing import Dict, Any, Sequence, List, Optional
from enum import Enum
from dataclasses import dataclass

from server.tools.mysql import ExecuteSQL
from server.utils.logger import get_logger, configure_logger
from server.tools.mysql.base import BaseHandler
from mcp import Tool
from mcp.types import TextContent

logger = get_logger(__name__)
configure_logger(log_level=logging.INFO, log_filename="ddl_alert_processor.log")


class RiskLevel(Enum):
    """DDL操作风险级别"""
    LOW = "低风险"
    MEDIUM = "中风险"
    HIGH = "高风险"
    CRITICAL = "极高风险"


class DDLType(Enum):
    """DDL操作类型"""
    CREATE_TABLE = "新建表"
    ADD_COLUMN = "加字段"
    ADD_INDEX = "加索引"
    MODIFY_COLUMN_LENGTH = "加长度"
    MODIFY_COMMENT = "修改备注"
    MODIFY_INDEX = "索引修改"
    DROP_INDEX = "索引删除"
    MODIFY_COLUMN_TYPE = "修改字段类型"
    MODIFY_UNIQUE_INDEX = "唯一索引变更"
    DROP_TABLE = "删除表"
    DROP_DATABASE = "删除数据库"
    DROP_COLUMN = "删除列"
    RENAME_TABLE = "重命名表"
    TRUNCATE_TABLE = "清空表"
    MIGRATE_TABLE = "库表迁移"
    DATA_CLEANUP = "数据清理"
    ARCHIVE = "归档"


@dataclass
class DDLAlert:
    """DDL告警信息"""
    operation: DDLType
    table: str
    database: str
    table_size_gb: Optional[float] = None
    column: Optional[str] = None
    index: Optional[str] = None
    old_type: Optional[str] = None
    new_type: Optional[str] = None
    is_unique: Optional[bool] = None
    is_archive: Optional[bool] = None
    is_data_cleanup: Optional[bool] = None
    is_migration: Optional[bool] = None


class DDLAlertProcessor(BaseHandler):
    """MySQL DDL告警智能处理器"""
    name = "mysql_ddl_alert_processor"
    description = (
        "智能处理MySQL DDL操作告警，评估风险级别并提供解决方案"
        "(Intelligently process MySQL DDL operation alerts, assess risk levels and provide solutions)"
    )

    # 风险规则定义
    RISK_RULES = {
        RiskLevel.LOW: [
            DDLType.CREATE_TABLE,
            (DDLType.ADD_COLUMN, lambda a: a.table_size_gb and a.table_size_gb < 2),
            (DDLType.ADD_INDEX, lambda a: a.table_size_gb and a.table_size_gb < 2),
            (DDLType.MODIFY_COLUMN_LENGTH, lambda a: a.table_size_gb and a.table_size_gb < 2),
            (DDLType.MODIFY_COMMENT, lambda a: a.table_size_gb and a.table_size_gb < 2),
        ],
        RiskLevel.MEDIUM: [
            (DDLType.ADD_COLUMN, lambda a: a.table_size_gb and 2 <= a.table_size_gb < 50),
            (DDLType.ADD_INDEX, lambda a: a.table_size_gb and 2 <= a.table_size_gb < 50),
            (DDLType.MODIFY_COLUMN_LENGTH, lambda a: a.table_size_gb and 2 <= a.table_size_gb < 50),
            (DDLType.MODIFY_COMMENT, lambda a: a.table_size_gb and 2 <= a.table_size_gb < 50),
            DDLType.MODIFY_INDEX,
            DDLType.DROP_INDEX,
        ],
        RiskLevel.HIGH: [
            (DDLType.ADD_COLUMN, lambda a: a.table_size_gb and a.table_size_gb >= 50),
            (DDLType.ADD_INDEX, lambda a: a.table_size_gb and a.table_size_gb >= 50),
            (DDLType.MODIFY_COLUMN_LENGTH, lambda a: a.table_size_gb and a.table_size_gb >= 50),
            (DDLType.MODIFY_COMMENT, lambda a: a.table_size_gb and a.table_size_gb >= 50),
            DDLType.MODIFY_COLUMN_TYPE,
            DDLType.MODIFY_UNIQUE_INDEX,
        ],
        RiskLevel.CRITICAL: [
            DDLType.DROP_TABLE,
            DDLType.DROP_DATABASE,
            DDLType.DROP_COLUMN,
            DDLType.RENAME_TABLE,
            DDLType.TRUNCATE_TABLE,
            (DDLType.MIGRATE_TABLE, lambda a: not a.is_migration),
            (DDLType.DATA_CLEANUP, lambda a: not a.is_data_cleanup),
            (DDLType.ARCHIVE, lambda a: not a.is_archive),
        ]
    }

    def get_tool_description(self) -> Tool:
        return Tool(
            name=self.name,
            description=self.description,
            inputSchema={
                "type": "object",
                "properties": {
                    "alerts": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "operation": {"type": "string", "description": "DDL操作类型"},
                                "table": {"type": "string", "description": "表名"},
                                "database": {"type": "string", "description": "数据库名"},
                                "table_size_gb": {"type": "number", "description": "表大小(GB)"},
                                "column": {"type": "string", "description": "列名(可选)"},
                                "index": {"type": "string", "description": "索引名(可选)"},
                                "old_type": {"type": "string", "description": "原字段类型(可选)"},
                                "new_type": {"type": "string", "description": "新字段类型(可选)"},
                                "is_unique": {"type": "boolean", "description": "是否唯一索引(可选)"},
                                "is_archive": {"type": "boolean", "description": "是否归档操作(可选)"},
                                "is_data_cleanup": {"type": "boolean", "description": "是否数据清理(可选)"},
                                "is_migration": {"type": "boolean", "description": "是否迁移操作(可选)"},
                            },
                            "required": ["operation", "table", "database"]
                        },
                        "description": "告警信息列表"
                    }
                },
                "required": ["alerts"]
            }
        )

    async def run_tool(self, arguments: Dict[str, Any]) -> Sequence[TextContent]:
        """处理DDL告警信息"""
        try:
            alerts_data = arguments.get("alerts", [])
            if not alerts_data:
                return [TextContent(type="text", text="错误: 未提供告警信息")]

            # 解析告警信息
            alerts = [self.parse_alert(alert) for alert in alerts_data]

            # 分析风险级别
            analyzed_alerts = [self.analyze_risk(alert) for alert in alerts]

            # 获取整体风险级别（取最高风险）
            overall_risk = self.get_overall_risk(analyzed_alerts)

            # 生成处理建议
            recommendations = self.generate_recommendations(analyzed_alerts)

            # 生成报告
            report = self.generate_report(analyzed_alerts, overall_risk, recommendations)

            return [TextContent(type="text", text=report)]

        except Exception as e:
            logger.error(f"处理告警失败: {str(e)}", exc_info=True)
            return [TextContent(type="text", text=f"处理告警失败: {str(e)}")]

    def parse_alert(self, alert_data: Dict[str, Any]) -> DDLAlert:
        """解析告警信息"""
        try:
            # 解析操作类型
            operation = DDLType[alert_data["operation"].upper()]
        except KeyError:
            raise ValueError(f"未知的操作类型: {alert_data['operation']}")

        return DDLAlert(
            operation=operation,
            table=alert_data["table"],
            database=alert_data["database"],
            table_size_gb=alert_data.get("table_size_gb"),
            column=alert_data.get("column"),
            index=alert_data.get("index"),
            old_type=alert_data.get("old_type"),
            new_type=alert_data.get("new_type"),
            is_unique=alert_data.get("is_unique"),
            is_archive=alert_data.get("is_archive"),
            is_data_cleanup=alert_data.get("is_data_cleanup"),
            is_migration=alert_data.get("is_migration"),
        )

    def analyze_risk(self, alert: DDLAlert) -> Dict[str, Any]:
        """分析单个告警的风险级别"""
        # 检查所有风险级别
        for risk_level, rules in self.RISK_RULES.items():
            for rule in rules:
                if isinstance(rule, tuple):
                    rule_type, condition = rule
                    if alert.operation == rule_type and condition(alert):
                        return {
                            "alert": alert,
                            "risk_level": risk_level,
                            "reason": self.get_risk_reason(alert, risk_level)
                        }
                else:
                    if alert.operation == rule:
                        return {
                            "alert": alert,
                            "risk_level": risk_level,
                            "reason": self.get_risk_reason(alert, risk_level)
                        }

        # 默认中等风险
        return {
            "alert": alert,
            "risk_level": RiskLevel.MEDIUM,
            "reason": "未知操作类型，默认中等风险"
        }

    def get_risk_reason(self, alert: DDLAlert, risk_level: RiskLevel) -> str:
        """获取风险原因描述"""
        size_info = f"({alert.table_size_gb}GB)" if alert.table_size_gb else ""

        reasons = {
            RiskLevel.LOW: f"低风险操作: {alert.operation.value}{size_info}",
            RiskLevel.MEDIUM: f"中风险操作: {alert.operation.value}{size_info}",
            RiskLevel.HIGH: f"高风险操作: {alert.operation.value}{size_info}",
            RiskLevel.CRITICAL: f"极高风险操作: {alert.operation.value}"
        }

        # 特殊原因说明
        if alert.operation == DDLType.MODIFY_COLUMN_TYPE:
            return f"修改字段类型({alert.old_type}→{alert.new_type})属于高风险操作"
        elif alert.operation == DDLType.MODIFY_UNIQUE_INDEX:
            return "唯一索引变更属于高风险操作"
        elif alert.operation in [DDLType.DROP_TABLE, DDLType.DROP_DATABASE, DDLType.DROP_COLUMN]:
            return "删除操作属于极高风险操作"
        elif alert.operation in [DDLType.RENAME_TABLE, DDLType.TRUNCATE_TABLE]:
            return "结构变更操作属于极高风险操作"

        return reasons.get(risk_level, "未知风险原因")

    def get_overall_risk(self, analyzed_alerts: List[Dict[str, Any]]) -> RiskLevel:
        """获取整体风险级别（取最高风险）"""
        risk_levels = [alert["risk_level"] for alert in analyzed_alerts]

        if RiskLevel.CRITICAL in risk_levels:
            return RiskLevel.CRITICAL
        if RiskLevel.HIGH in risk_levels:
            return RiskLevel.HIGH
        if RiskLevel.MEDIUM in risk_levels:
            return RiskLevel.MEDIUM
        return RiskLevel.LOW

    def generate_recommendations(self, analyzed_alerts: List[Dict[str, Any]]) -> List[str]:
        """生成处理建议"""
        recommendations = []

        for alert_info in analyzed_alerts:
            alert = alert_info["alert"]
            risk_level = alert_info["risk_level"]

            if risk_level == RiskLevel.LOW:
                rec = f"✅ 操作安全: {alert.operation.value} 可在业务低峰期直接执行"
            elif risk_level == RiskLevel.MEDIUM:
                rec = (
                    f"⚠️ 建议: {alert.operation.value} 操作需在DBA监督下执行\n"
                    f"   - 执行前备份数据\n"
                    f"   - 使用pt-online-schema-change工具在线修改\n"
                    f"   - 监控执行进度"
                )
            elif risk_level == RiskLevel.HIGH:
                rec = (
                    f"🚨 高风险操作: {alert.operation.value} 需要严格审批\n"
                    f"   - 提交详细变更方案\n"
                    f"   - 在测试环境验证\n"
                    f"   - 业务低峰期执行\n"
                    f"   - 使用在线DDL工具\n"
                    f"   - 准备回滚方案"
                )
            else:  # CRITICAL
                rec = (
                    f"🔥 极高风险操作: {alert.operation.value} 禁止直接执行\n"
                    f"   - 需要部门负责人审批\n"
                    f"   - 提交详细影响分析报告\n"
                    f"   - 在测试环境充分验证\n"
                    f"   - 制定详细执行和回滚计划\n"
                    f"   - 执行时DBA全程监控"
                )

            # 特殊操作建议
            if alert.operation == DDLType.MODIFY_COLUMN_TYPE:
                rec += (
                    f"\n   - 特别注意: 修改字段类型可能导致数据丢失或截断\n"
                    f"     原类型: {alert.old_type} → 新类型: {alert.new_type}"
                )
            elif alert.operation in [DDLType.DROP_TABLE, DDLType.DROP_DATABASE, DDLType.DROP_COLUMN]:
                rec += (
                    f"\n   - 特别注意: 删除操作不可逆，必须确认备份有效\n"
                    f"   - 建议使用软删除或归档代替物理删除"
                )

            recommendations.append(rec)

        return recommendations

    def generate_report(
            self,
            analyzed_alerts: List[Dict[str, Any]],
            overall_risk: RiskLevel,
            recommendations: List[str]
    ) -> str:
        """生成告警处理报告"""
        report = f"# MySQL DDL操作风险分析报告\n\n"
        report += f"**整体风险级别**: {overall_risk.value}\n\n"

        report += "## 告警详情\n"
        for i, alert_info in enumerate(analyzed_alerts, 1):
            alert = alert_info["alert"]
            report += (
                f"### 告警 #{i}\n"
                f"- **数据库**: {alert.database}\n"
                f"- **表名**: {alert.table}\n"
                f"- **操作类型**: {alert.operation.value}\n"
                f"- **风险级别**: {alert_info['risk_level'].value}\n"
                f"- **风险原因**: {alert_info['reason']}\n"
            )

            if alert.column:
                report += f"- **涉及列**: {alert.column}\n"
            if alert.index:
                report += f"- **涉及索引**: {alert.index}\n"
            if alert.table_size_gb:
                report += f"- **表大小**: {alert.table_size_gb} GB\n"

            report += "\n"

        report += "## 处理建议\n"
        for i, rec in enumerate(recommendations, 1):
            report += f"### 建议 #{i}\n{rec}\n\n"

        report += "## 整体处理策略\n"
        if overall_risk == RiskLevel.LOW:
            report += (
                "所有操作均为低风险，可在业务低峰期批量执行。\n"
                "建议: 使用自动化脚本执行，记录执行日志。"
            )
        elif overall_risk == RiskLevel.MEDIUM:
            report += (
                "存在中风险操作，需要谨慎处理。\n"
                "建议:\n"
                "  - 制定详细执行计划\n"
                "  - 业务低峰期执行\n"
                "  - DBA监督执行过程\n"
                "  - 准备回滚方案"
            )
        elif overall_risk == RiskLevel.HIGH:
            report += (
                "存在高风险操作，需要严格审批和充分准备。\n"
                "建议:\n"
                "  - 提交变更审批流程\n"
                "  - 在测试环境充分验证\n"
                "  - 使用在线DDL工具\n"
                "  - 制定详细回滚计划\n"
                "  - 执行时DBA全程监控"
            )
        else:
            report += (
                "存在极高风险操作，禁止直接执行！\n"
                "必须:\n"
                "  - 提交部门负责人审批\n"
                "  - 提供详细影响分析报告\n"
                "  - 在测试环境充分验证\n"
                "  - 制定详细执行和回滚计划\n"
                "  - 执行时DBA和开发人员全程在场\n"
                "  - 建议考虑替代方案，避免直接执行高危操作"
            )

        report += "\n\n**报告生成时间**: " + datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        return report


########################################################################################################################
########################################################################################################################
class AlertDiscoveryTool(BaseHandler):
    """告警信息发现工具"""
    name = "alert_discovery"
    description = (
        "在数据库中自动发现告警信息表和字段"
        "(Automatically discover alert-related tables and columns in the database)"
    )

    def get_tool_description(self) -> Tool:
        return Tool(
            name=self.name,
            description=self.description,
            inputSchema={
                "type": "object",
                "properties": {
                    "keywords": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "搜索关键词列表（如['alert', 'alarm', 'warning']）",
                        "default": ["alert", "alarm", "warning", "error"]
                    },
                    "search_depth": {
                        "type": "integer",
                        "description": "搜索深度（1-3），1=表名，2=列名，3=注释",
                        "default": 3
                    },
                    "max_results": {
                        "type": "integer",
                        "description": "返回的最大结果数量",
                        "default": 20
                    }
                },
                "required": []
            }
        )

    async def run_tool(self, arguments: Dict[str, Any]) -> Sequence[TextContent]:
        """在数据库中搜索告警信息表和字段"""
        try:
            keywords = arguments.get("keywords", ["alert", "alarm", "warning", "error"])
            search_depth = min(max(arguments.get("search_depth", 3), 1), 3)
            max_results = arguments.get("max_results", 20)

            logger.info(f"开始告警信息发现: 关键词={keywords}, 深度={search_depth}")

            # 获取数据库连接
            execute_sql = ExecuteSQL()

            # 构建搜索条件
            conditions = []
            for keyword in keywords:
                escaped_keyword = keyword.replace("'", "''")

                # 表名搜索
                if search_depth >= 1:
                    conditions.append(f"TABLE_NAME LIKE '%{escaped_keyword}%'")

                # 列名搜索
                if search_depth >= 2:
                    conditions.append(f"COLUMN_NAME LIKE '%{escaped_keyword}%'")

                # 注释搜索
                if search_depth >= 3:
                    conditions.append(f"TABLE_COMMENT LIKE '%{escaped_keyword}%'")
                    conditions.append(f"COLUMN_COMMENT LIKE '%{escaped_keyword}%'")

            where_clause = " OR ".join(conditions) if conditions else "1=1"

            # 构建查询语句
            query = f"""
                SELECT 
                    TABLE_SCHEMA AS database_name,
                    TABLE_NAME AS table_name,
                    COLUMN_NAME AS column_name,
                    DATA_TYPE AS data_type,
                    COLUMN_COMMENT AS column_comment,
                    TABLE_COMMENT AS table_comment,
                    CASE 
                        WHEN COLUMN_NAME IS NOT NULL THEN 'column'
                        ELSE 'table'
                    END AS match_type
                FROM information_schema.COLUMNS
                WHERE ({where_clause})
                UNION
                SELECT 
                    TABLE_SCHEMA AS database_name,
                    TABLE_NAME AS table_name,
                    NULL AS column_name,
                    NULL AS data_type,
                    NULL AS column_comment,
                    TABLE_COMMENT AS table_comment,
                    'table' AS match_type
                FROM information_schema.TABLES
                WHERE ({where_clause.replace('COLUMN_COMMENT', 'TABLE_COMMENT')})
                ORDER BY database_name, table_name, column_name
                LIMIT {max_results}
            """

            logger.debug(f"执行查询: {query}")

            # 执行查询
            results = await execute_sql.run_tool({"query": query})

            # 处理结果
            if not results:
                return [TextContent(type="text", text="未找到匹配的告警信息表或字段")]

            # 解析结果 - 假设所有结果都是TextContent类型
            alert_tables = {}
            for result in results:
                if isinstance(result, TextContent):
                    # 解析CSV格式的结果
                    lines = result.text.strip().split('\n')
                    if not lines:
                        continue

                    # 提取表头
                    headers = [h.strip() for h in lines[0].split(',')]

                    # 处理数据行
                    for line in lines[1:]:
                        values = [v.strip() for v in line.split(',')]
                        if len(values) >= len(headers):
                            row = dict(zip(headers, values))
                            self._process_row(row, alert_tables)

            # 生成报告
            report = self.generate_report(alert_tables, keywords)
            return [TextContent(type="text", text=report)]

        except Exception as e:
            logger.error(f"告警信息发现失败: {str(e)}", exc_info=True)
            return [TextContent(type="text", text=f"告警信息发现失败: {str(e)}")]

    def _process_row(self, row: Dict[str, str], alert_tables: Dict[str, Dict]):
        """处理查询结果行"""
        db_table = f"{row['database_name']}.{row['table_name']}"

        # 初始化表信息
        if db_table not in alert_tables:
            alert_tables[db_table] = {
                "database": row['database_name'],
                "table": row['table_name'],
                "comment": row.get('table_comment', ''),
                "columns": []
            }

        # 添加列信息
        if row.get('column_name'):
            alert_tables[db_table]["columns"].append({
                "name": row['column_name'],
                "type": row.get('data_type', ''),
                "comment": row.get('column_comment', '')
            })

    def generate_report(self, alert_tables: Dict[str, Dict], keywords: List[str]) -> str:
        """生成告警信息发现报告"""
        report = "# 告警信息发现报告\n\n"
        report += f"**搜索关键词**: {', '.join(keywords)}\n\n"

        if not alert_tables:
            report += "未发现匹配的告警信息表或字段\n"
            return report

        report += "## 发现的告警信息表\n"

        for table_info in alert_tables.values():
            report += f"### 数据库: `{table_info['database']}` 表名: `{table_info['table']}`\n"

            if table_info['comment']:
                report += f"**表注释**: {table_info['comment']}\n"

            if table_info['columns']:
                report += "**相关字段**:\n"
                for col in table_info['columns']:
                    report += f"- `{col['name']}` ({col['type']})"
                    if col['comment']:
                        report += f": {col['comment']}"
                    report += "\n"
            else:
                report += "> 表名匹配但未发现相关字段\n"

            report += "\n"

        report += "## 后续步骤建议\n"
        report += ("1. 验证发现的表是否确实包含告警信息\n"
                   "2. 使用数据查询工具进一步分析告警数据\n"
                   "3. 创建告警分析视图或物化视图\n"
                   "4. 设置定期告警分析任务\n")

        report += "\n> **注意**: 本报告基于元数据搜索生成，实际内容需进一步验证"

        return report


########################################################################################################################
########################################################################################################################
class AlertDataAnalyzer(BaseHandler):
    """告警数据分析工具"""
    name = "alert_data_analyzer"
    description = (
        "分析告警数据并提供解决方案"
        "(Analyze alert data and provide solutions)"
    )

    def get_tool_description(self) -> Tool:
        return Tool(
            name=self.name,
            description=self.description,
            inputSchema={
                "type": "object",
                "properties": {
                    "database": {
                        "type": "string",
                        "description": "数据库名称"
                    },
                    "table": {
                        "type": "string",
                        "description": "表名"
                    },
                    "time_range": {
                        "type": "object",
                        "properties": {
                            "start": {"type": "string", "description": "开始时间（YYYY-MM-DD HH:MM:SS）"},
                            "end": {"type": "string", "description": "结束时间（YYYY-MM-DD HH:MM:SS）"}
                        },
                        "description": "时间范围（可选）"
                    },
                    "filters": {
                        "type": "object",
                        "description": "附加过滤条件（可选）"
                    },
                    "analysis_depth": {
                        "type": "string",
                        "enum": ["summary", "detailed", "root_cause"],
                        "description": "分析深度",
                        "default": "summary"
                    }
                },
                "required": ["database", "table"]
            }
        )

    async def run_tool(self, arguments: Dict[str, Any]) -> Sequence[TextContent]:
        """分析告警数据"""
        try:
            database = arguments["database"]
            table = arguments["table"]
            time_range = arguments.get("time_range")
            filters = arguments.get("filters", {})
            analysis_depth = arguments.get("analysis_depth", "summary")

            logger.info(f"开始分析告警数据: {database}.{table}")

            # 获取表结构
            table_structure = await self.get_table_structure(database, table)

            # 分析告警字段
            alert_fields = self.identify_alert_fields(table_structure)

            if not alert_fields:
                return [TextContent(type="text", text=f"未能在表 {table} 中识别告警字段")]

            # 获取告警数据
            alert_data = await self.get_alert_data(database, table, alert_fields, time_range, filters)

            # 分析告警数据
            analysis = self.analyze_alerts(alert_data, alert_fields, analysis_depth)

            # 生成报告
            report = self.generate_report(database, table, alert_fields, analysis)

            return [TextContent(type="text", text=report)]

        except Exception as e:
            logger.error(f"告警数据分析失败: {str(e)}", exc_info=True)
            return [TextContent(type="text", text=f"告警数据分析失败: {str(e)}")]

    async def get_table_structure(self, database: str, table: str) -> List[Dict]:
        """获取表结构信息"""
        execute_sql = ExecuteSQL()

        query = f"""
            SELECT 
                COLUMN_NAME, DATA_TYPE, COLUMN_COMMENT
            FROM information_schema.COLUMNS
            WHERE TABLE_SCHEMA = '{database}' 
              AND TABLE_NAME = '{table}'
        """

        results = await execute_sql.run_tool({"query": query})

        # 解析结果 - 只处理TextContent类型
        structure = []
        for result in results:
            if isinstance(result, TextContent):
                lines = result.text.strip().split('\n')
                if not lines:
                    continue

                # 提取表头
                headers = [h.strip() for h in lines[0].split(',')]

                # 处理数据行
                for line in lines[1:]:
                    values = [v.strip() for v in line.split(',')]
                    if len(values) >= len(headers):
                        row = dict(zip(headers, values))
                        structure.append(row)

        return structure

    def identify_alert_fields(self, structure: List[Dict]) -> Dict[str, str]:
        """识别告警相关字段"""
        alert_fields = {}

        # 常见告警字段模式
        patterns = {
            "level": r"level|severity|priority",
            "type": r"type|category",
            "message": r"message|content|description",
            "timestamp": r"time|timestamp|created_at",
            "source": r"source|origin|host",
            "status": r"status|state"
        }

        for col in structure:
            col_name = col.get("COLUMN_NAME", "")
            col_comment = col.get("COLUMN_COMMENT", "")

            for field_type, pattern in patterns.items():
                if (re.search(pattern, col_name, re.IGNORECASE) or
                        re.search(pattern, col_comment, re.IGNORECASE)):
                    alert_fields[field_type] = col_name
                    break

        return alert_fields

    async def get_alert_data(self, database: str, table: str, alert_fields: Dict,
                             time_range: Optional[Dict], filters: Dict) -> List[Dict]:
        """获取告警数据"""
        execute_sql = ExecuteSQL()

        # 构建查询字段
        select_fields = list(alert_fields.values())
        if not select_fields:
            return []

        # 构建WHERE条件
        conditions = []

        # 时间范围条件
        if time_range and "timestamp" in alert_fields:
            time_field = alert_fields["timestamp"]
            conditions.append(f"`{time_field}` BETWEEN '{time_range['start']}' AND '{time_range['end']}'")

        # 附加过滤条件
        for field, value in filters.items():
            conditions.append(f"`{field}` = '{value}'")

        where_clause = " AND ".join(conditions) if conditions else "1=1"

        # 构建查询
        query = f"""
            SELECT {', '.join([f'`{f}`' for f in select_fields])}
            FROM `{database}`.`{table}`
            WHERE {where_clause}
            LIMIT 1000
        """

        results = await execute_sql.run_tool({"query": query})

        # 解析结果 - 只处理TextContent类型
        data = []
        for result in results:
            if isinstance(result, TextContent):
                lines = result.text.strip().split('\n')
                if not lines:
                    continue

                # 提取表头
                headers = [h.strip() for h in lines[0].split(',')]

                # 处理数据行
                for line in lines[1:]:
                    values = [v.strip() for v in line.split(',')]
                    if len(values) >= len(headers):
                        row = dict(zip(headers, values))
                        data.append(row)

        return data

    def analyze_alerts(self, alert_data: List[Dict], alert_fields: Dict, depth: str) -> Dict:
        """分析告警数据"""
        analysis = {
            "summary": {},
            "trends": {},
            "patterns": {},
            "recommendations": []
        }

        if not alert_data:
            return analysis

        # 基本统计
        total_alerts = len(alert_data)

        # 按级别统计
        if "level" in alert_fields:
            level_field = alert_fields["level"]
            level_counts = {}
            for alert in alert_data:
                level = alert.get(level_field, "unknown")
                level_counts[level] = level_counts.get(level, 0) + 1

            analysis["summary"]["level_distribution"] = level_counts

        # 按类型统计
        if "type" in alert_fields:
            type_field = alert_fields["type"]
            type_counts = {}
            for alert in alert_data:
                alert_type = alert.get(type_field, "unknown")
                type_counts[alert_type] = type_counts.get(alert_type, 0) + 1

            analysis["summary"]["type_distribution"] = type_counts
            analysis["recommendations"].append("检查高频告警类型，优化相关系统")

        # 时间趋势分析
        if "timestamp" in alert_fields and depth in ["detailed", "root_cause"]:
            time_field = alert_fields["timestamp"]
            time_series = {}
            for alert in alert_data:
                # 简化时间到小时级别
                time_key = alert[time_field][:13] + ":00:00"
                time_series[time_key] = time_series.get(time_key, 0) + 1

            analysis["trends"]["hourly_distribution"] = time_series

            # 检测高峰时段
            max_count = max(time_series.values())
            peak_hours = [hour for hour, count in time_series.items() if count == max_count]
            analysis["patterns"]["peak_hours"] = peak_hours
            analysis["recommendations"].append(f"高峰时段: {', '.join(peak_hours)}，建议加强监控")

        # 根因分析（深度模式）
        if depth == "root_cause" and "source" in alert_fields and "message" in alert_fields:
            source_field = alert_fields["source"]
            message_field = alert_fields["message"]

            # 分析常见错误消息
            error_patterns = {}
            for alert in alert_data:
                message = alert.get(message_field, "")
                if "error" in message.lower() or "fail" in message.lower():
                    # 提取错误关键词
                    match = re.search(r'\b(error|failed|exception|timeout)\b', message, re.IGNORECASE)
                    if match:
                        error_key = match.group(0).lower()
                        error_patterns[error_key] = error_patterns.get(error_key, 0) + 1

            analysis["patterns"]["error_patterns"] = error_patterns

            # 分析来源系统
            source_counts = {}
            for alert in alert_data:
                source = alert.get(source_field, "unknown")
                source_counts[source] = source_counts.get(source, 0) + 1

            analysis["patterns"]["source_distribution"] = source_counts

            # 生成根因建议
            if error_patterns:
                top_error = max(error_patterns, key=error_patterns.get)
                analysis["recommendations"].append(f"主要错误类型: {top_error}，建议检查相关系统日志")

            if source_counts:
                top_source = max(source_counts, key=source_counts.get)
                analysis["recommendations"].append(f"主要告警来源: {top_source}，建议重点排查")

        # 添加通用建议
        analysis["recommendations"].extend([
            "定期审查告警规则，减少误报",
            "设置告警分级响应机制",
            "建立告警闭环处理流程"
        ])

        return analysis

    def generate_report(self, database: str, table: str, alert_fields: Dict, analysis: Dict) -> str:
        """生成告警分析报告"""
        report = f"# 告警数据分析报告\n\n"
        report += f"**数据库**: `{database}`\n"
        report += f"**表名**: `{table}`\n\n"

        report += "## 告警字段识别\n"
        for field_type, field_name in alert_fields.items():
            report += f"- **{field_type}**: `{field_name}`\n"
        report += "\n"

        report += "## 分析摘要\n"
        if "summary" in analysis:
            for section, data in analysis["summary"].items():
                report += f"### {section.replace('_', ' ').title()}\n"
                if isinstance(data, dict):
                    for key, value in data.items():
                        report += f"- {key}: {value}\n"
                else:
                    report += f"{data}\n"
                report += "\n"

        if "trends" in analysis and analysis["trends"]:
            report += "## 时间趋势分析\n"
            for section, data in analysis["trends"].items():
                report += f"### {section.replace('_', ' ').title()}\n"
                if isinstance(data, dict):
                    report += "| 时间 | 告警数量 |\n"
                    report += "|------|----------|\n"
                    for time, count in data.items():
                        report += f"| {time} | {count} |\n"
                report += "\n"

        if "patterns" in analysis and analysis["patterns"]:
            report += "## 模式识别\n"
            for section, data in analysis["patterns"].items():
                report += f"### {section.replace('_', ' ').title()}\n"
                if isinstance(data, dict):
                    for key, value in data.items():
                        report += f"- {key}: {value}\n"
                elif isinstance(data, list):
                    report += ", ".join(data)
                report += "\n"

        if "recommendations" in analysis and analysis["recommendations"]:
            report += "## 优化建议\n"
            for i, rec in enumerate(analysis["recommendations"], 1):
                report += f"{i}. {rec}\n"

        report += "\n## 后续步骤\n"
        report += ("1. 验证分析结果准确性\n"
                   "2. 实施优化建议\n"
                   "3. 监控告警变化趋势\n"
                   "4. 定期重新分析告警数据\n")

        return report

########################################################################################################################
########################################################################################################################
