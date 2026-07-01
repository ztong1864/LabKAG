# LabKAG v0.1 设计文档

## 0. 文档信息

| 项目 | 内容 |
|---|---|
| 文档名称 | LabKAG v0.1 设计文档 |
| 版本 | v0.1 |
| 架构路线 | Skill-first 架构 |
| 后端底座 | OpenSPG / KAG |
| 第一阶段范围 | 文献抽取、文献知识入图、文献证据检索、文献问答 |
| 不包含范围 | 实验记录、样品追踪、试剂管理、仪器数据、失败案例、实验复现性检查 |
| 目标形态 | 可被外部大模型、Agent、科研助手或工作流系统调用的外接 Skill |
| 核心交付 | LabKAG Skill Server + 文献抽取 Schema + OpenSPG/KAG 适配层 + 5 个核心 Skill Function |

---

## 1. 项目定位

### 1.1 LabKAG 总体定位

**LabKAG**，即 **Laboratory Knowledge Augmented Generation**，是面向科学实验室场景的知识增强生成框架。

LabKAG 的长期目标是将实验室中的科研文献、实验记录、实验方案、样品信息、试剂耗材、仪器数据、测量结果、失败案例和人员经验组织为可追溯、可检索、可推理的知识体系，并通过大语言模型和知识图谱推理，为实验设计、实验复现、异常分析和科研决策提供智能支持。

### 1.2 v0.1 定位

LabKAG v0.1 不直接实现完整实验室系统，而是实现一个 **外接 Skill**。

v0.1 的目标是：

> **构建一个基于 OpenSPG/KAG 的 LabKAG Skill Server，对外提供文献抽取、文献知识入图、证据检索和文献问答能力。**

换句话说，v0.1 不是一个独立网页产品，而是一个可以被外部大模型、Agent、ChatGPT、科研助手或自动化工作流调用的能力模块。

系统调用关系如下：

```text
外部大模型 / Agent / 科研助手 / 工作流系统
-> LabKAG Skill API
-> LabKAG Orchestrator
-> 文献解析与抽取模块
-> OpenSPG / KAG
-> 返回结构化结果 + Evidence
```

---

## 2. 设计目标

### 2.1 v0.1 核心目标

LabKAG v0.1 的核心目标是跑通以下闭环：

```text
论文输入
-> 文献解析
-> 文献结构化抽取
-> Evidence 绑定
-> OpenSPG Schema 映射
-> KAG 知识库构建
-> 文献证据检索
-> 文献问答
-> 外部 Skill 调用返回
```

### 2.2 能力目标

v0.1 需要实现以下能力：

1. **文献解析能力**
   - 支持 PDF 文献输入；
   - 支持文本型 PDF 解析；
   - 生成带页码和 chunk_id 的文献切片。

2. **文献抽取能力**
   - 抽取论文元数据；
   - 抽取研究对象、方法、材料、实验条件、指标、结果和结论；
   - 输出结构化 JSON。

3. **证据绑定能力**
   - 每个关键结果和结论必须绑定来源；
   - 来源包括 page、chunk_id、source_text；
   - 支持外部系统追溯原文。

4. **OpenSPG/KAG 入库能力**
   - 将文献抽取结果映射为 OpenSPG/KAG 可接收的实体和关系；
   - 写入文献知识库；
   - 支持后续基于 KAG 的检索和问答。

5. **Skill API 能力**
   - 通过标准 HTTP API 暴露；
   - API 返回稳定 JSON；
   - 支持外部 Agent 调用；
   - 不暴露底层 OpenSPG/KAG 复杂接口。

---

## 3. v0.1 范围边界

### 3.1 v0.1 包含内容

v0.1 仅聚焦 **文献 KAG**。

包含：

```text
PDF 上传 / 输入
PDF 文本解析
文献 chunk
论文元数据抽取
方法 / 材料 / 条件 / 指标 / 结果 / 结论抽取
Evidence 绑定
OpenSPG Schema 映射
文献知识入图
KAG 文献问答
Skill API 封装
OpenAPI 文档
示例调用脚本
```

### 3.2 v0.1 不包含内容

v0.1 暂不实现完整实验室对象。

不包含：

```text
实验记录抽取
样品追踪
试剂批次管理
仪器数据解析
实验失败案例
实验复现性检查
谱图 / 图像理解
复杂权限系统
自动实验建议
SOP 审计
ELN / LIMS 对接
```

