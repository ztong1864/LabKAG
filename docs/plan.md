# LabKAG v0.1 Plan

## 1. 当前基线

LabKAG v0.1 当前是 **Neo4j-only KAG Skill Server**。运行链路如下：

```text
PDF 上传
-> PDF 文本解析与 chunk
-> LLM / Mock 文献抽取
-> Evidence 绑定
-> LabKAG 图结构映射
-> Neo4j 入图
-> Evidence 检索
-> 文献问答
```

当前运行流程只依赖：

```text
FastAPI
Python 3.10
LLM API，必需；抽取失败直接返回 `extraction_failed`
Neo4j
```

当前图后端配置：

```env
GRAPH_BACKEND=neo4j
NEO4J_URI=bolt://127.0.0.1:7687
NEO4J_USER=neo4j
NEO4J_PASSWORD=labkagneo4j
NEO4J_DATABASE=neo4j
```

当前本地部署：

```powershell
docker compose -f deploy\neo4j\docker-compose.yml up -d
```

当前闭环验证：

```powershell
py -3.10 scripts\verify_m8_neo4j_closed_loop.py
```

## 2. 已完成能力

### M1 Skill Server

已完成：

```text
FastAPI 项目
/health
统一 SkillResponse
统一错误响应
配置读取
```

### M2 PDF 上传与解析

已完成：

```text
POST /v1/papers/upload
PDF 文件保存
PyMuPDF 文本解析
pages 生成
chunks 生成
page / chunk_id 保留
```

当前限制：

```text
仅支持文本型 PDF
暂不支持 OCR
暂不支持复杂表格理解
暂不支持图片理解
```

### M3 文献结构化抽取

已完成：

```text
OpenAI-compatible Chat Completions 抽取
`extract_level` 仅支持 `basic` / `detailed`
LLM 抽取异常统一转换为 extraction_failed
```

当前抽取对象：

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

### M4 Evidence 绑定

已完成：

```text
page
chunk_id
section_title
source_text
needs_review
```

规则：

```text
Result / Conclusion 必须绑定 Evidence 才能作为确定事实
缺少 Evidence 时标记 needs_review
```

### M5 Neo4j 入图

已完成：

```text
app/adapters/graph_mapper.py
app/adapters/graph_client.py
app/adapters/graph_store_factory.py
app/adapters/neo4j_graph_store.py
POST /v1/papers/ingest confirm=true
request.project_id 写入节点和关系
MERGE 幂等写入
graph_write_failed
```

当前图模型：

```text
Paper
Method
Material
Condition
Metric
Result
Conclusion
Evidence

Paper -> Method / Material / Condition / Metric / Result / Conclusion / Evidence
Method / Material / Condition / Metric / Result / Conclusion -> Evidence
```

### M6 Evidence 检索与文献问答

已完成：

```text
POST /v1/evidence/search
POST /v1/literature/query
Neo4jQueryStore
Evidence.source_text 关键词检索
project_id / paper_id / top_k 过滤
answer / evidence / related_entities / reasoning_path / confidence
kag_query_failed
```

当前限制：

```text
answer 是证据原文拼接
检索是关键词匹配
尚未支持 embedding / vector search
尚未支持 LLM answer synthesis
```

### M7-M8 交付整理与 Neo4j-only 清理

已完成：

```text
Readme.md
docs/API.md
docs/LabKAG_v0.1.md
docs/LabKAG_Literature_Schema_v0.1.md
.env.example
deploy/neo4j/docker-compose.yml
scripts/verify_m8_neo4j_closed_loop.py
pytest / ruff
```

## 3. 当前 API

```text
GET  /health
POST /v1/papers/upload
POST /v1/papers/extract
POST /v1/papers/ingest
GET  /v1/papers/{paper_id}/knowledge
POST /v1/evidence/search
POST /v1/literature/query
```

## 4. 当前验收标准

```text
只启动 Neo4j
POST /v1/papers/ingest confirm=true 成功
POST /v1/evidence/search 能搜到 Evidence
POST /v1/literature/query 能返回 answer + evidence
pytest 全通过
ruff 全通过
Neo4j-only closed loop 通过
```

验收命令：

```powershell
py -3.10 -m pytest -q
py -3.10 -m ruff check .
py -3.10 scripts\verify_m8_neo4j_closed_loop.py
```

最近一次验证结果：

```text
pytest: 39 passed
ruff: All checks passed
Neo4j-only closed loop: passed
```

## 5. 下一阶段：M9 Embedding 与向量检索

目标：把当前关键词检索升级为语义检索，并为更可靠的文献问答打基础。

### M9.1 Embedding 配置

新增配置：

```env
ENABLE_EMBEDDING=false
EMBEDDING_BASE_URL=https://api.openai.com/v1
EMBEDDING_API_KEY=
EMBEDDING_MODEL=text-embedding-3-large
EMBEDDING_DIM=3072
EMBEDDING_TIMEOUT_SECONDS=60
```

验收：

```text
ENABLE_EMBEDDING=false 时现有流程不变
ENABLE_EMBEDDING=true 但缺少 API key 时返回明确错误
```

### M9.2 EmbeddingProvider

计划新增：

```text
app/adapters/embedding_client.py
tests/test_embedding_client.py
```

职责：

```text
调用 OpenAI-compatible embeddings API
输入文本列表
返回 vector list
统一处理超时、HTTP 错误、维度不匹配
```

### M9.3 Evidence embedding 写入

计划修改：

```text
app/adapters/neo4j_graph_store.py
app/services/skill_orchestrator.py
```

策略：

```text
第一版只给 Evidence.source_text 生成 embedding
embedding 写入 Evidence.embedding
同时写入 embedding_model / embedding_dim
未启用 embedding 时不写向量
```

### M9.4 Neo4j vector index

计划新增：

```text
app/adapters/neo4j_vector_store.py
scripts/init_neo4j_vector_index.py
```

索引目标：

```text
Evidence.embedding
cosine similarity
维度来自 EMBEDDING_DIM
```

### M9.5 Hybrid retrieval

计划修改：

```text
app/adapters/neo4j_query_store.py
app/adapters/kag_client.py
```

检索策略：

```text
keyword search 保留
vector search 新增
合并去重
project_id / paper_id 过滤保持一致
top_k 控制最终返回数量
```

### M9.6 LLM answer synthesis

计划新增：

```text
app/services/answer_synthesizer.py
tests/test_answer_synthesizer.py
```

第一版要求：

```text
只基于召回 Evidence 生成回答
回答必须保留 evidence 引用
没有 Evidence 时返回 No matching evidence found.
LLM 失败时可退回证据原文拼接
```

## 6. 暂不做

```text
OCR
复杂表格理解
图片理解
前端 UI
权限系统
多租户
全图所有实体 embedding
复杂 agentic reasoning
```
