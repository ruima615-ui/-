# 课程资料双 Embedding 索引

资料解析后，`index_course_material_dual()` 把同一批 Chunk 分别写入
`course_material_chunks_primary` 和 `course_material_chunks_backup`。两套向量由
`CourseEmbeddings` 调用 `embedding_service.embed_texts()` 生成。两种模型即使返回相同维度，
也只在各自的 collection 中比较相似度。

每份资料在 `course_material_embedding_indexes` 表中按 `(material_id, backend)`
保存两行独立状态。主索引失败不会阻止备份索引；失败行记为 `failed`，下次批量运行可重试。
教师上传后的后台任务与 `python -m app.index_course_materials --course-id 课程ID`
均使用双后端索引。后台任务会同时回填该课程中已解析的旧资料，避免只索引新上传的
一份资料而让旧资料退出检索。已有旧索引继续保存在 `course_material_chunks`，
未建立任何双后端状态行的课程仍可走旧检索路径。

学生资料检索优先查询已就绪的主索引。主模型返回 `EmbeddingUnavailable` 时，
仅在备份状态为 `indexed` 的资料范围内查询备份索引；两者均不可用时返回
`embedding_unavailable`。结果会附带 `embedding_backend` 和 `collection_name`。
按 Chunk ID 回读也只接受当前课程、且索引状态为 `indexed` 的资料。
资料删除时清理主、备及旧 collection 中该资料的 Chunk 和对应状态。

当前模型配置来自项目 `.env`：`PRIMARY_EMBEDDING_MODEL`、`BACKUP_EMBEDDING_MODEL`、
`EMBEDDING_DIMENSION`、`DASHSCOPE_BASE_URL`、`DASHSCOPE_API_KEY` 和 `OLLAMA_EMBED_URL`。
百炼客户端默认直连，避免本机失效代理导致每次查询都降级；部署环境确需使用系统
代理时设置 `DASHSCOPE_TRUST_ENV=true`。
模型名称、维度或资料内容变化后，需要重新运行批量索引；旧向量不可直接复用。

离线测试使用确定性向量验证双份写入、主故障切换、备份缺失、状态隔离与清理，
不代表云端鉴权成功。真实模型小样本应在独立 Chroma 测试库中验证后，再为现有课程
运行批量建索引。

2026-10-10 的真实检查中，云端接口绕过失效的本机代理后返回 HTTP 401，错误码
`invalid_api_key`。这是当前主索引不能入库的外部鉴权问题。对现有 `PYTHON101`
两份资料执行批量回填后，SQLite 中分别有两条 `primary=failed` 与
`backup=indexed` 状态；每份资料的备份 collection 都有 2 个片段。实际课程检索和
学生工具入口均返回 `success / backup`，片段 ID 回读成功，其他课程回读该 ID 返回
`chunk_not_found`。重复批量运行得到 `backup=already_indexed`，没有重复写入。
原有 2 条旧索引状态仍保留。

云端密钥或模型权限修复后，先在独立临时 Chroma 中验证主模型；再运行
`python -m app.index_course_materials` 重试 `primary=failed` 的资料，并确认其状态
变为 `indexed`、检索结果带 `embedding_backend=primary`。不要把 401 误判为
Chroma 向量维度问题，也不要将两个模型的向量混入同一 collection。

密钥更新后已完成上述验收：主模型返回 1024 维向量；`PYTHON101` 两份资料的
`primary` 状态均从 `failed` 变为 `indexed`，各有 2 个 Chunk，`backup` 保持
`indexed`。未手动清除代理环境变量的正常进程中，服务检索和学生工具入口都返回
`success / primary`，按 ID 回读成功，其他课程回读返回 `chunk_not_found`。
再次运行批量命令，两个后端均返回 `already_indexed`。