这些能力放入后续版本：

```text
v0.2：实验记录抽取
v0.3：样品、试剂、仪器和失败案例
v0.4：复现性检查和实验推理
```

---

## 4. 总体架构

### 4.1 架构原则

LabKAG v0.1 采用 **Skill-first 架构**。

OpenSPG/KAG 作为内部知识图谱与问答推理底座，不直接暴露给外部调用方。外部调用方只访问 LabKAG Skill API。

这种设计有三个好处：

1. 外部 Agent 不需要理解 OpenSPG/KAG 的内部接口；
2. LabKAG 可以定义自己的稳定 API Contract；
3. 后续即使替换或升级 OpenSPG/KAG，也不影响外部调用方。

---

### 4.2 总体架构图

```text
┌─────────────────────────────────────────────────────────────┐
│ 外部调用方                                                   │
│ ChatGPT / Agent / 科研助手 / 自动化工作流 / 其他应用系统       │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│ LabKAG Skill API 层                                         │
│ extract_paper / ingest_paper / query_literature             │
│ search_evidence / get_paper_knowledge                       │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│ LabKAG Orchestrator 编排层                                   │
│ 参数校验 / 任务路由 / 状态管理 / 错误处理 / 响应格式化          │
└─────────────────────────────────────────────────────────────┘
                              │
                 ┌────────────┼────────────┐
                 ▼            ▼            ▼
┌──────────────────────┐ ┌──────────────────────┐ ┌──────────────────────┐
│ 文献处理层            │ │ 文献抽取层            │ │ Evidence 绑定层      │
│ PDF Parser / Chunker │ │ LLM Extractor        │ │ page / chunk / quote │
└──────────────────────┘ └──────────────────────┘ └──────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│ OpenSPG/KAG Adapter 层                                      │
│ Schema 映射 / 实体转换 / 关系转换 / 入图 / 查询适配            │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│ OpenSPG / KAG 后端                                          │
│ 领域模型 / 知识图谱 / 检索 / 推理 / 问答                      │
└─────────────────────────────────────────────────────────────┘
```

---

## 5. 核心模块设计

## 5.1 LabKAG Skill API 层

### 5.1.1 模块职责

Skill API 层是 LabKAG v0.1 的对外入口。

它负责：

```text
接收外部调用
校验请求参数
调用内部服务
返回标准 JSON
提供 OpenAPI 文档
屏蔽 OpenSPG/KAG 内部复杂度
```

### 5.1.2 v0.1 核心 Skill Function

v0.1 暴露 5 个核心函数：

```text
extract_paper
ingest_paper
query_literature
search_evidence
get_paper_knowledge
```

---

## 5.2 文献处理层

### 5.2.1 模块职责

文献处理层负责将论文文件转化为可抽取、可检索、可绑定证据的文本结构。

### 5.2.2 支持输入

v0.1 先支持：

```text
PDF 文件
纯文本
Markdown
```

v0.1 不支持或弱支持：

```text
扫描 PDF
图片型 PDF
复杂表格解析
复杂图像理解
公式语义解析
```

### 5.2.3 文档解析结果

解析后输出：

```json
{
  "document_id": "doc_001",
  "file_name": "paper.pdf",
  "title": "",
  "pages": [
    {
      "page": 1,
      "text": ""
    }
  ],
  "chunks": [
    {
      "chunk_id": "chunk_001",
      "page": 1,
      "section_title": "Abstract",
      "text": ""
    }
  ]
}
```

### 5.2.4 Chunk 设计原则

文献 chunk 必须满足：

1. 保留 `document_id`；
2. 保留 `chunk_id`；
3. 保留 `page`；
4. 尽量保留 `section_title`；
5. 保持语义完整；
6. 支持后续 Evidence 绑定。

---

## 5.3 文献抽取层

### 5.3.1 模块职责

文献抽取层负责从论文文本中抽取结构化知识。

v0.1 只抽取文献级知识，不抽取真实实验室内部记录。

### 5.3.2 抽取对象

v0.1 抽取以下对象：

```text
Paper
Method
Material
Condition
Metric
Result
Conclusion
Evidence
```

暂不作为第一版实体建模：

```text
Author
Institution
ResearchObject
ResearchProblem
```

说明：作者先保存在 `Paper.authors`；研究对象先由 `Material` 承担；研究问题先保留在
`Paper.abstract`、`Result` 或 `Conclusion` 的文本描述里。

