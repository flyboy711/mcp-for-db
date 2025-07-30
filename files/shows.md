
提问：深度分析仓库源码逻辑，帮我生成一份精美的完整的整体架构设计图以及各个组件模块之间的逻辑调用图给我。

再次提问：生成的太宏观了，请再次生成一份精美的细致的整体架构图以及各个模块之间的执行流程图，以及客户端请求服务端后，服务端的执行流程和响应结果的整体流程图。



## 系统架构图

上面生成的整体架构图已经非常完美了，但还存在一些问题，如下代码是我修改后的，请你美化一下颜色和各个模块之间的排版以及模块之间箭头要双向表明请求和响应是完整的，最后可视化出来：

```Mermaid
graph LR
    classDef process fill:#E5F6FF,stroke:#73A6FF,stroke-width:2px;
    classDef subgraphFill fill:#f9f9f9,stroke:#ccc,stroke-width:2px;
    
    subgraph 用户端
        style 用户端 fill:#ffffff,stroke:#000000,stroke-width:2px,shape:rounded
        VSCode(VSCode Cline插件):::process
        Browser(浏览器):::process
    end
    
    subgraph 服务端
        style 服务端 fill:#ffffff,stroke:#000000,stroke-width:2px,shape:rounded
        
        subgraph 认证模块
            style 认证模块 fill:#e6f7ff,stroke:#91caff,stroke-width:1px,shape:rounded
            OAuth(OAuth 2.0认证):::process
        end

        subgraph SQL鉴权模块
            style SQL鉴权模块 fill:#e6f7ff,stroke:#91caff,stroke-width:1px,shape:rounded
            SQLIntercept(SQL拦截解析权限认证):::process
        end
        
        subgraph 工具模块
            style 工具模块 fill:#fff6cc,stroke:#ffbc52,stroke-width:1px,shape:rounded
            SmartTool(智能工具协调器):::process
            GetTableName(表名查找器):::process
            GetTableDesc(表结构查询器):::process
            SqlExecutor(SQL执行器):::process
            AnalyzeQuery(查询性能分析器):::process
            LogTool(SQL执行日志工具):::process
            OtherTools(其他工具):::process
        end
        
        subgraph 工作流模块
            style 工作流模块 fill:#d9f7be,stroke:#95de64,stroke-width:1px,shape:rounded
            Workflow(工作流编排器):::process
        end
        
        subgraph 提示词模块
            style 提示词模块 fill:#e9d8fd,stroke:#b37feb,stroke-width:1px,shape:rounded
            QueryTableDataPrompt(查询表数据提示词):::process
            PerformOptPrompt(性能优化提示词):::process
            IndexOptAdvisorPrompt(索引优化顾问提示词):::process
        end

        subgraph 资源模块
            style 资源模块 fill:#fff0f6,stroke:#ff85c0,stroke-width:1px,shape:rounded
            LogsResources(系统SQL执行日志资源):::process
        end
        
        Server(server_mysql):::process
    end
    
    subgraph 数据库管理器
        style 数据库管理器 fill:#ffffff,stroke:#000000,stroke-width:2px,shape:rounded
        DBManager(MySQL数据库管理器):::process
    end

    subgraph 数据库
        style 数据库 fill:#ffffff,stroke:#000000,stroke-width:2px,shape:rounded
        MySQL(MySQL数据库):::process
    end
    
    VSCode <-->|请求/响应| Server
    Browser <-->|请求/响应| Server
    Server <-->|认证请求/结果| OAuth
    Server <-->|任务分发/状态反馈| SmartTool
    Server <-->|调用请求/返回结果| GetTableName
    Server <-->|调用请求/返回结果| GetTableDesc
    Server <-->|调用请求/返回结果| SqlExecutor
    Server <-->|调用请求/返回结果| AnalyzeQuery
    Server <-->|调用请求/返回结果| LogTool
    Server <-->|调用请求/返回结果| OtherTools
    SmartTool <-->|任务编排/状态更新| Workflow
    Workflow <-->|工具调用/执行结果| GetTableName
    Workflow <-->|工具调用/执行结果| GetTableDesc
    Workflow <-->|工具调用/执行结果| SqlExecutor
    Workflow <-->|工具调用/执行结果| AnalyzeQuery
    Workflow <-->|工具调用/执行结果| LogTool
    Workflow <-->|工具调用/执行结果| OtherTools
    LogTool <-->|日志记录/日志获取| LogsResources
    LogsResources <-->|日志反馈/日志请求| Server
    GetTableName <-->|表名提供/需求确认| SqlExecutor
    GetTableDesc <-->|表结构提供/需求确认| SqlExecutor
    AnalyzeQuery <-->|性能分析提供/需求确认| SqlExecutor
    OtherTools <-->|辅助信息提供/需求确认| SqlExecutor
    SqlExecutor <-->|待鉴权SQL/鉴权结果| SQLIntercept
    SQLIntercept <-->|鉴权通过/操作结果| DBManager
    DBManager <-->|数据操作/操作结果| MySQL
    QueryTableDataPrompt -->|指导| SmartTool
    PerformOptPrompt -->|指导| SmartTool
    IndexOptAdvisorPrompt -->|指导| SmartTool
    QueryTableDataPrompt -->|指导| OtherTools
    PerformOptPrompt -->|指导| OtherTools
    IndexOptAdvisorPrompt -->|指导| OtherTools
    QueryTableDataPrompt -->|指导| SqlExecutor
    PerformOptPrompt -->|指导| SqlExecutor
    IndexOptAdvisorPrompt -->|指导| SqlExecutor
```

