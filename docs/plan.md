# LabKAG v0.1 实现计划

## 当前总体状态

LabKAG v0.1 已经完成第一版 FastAPI Skill Server、PDF 文本解析、LLM/Mock 文献抽取、Evidence 绑定、OpenSPG 容器底座和 M5 适配层雏形。

当前重点推进 M5：把 LabKAG 的结构化文献知识真正写入 OpenSPG/KAG，而不是停留在本地 graph payload 和 mock 统计。

---

## M1：Skill Server 骨架

目标是先让服务跑起来。

包括：

```text
FastAPI 项目
配置读取
统一返回格式
/health
OpenAPI 文档
基础错误响应
```

当前状态：已完成。

---

## M2：文献上传与解析

目标是让系统能够接收 PDF，并把 PDF 转成可处理文本。

包括：

```text
POST /v1/papers/upload
PDF 文件保存
PDF 文本解析
pages 生成
chunks 生成
page / chunk_id 保留
```

当前状态：已完成第一版。

限制：

```text
支持文本型 PDF
暂不支持 OCR
暂不支持复杂表格理解
暂不支持图片理解
```

---

## M3：文献结构化抽取

目标是从论文文本中抽取结构化知识。

包括：

```text
论文标题、作者、年份、摘要
方法
材料
实验条件
指标
结果
结论
Evidence
```

当前状态：已完成第一版。

实现情况：

```text
支持 OpenAI-compatible Chat Completions LLM 抽取
支持 ALLOW_MOCK_EXTRACTOR 控制 mock fallback
LLM 抽取异常统一转换为 extraction_failed
extract_level=mock 可显式走 mock 抽取
```

---

## M4：Evidence 绑定

目标是保证结果和结论都有来源。

包括：

```text
page
chunk_id
section_title
source_text
```

规则：

```text
没有 Evidence 的 Result / Conclusion 不能当成确定事实
缺少 Evidence 时标记 needs_review
```

当前状态：已完成第一版。

---

## M5：OpenSPG/KAG Adapter

目标是把抽取结果转换成 OpenSPG/KAG 可写入的实体和关系，并完成真实入图闭环。

### 已完成

```text
deploy/openspg/docker-compose.yml
OpenSPG MySQL / Neo4j / Server 三容器启动
OpenSPGClient mock / remote 模式
OpenSPG mapper 中间 graph payload
Neo4jGraphStore 最小真实图写入后端
OpenSPG 写入异常统一为 openspg_write_failed
HTTP 200 但 success=false 的 OpenSPG 业务失败识别
```

当前容器验证结果：

```text
labkag-mysql healthy
labkag-neo4j healthy
labkag-server healthy
http://localhost:8887/ 返回 HTTP 200
```

### 闭环验证结论

已用最小 PaperExtractionResult 跑过真实写入尝试：

```text
未登录访问 /api/graph/write：
返回 success=false, errorCode=LOGIN_0002

登录后访问 /api/graph/write：
返回 404 Not Found

Neo4j closed_loop 测试节点数量：
0
```

结论：

```text
OpenSPG 服务本身可用
LabKAG graph payload 生成正常
OPENSPG_WRITE_PATH=/api/graph/write 不是当前 OpenSPG 镜像的真实写入接口
M5 不能继续按通用 graph write API 假设实现
```

### 下一步实现计划

#### M5.1：反查当前 OpenSPG 镜像真实 API

目标是确定项目、Schema、数据写入的真实接口和请求格式。

已发现的前端接口包括：

```text
/v1/accounts/login
/v1/projects
/v1/projects/list
/v1/schemas
/v1/schemas/tree/{projectId}
/v1/schemas/getSchemaScript
/v1/schemas/getSchemaNameMap
/v1/datas/search
/v1/datas/getEntityDetail
/v1/datas/getOneHopGraph
```

需要继续确认：

```text
创建项目接口参数
创建/更新 Schema 接口参数
实体数据导入接口
关系数据导入接口
是否需要 builder job 或 schema release
```

#### M5.2：实现 OpenSPG 登录 client

当前镜像使用 cookie 登录，不是 Bearer token。

需要实现：

```text
POST /v1/accounts/login
密码规则：SHA256(raw_password + "OPENSPG")
复用 OPEN_SPG_TOKEN cookie
请求失败时返回 openspg_write_failed
```

当前状态：已完成。

已验证：

```text
OpenSPGClient 默认使用 requests.Session()
登录后可以保留 OPEN_SPG_TOKEN cookie
GET /v1/projects/list 可正常调用
GET /v1/configs/KAG_ENV/version/1 可正常调用
```

建议新增配置：

```env
OPENSPG_ACCOUNT=openspg
OPENSPG_PASSWORD=openspg123
```

说明：`openspg123` 是当前本地 Docker 测试库中临时重置的密码，不应写死到代码里。

#### M5.3：实现项目与 Schema 初始化