### 5.3.3 抽取策略

采用 LLM 结构化抽取。

基本流程：

```text
文献 chunks
-> 按 section 或全文组织 prompt
-> LLM 输出结构化 JSON
-> JSON Schema 校验
-> Evidence 对齐检查
-> 返回 PaperExtractionResult
```

### 5.3.4 抽取原则

1. 不抽取没有证据的结果；
2. 结果和结论必须带 evidence；
3. 条件、指标、结果尽量保留单位；
4. 不确定字段允许为空；
5. 模型推测必须标记为 inferred，不可作为确定事实。

---

## 5.4 Evidence 绑定层

### 5.4.1 模块职责

Evidence 绑定层负责把抽取出的实体、结果、结论和原文来源关联起来。

### 5.4.2 Evidence 字段

```json
{
  "evidence_id": "ev_001",
  "document_id": "doc_001",
  "chunk_id": "chunk_012",
  "page": 5,
  "section_title": "Results",
  "source_text": "",
  "offset_start": 0,
  "offset_end": 100
}
```

### 5.4.3 Evidence 绑定规则

1. 每个 Result 必须至少有一个 Evidence；
2. 每个 Conclusion 必须至少有一个 Evidence；
3. Evidence 必须来自原始文档 chunk；
4. 如果无法绑定 Evidence，则该 Result 或 Conclusion 标记为 `needs_review`；
5. 不允许生成没有来源的确定结论。

---

## 5.5 OpenSPG/KAG Adapter 层

### 5.5.1 模块职责

Adapter 层负责将 LabKAG 的中间 JSON 转换为 OpenSPG/KAG 可用的数据结构。

该层不暴露给外部调用方，只作为内部适配模块。

### 5.5.2 Adapter 职责

```text
读取 PaperExtractionResult
映射 LabKAG Literature Schema
生成实体
生成关系
生成 Evidence 节点
调用 OpenSPG/KAG 写入接口
调用 KAG 查询接口
统一异常处理
返回标准结果
```

### 5.5.3 为什么需要 Adapter

不建议外部调用方直接调用 OpenSPG/KAG，原因是：

1. OpenSPG/KAG 接口可能变化；
2. LabKAG 需要自己的领域 Schema；
3. 外部 Skill API 需要稳定；
4. 后续可能替换知识图谱底座；
5. LabKAG 需要统一 Evidence 返回格式。

---

## 5.6 KAG 查询层

### 5.6.1 模块职责

KAG 查询层负责基于已入库文献知识完成检索、推理和问答。

### 5.6.2 查询类型

v0.1 支持：

```text
论文摘要类问题
方法类问题
材料类问题
实验条件类问题
指标类问题
结果类问题
结论证据类问题
相似研究对象检索
```

### 5.6.3 示例问题

```text
这篇论文研究了什么？
这篇论文提出了什么方法？
这篇论文使用了哪些材料？
这篇论文报告了哪些实验结果？
哪个结果支持了作者的结论？
哪些论文研究了同一种材料？
哪些论文使用了类似方法？
```

---

## 6. LabKAG Literature Schema v0.1

### 6.1 Schema 名称

```text
LabKAG_Literature_v0_1
```

### 6.2 实体类型

#### Paper

论文实体。

字段：

```text
paper_id
title
authors
year
journal
doi
abstract
keywords
document_id
```

#### Method

方法实体。

字段：

```text
method_id
name
description
method_type
```

#### Material

材料或研究材料实体。

字段：

```text
material_id
name
material_type
description
```

#### Condition

实验条件。

字段：

```text
condition_id
name
value
unit
normalized_value
normalized_unit
description
```

#### Metric

评价指标。

字段：

```text
metric_id
name
value
unit
description
```

#### Result

实验结果或研究结果。

字段：

```text
result_id
description
value
unit
result_type
```

#### Conclusion

论文结论。

字段：

```text
conclusion_id
description
scope
```

#### Evidence

证据节点。

字段：

```text
evidence_id
document_id
chunk_id
page
section_title
source_text
```

---

### 6.3 关系类型

v0.1 定义以下关系：

```text
Paper proposes Method
Paper uses Material
Paper hasCondition Condition
Paper measures Metric
Paper reports Result
Paper drawsConclusion Conclusion
Paper hasEvidence Evidence

Method supportedBy Evidence
Material supportedBy Evidence
Condition supportedBy Evidence
Metric supportedBy Evidence
Result supportedBy Evidence
Conclusion supportedBy Evidence
```