## 模块之间的关系图

上面生成的模块之间的关系图已经非常完美了，但还存在一些问题，如下代码是我修改后的，请你美化一下颜色和各个模块之间的排版以及模块之间箭头要双向表明请求和响应是完整的，最后可视化出来：

```mermaid
graph LR
    classDef process fill:#E5F6FF,stroke:#73A6FF,stroke-width:2px,shape:rounded
    
    subgraph 用户交互
        style 用户交互 fill:#ffffff,stroke:#000000,stroke-width:2px,shape:rounded
        A(用户输入自然语言指令):::process
        N(提示词模块):::process
        A <-->|指令/提示| N
    end
    
    subgraph 处理核心
        style 处理核心 fill:#ffffff,stroke:#000000,stroke-width:2px,shape:rounded
        B(LLM):::process
        C{解析自然语言指令生成工具的参数}:::process
        B <-->|指令解析/结果反馈| C
    end
    
    subgraph 工具模块
        style 工具模块 fill:#ffffff,stroke:#000000,stroke-width:2px,shape:rounded
        D(工具集合):::process
        E(数据查询工具):::process
        D <-->|工具选择/调用结果| B
        C <-->|调用请求/执行结果| E
    end
    
    subgraph 数据模块
        style 数据模块 fill:#ffffff,stroke:#000000,stroke-width:2px,shape:rounded
        F(查询数据):::process
        E <-->|查询请求/查询结果| F
        F <-->|数据/处理需求| B
    end
    
    A <-->|指令/处理结果| B
```


## 客户端请求服务端后，服务端的执行流程和响应结果的整体流程图

上面生成的客户端请求服务端后，服务端的执行流程和响应结果的整体流程图有些简单了，缺少通信机制，会话管理等逻辑流程。现在我想让你再次深入的分析仓库源码逻辑，修改如下绘图代码可视化从用户在客户端发起提问请求，到服务器端进行解析调用工具处理数据，再返回给客户端的完整流程：

