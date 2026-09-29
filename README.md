# 等保测评报告评审平台（第一版）

单位内网使用的多人评审工作台。输入为调研表、测评方案、测评报告三个 DOCX；依据为管理员发布的核查点 XLSX、高风险判定指引和附录 A 等级映射。项目数据、原始文档、模型密钥全部存放在运行时 `data/` 或部署数据库中。

目前可用的流程：上传并保留文档版本 → 提取资产、附录 D 结果记录及风险表 → 全对象三文档比对、抽选对象方案/报告比对 → 按 S/A/G 与扩展选择核查点 → 宽松或严格的附录 D 模型审核 → 高风险指引候选与风险表交叉核查 → 按章节复核问题 → 导出已确认问题的 Excel/Word。未配置的章节显示明确占位。质量总分未启用。

## 本地启动（Windows）

在仓库根目录执行：

```powershell
py -3 -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
cd frontend
npm install
npm run build
cd ..
.venv\Scripts\python.exe -m uvicorn backend.app:app --host 127.0.0.1 --port 8000
```

打开 `http://127.0.0.1:8000`。首次启动生成管理员 `admin` 的随机初始密码，读取 `data/bootstrap-admin.txt`；登录后在界面修改密码。该文件及所有运行数据被 Git 忽略。浏览器调试前端可在 `frontend` 执行 `npm run dev`，开发服务器把 `/api` 转到本地后端。

管理员可在“核查点库”逐份导入并发布 Excel。已有完整目录时，也可在本机执行：

```powershell
.venv\Scripts\python.exe -m backend.cli import-catalog "核查点目录"
.venv\Scripts\python.exe -m backend.cli import-catalog "高风险指引.xlsx"
.venv\Scripts\python.exe -m backend.cli import-catalog "附录A等级映射.xlsx"
```

请使用用户实际整理的工作簿，勿将它们复制进源码仓库。通用条款按二/三/四级的 S/A/G 标识取对应条目，扩展也按所属等级选择；旧式电力行标使用完整 SxAxGx 组合。缺判定规则的来源仅能核对描述覆盖，不能据此自动判错。附录 A 要求 G 为 S、A 两者较高等级。

## 多人部署

仓库提供 `Dockerfile` 与 `compose.yaml`。将 `.env.example` 复制为 `.env`，设置强 PostgreSQL 密码，然后执行 `docker compose up --build -d`。首次密码用 `docker compose exec app cat /app/data/bootstrap-admin.txt` 查看。默认为只监听本机；单位内网访问时在 `.env` 设置 `BIND_ADDR=0.0.0.0`，并由单位的反向代理配置 HTTPS。应用进程保持一个 Uvicorn 进程，由内部任务池并行审核。数据库卷和应用数据卷需要备份。

模型配置由管理员在页面填写 OpenAI 兼容 Chat Completions 地址、模型名称和密钥。内网地址可直接配置；发送到外部服务必须显式勾选。未配置模型时附录 D 模块会阻止启动；资产和高风险程序核查仍可运行。模型请求按结果记录逐条发送，仅包含该条结果记录及匹配的核查点、判定规则。模型输出必须逐项回应并引用原文，错误或无法验证的输出会使子任务失败，留待重试。审核结论始终由人确认。

## 已知边界

- 只读取 DOCX 报告和 XLSX 依据。图片扫描件、复杂嵌套表格和非标准列名可能无法提取；页面会显示解析数量与异常，不把“未提取”当作“确实没有”。
- 一致性比对先按对象类别和名称匹配；别名可人工确认。同名多对象、字段差异都保留原文来源，供审核员判断。
- 高风险指引采用候选检索与明确的表内冲突检查；重大隐患成立与否不自动定论。
- 运行中的任务保留文档和核查点版本快照。更换材料或等级后需创建新审核任务。
- SQLite 适合本机试用；多人正式部署使用 PostgreSQL。当前使用 `create_all` 初始化，升级已有正式库之前应备份并安排数据库迁移。

## 验证

```powershell
.venv\Scripts\python.exe -m pytest -q
cd frontend
npm run build
```

测试使用运行时生成的合成文档，不需要也不会提交真实报告或核查点。