### 6.4 v0.1 最小关系

第一版最小必须实现：

```text
Paper proposes Method
Paper uses Material
Paper hasCondition Condition
Paper measures Metric
Paper reports Result
Paper drawsConclusion Conclusion
Paper hasEvidence Evidence
Method supportedBy Evidence
Material supportedBy Evidence
Condition supportedBy Evidence
Metric supportedBy Evidence
Result supportedBy Evidence
Conclusion supportedBy Evidence
```

---

## 7. 中间 JSON Schema

### 7.1 设计目的

LabKAG v0.1 不建议直接让 LLM 输出 OpenSPG/KAG 的底层格式。

推荐增加中间结构：

```text
PaperExtractionResult
```

好处：

1. 便于调试；
2. 便于人工检查；
3. 便于重复入库；
4. 便于未来替换 OpenSPG/KAG；
5. 便于给外部 Agent 返回结构化结果。

---

### 7.2 PaperExtractionResult 示例

```json
{
  "paper": {
    "title": "",
    "authors": [],
    "year": "",
    "doi": "",
    "journal": "",
    "abstract": "",
    "keywords": []
  },
  "research": {
    "research_objects": [],
    "research_problems": [],
    "methods": [
      {
        "name": "",
        "description": "",
        "evidence": []
      }
    ],
    "materials": [
      {
        "name": "",
        "type": "",
        "description": "",
        "evidence": []
      }
    ]
  },
  "experiments": [
    {
      "experiment_name": "",
      "conditions": [
        {
          "name": "",
          "value": "",
          "unit": "",
          "evidence": []
        }
      ],
      "metrics": [
        {
          "name": "",
          "value": "",
          "unit": "",
          "evidence": []
        }
      ],
      "results": [
        {
          "description": "",
          "value": "",
          "unit": "",
          "evidence": []
        }
      ],
      "conclusions": [
        {
          "description": "",
          "evidence": []
        }
      ]
    }
  ],
  "evidence": [
    {
      "evidence_id": "",
      "chunk_id": "",
      "page": 0,
      "section_title": "",
      "source_text": ""
    }
  ],
  "metadata": {
    "document_id": "",
    "extractor_version": "v0.1",
    "created_at": ""
  }
}
```

---

## 8. Skill Function 设计

## 8.1 统一返回格式

所有 Skill Function 统一返回：

```json
{
  "status": "success",
  "data": {},
  "evidence": [],
  "warnings": [],
  "errors": [],
  "metadata": {
    "request_id": "",
    "project_id": "",
    "created_at": ""
  }
}
```

### 8.1.1 status

可选值：

```text
success
partial_success
failed
needs_review
```

### 8.1.2 warnings

用于返回非致命问题，例如：

```text
PDF 存在无法解析页面
部分结果未绑定 evidence
部分字段缺失
OpenSPG 入库部分成功
```

### 8.1.3 errors

用于返回错误：

```text
file_not_found
parse_failed
extract_failed
schema_validation_failed
openspg_write_failed
kag_query_failed
```

---

## 8.2 extract_paper

### 8.2.1 功能说明

从论文 PDF 或文本中抽取结构化文献信息。

该函数只抽取，不写入 OpenSPG/KAG。

### 8.2.2 输入

```json
{
  "file_id": "paper_001.pdf",
  "project_id": "labkag_demo",
  "extract_level": "basic",
  "return_chunks": false
}
```

### 8.2.3 参数说明

| 参数 | 类型 | 必填 | 说明 |
|---|---|---|---|
| file_id | string | 是 | 已上传文件 ID |
| project_id | string | 否 | 项目 ID |
| extract_level | string | 否 | basic / detailed |
| return_chunks | boolean | 否 | 是否返回 chunk |

### 8.2.4 输出

```json
{
  "status": "success",
  "data": {
    "paper_extraction": {}
  },
  "evidence": [],
  "warnings": [],
  "errors": [],
  "metadata": {
    "request_id": "req_001",
    "project_id": "labkag_demo",
    "created_at": "2026-06-29T00:00:00Z"
  }
}
```

---

## 8.3 ingest_paper

### 8.3.1 功能说明

将论文抽取结果写入 OpenSPG/KAG 文献知识库。

### 8.3.2 输入

```json
{
  "project_id": "labkag_demo",
  "paper_extraction": {},
  "confirm": true
}
```