```mermaid
graph LR
    classDef client fill:#e6f7ff,stroke:#91caff,stroke-width:2px;
    classDef server fill:#fff6cc,stroke:#ffbc52,stroke-width:2px;
    classDef db fill:#d9f7be,stroke:#95de64,stroke-width:2px;
    classDef process fill:transparent,stroke-width:0px;
    
    subgraph 客户端
        style 客户端 fill:#ffffff,stroke:#000000,stroke-width:2px,shape:rounded
        A(用户输入提问):::client
        B(客户端LLM):::client
        C(客户端请求生成):::client
        D(客户端接收响应):::client
        
        A --> B
        B -->|解析提问| C
    end
    
    subgraph 服务器端
        style 服务器端 fill:#ffffff,stroke:#000000,stroke-width:2px,shape:rounded
        
        subgraph 通信层
            style 通信层 fill:#fff6cc,stroke:#ffbc52,stroke-width:1px,shape:rounded
            E(接收客户端请求):::server
            F(Streamable HTTP):::server
            G(SSE):::server
            H(STDIO):::server
            I(发送响应到客户端):::server
        end
        
        subgraph 会话管理
            style 会话管理 fill:#fff6cc,stroke:#ffbc52,stroke-width:1px,shape:rounded
            J(会话初始化):::server
            K(会话状态跟踪):::server
            L(会话关闭):::server
        end
        
        subgraph 工具调度
            style 工具调度 fill:#fff6cc,stroke:#ffbc52,stroke-width:1px,shape:rounded
            M(智能工具协调器):::server
            N(工作流编排器):::server
            O(工具执行器):::server
        end
        
        subgraph 数据库管理
            style 数据库管理 fill:#d9f7be,stroke:#95de64,stroke-width:1px,shape:rounded
            P(数据库连接池):::db
            Q(数据库操作):::db
            R(数据库关闭):::db
        end
        
        E --> J
        J --> K
        K --> F
        K --> G
        K --> H
        F --> M
        G --> M
        H --> M
        M -->|复杂任务| N
        M -->|简单任务| O
        N --> O
        O --> P
        P --> Q
        Q --> I
        I --> D
        K -->|会话结束| L
        L --> R
    end
    
    C --> E
    D -->|会话是否结束| K
```

## 服务启动脚本架构图

```mermaid
%% 优化后架构图 - 增强视觉层次与可读性
graph TB
    %% 样式定义 - 增强区分度
    classDef handler fill:#e1f5fe,stroke:#0288d1,stroke-width:2px,rx:5
    classDef registry fill:#e8f5e9,stroke:#388e3c,stroke-width:2px,rx:5
    classDef transport fill:#fff3e0,stroke:#ff9800,stroke-width:2px,rx:5
    classDef core fill:#bbdefb,stroke:#1976d2,stroke-width:2px,rx:8,font-weight:bold
    classDef session fill:#ffebee,stroke:#e53935,stroke-width:2px,rx:5
    classDef subgraphTitle fill:#f5f5f5,font-weight:bold,font-size:14px

    %% ========== 左侧区域 - 垂直紧凑布局 ==========
    subgraph Left[<b>Handler Functions</b>]
        direction TB
        A1["@app.list_tools()"] 
        A2["@app.call_tool()"]
        A3["@app.list_resources()"]
        A4["@app.read_resource()"]
        A5["@app.list_prompts()"]
        A6["@app.get_prompts()"]
        class A1,A2,A3,A4,A5,A6 handler
    end

    subgraph LeftRegistry[<b>Registry Systems</b>]
        direction LR
        B1[ToolRegistry]
        B2[ResourceRegistry]
        B3[PromptRegistry]
        class B1,B2,B3 registry
    end

    %% 左侧连接 - 增加视觉指引
    A1 -->|查询/调用| B1
    A2 -->|查询/调用| B1
    A3 -->|查询/读取| B2
    A4 -->|查询/读取| B2
    A5 -->|查询/获取| B3
    A6 -->|查询/获取| B3

    %% ========== 右侧区域 - 模块化分层 ==========
    subgraph Right[<b>Transport Layer</b>]
        direction TB
        C1["run_stdio()"]
        C2["run_sse()"]
        C3["run_streamable_http()"]
        class C1,C2,C3 transport
    end

    subgraph Core[<b>MCP Server Core</b>]
        D1[("Server('mcp-for-db')")]:::core
        D2["initialize_global_resources()"]
        D3["close_global_resources()"]
        class D2,D3 core
    end

    subgraph Session[<b>Session Management</b>]
        direction LR
        E1[SessionConfigManager]
        E2[DatabaseManager]
        E3[RequestContext]
        class E1,E2,E3 session
    end

    %% 右侧连接 - 区分连接类型
    C1 -->|启动| D1
    C2 -->|启动| D1
    C3 -->|启动| D1

    D1 -->|初始化| D2
    D1 -->|释放| D3

    E1 -->|配置| E2
    E2 -->|管理| E3

    %% 跨区域核心连接 - 突出关键链路
    D1 -->|依赖| E1
    D1 -.->|上下文传递| E3

    %% 布局调整 - 增加间距与层次
    Left ~~~ LeftRegistry
    Right ~~~ Core
    Core ~~~ Session
    LeftRegistry ~~~ Core
```