把 M5 从单一 `write_graph()` 拆成：

```text
ensure_project()
ensure_schema()
write_extraction()
```

当前状态：进行中。

已完成：

```text
list_projects()
find_project_by_name()，兼容 OpenSPG 返回 records/data 两种分页字段
ensure_project()
get_config("KAG_ENV")
远程写入前按 OPENSPG_PROJECT_NAME 检查项目是否存在
```

本地验证结果：

```text
/v1/model/list/ 已能读取 OpenAI text-embedding-3-large embedding 模型
已通过 POST /v1/projects 创建 LabKAG 项目
/v1/projects/list 当前 total=1
/v1/projects/1 返回 success=true
/v1/schemas/tree/1 返回 success=true
/v1/schemas/graph/1 返回 success=true
/v1/configs/KAG_ENV/version/1 存在 graph_store 和 prompt
```

当前剩余问题：

```text
项目层已打通，最小图数据可通过 Neo4j graph-store 后端真实写入
OPENSPG_WRITE_PATH=/api/graph/write 仍然不是当前镜像的真实写入接口
OpenSPG 官方 Schema 初始化已通过 POST /v1/schemas 的 KGDSL 路径打通
OpenSPG 官方数据写入接口仍需继续验证
```

目标：

```text
确保存在 LabKAG 项目
确保存在 v0.1 文献 schema：已完成
确保 schema 可用于 OpenSPG schema graph 查询：已完成
```

Schema 应用验证结果：

```text
POST /v1/schemas 返回 success=true
/v1/schemas/getSchemaScript 可看到 Paper / Method / Material / Condition / Metric / Result / Conclusion / Evidence
/v1/schemas/graph/1 可看到 8 类实体
/v1/schemas/graph/1 可看到 13 条关系：
proposes / uses / hasCondition / measures / reports / drawsConclusion / hasEvidence / supportedBy
```

建议新增配置：

```env
OPENSPG_PROJECT_ID=
OPENSPG_PROJECT_NAME=LabKAG
OPENSPG_NAMESPACE=LabKAG
```

#### M5.4：实现最小实体写入

先不要一次性写完整 schema。

当前状态：已完成。

第一步只写：

```text
Paper
Evidence
Paper -> Evidence
```

实现方式：

```text
OPENSPG_WRITE_BACKEND=neo4j
Neo4jGraphStore 直连 OpenSPG compose 中的 Neo4j graph-store
OpenSPGClient 仍会先登录 OpenSPG 并检查 LabKAG 项目存在
```

真实闭环验证结果：

```text
POST /v1/papers/ingest confirm=true 返回 HTTP 200
返回 entities_created=2, relations_created=1, evidence_created=1
Neo4j 查询确认存在：
paper_closed_loop_api_001 -[:hasEvidence]-> ev_closed_loop_api_001
project_id=1
mock=false
```

验收标准：

```text
ingest_paper(confirm=true) 返回 success：已完成
Neo4j 查询能看到 paper_closed_loop_* 测试数据：已完成
重复写入通过 MERGE 保持同 id 幂等：已完成
```

#### M5.5：扩展完整文献图谱

在最小闭环成功后扩展：

当前状态：已完成。

```text
Method
Material
Condition
Metric
Result
Conclusion
supportedBy Evidence 关系
```

真实闭环验证结果：

```text
POST /v1/papers/ingest confirm=true 返回 HTTP 200
返回 entities_created=8, relations_created=13, evidence_created=1
Neo4j 查询确认存在实体：
Paper / Method / Material / Condition / Metric / Result / Conclusion / Evidence
Neo4j 查询确认存在关系：
proposes / uses / hasCondition / measures / reports / drawsConclusion / hasEvidence / supportedBy
```

保留当前 LabKAG 中间格式：

```text
PaperExtractionResult
-> LabKAG GraphPayload
-> OpenSPG Schema/Data Payload
```

不要让 LLM 直接输出 OpenSPG 底层格式。

#### M5.6：真实端到端测试

需要新增测试或脚本：

```text
OpenSPG 登录测试
项目存在性检查
Schema 初始化测试
最小 Paper + Evidence 入图测试
入图后查询验证
业务失败 success=false 的错误转换测试
```

---

## M6：文献问答与证据检索

目标是对已入库文献做 KAG 查询。

包括：

```text
POST /v1/literature/query
POST /v1/evidence/search
answer + evidence
matched_entities
confidence
reasoning_path
```

当前状态：mock 版本。

要等 M5 真实入图完成后，再接真实 OpenSPG/KAG 查询能力。

---

## M7：示例、测试与文档

目标是让项目可运行、可验证、可交接。

包括：

```text
examples/
tests/
README.md
docs/API.md
docs/LabKAG_Literature_Schema_v0.1.md
pytest
ruff
OpenSPG 本地部署说明
真实闭环验证脚本
```

当前状态：持续补充中。