### 8.3.3 输出

```json
{
  "status": "success",
  "data": {
    "paper_id": "paper_001",
    "entities_created": 18,
    "relations_created": 27,
    "evidence_created": 12
  },
  "evidence": [],
  "warnings": [],
  "errors": [],
  "metadata": {
    "request_id": "req_002",
    "project_id": "labkag_demo",
    "created_at": "2026-06-29T00:00:00Z"
  }
}
```

### 8.3.4 规则

1. `confirm=false` 时只做 dry-run；
2. `confirm=true` 时写入 OpenSPG/KAG；
3. 入库前必须完成 JSON Schema 校验；
4. 缺少 Evidence 的 Result / Conclusion 不应作为确定事实入库，或需标记为 `needs_review`。

---

## 8.4 query_literature

### 8.4.1 功能说明

对已入库文献做 KAG 问答。

### 8.4.2 输入

```json
{
  "question": "这篇论文提出了什么方法？",
  "project_id": "labkag_demo",
  "paper_id": "paper_001",
  "top_k": 5
}
```

### 8.4.3 输出

```json
{
  "status": "success",
  "data": {
    "answer": "",
    "related_entities": [],
    "reasoning_path": [],
    "confidence": "medium"
  },
  "evidence": [
    {
      "evidence_id": "ev_001",
      "paper_id": "paper_001",
      "chunk_id": "chunk_012",
      "page": 5,
      "source_text": ""
    }
  ],
  "warnings": [],
  "errors": [],
  "metadata": {
    "request_id": "req_003",
    "project_id": "labkag_demo",
    "created_at": "2026-06-29T00:00:00Z"
  }
}
```

### 8.4.4 规则

1. 没有证据时，返回“未找到足够证据”；
2. 回答必须引用 evidence；
3. 如果证据冲突，必须在 warnings 中标记；
4. 不允许返回无来源的确定结论。

---

## 8.5 search_evidence

### 8.5.1 功能说明

只检索证据，不生成最终答案。

该函数适合外部 Agent 自行推理，只需要 LabKAG 返回相关证据。

### 8.5.2 输入

```json
{
  "query": "材料 A 的性能指标",
  "project_id": "labkag_demo",
  "entity_types": ["Result", "Metric", "Material"],
  "top_k": 10
}
```

### 8.5.3 输出

```json
{
  "status": "success",
  "data": {
    "matched_entities": []
  },
  "evidence": [
    {
      "evidence_id": "ev_001",
      "document_id": "doc_001",
      "paper_id": "paper_001",
      "chunk_id": "chunk_012",
      "page": 5,
      "section_title": "Results",
      "source_text": ""
    }
  ],
  "warnings": [],
  "errors": [],
  "metadata": {
    "request_id": "req_004",
    "project_id": "labkag_demo",
    "created_at": "2026-06-29T00:00:00Z"
  }
}
```

---

## 8.6 get_paper_knowledge

### 8.6.1 功能说明

获取某篇论文已经抽取并入库的知识结构。

### 8.6.2 输入

```json
{
  "paper_id": "paper_001",
  "project_id": "labkag_demo",
  "include_evidence": true
}
```

### 8.6.3 输出

```json
{
  "status": "success",
  "data": {
    "paper": {},
    "methods": [],
    "materials": [],
    "conditions": [],
    "metrics": [],
    "results": [],
    "conclusions": [],
    "relations": []
  },
  "evidence": [],
  "warnings": [],
  "errors": [],
  "metadata": {
    "request_id": "req_005",
    "project_id": "labkag_demo",
    "created_at": "2026-06-29T00:00:00Z"
  }
}
```

---

## 9. API 设计

### 9.1 REST API 路由

```text
POST /v1/papers/upload
POST /v1/papers/extract
POST /v1/papers/ingest
POST /v1/literature/query
POST /v1/evidence/search
GET  /v1/papers/{paper_id}/knowledge
GET  /health
GET  /openapi.json
```

### 9.2 路由与 Skill Function 对应关系

| HTTP 路由 | Skill Function | 说明 |
|---|---|---|
| POST /v1/papers/upload | upload_paper | 上传论文文件 |
| POST /v1/papers/extract | extract_paper | 文献抽取 |
| POST /v1/papers/ingest | ingest_paper | 知识入库 |
| POST /v1/literature/query | query_literature | 文献问答 |
| POST /v1/evidence/search | search_evidence | 证据检索 |
| GET /v1/papers/{paper_id}/knowledge | get_paper_knowledge | 获取论文知识结构 |