### 服务脚本生命周期图

```mermaid
sequenceDiagram
    %% 参与者定义（严格保持原图从左至右顺序）
    participant M as main()
    participant G as global_default_session_config
    participant I as initialize_global_resources()
    participant T as Transport Layer
    participant C as close_global_resources()

    %% ===== 配置初始化阶段 =====
    Note left of M: 配置初始化
    M ->> G: Create SessionConfigManager()
    activate G
    G ->> G: Load .env configurations
    G ->> G: Update default config
    deactivate G
    
    %% ===== 资源初始化阶段 =====
    Note left of M: 资源预加载
    M ->> I: initialize_global_resources()
    activate I
    I ->> I: Initiate global resources
    I ->> I: QueryLogResource.start_flush_thread()
    I -->> M: resources_initialized = True
    deactivate I
    
    %% ===== 核心请求处理阶段 =====（黄色高亮区）
    rect rgba(255, 255, 0, 0.3)
        Note over T: 请求处理核心区
        M ->> T: Start transport (stdio/sse/http)
        activate T
        loop 持续处理客户端请求
            T ->> T: Handle client requests
        end
        deactivate T
    end
    
    %% ===== 资源清理阶段 =====
    Note left of M: 关闭清理
    M ->> C: close_global_resources()
    activate C
    C ->> C: Cleanup on shutdown
    C ->> C: get_current_database_manager().close_pool()
    C ->> C: QueryLogResource.stop_flush_thread()
    C -->> M: resources_initialized = False
    deactivate C
    
    %% ===== 结束流程 =====
    M ->> M: Shutdown complete
```






## 整个工具框架设计图

```mermaid
graph LR;
    classDef startend fill:#F5EBFF,stroke:#BE8FED,stroke-width:2px;
    classDef process fill:#E5F6FF,stroke:#73A6FF,stroke-width:2px;
    classDef decision fill:#FFF6CC,stroke:#FFBC52,stroke-width:2px;
    
    A(BaseHandler):::process -->|子类继承并初始化| B(ToolRegistry):::process;
    B -->|注册工具| C(ToolSelector):::process;
    B -->|注册工具| D(WorkflowOrchestrator):::process;
    C -->|推荐工具| E(SmartTool):::process;
    C -->|选择主工具| E;
    D -->|生成工作流| E;
    E -->|执行工作流| B;
    F(用户请求):::process --> E;
    E -->|返回结果| F;
    G(资源注册表):::process -->|提供资源| E;

```

### 工具注册逻辑图

