# 架构与数据流

## 系统组件图

```mermaid
flowchart TB
    Browser["浏览器"]
    Home["主页 /app/home.html"]
    FinanceUI["财报掘金 /app/index.html"]
    ProfileUI["公司画像 /app/profile.html"]
    SummaryUI["3 分钟总结 /app/summary.html"]
    ScriptUI["短视频脚本 /app/summary-video.html"]
    SupportUI["查询中心 /app/support.html"]

    Browser --> Home
    Home -->|"ticker + market"| FinanceUI
    Home -->|"ticker + market"| ProfileUI
    Home -->|"ticker + market"| SummaryUI
    Home --> SupportUI
    SummaryUI --> ScriptUI

    subgraph MainApp["主应用：FastAPI backend/main.py"]
        Auth["认证 API"]
        ReportAPI["财报 Agent API"]
        ProfileAPI["公司画像 API"]
        SummaryAPI["3 分钟总结 API"]
        SupportAPI["查询中心 API"]
        LegacyAPI["兼容公司 / 报告 / 问答 API"]
    end

    FinanceUI --> ReportAPI
    ProfileUI --> ProfileAPI
    SummaryUI --> SummaryAPI
    SupportUI --> SupportAPI
    Browser --> Auth

    subgraph Domains["独立业务域"]
        Financial["financial_agent\n财务事实抽取、趋势与风险评估"]
        Profile["company_profile\n画像事实、综合与风险评估"]
        Summary["three_minute_summary\n总结、评分、追问、视频脚本"]
    end

    ReportAPI --> Financial
    ProfileAPI --> Profile
    SummaryAPI --> Summary

    subgraph DataPlatform["统一知识整理层：data_platform"]
        DataService["DataService"]
        Snapshot["SQLite 快照 / 元数据"]
        Canonical["标准化文档、页面、证据块、财务事实"]
        Assets["原始 SEC HTML / 巨潮 PDF"]
        ModelCache["模型运行与派生产物缓存"]
    end

    Financial --> DataService
    Profile --> DataService
    Summary --> DataService
    DataService --> Snapshot
    DataService --> Canonical
    DataService --> Assets
    DataService --> ModelCache

    subgraph External["外部依赖"]
        SEC["SEC EDGAR"]
        CNInfo["巨潮资讯"]
        Wiki["Wikipedia / 百度百科"]
        DeepSeek["DeepSeek OpenAI-compatible API"]
    end
    DataService --> SEC
    DataService --> CNInfo
    DataService --> Wiki
    Financial --> DeepSeek
    Profile --> DeepSeek
    Summary --> DeepSeek

    ScriptUI -->|"签名 Video Brief"| Media
    subgraph Media["独立媒体服务"]
        MediaAPI["media_production API"]
        Approval["管理员审批"]
        Worker["TTS / 即梦 / FFmpeg Worker"]
        MediaStore["独立媒体存储卷"]
    end
    MediaAPI --> Approval --> Worker --> MediaStore
```

## 强制解耦边界

1. `app/home.*` 仅负责输入、认证状态和跳转，不能包含财报、画像或总结的业务编排。
2. `financial_agent`、`company_profile`、`three_minute_summary` 是独立领域；允许共享 `DataService` 和标准化知识，但不直接互相 import 内部实现。
3. `data_platform` 可以访问外部公开数据源；业务域不应绕过它直接调用 SEC、巨潮或百科 Client。
4. `media_production` 只接收签名 `Video Brief`，使用独立存储与环境变量，禁止读取主应用 SQLite、财报缓存和 DeepSeek Key。
5. 前端页面仅经 HTTP API 耦合，不能依赖其他页面的 JavaScript 状态。

## 财报 Agent 时序

```mermaid
sequenceDiagram
    participant UI as 财报页面
    participant API as FinancialAnalysisOrchestrator
    participant Data as DataService
    participant LLM as DeepSeek
    participant DB as 本地知识库

    UI->>API: 创建分析任务(ticker, market, periods)
    API->>Data: 解析公司、读取财务数据与披露
    Data-->>API: 已验证事实 + 标准化证据块
    API->>DB: 以输入指纹查询模型缓存
    alt 缓存命中
        DB-->>API: 已完成 Agent 结果
    else 缓存未命中
        API->>LLM: 事实与风险事实抽取
        API->>LLM: 财务趋势综合
        API->>LLM: 风险等级评估
        API->>DB: 保存模型运行与证据产物
    end
    API-->>UI: 轮询任务完成，返回分析
```