---

## 10. 技术栈

### 10.1 Skill Server

```text
Python 3.10
FastAPI
Pydantic
Uvicorn
```

### 10.2 文献解析

```text
PyMuPDF
pdfplumber
pypdf
```

### 10.3 LLM 抽取

```text
OpenAI API 或兼容 Chat Completions API 的模型
Structured JSON Output
JSON Schema Validation
Prompt Template
```

当前实现约定：

```text
LLM_API_KEY：启用真实 LLM 抽取
LLM_BASE_URL：OpenAI-compatible API base URL
LLM_MODEL：抽取模型
LLM_TIMEOUT_SECONDS：请求超时
ALLOW_MOCK_EXTRACTOR：是否允许 mock extractor 作为开发 fallback
```

未配置 `LLM_API_KEY` 且 `ALLOW_MOCK_EXTRACTOR=true` 时，系统保留 mock extractor
作为开发 fallback。若 `ALLOW_MOCK_EXTRACTOR=false`，则返回 `extraction_failed`，
避免生产环境静默写入 mock 数据。

### 10.4 OpenSPG/KAG 后端

```text
OpenSPG
KAG
OpenSPG Project / Namespace
LabKAG_Literature_v0_1 Schema
```

### 10.5 存储

v0.1 可采用轻量存储：

```text
本地文件系统：保存上传 PDF
SQLite / PostgreSQL：保存 task、document、extraction metadata
OpenSPG/KAG：保存知识实体和关系
```

如果要更接近后续部署，建议直接使用：

```text
PostgreSQL
MinIO
OpenSPG/KAG
```

### 10.6 开发辅助

```text
Docker Compose
pytest
ruff
mypy 可选
OpenAPI / Swagger UI
```

---

## 11. 项目目录结构

```text
labkag-skill/
├── app/
│   ├── main.py
│   ├── config.py
│   ├── api/
│   │   ├── papers.py
│   │   ├── literature.py
│   │   ├── evidence.py
│   │   └── health.py
│   ├── schemas/
│   │   ├── common.py
│   │   ├── paper.py
│   │   ├── evidence.py
│   │   ├── extraction.py
│   │   ├── skill_response.py
│   │   └── errors.py
│   ├── services/
│   │   ├── pdf_parser.py
│   │   ├── chunker.py
│   │   ├── paper_extractor.py
│   │   ├── evidence_binder.py
│   │   ├── openspg_client.py
│   │   ├── kag_client.py
│   │   └── skill_orchestrator.py
│   ├── prompts/
│   │   ├── paper_extraction_basic.md
│   │   └── paper_extraction_detailed.md
│   ├── adapters/
│   │   ├── openspg_mapper.py
│   │   └── kag_query_adapter.py
│   ├── storage/
│   │   ├── file_store.py
│   │   └── metadata_store.py
│   └── utils/
│       ├── ids.py
│       ├── time.py
│       └── logging.py
├── examples/
│   ├── upload_paper.py
│   ├── extract_paper.py
│   ├── ingest_paper.py
│   ├── query_literature.py
│   └── search_evidence.py
├── docs/
│   ├── LabKAG_v0.1_设计文档.md
│   ├── LabKAG_Literature_Schema_v0.1.md
│   └── API.md
├── tests/
│   ├── test_pdf_parser.py
│   ├── test_extraction_schema.py
│   ├── test_evidence_binder.py
│   └── test_skill_api.py
├── docker-compose.yml
├── requirements.txt
├── README.md
└── .env.example
```

---

## 12. 核心流程

### 12.1 文献抽取流程

```text
上传 PDF
-> 生成 document_id
-> 解析 PDF
-> 生成 pages
-> 生成 chunks
-> 调用 LLM 抽取
-> JSON Schema 校验
-> Evidence 绑定
-> 返回 PaperExtractionResult
```

### 12.2 文献入库流程

```text
PaperExtractionResult
-> Schema 校验
-> LabKAG Literature Schema 映射
-> 生成 OpenSPG 实体
-> 生成 OpenSPG 关系
-> 写入 OpenSPG/KAG
-> 返回入库统计
```

### 12.3 文献问答流程

```text
用户问题
-> query_literature
-> KAG 查询
-> 获取相关实体和证据
-> 生成答案
-> 统一格式返回
```