```mermaid
%% 工具注册流程图（优化视觉层次与交互指引）
graph LR
    %% 样式定义 - 增强区分度与质感
    classDef process fill:#e3f2fd,stroke:#1976d2,stroke-width:2px,rx:6;
    classDef registry fill:#e8f5e9,stroke:#388e3c,stroke-width:2px,rx:6;
    classDef enhance fill:#fff3e0,stroke:#fb8c00,stroke-width:2px,rx:6;
    classDef methods fill:#f5f5f5,stroke:#616161,stroke-width:1.5px,rx:4;
    classDef highlight stroke:#424242,stroke-width:2.5px;

    %% ========== 主注册流程（增强步骤说明） ==========
    A[("🔧 Tool Class<br/>Inherits BaseHandler")]:::process
    B[["📝 init_subclass<br/>Auto Registration"]]:::process
    C[("📦 ToolRegistry._tools<br/>Dict[str, BaseHandler]")]:::registry
    D[["✨ Enhanced Description<br/>Application"]]:::enhance

    %% 主流程连接（添加交互说明）
    A -->|继承并触发| B
    B -->|自动注册到| C
    C -->|应用元数据增强| D

    %% ========== 工具访问方法区（优化布局与标识） ==========
    subgraph Methods[<b>Tool Access Methods</b>]
        direction TB
        M1["▸ get_tool(name)<br/>Single Tool Retrieval"]
        M2["▸ get_all_tools()<br/>All Tool Descriptions"]
        M3["▸ execute_workflow()<br/>Multi-tool Execution"]
        class M1,M2,M3 methods
    end

    %% 连接关系（明确数据流向）
    D -->|支持| Methods
    C -.->|实时同步注册信息| M2

    %% 布局调整（增加呼吸感）
    A ~~~ B
    B ~~~ C
    C ~~~ D
    D ~~~ Methods

    %% 强调核心节点
    style C highlight
    style Methods stroke:#616161,stroke-width:2px
```



## 数据库管理类

```mermaid
classDiagram
    class SessionConfigManager {
        +__init__(initial_config: Optional[Dict[str, Any]] = None)
        +_normalize_external_config(raw_config: Dict[str, Any]): Dict[str, Any]
        +_update_hash()
        +_parse_int_env(key: str, default: int): int
        +_parse_float_env(key: str, default: float): float
        +_parse_bool_env(key: str, default: bool): bool
        +_parse_risk_levels(levels_str: str): Set[SQLRiskLevel]
        +_load_from_env(env_path: str = ".env")
        +get(key: str): Any
        +update(config: Dict[str, Any])
    }

    class DatabaseManager {
        +__init__(session_config: SessionConfigManager)
        +state: DatabaseConnectionState
        +async close_all_instances()
        +async close_pool()
        +async ensure_pool()
        +async initialize_pool(max_retries: int = 3)
        +get_current_config(): Dict[str, Any]
        +_compute_config_hash(config: Dict[str, Any]): str
        +_build_connection_params(): Dict[str, Any]
        +async _try_alternative_auth(params: Dict[str, Any], max_retries: int)
        +_handle_connection_error(e: Exception)
    }

    class DatabaseConnectionState {
        <<enumeration>>
        UNINITIALIZED
        ACTIVE
        CLOSED
        ERROR
        RECONNECTING
    }

    class DatabasePermissionError {
        +__init__(message: str, operation: str, table: str)
    }

    SessionConfigManager "1" -- "1" DatabaseManager : contains
    DatabaseManager "1" -- "1" DatabaseConnectionState : has state
    DatabaseManager "1" -- "1" DatabasePermissionError : may raise
```



## SQL鉴权逻辑链路图

```mermaid
graph LR
    classDef startend fill:#F5EBFF,stroke:#BE8FED,stroke-width:2px
    classDef process fill:#E5F6FF,stroke:#73A6FF,stroke-width:2px
    classDef decision fill:#FFF6CC,stroke:#FFBC52,stroke-width:2px
    
    A([用户发起 SQL 请求]):::startend --> B(QueryLimiter):::process
    B -->|检查 SQL 长度| C{长度是否超过限制?}:::decision
    C -- 是 --> D(拒绝执行):::process
    C -- 否 --> E(SQLParser):::process
    E -->|解析 SQL| F(分析操作类型、表等信息):::process
    F --> G(SQLRiskAnalyzer):::process
    G -->|确定风险等级| H{风险是否允许?}:::decision
    H -- 否 --> D
    H -- 是 --> I(DatabaseScopeChecker):::process
    I -->|检查数据库范围| J{是否符合范围?}:::decision
    J -- 否 --> D
    J -- 是 --> K(SQLInterceptor):::process
    K -->|综合检查| L{是否允许执行?}:::decision
    L -- 是 --> M(执行 SQL):::process
    L -- 否 --> D
    D --> N([返回错误信息]):::startend
    M --> O([返回执行结果]):::startend
    
    P(SessionConfigManager):::process --> B
    P --> E
    P --> G
    P --> I
    P --> K
```