### 12.4 证据检索流程

```text
用户 query
-> search_evidence
-> KAG / OpenSPG 检索
-> 召回 Evidence
-> 返回 evidence 列表
```

---

## 13. 设计原则

### 13.1 Skill-first

LabKAG v0.1 首先是外接 Skill，不是独立网页系统。

因此优先级是：

```text
API 稳定性 > 页面完整性
结构化输出 > 自然语言输出
外部可调用 > 内部展示效果
```

### 13.2 OpenSPG/KAG as Backend

OpenSPG/KAG 是内部后端，不直接暴露给外部调用方。

LabKAG Skill Server 负责封装底层复杂度。

### 13.3 Evidence First

所有 Result 和 Conclusion 必须绑定 Evidence。

没有 Evidence 的信息不能作为确定事实返回。

### 13.4 Schema First

v0.1 必须先定义 LabKAG Literature Schema，再写入知识库。

不允许直接把自然语言文本无结构地塞进知识库。

### 13.5 Stable API Contract

外部 Agent 依赖稳定接口。因此 v0.1 必须保持：

```text
稳定的输入字段
稳定的输出字段
稳定的错误格式
稳定的 Evidence 结构
```

### 13.6 Intermediate JSON First

LLM 输出先进入 PaperExtractionResult 中间格式，再映射到 OpenSPG/KAG。

不要让 LLM 直接写 OpenSPG/KAG 底层结构。

### 13.7 Minimal Scope

v0.1 只做文献抽取，不做实验室全流程。

这是为了快速打通 OpenSPG/KAG 与外接 Skill 的核心闭环。

### 13.8 Replaceable Backend

虽然 v0.1 使用 OpenSPG/KAG，但 LabKAG Skill API 不应与其强耦合。

后续如果需要替换图谱后端或增加其他存储，不应影响外部 API。

---

## 14. 错误处理设计

### 14.1 错误码

| 错误码 | 说明 |
|---|---|
| file_not_found | 文件不存在 |
| unsupported_file_type | 文件类型不支持 |
| parse_failed | 文献解析失败 |
| extraction_failed | LLM 抽取失败 |
| schema_validation_failed | JSON Schema 校验失败 |
| evidence_binding_failed | Evidence 绑定失败 |
| openspg_write_failed | OpenSPG 写入失败 |
| kag_query_failed | KAG 查询失败 |
| internal_error | 内部错误 |

### 14.2 错误返回示例

```json
{
  "status": "failed",
  "data": {},
  "evidence": [],
  "warnings": [],
  "errors": [
    {
      "code": "parse_failed",
      "message": "PDF text extraction failed on pages 3-5.",
      "detail": {}
    }
  ],
  "metadata": {
    "request_id": "req_001",
    "project_id": "labkag_demo",
    "created_at": "2026-06-29T00:00:00Z"
  }
}
```

---

## 15. v0.1 开发里程碑

### M1：Skill Server 骨架

目标：

```text
FastAPI 项目初始化
统一返回格式
OpenAPI 文档
health check
基础配置
```

交付：

```text
GET /health
GET /openapi.json
统一 SkillResponse schema
```

---

### M2：文献上传与解析

目标：

```text
支持 PDF 上传
支持文本型 PDF 解析
生成 pages 和 chunks
保留 page 和 chunk_id
```

交付：

```text
POST /v1/papers/upload
PDF parser
Chunker
Document metadata
```

---

### M3：文献结构化抽取

目标：

```text
实现 PaperExtractionResult schema
实现 LLM 抽取
实现 JSON Schema 校验
支持 extract_paper
```

交付：

```text
POST /v1/papers/extract
paper_extractor
paper_extraction_basic prompt
```

---

### M4：Evidence 绑定

目标：

```text
Result 绑定 Evidence
Conclusion 绑定 Evidence
Evidence 返回 page / chunk / source_text
缺失 evidence 时生成 warning
```

交付：

```text
evidence_binder
Evidence schema
Evidence validation
```

---

### M5：OpenSPG/KAG Adapter

目标：

```text
定义 LabKAG_Literature_v0_1 Schema
实现 JSON 到 OpenSPG 实体关系映射
支持 ingest_paper
```

交付：

```text
openspg_mapper
openspg_client
POST /v1/papers/ingest
```

---

### M6：文献问答与证据检索

目标：

```text
实现 query_literature
实现 search_evidence
返回 answer + evidence
支持 KAG 查询
```

交付：

```text
POST /v1/literature/query
POST /v1/evidence/search
kag_query_adapter
```

---

### M7：示例、测试与文档

目标：

```text
提供示例论文导入脚本
提供示例问答脚本
完成 README
完成 API 文档
完成基础测试
```

交付：

```text
examples/
docs/
tests/
README.md
```

---

## 16. 验收标准

### 16.1 功能验收

v0.1 完成后，系统应满足：

1. 可以通过 API 上传至少 10 篇 PDF；
2. 可以解析文本型 PDF；
3. 可以抽取论文标题、作者、年份、摘要；
4. 可以抽取方法、材料、实验条件、结果和结论；
5. Result 和 Conclusion 至少能绑定一个 Evidence；
6. 可以将抽取结果写入 OpenSPG/KAG；
7. 可以通过 `query_literature` 回答文献问题；
8. 可以通过 `search_evidence` 检索证据；
9. 可以通过 `get_paper_knowledge` 获取论文结构化知识。

### 16.2 API 验收

API 应满足：

1. 所有接口有 OpenAPI 描述；
2. 所有接口返回统一格式；
3. 错误响应结构稳定；
4. Evidence 结构稳定；
5. 示例脚本可以正常调用。

### 16.3 质量验收

抽取质量初步目标：

```text
论文元数据抽取准确率：> 90%
方法 / 材料抽取可用率：> 70%
结果 / 结论 evidence 绑定率：> 70%
问答返回 evidence 覆盖率：> 80%
```

v0.1 是原型阶段，目标是验证闭环，不追求生产级准确率。

---

## 17. v0.1 风险与应对

### 17.1 PDF 解析不稳定

风险：

```text
复杂版式、双栏论文、扫描 PDF、公式和表格可能解析失败。
```

应对：

```text
v0.1 只承诺文本型 PDF；
扫描件 OCR 放到后续版本；
复杂表格抽取后置。
```

### 17.2 LLM 抽取幻觉

风险：

```text
模型可能生成原文不存在的方法、结果或结论。
```

应对：

```text
强制 Evidence 绑定；
没有 evidence 的内容标记 needs_review；
不作为确定事实入库。
```

### 17.3 OpenSPG/KAG 集成复杂

风险：

```text
OpenSPG/KAG 学习和集成成本较高。
```

应对：

```text
通过 Adapter 层隔离复杂度；
先实现最小 schema；
先打通单篇论文入库，再扩展批量入库。
```

### 17.4 API 过早膨胀

风险：

```text
Skill Function 过多导致接口不稳定。
```

应对：

```text
v0.1 固定 5 个核心函数；
新增功能进入 v0.2。
```

### 17.5 Evidence 粒度不一致

风险：

```text
有些 evidence 来自段落，有些来自句子，粒度不一致。
```

应对：

```text
v0.1 统一 evidence 到 chunk 级；
后续版本再细化到 sentence / table cell。
```

---

## 18. v0.2 演进方向

v0.1 完成后，v0.2 可以扩展：

1. 实验记录抽取；
2. Protocol 抽取；
3. 样品实体；
4. Reagent / Instrument 实体；
5. 实验条件与实验室记录对齐；
6. Paper Method 与 Lab Protocol 对齐；
7. 简单实验记录问答；
8. 批量文献导入；
9. 人工确认 UI；
10. 更复杂的图谱推理。

v0.2 的定位可以从 **Literature Skill** 扩展为 **Literature + Lab Record Skill**。

---

## 19. 最终定版说明

LabKAG v0.1 的正式路线为：

> **LabKAG v0.1 采用 Skill-first 架构。系统以 OpenSPG/KAG 作为知识建模、知识存储和推理问答底座，但不直接暴露 OpenSPG/KAG 接口，而是通过 LabKAG Skill Server 对外提供标准化能力。v0.1 仅实现文献抽取与文献问答能力，暴露 extract_paper、ingest_paper、query_literature、search_evidence、get_paper_knowledge 五个核心 Skill Function。**

v0.1 的成功标准不是实现完整实验室智能系统，而是打通：

```text
PDF 文献
-> 结构化抽取
-> Evidence 绑定
-> OpenSPG/KAG 入库
-> KAG 问答
-> 外部 Skill 调用
```

这条链路一旦跑通，LabKAG 就具备从文献知识扩展到实验室知识的基础。
