import React, { useEffect, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import "./style.css";
import ConsistencyReview from "./ConsistencyReview";
import AppendixReview from "./AppendixReview";
import KeyInformation from "./KeyInformation";
import ChapterContent, { type ChapterContentData } from "./ChapterContent";
import { activeIssueRunId, keepVisibleSelection, visibleIssues as filterIssues } from "./issueView";

type Any = Record<string, any>;
const labels: Any = {
  survey: "调研表",
  plan: "测评方案",
  report: "测评报告",
  full: "全对象",
  sample: "抽选对象",
  assets_full: "三文档完整资产",
  assets_sample: "方案与报告抽选对象",
  appendix_d: "附录D结果记录",
  high_risk: "高风险与重大隐患",
  lenient: "常规审核",
  strict: "严格审核",
};
const extNames: Any = {
  cloud: "云计算",
  mobile: "移动互联",
  iot: "物联网",
  ics: "工业控制",
  bigdata: "大数据",
};
const stateNames: Any = {
  parsed: "解析完成",
  consistent: "一致",
  missing: "来源缺失",
  different: "属性差异",
  ambiguous: "需要匹配",
  pending: "待复核",
  confirmed: "已确认",
  rejected: "误报",
  needs_evidence: "待核实",
  resolved: "已解决",
  queued: "排队中",
  running: "处理中",
  done: "已完成",
  partial: "部分完成",
  blocked: "待确认",
  failed: "失败",
  cancelled: "已取消",
};
const categoryNames: Any = {
  asset_match: "对象身份",
  asset_missing: "对象缺失",
  asset_difference: "属性差异",
  description_coverage: "描述覆盖",
  verdict: "符合性判定",
  writing: "文字表述",
  risk_consistency: "风险等级冲突",
  high_risk_screening: "高风险候选",
  major_hazard_table: "重大隐患表",
};
const riskSummaryColumns = [
  "序号", "问题编号", "报告安全问题描述", "报告4.3整体测评描述", "报告第5章问题风险分析",
  "报告涉及对象", "高风险条款号", "适用范围", "报告判定", "是否重大风险",
  "指引-场景/问题描述", "指引-可能的缓解措施", "指引-风险评价-参考",
];
const CODES: [string, string][] = [
  ["ALL", "全部问题"],
  ["CROSS_DOCUMENT", "前后一致性"],
  ["FULL_TEXT", "规范性问题"],
  ["COVER", "封面"],
  ["BASIC_INFO", "基本信息"],
  ["STATEMENT", "声明"],
  ["CONCLUSION", "结论页"],
  ["MAJOR_HAZARD", "重大风险隐患"],
  ["RECTIFICATION", "整改建议"],
  ...Array.from(
    { length: 8 },
    (_, i) =>
      [`CH${String(i + 1).padStart(2, "0")}`, `第${i + 1}章`] as [
        string,
        string,
      ],
  ),
  ..."ABCDEFGH"
    .split("")
    .map((x) => [`APP_${x}`, `附录${x}`] as [string, string]),
  ["OTHER", "未归类内容"],
];
const configured = new Set([
  "ALL",
  "CROSS_DOCUMENT",
  "APP_D",
  "CH05",
  "MAJOR_HAZARD",
]);
let csrf = "";
async function api(
  path: string,
  method = "GET",
  body?: any,
  upload = false,
): Promise<any> {
  const headers: Any = {};
  if (csrf) headers["X-CSRF-Token"] = csrf;
  if (body !== undefined && !upload)
    headers["Content-Type"] = "application/json";
  const response = await fetch("/api" + path, {
    method,
    credentials: "same-origin",
    headers,
    body: body === undefined ? undefined : upload ? body : JSON.stringify(body),
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok)
    throw new Error(
      typeof data.detail === "string"
        ? data.detail
        : JSON.stringify(data.detail || data),
    );
  return data;
}

function App() {
  const [user, setUser] = useState<Any | null>(null),
    [login, setLogin] = useState({ username: "admin", password: "" }),
    [projects, setProjects] = useState<Any[]>([]),
    [project, setProject] = useState<Any>(null as any);
  const [view, setView] = useState("overview"),
    [error, setError] = useState(""),
    [message, setMessage] = useState(""),
    [busy, setBusy] = useState(false);
  const [docs, setDocs] = useState<Any[]>([]),
    [facts, setFacts] = useState<Any>({});
  const [knowledge, setKnowledge] = useState<Any[]>([]),
    [requirements, setRequirements] = useState<Any>({
      summary: { count: 0 },
      items: [],
    }),
    [records, setRecords] = useState<Any>({ items: [] });
  const [runs, setRuns] = useState<Any[]>([]),
    [runDetail, setRunDetail] = useState<Any | null>(null),
    [redactionPreview, setRedactionPreview] = useState<Any | null>(null),
    [issues, setIssues] = useState<Any[]>([]),
    [chapter, setChapter] = useState("ALL"),
    [selectedIssue, setSelectedIssue] = useState<Any | null>(null),
    [selectedIssueIds, setSelectedIssueIds] = useState<string[]>([]),
    [batchNote, setBatchNote] = useState(""),
    [issueCoverage, setIssueCoverage] = useState<Any[]>([]),
    [chapterContent, setChapterContent] = useState<ChapterContentData | null>(null);
  const [risk, setRisk] = useState<Any>({ candidates: [] }),
    [riskRunId, setRiskRunId] = useState(""),
    [model, setModel] = useState<Any>({}),
    [modelServices, setModelServices] = useState<Any[]>([]),
    [modelProfiles, setModelProfiles] = useState<Any[]>([]),
    [modelServiceDraft, setModelServiceDraft] = useState<Any>({ name: "", base_url: "", models: "", enabled: true }),
    [modelProfileDraft, setModelProfileDraft] = useState<Any>({ service_id: "", model: "", api_key: "" }),
    [modelProfileEditId, setModelProfileEditId] = useState(""),
    [selectedModelProfile, setSelectedModelProfile] = useState(""),
    [modules, setModules] = useState<string[]>([
      "assets_full",
      "appendix_d",
      "high_risk",
    ]),
    [mode, setMode] = useState("lenient");
  const [precheck, setPrecheck] = useState<Any | null>(null),
    [newName, setNewName] = useState(""),
    [newUser, setNewUser] = useState({
      username: "",
      display_name: "",
      password: "",
    }),
    [users, setUsers] = useState<Any[]>([]);
  const [note, setNote] = useState(""),
    [redactionReviewedHashes, setRedactionReviewedHashes] = useState<string[]>([]),
    [redactionExtraTerms, setRedactionExtraTerms] = useState(""),
    [redactionExtraKind, setRedactionExtraKind] = useState("name"),
    [recordQuery, setRecordQuery] = useState(""),
    [recordUnmatchedOnly, setRecordUnmatchedOnly] = useState(false),
    [issueStatus, setIssueStatus] = useState("ALL"),
    [issueRunId, setIssueRunId] = useState(""),
    [issueModule, setIssueModule] = useState(""),
    [issueQuery, setIssueQuery] = useState(""),
    [issueCategory, setIssueCategory] = useState(""),
    [passwords, setPasswords] = useState({ old: "", new: "" }),
    [settings, setSettings] = useState<Any>({}),
    [redactionDraft, setRedactionDraft] = useState<Any>({}),
    [auditRows, setAuditRows] = useState<Any[]>([]);
  const action = async (fn: () => Promise<any>, ok = "操作完成") => {
    setBusy(true);
    setError("");
    try {
      await fn();
      setMessage(ok);
      setTimeout(() => setMessage(""), 4000);
    } catch (e: any) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  };
  const refreshProjects = async () => {
    const ps = await api("/projects");
    setProjects(ps);
    return ps;
  };
  const currentProjectId = useRef(project?.id);
  currentProjectId.current = project?.id;
  const load = async (
    p: Any,
    screen = view,
    tab = chapter,
  ) => {
    const pid = p.id;
    const common = await Promise.all([
      api(`/projects/${pid}/documents`),
      api(`/projects/${pid}/facts`),
      api(`/projects/${pid}/runs`),
    ]);
    if (currentProjectId.current !== pid) return;
    const activeRunId = activeIssueRunId(common[2], issueRunId);
    if (screen === "issues" && issueRunId !== activeRunId) setIssueRunId(activeRunId);
    setDocs(common[0]);
    setFacts(common[1]);
    setRuns(common[2]);
    if (screen === "issues" || screen === "overview") {
      const issueRows = await api(`/projects/${pid}/issues?run_id=${encodeURIComponent(activeRunId)}${issueModule ? `&module=${encodeURIComponent(issueModule)}` : ""}`);
      if (currentProjectId.current !== pid) return;
      setIssues(issueRows);
      if (screen === "issues") {
        const [coverage, content] = await Promise.all([
          api(`/projects/${pid}/issues/coverage?run_id=${encodeURIComponent(activeRunId)}`),
          tab !== "ALL" ? api(`/projects/${pid}/issues/chapter-content?run_id=${encodeURIComponent(activeRunId)}&chapter=${encodeURIComponent(tab)}`) : Promise.resolve(null),
        ]);
        if (currentProjectId.current !== pid) return;
        setIssueCoverage(coverage.chapters || []);
        setChapterContent(content);
      }
    }
    setSettings(p.config || {});
    setRedactionDraft(p.config?.redaction_terms || {});
    if (screen === "appendix") {
      const [a, b] = await Promise.all([
        api(`/projects/${pid}/requirements`),
        api(`/projects/${pid}/records`),
      ]);
      setRequirements(a);
      setRecords(b);
    }
    if (screen === "risk") {
      const riskRuns = common[2].filter((run: Any) => run.modules?.includes("high_risk") && ["done", "partial"].includes(run.status));
      const riskRun = riskRuns.find((run: Any) => run.id === riskRunId) || riskRuns[0];
      setRiskRunId(riskRun?.id || "");
      setRisk(riskRun ? await api(`/projects/${pid}/runs/${riskRun.id}/risk`) : { candidates: [] });
    }
    if (screen === "audit") setAuditRows(await api(`/projects/${pid}/audit`));
    if (screen === "knowledge") setKnowledge(await api("/knowledge"));
    if (screen === "model") {
      const [services, profiles] = await Promise.all([api("/model-services"), api("/me/model-profiles")]);
      setModelServices(services);
      setModelProfiles(profiles);
      setSelectedModelProfile((previous) => previous || profiles.find((p: Any) => p.enabled)?.id || "");
    }
    if (screen === "users" && user?.admin) setUsers(await api("/users"));
  };
  useEffect(() => {
    api("/me")
      .then(async (x) => {
        csrf = x.csrf;
        setUser(x.user);
        const ps = await refreshProjects();
        if (ps.length) setProject(ps[0]);
      })
      .catch(() => {});
  }, []);
  useEffect(() => {
    if (project) load(project).catch((e) => setError(e.message));
  }, [project?.id, view, chapter, issueRunId, issueModule]);
  useEffect(() => {
    if (!project || (view !== "runs" && view !== "overview")) return;
    const id = setInterval(() => load(project).catch(() => {}), 5000);
    return () => clearInterval(id);
  }, [project?.id, view]);
  const navigate = (next: string) => {
    setView(next);
    setError("");
    setSelectedIssue(null);
    setSelectedIssueIds([]);
  };
  const loginSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    await action(async () => {
      const x = await api("/login", "POST", login);
      csrf = x.csrf;
      setUser(x.user);
      const ps = await refreshProjects();
      if (ps.length) setProject(ps[0]);
    }, "登录成功");
  };
  if (!user)
    return (
      <div className="login-layout">
        <div className="login-intro">
          <div className="mark">盾</div>
          <span className="eyebrow">ASSESSMENT WORKBENCH</span>
          <h1>
            网络安全等级保护
            <br />
            测评报告评审平台
          </h1>
          <p>
            把调研表、测评方案与测评报告放在同一条证据链中，逐项核查、逐条复核。
          </p>
          <div className="login-highlights">
            <span>三文档一致性</span>
            <span>附录D逐项核查</span>
            <span>问题人工闭环</span>
          </div>
        </div>
        <form className="login-card" onSubmit={loginSubmit}>
          <div className="small-label">单位内网 · 多人协作</div>
          <h2>登录工作台</h2>
          <p className="muted">使用管理员或审核员账号进入项目。</p>
          <label>
            用户名
            <input
              value={login.username}
              onChange={(e) => setLogin({ ...login, username: e.target.value })}
            />
          </label>
          <label>
            密码
            <input
              type="password"
              value={login.password}
              onChange={(e) => setLogin({ ...login, password: e.target.value })}
            />
          </label>
          <button disabled={busy}>
            进入平台 <span>→</span>
          </button>
          {error && <div className="alert">{error}</div>}
          <small>首次管理员密码保存在服务器 data/bootstrap-admin.txt</small>
        </form>
      </div>
    );
  const docFor = (role: string): Any =>
    docs.find((d) => d.role === role) as any;
  const visibleIssues = filterIssues(issues, chapter, issueStatus, issueQuery).filter(
    (x) => !issueCategory || x.category === issueCategory,
  );
  const visibleSelectedIssueIds = keepVisibleSelection(selectedIssueIds, visibleIssues);
  const saveMatch = (matchKey: string, requirementKey: string) =>
    action(async () => {
      const matches = {
        ...(project.config?.matches || {}),
        [matchKey]: requirementKey,
      };
      const updated = await api(`/projects/${project.id}`, "PATCH", {
        version: project.version,
        matches,
      });
      setProject(updated);
      await load(updated, "appendix");
    }, "测评项已确认");
  const nav = [
    ["overview", "总览", "◫"],
    ["documents", "文档与提取", "▤"],
    ["key-info", "关键信息", "▥"],
    ["assets", "一致性审核", "⇄"],
    ["appendix", "附录D审核", "▦"],
    ["risk", "高风险核查", "△"],
    ["runs", "审核任务", "◷"],
    ["issues", "问题展示", "◉"],
    ["knowledge", "核查点库", "◇"],
    ["settings", "项目设置", "⚙"],
    ["account", "我的账号", "♙"],
    ["model", "我的模型", "⌘"],
    ...(user.admin
      ? [
          ["users", "用户管理", "♙"],
        ]
      : []),
    ["audit", "操作记录", "≡"],
  ];
  return (
    <div className="shell">
      <aside className="sidebar">
        <div className="brand">
          <div className="brand-icon">盾</div>
          <div>
            <strong>等保评审平台</strong>
            <small>DB PRO CHECK</small>
          </div>
        </div>
        <div className="project-select">
          <span>当前项目</span>
          <select
            value={project?.id || ""}
            onChange={(e) => {
              setIssueRunId(""); setIssues([]); setIssueCoverage([]); setChapterContent(null);
              setSelectedIssue(null); setSelectedIssueIds([]); setError("");
              setProject(
                (projects.find((x) => x.id === e.target.value) || null) as any,
              );
            }}
          >
            <option value="">选择项目</option>
            {projects.map((p) => (
              <option key={p.id} value={p.id}>
                {p.name}
              </option>
            ))}
          </select>
        </div>
        <nav>
          {nav.map(([id, title, icon]) => (
            <button
              key={id}
              className={view === id ? "active" : ""}
              onClick={() => navigate(id)}
            >
              <span className="nav-icon">{icon}</span>
              {title}
              {id === "issues" && <i>{issues.length}</i>}
            </button>
          ))}
        </nav>
        <div className="sidebar-foot">
          <div className="avatar">{user.display_name.slice(0, 1)}</div>
          <div>
            <strong>{user.display_name}</strong>
            <small>{user.admin ? "管理员" : "审核员"}</small>
          </div>
          <button
            title="退出登录"
            onClick={() =>
              action(async () => {
                await api("/logout", "POST", {});
                csrf = "";
                setUser(null);
                setProject(null as any);
              }, "已退出")
            }
          >
            ↗
          </button>
        </div>
      </aside>
      <main>
        <header className="topbar">
          <div className="crumb">
            工作台 <span>/</span> {nav.find((x) => x[0] === view)?.[1]}
          </div>
          <div className="top-actions">
            <span className="env">● 内网工作台</span>
            <button
              className="ghost"
              onClick={() => project && action(() => load(project), "已刷新")}
            >
              刷新
            </button>
          </div>
        </header>
        <div className="content">
          {error && (
            <div className="alert">
              {error}
              <button onClick={() => setError("")}>×</button>
            </div>
          )}
          {message && <div className="success">{message}</div>}
          {!project ? (
            <div className="empty-card">
              <h1>建立第一个评审项目</h1>
              <p>一个项目对应一套调研表、测评方案与测评报告。</p>
              <div className="inline">
                <input
                  placeholder="例如：某信息系统年度测评"
                  value={newName}
                  onChange={(e) => setNewName(e.target.value)}
                />
                <button
                  className="primary"
                  onClick={() =>
                    action(async () => {
                      const p = await api("/projects", "POST", {
                        name: newName,
                      });
                      await refreshProjects();
                      setProject(p);
                      setNewName("");
                    }, "项目已创建")
                  }
                >
                  创建项目
                </button>
              </div>
            </div>
          ) : (
            <>
              {view === "overview" && (
                <>
                  <div className="page-heading">
                    <div>
                      <span className="eyebrow">PROJECT OVERVIEW</span>
                      <h1>{project.name}</h1>
                      <p>
                        从原始材料到已确认问题，每一步都保留来源与处理状态。
                      </p>
                    </div>
                    <button
                      className="primary"
                      onClick={() => navigate("documents")}
                    >
                      上传评审材料 →
                    </button>
                  </div>
                  <div className="stats">
                    <Stat
                      label="已上传文档"
                      value={
                        ["survey", "plan", "report"].filter((x) => docFor(x))
                          .length + "/3"
                      }
                      hint="调研表 · 方案 · 报告"
                    />
                    <Stat
                      label="报告结果记录"
                      value={facts.report?.counts?.records || 0}
                      hint="附录D可识别条目"
                    />
                    <Stat
                      label="待复核问题"
                      value={
                        issues.filter((x) => x.status === "pending").length
                      }
                      hint="需要人工确认"
                    />
                    <Stat
                      label="已确认问题"
                      value={
                        issues.filter((x) => x.status === "confirmed").length
                      }
                      hint="可导出问题清单"
                    />
                  </div>
                  <div className="grid2">
                    <section className="panel">
                      <SectionTitle
                        title="资料准备"
                        subtitle="当前各文档的最新版本"
                      />
                      {["survey", "plan", "report"].map((role) => (
                        <div className="source-row" key={role}>
                          <span className="source-icon">▤</span>
                          <div>
                            <strong>{labels[role]}</strong>
                            <small>
                              {docFor(role)?.filename || "尚未上传"}
                            </small>
                          </div>
                          <Badge
                            text={
                              docFor(role)
                                ? `第 ${docFor(role).version} 版`
                                : "待上传"
                            }
                            tone={docFor(role) ? "good" : "soft"}
                          />
                        </div>
                      ))}
                    </section>
                    <section className="panel">
                      <SectionTitle
                        title="审核流程"
                        subtitle="建议先确认提取结果和核查点，再启动任务"
                      />
                      {[
                        ["01", "上传并确认三份文档", "documents"],
                        ["02", "核对三文档关键信息", "key-info"],
                        ["03", "检查资产与结果记录", "assets"],
                        ["04", "配置模型和审核任务", "runs"],
                        ["05", "复核问题并导出", "issues"],
                      ].map(([no, text, dest]) => (
                        <button
                          className="step-row"
                          key={no}
                          onClick={() => navigate(dest)}
                        >
                          <b>{no}</b>
                          <span>{text}</span>
                          <span>→</span>
                        </button>
                      ))}
                    </section>
                  </div>
                </>
              )}
              {view === "documents" && (
                <>
                  <PageTitle
                    kicker="SOURCE DOCUMENTS"
                    title="文档与关键信息提取"
                    desc="上传 DOCX 后立即解析。先查看数量和异常提示，再开展比对与评审。"
                  />
                  <div className="cards3">
                    {["survey", "plan", "report"].map((role) => (
                      <div className="panel upload-card" key={role}>
                        <div className="doc-icon">
                          {role === "survey"
                            ? "调"
                            : role === "plan"
                              ? "案"
                              : "报"}
                        </div>
                        <h3>{labels[role]}</h3>
                        <p>{docFor(role)?.filename || "尚未上传 DOCX 文档"}</p>
                        <label className="file-button">
                          选择文件
                          <input
                            type="file"
                            accept=".docx"
                            onChange={(e) => {
                              const file = e.target.files?.[0];
                              if (!file) return;
                              action(async () => {
                                const fd = new FormData();
                                fd.append("role", role);
                                fd.append("file", file);
                                await api(
                                  `/projects/${project.id}/documents`,
                                  "POST",
                                  fd,
                                  true,
                                );
                                await load(project);
                              }, "文档已解析");
                            }}
                          />
                        </label>
                        {docFor(role) && (
                          <>
                            <div className="file-meta">
                              第 {docFor(role).version} 版 ·{" "}
                              {stateNames[docFor(role).status] ||
                                docFor(role).status}
                            </div>
                            <small>
                              资产 {docFor(role).counts?.assets || 0} · 表格{" "}
                              {docFor(role).counts?.tables || 0} · 结果记录{" "}
                              {docFor(role).counts?.records || 0}
                            </small>
                          </>
                        )}
                        {docFor(role)?.diagnostics?.map(
                          (d: string, i: number) => (
                            <div className="hint-warning" key={i}>
                              {d}
                            </div>
                          ),
                        )}
                      </div>
                    ))}
                  </div>
                  <section className="panel mt">
                    <SectionTitle
                      title="提取预览"
                      subtitle="以下信息来自当前文档解析版本；任何缺项都需先核对原文。"
                    />
                    <div className="cards3">
                      {["survey", "plan", "report"].map((role) => (
                        <div key={role}>
                          <h4>{labels[role]}</h4>
                          <div className="fact-line">
                            资产 <b>{facts[role]?.counts?.assets ?? "—"}</b>
                          </div>
                          <div className="fact-line">
                            表格 <b>{facts[role]?.counts?.tables ?? "—"}</b>
                          </div>
                          <div className="fact-line">
                            结果记录{" "}
                            <b>{facts[role]?.counts?.records ?? "—"}</b>
                          </div>
                          <div className="fact-line">
                            等级候选{" "}
                            <b>
                              {facts[role]?.facts?.profile_candidates?.join(
                                "、",
                              ) || "待确认"}
                            </b>
                          </div>
                        </div>
                      ))}
                    </div>
                  </section>
                </>
              )}
              {view === "key-info" && <KeyInformation projectId={project.id} api={api} />}
              {view === "assets" && (
                <ConsistencyReview key={project.id} projectId={project.id} runs={runs}
                  api={api} onRefresh={() => load(project, "assets")} />
              )}
              {view === "appendix" && <>
                <PageTitle kicker="APPENDIX D" title="附录 D 结果记录审核" desc="按层面、对象和复核状态筛选结果记录，展开 J-N 问题证据并保留人工复核。" />
                <AppendixReview projectId={project.id} runs={runs} api={api} onRefresh={() => load(project, "appendix")} />
              </>}
              {view === "risk" && (
                <>
                  <PageTitle
                    kicker="RISK REVIEW"
                    title="高风险与重大隐患核查"
                    desc="跨问题汇总、整体测评和风险分析表，展示指引候选及明确冲突。候选需人工确认。"
                  />
                  <div className="stats compact">
                    <Stat
                      label="指引候选"
                      value={risk.candidates?.length || 0}
                      hint="待核对条件及缓解措施"
                    />
                    <Stat
                      label="已关联表格行"
                      value={risk.linked_rows?.length || 0}
                      hint="报告来源可追溯"
                    />
                    <Stat
                      label="结论"
                      value="人工确认"
                      hint="不自动判定重大隐患"
                    />
                  </div>
                  <div className="panel inline risk-run-picker">
                    <label>审核批次
                      <select value={riskRunId} onChange={(e) => action(async () => {
                        const id = e.target.value;
                        setRiskRunId(id);
                        setRisk(id ? await api(`/projects/${project.id}/runs/${id}/risk`) : { candidates: [] });
                      }, "高风险结果已更新")}>
                        <option value="">请选择一次高风险核查</option>
                        {runs.filter((run: Any) => run.modules?.includes("high_risk") && ["done", "partial"].includes(run.status)).map((run: Any) => (
                          <option key={run.id} value={run.id}>{new Date(run.created_at * 1000).toLocaleString()} · {run.status}</option>
                        ))}
                      </select>
                    </label>
                  </div>
                  {risk.note && <Notice text={risk.note} />}
                  {riskRunId && <div className="inline"><a className="button" href={`/api/projects/${project.id}/runs/${riskRunId}/risk/export`}>导出当前运行</a></div>}
                  <section className="panel">
                    <SectionTitle title="高风险核查汇总" subtitle={`按旧版 13 列格式关联报告三张表与指引：${risk.legacy_rows?.length || 0} 条。匹配结果需人工复核。`} />
                    {risk.legacy_note && <Notice text={risk.legacy_note} />}
                    <div className="key-scroll">
                      <table className="risk-summary-grid">
                        <thead><tr>{riskSummaryColumns.map((name) => <th key={name}>{name}</th>)}</tr></thead>
                        <tbody>{(risk.legacy_rows || []).map((row: Any, index: number) => (
                          <tr key={`${row.source_row_id}-${row.guide_key}-${index}`} title={`来源：${(row.source_locations || []).join('、')}；匹配度：${row.score || 0}%`}>
                            {riskSummaryColumns.map((name) => <td key={name}>{row.values?.[name] ?? ""}</td>)}
                          </tr>
                        ))}</tbody>
                      </table>
                    </div>
                    {!risk.legacy_rows?.length && <Empty text="未找到符合旧版 98% 要求项匹配条件的记录；请查看下方完整来源与候选。" />}
                  </section>
                  <section className="panel">
                    <SectionTitle title="全部来源行" subtitle={`3/4/5 章来源 ${risk.source_rows?.length || 0} 行`} />
                    {(risk.source_rows || []).map((row: Any) => <div className="list-row" key={row.row_id}><b>{row.source}</b><span>{row.description || "未解析描述"} · {row.review?.status || "待复核"}</span></div>)}
                  </section>
                  <section className="panel risk-raw-panel"><SectionTitle title="来源原始值" subtitle="按第3、4、5章定位来源行，核对提取值和复核状态。" />{(risk.source_rows || []).map((row: Any) => <details key={`raw-${row.row_id}`}><summary>{row.source} · {row.review?.status || "待复核"}</summary><pre>{JSON.stringify({ row_id: row.row_id, chapter: row.chapter, table_location: row.table_location, row_number: row.row_number, raw_values: row.raw_values || row.values || {} }, null, 2)}</pre></details>)}</section>
                  <div className="panel">
                    <SectionTitle
                      title="风险问题候选"
                      subtitle="匹配度只辅助检索，不代表风险成立。"
                    />
                    {risk.candidates?.map((item: Any, i: number) => (
                      <div className="risk-item" key={i}>
                        <div className="risk-index">
                          {String(i + 1).padStart(2, "0")}
                        </div>
                        <div>
                          <b>{item.description}</b>
                          <small>
                            {item.object || "对象待确认"} · {item.source}
                          </small>
                          <p>
                            关联其他表格：{item.related?.length || 0} 行 ·
                            指引候选：{item.matches?.length || 0} 条
                          </p>
                          {item.matches?.map((m: Any) => (
                            <div className="risk-match" key={m.key}>
                              <b>
                                {m.clause} · {Math.round(m.score * 100)}%
                                文本相似
                              </b>
                              <span>{m.scenario}</span>
                              <small>{m.source}</small>
                            </div>
                          ))}
                          <details className="risk-evidence"><summary>查看候选原始值和依据</summary><pre>{JSON.stringify(item, null, 2)}</pre></details>
                          <div className="review-actions"><button onClick={() => action(async () => { const updated = await api(`/projects/${project.id}/runs/${riskRunId}/risk/candidate:${item.row_id}`, "PATCH", { version: item.review?.version || 0, status: "confirmed", conclusion: "人工确认候选关联", reason: "" }); setRisk(await api(`/projects/${project.id}/runs/${riskRunId}/risk`)); }, "高风险关联已复核")}>确认关联</button><button onClick={() => action(async () => { await api(`/projects/${project.id}/runs/${riskRunId}/risk/candidate:${item.row_id}`, "PATCH", { version: item.review?.version || 0, status: "needs_evidence", conclusion: "", reason: "需要补充证据" }); setRisk(await api(`/projects/${project.id}/runs/${riskRunId}/risk`)); }, "已标记补证")}>需要补证</button></div>
                        </div>
                      </div>
                    ))}
                    {!risk.candidates?.length && (
                      <Empty text="完成高风险核查任务后显示候选" />
                    )}
                  </div>
                  <div className="grid2 mt">
                    <section className="panel"><SectionTitle title="未匹配来源" subtitle={`需要人工补充：${risk.unmatched?.length || 0} 条`} />{risk.unmatched?.map((item: Any) => <div className="list-row" key={item.source_row_id}><b>{item.source || item.source_row_id}</b><span>{item.reason}</span></div>)}{!risk.unmatched?.length && <Empty text="暂无未匹配来源" />}</section>
                    <section className="panel"><SectionTitle title="冲突与适用性" subtitle={`冲突：${risk.conflicts?.length || 0} 条`} />{risk.conflicts?.map((item: Any, index: number) => <div className="list-row" key={index}><b>{item.type || "冲突"}</b><span>{item.reason || JSON.stringify(item)}</span></div>)}{risk.applicability?.status === "unknown" && <Notice text="适用性尚未确认，不能自动下结论。" />}{!risk.conflicts?.length && risk.applicability?.status !== "unknown" && <Empty text="暂无冲突" />}</section>
                  </div>
                </>
              )}
              {view === "runs" && (
                <>
                  <PageTitle
                    kicker="REVIEW TASKS"
                    title="启动审核任务"
                    desc="勾选需要的模块。常规与严格使用相同判定规则，只改变描述覆盖要求。"
                  />
                  <div className="grid2">
                    <section className="panel">
                      <SectionTitle
                        title="本次审核"
                        subtitle="启动前检查资料和依据是否齐备"
                      />
                      <div className="field-label">审核模块</div>
                      <div className="check-list">
                        {Object.keys(labels)
                          .filter((x) =>
                            [
                              "assets_full",
                              "assets_sample",
                              "appendix_d",
                              "high_risk",
                            ].includes(x),
                          )
                          .map((x) => (
                            <label key={x}>
                              <input
                                type="checkbox"
                                checked={modules.includes(x)}
                                onChange={(e) =>
                                  setModules(
                                    e.target.checked
                                      ? [...modules, x]
                                      : modules.filter((m) => m !== x),
                                  )
                                }
                              />
                              <span>{labels[x]}</span>
                            </label>
                          ))}
                      </div>
                      <div className="field-label mt">附录D描述覆盖模式</div>
                      <div className="segmented">
                        <button
                          className={mode === "lenient" ? "on" : ""}
                          onClick={() => setMode("lenient")}
                        >
                          常规审核
                        </button>
                        <button
                          className={mode === "strict" ? "on" : ""}
                          onClick={() => setMode("strict")}
                        >
                          严格审核
                        </button>
                      </div>
                      <p className="muted">
                        两种模式均不允许遗漏关键条件，也都按同一判定规则复核原结论。
                      </p>
                      {modules.includes("appendix_d") && (
                        <label className="field-label mt">
                          本次使用的个人模型档案
                          <select value={selectedModelProfile} onChange={(e) => setSelectedModelProfile(e.target.value)}>
                            <option value="">请选择</option>
                            {modelProfiles.filter((p) => p.enabled).map((p) => (
                              <option key={p.id} value={p.id}>{modelServices.find((s) => s.id === p.service_id)?.name || "服务"} · {p.model}</option>
                            ))}
                          </select>
                        </label>
                      )}
                      <div className="inline mt">
                        <button
                          onClick={() =>
                            action(
                              async () =>
                                setPrecheck(
                                  await api(
                                    `/projects/${project.id}/precheck`,
                                    "POST",
                                    { modules, model_profile_id: selectedModelProfile, preview_only: modules.includes("appendix_d") },
                                  ),
                                ),
                              "预检查完成",
                            )
                          }
                        >
                          预检查
                        </button>
                        <button
                          className="primary"
                          disabled={busy}
                          onClick={() =>
                            action(async () => {
                              const result = await api(
                                `/projects/${project.id}/precheck`,
                                "POST",
                                { modules, model_profile_id: selectedModelProfile, preview_only: modules.includes("appendix_d") },
                              );
                              setPrecheck(result);
                              if (result.blockers?.length)
                                throw new Error(result.blockers.join("；"));
                              const run = await api(
                                `/projects/${project.id}/runs`,
                                "POST",
                                {
                                  modules,
                                  mode,
                                  model_profile_id: selectedModelProfile,
                                  preview_only: modules.includes("appendix_d"),
                                  request_key: crypto.randomUUID(),
                                },
                              );
                              if (modules.includes("appendix_d")) {
                                setRunDetail(await api(`/projects/${project.id}/runs/${run.id}`));
                                setRedactionPreview(await api(`/projects/${project.id}/runs/${run.id}/redaction`));
                              }
                              await load(project, "runs");
                            }, "审核任务已创建")
                          }
                        >
                          开始审核 →
                        </button>
                      </div>
                      {precheck?.blockers?.map((b: string, i: number) => (
                        <div className="hint-warning" key={i}>
                          {b}
                        </div>
                      ))}
                      {precheck && !precheck.blockers?.length && (
                        <div className="hint-good">材料与规则预检查通过</div>
                      )}
                    </section>
                    <section className="panel">
                      <SectionTitle
                        title="任务记录"
                        subtitle="逐条保留结果和错误，可重试待确认或失败的子任务"
                      />
                      {runs.map((r) => (
                        <div className="run-row" key={r.id}>
                          <div>
                            <b>
                              {r.modules
                                .map((x: string) => labels[x])
                                .join("、")}
                            </b>
                            <small>
                              {new Date(r.created_at * 1000).toLocaleString()} ·{" "}
                              {labels[r.mode]}
                            </small>
                            <div className="run-counts">
                              {Object.entries(r.tasks || {}).map(([k, v]) => (
                                <span key={k}>
                                  {stateNames[k] || k} {String(v)}
                                </span>
                              ))}
                            </div>
                          </div>
                          <div>
                            <Badge
                              text={stateNames[r.status] || r.status}
                              tone={
                                r.status === "done"
                                  ? "good"
                                  : r.status === "partial"
                                    ? "warn"
                                    : "soft"
                              }
                            />
                            <button
                              className="link"
                              onClick={() =>
                                action(
                                  async () => {
                                    setRunDetail(await api(`/projects/${project.id}/runs/${r.id}`));
                                    if (r.modules?.includes("appendix_d") && ["awaiting_redaction", "queued", "running"].includes(r.status)) {
                                      setRedactionPreview(await api(`/projects/${project.id}/runs/${r.id}/redaction`));
                                    } else {
                                      setRedactionPreview(null);
                                    }
                                  },
                                  "任务详情已展开",
                                )
                              }
                            >
                              查看详情
                            </button>
                            {["queued", "running"].includes(r.status) && (
                              <button
                                className="link danger"
                                onClick={() =>
                                  action(async () => {
                                    await api(
                                      `/projects/${project.id}/runs/${r.id}/cancel`,
                                      "POST",
                                      {},
                                    );
                                    await load(project, "runs");
                                  }, "任务已取消")
                                }
                              >
                                取消
                              </button>
                            )}
                          </div>
                        </div>
                      ))}
                      {!runs.length && <Empty text="尚未发起审核任务" />}
                    </section>
                  </div>
                  {runDetail && (
                    <section className="panel mt">
                      <SectionTitle
                        title="子任务详情"
                        subtitle={`共 ${runDetail.tasks?.length || 0} 项`}
                      />
                      <div className="task-list">
                        {runDetail.tasks?.map((t: Any) => (
                          <div className="task-row" key={t.id}>
                            <div>
                              <b>{t.label}</b>
                              <small>{t.error || t.output?.reason || ""}</small>
                            </div>
                            <Badge
                              text={stateNames[t.status] || t.status}
                              tone={t.status === "done" ? "good" : "warn"}
                            />
                            {["failed", "blocked"].includes(t.status) && (
                              <button
                                className="link"
                                onClick={() =>
                                  action(async () => {
                                    await api(
                                      `/projects/${project.id}/tasks/${t.id}/retry`,
                                      "POST",
                                      {},
                                    );
                                    setRunDetail(
                                      await api(
                                        `/projects/${project.id}/runs/${runDetail.run.id}`,
                                      ),
                                    );
                                  }, "已重新排队")
                                }
                              >
                                重试
                              </button>
                            )}
                          </div>
                        ))}
                      </div>
                    </section>
                  )}
                  {redactionPreview && (
                    <section className="panel mt">
                      <SectionTitle title="脱敏请求复核" subtitle={`请求 ${redactionPreview.counts?.requests || 0} 项 · 命中 ${redactionPreview.counts?.hits || 0} 处 · 待确认 ${redactionPreview.counts?.uncertain || 0} 项`} />
                      <p className="muted">请逐条核对预览中的姓名、地址等敏感值。发现遗漏时补充词典并重新生成预览，再确认发送。</p>
                      {redactionPreview.items?.map((item: Any) => (
                        <details className="redaction-item" key={item.task_id}>
                          <summary>{runDetail?.tasks?.find((task: Any) => task.id === item.task_id)?.label || item.task_id} · {item.hits.length} 处替换 · {item.uncertain.length ? "需处理" : "待人工核对"}</summary>
                          {item.uncertain.length > 0 && <Notice text={`发现需人工确认的片段：${item.uncertain.join("、")}`} />}
                          <pre>{JSON.stringify(item.payload, null, 2)}</pre>
                          <label><input type="checkbox" checked={redactionReviewedHashes.includes(item.request_hash)} onChange={(e) => setRedactionReviewedHashes(e.target.checked ? [...redactionReviewedHashes, item.request_hash] : redactionReviewedHashes.filter((hash) => hash !== item.request_hash))} />已核对本条请求的脱敏结果</label>
                        </details>
                      ))}
                      <div className="inline">
                        <select aria-label="补充敏感词类型" value={redactionExtraKind} onChange={(e) => setRedactionExtraKind(e.target.value)}><option value="name">人名</option><option value="address">地址</option><option value="organization">单位</option><option value="identifier">编号</option></select>
                        <textarea aria-label="补充敏感词" placeholder="补充遗漏的敏感原值，一行一个" value={redactionExtraTerms} onChange={(e) => setRedactionExtraTerms(e.target.value)} />
                        <button disabled={busy || !redactionExtraTerms.trim()} onClick={() => action(async () => {
                          const terms = { ...(project.config?.redaction_terms || {}) };
                          terms[redactionExtraKind] = [...new Set([...(terms[redactionExtraKind] || []), ...redactionExtraTerms.split(/\r?\n/).map((value) => value.trim()).filter(Boolean)])];
                          const updated = await api(`/projects/${project.id}`, "PATCH", { redaction_terms: terms });
                          setProject(updated); setRedactionDraft(terms);
                          await api(`/projects/${project.id}/runs/${redactionPreview.run_id}/redaction/refresh`, "POST", {});
                          setRedactionPreview(await api(`/projects/${project.id}/runs/${redactionPreview.run_id}/redaction`));
                          setRedactionReviewedHashes([]); setRedactionExtraTerms("");
                        }, "词典已补充，预览已重新生成")}>补充词典并重新预览</button>
                      </div>
                      <button className="primary" disabled={busy || !redactionPreview.items?.length || redactionPreview.items.some((item: Any) => item.uncertain.length || !redactionReviewedHashes.includes(item.request_hash))} onClick={() => action(async () => {
                        const hashes = Object.fromEntries(redactionPreview.items.map((item: Any) => [item.task_id, item.request_hash]));
                        await api(`/projects/${project.id}/runs/${redactionPreview.run_id}/redaction/authorize`, "POST", { hashes, list_hash: redactionPreview.list_hash });
                        setRedactionPreview(null);
                        setRunDetail(await api(`/projects/${project.id}/runs/${redactionPreview.run_id}`));
                        await load(project, "runs");
                      }, "脱敏请求已授权，任务开始处理")}>确认脱敏结果并发送</button>
                    </section>
                  )}
                </>
              )}
              {view === "issues" && (
                <>
                  <div className="page-heading">
                    <div>
                      <span className="eyebrow">FINDINGS DESK</span>
                      <h1>审核问题展示</h1>
                      <p>按章节查看，核对原文和依据后确定处理意见。</p>
                    </div>
                    <div className="inline">
                      <button
                        disabled={!issueRunId}
                        onClick={() =>
                          window.open(
                            `/api/projects/${project.id}/export?format=xlsx&run_id=${encodeURIComponent(issueRunId)}${issueModule ? `&module=${encodeURIComponent(issueModule)}` : ""}`,
                            "_blank",
                          )
                        }
                      >
                        导出 Excel
                      </button>
                      <button
                        className="primary"
                        disabled={!issueRunId}
                        onClick={() =>
                          window.open(
                            `/api/projects/${project.id}/export?format=docx&run_id=${encodeURIComponent(issueRunId)}${issueModule ? `&module=${encodeURIComponent(issueModule)}` : ""}`,
                            "_blank",
                          )
                        }
                      >
                        导出 Word ↗
                      </button>
                    </div>
                  </div>
                  <div className="issue-filters">
                    <select aria-label="审核批次" value={issueRunId} onChange={(e) => { setIssueRunId(e.target.value); setSelectedIssueIds([]); setSelectedIssue(null); }}>
                      <option value="">选择审核批次</option>
                      {runs.map((run: Any) => <option key={run.id} value={run.id}>{new Date(run.created_at * 1000).toLocaleString()} · {stateNames[run.status] || run.status}</option>)}
                    </select>
                    <select aria-label="审核模块" value={issueModule} onChange={(e) => { setIssueModule(e.target.value); setSelectedIssueIds([]); }}>
                      <option value="">全部模块</option>
                      <option value="assets_full">三文档一致性</option>
                      <option value="appendix_d">附录D审核</option>
                      <option value="high_risk">高风险核查</option>
                    </select>
                    <select aria-label="问题类别" value={issueCategory} onChange={(e) => { setIssueCategory(e.target.value); setSelectedIssueIds([]); }}>
                      <option value="">全部类别</option>
                      {[...new Set(issues.map((x: Any) => x.category))].map((category) => <option key={category} value={category}>{categoryNames[category] || category}</option>)}
                    </select>
                    <select aria-label="问题状态" value={issueStatus} onChange={(e) => { setIssueStatus(e.target.value); setSelectedIssueIds([]); }}>
                      <option value="ALL">全部状态</option>
                      {(["pending", "confirmed", "rejected", "needs_evidence"] as const).map((status) => <option key={status} value={status}>{stateNames[status]}</option>)}
                    </select>
                    <input aria-label="搜索问题或对象" placeholder="搜索问题或对象" value={issueQuery} onChange={(e) => { setIssueQuery(e.target.value); setSelectedIssueIds([]); }} />
                    <span>{visibleIssues.length} 项匹配</span>
                  </div>
                  <div className="issue-workbench">
                  <div className="chapter-tabs">
                    {CODES.map(([code, title]) => (
                      <button
                        key={code}
                        className={chapter === code ? "active" : ""}
                        onClick={() => {
                          setChapter(code);
                          setChapterContent(null);
                          setSelectedIssue(null);
                          setSelectedIssueIds([]);
                        }}
                      >
                        {title}
                        <b>{filterIssues(issues, code, "ALL", "").length}</b>
                      </button>
                    ))}
                  </div>
                  {(!configured.has(chapter) || issueCoverage.find((item: Any) => item.code === chapter)?.review_status === "规则待配置") && (
                    <Notice text="本章节已保留内容入口，审核规则待配置；此处无问题不代表审核通过。" />
                  )}
                  <div className="issue-main">
                  {issueCoverage.length > 0 && <div className="coverage-strip">{issueCoverage.filter((item: Any) => chapter === "ALL" || item.code === chapter).map((item: Any) => <span key={item.code}>{item.title || item.code}：{item.content_status} / {item.review_status}</span>)}</div>}
                  <ChapterContent data={chapterContent} />
                  <div className="batch-toolbar">
                    <label><input type="checkbox" checked={visibleIssues.length > 0 && visibleSelectedIssueIds.length === visibleIssues.length} onChange={(e) => setSelectedIssueIds(e.target.checked ? visibleIssues.map((item) => item.id) : [])} />选择当前可见 {visibleIssues.length} 项</label>
                    <span>已选 {visibleSelectedIssueIds.length} 项</span>
                    <input aria-label="批量复核意见" placeholder="批量复核意见" value={batchNote} onChange={(e) => setBatchNote(e.target.value)} />
                    <button className="primary" disabled={busy || !issueRunId || !visibleSelectedIssueIds.length} onClick={() => action(async () => {
                      await api(`/projects/${project.id}/issues/batch`, "POST", { run_id: issueRunId, items: visibleIssues.filter((item) => visibleSelectedIssueIds.includes(item.id)).map((item) => ({ id: item.id, version: item.version })), status: "confirmed", note: batchNote });
                      setSelectedIssueIds([]); setSelectedIssue(null); await load(project, "issues", chapter);
                    }, "所选问题已确认")}>批量确认问题</button>
                  </div>
                  <div className="issue-layout">
                    <section className="panel issue-list">
                      <div className="list-head">
                        <b>
                          {chapter === "ALL"
                            ? "全部问题"
                            : CODES.find((x) => x[0] === chapter)?.[1]}
                        </b>
                        <span>
                          {issues.length} 项 ·{" "}
                          {issues.filter((x) => x.status === "pending").length}{" "}
                          项待复核
                        </span>
                      </div>
                      {visibleIssues.map((x) => (
                        <div className="issue-select-row" key={x.id}>
                        <input type="checkbox" aria-label={`选择问题 ${x.title}`} checked={visibleSelectedIssueIds.includes(x.id)} onChange={(e) => setSelectedIssueIds(e.target.checked ? [...visibleSelectedIssueIds, x.id] : visibleSelectedIssueIds.filter((id) => id !== x.id))} />
                        <button
                          className={
                            "issue-card " +
                            (selectedIssue?.id === x.id ? "selected" : "")
                          }
                          onClick={() => {
                            setSelectedIssue(x);
                            setNote(x.note || "");
                          }}
                        >
                          <div>
                            <span className="category">
                              {categoryNames[x.category] || x.category}
                            </span>
                            <Badge
                              text={stateNames[x.status] || x.status}
                              tone={
                                x.status === "confirmed"
                                  ? "good"
                                  : x.status === "pending"
                                    ? "warn"
                                    : "soft"
                              }
                            />
                          </div>
                          <h3>{x.title}</h3>
                          <p>{x.description}</p>
                          <small>
                            {x.object_name || "未关联对象"} ·{" "}
                            {x.evidence?.[0]?.source || "来源待核实"}
                          </small>
                        </button>
                        </div>
                      ))}
                      {!visibleIssues.length && (
                        <Empty text="当前章节暂无问题。运行审核后会显示候选；未配置章节不会显示虚构结果。" />
                      )}
                    </section>
                    <section className="panel issue-detail">
                      {selectedIssue ? (
                        <>
                          <div className="detail-top">
                            <span className="eyebrow">FINDING DETAIL</span>
                            <Badge
                              text={
                                stateNames[selectedIssue.status] ||
                                selectedIssue.status
                              }
                              tone={
                                selectedIssue.status === "confirmed"
                                  ? "good"
                                  : "warn"
                              }
                            />
                          </div>
                          <h2>{selectedIssue.title}</h2>
                          <div className="detail-meta">
                            <span>章节 {selectedIssue.chapter}</span>
                            <span>
                              类别{" "}
                              {categoryNames[selectedIssue.category] ||
                                selectedIssue.category}
                            </span>
                            <span>对象 {selectedIssue.object_name || "—"}</span>
                          </div>
                          <h4>问题说明</h4>
                          <p>{selectedIssue.description}</p>
                          <h4>修改建议</h4>
                          <p>{selectedIssue.suggestion}</p>
                          <h4>原文与依据</h4>
                          {selectedIssue.evidence?.map((e: Any, i: number) => (
                            <div className="evidence" key={i}>
                              <small>
                                {labels[e.role] ||
                                  (e.role === "knowledge"
                                    ? "核查依据"
                                    : "来源")}{" "}
                                · {e.source}
                              </small>
                              <p>{e.quote}</p>
                            </div>
                          ))}
                          <h4>复核意见</h4>
                          <textarea
                            value={note}
                            onChange={(e) => setNote(e.target.value)}
                            placeholder="记录确认依据、排除原因或待补证要求"
                          />
                          <div className="review-actions">
                            {[
                              ["confirmed", "确认问题"],
                              ["rejected", "标记误报"],
                              ["needs_evidence", "待核实"],
                              ["pending", "待确认"],
                            ].map(([s, title]) => (
                              <button
                                key={s}
                                className={s === "confirmed" ? "primary" : ""}
                                onClick={() =>
                                  action(async () => {
                                    const updated = await api(
                                      `/projects/${project.id}/issues/${selectedIssue.id}`,
                                      "PATCH",
                                      {
                                        version: selectedIssue.version,
                                        status: s,
                                        note,
                                      },
                                    );
                                    setSelectedIssue(updated);
                                    await load(
                                      project,
                                      "issues",
                                      chapter,
                                    );
                                  }, "复核状态已保存")
                                }
                              >
                                {title}
                              </button>
                            ))}
                          </div>
                        </>
                      ) : (
                        <div className="detail-placeholder">
                          <div>◎</div>
                          <h3>选择左侧问题</h3>
                          <p>查看原文、核查依据和修改建议，再记录复核结果。</p>
                        </div>
                      )}
                    </section>
                  </div>
                  </div>
                  </div>
                </>
              )}
              {view === "knowledge" && (
                <>
                  <PageTitle
                    kicker="KNOWLEDGE BASE"
                    title="核查点与判定规则"
                    desc="管理员导入并发布依据文件。系统按项目选择的 S、A、G 等级及扩展组合读取条目。"
                  />
                  {user.admin && (
                    <div className="panel upload-strip">
                      <div>
                        <b>导入 Excel 核查点或高风险指引</b>
                        <p>
                          保留文件名中的通用/扩展、等级信息；导入后先检查告警，再发布。
                        </p>
                      </div>
                      <label className="file-button">
                        选择 XLSX
                        <input
                          type="file"
                          accept=".xlsx"
                          onChange={(e) => {
                            const file = e.target.files?.[0];
                            if (!file) return;
                            action(async () => {
                              const fd = new FormData();
                              fd.append("file", file);
                              await api("/knowledge", "POST", fd, true);
                              setKnowledge(await api("/knowledge"));
                            }, "依据已导入为草稿");
                          }}
                        />
                      </label>
                    </div>
                  )}
                  <div className="panel mt table-panel">
                    <table>
                      <thead>
                        <tr>
                          <th>依据文件</th>
                          <th>类别</th>
                          <th>等级</th>
                          <th>条目</th>
                          <th>状态</th>
                          <th>提示 / 操作</th>
                        </tr>
                      </thead>
                      <tbody>
                        {knowledge.map((k) => (
                          <tr key={k.id}>
                            <td>
                              <b>{k.filename}</b>
                            </td>
                            <td>
                              {extNames[k.family] ||
                                (
                                  {
                                    general: "安全通用",
                                    high_risk: "高风险指引",
                                    mapping: "等级映射",
                                  } as Any
                                )[k.family] ||
                                k.family}
                            </td>
                            <td>{k.profile || k.level || "—"}</td>
                            <td>{k.count}</td>
                            <td>
                              <Badge
                                text={
                                  k.status === "published" ? "已发布" : "草稿"
                                }
                                tone={
                                  k.status === "published" ? "good" : "warn"
                                }
                              />
                            </td>
                            <td>
                              {k.warnings?.length || 0} 条导入提示{" "}
                              {user.admin && k.status === "draft" && (
                                <button
                                  className="link"
                                  onClick={() =>
                                    action(async () => {
                                      await api(
                                        `/knowledge/${k.id}/publish`,
                                        "POST",
                                        {},
                                      );
                                      setKnowledge(await api("/knowledge"));
                                    }, "依据已发布")
                                  }
                                >
                                  发布
                                </button>
                              )}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                    {!knowledge.length && (
                      <Empty text="暂无核查点。管理员可导入整理后的 Excel 文件。" />
                    )}
                  </div>
                </>
              )}
              {view === "settings" && (
                <>
                  <PageTitle
                    kicker="PROJECT SETTINGS"
                    title="项目范围与对象确认"
                    desc="选择 S/A/G 等级及扩展类别；调整后重新审核，既有任务仍保留当时的来源快照。"
                  />
                  <div className="grid2">
                    <section className="panel">
                      <SectionTitle
                        title="等级选择"
                        subtitle="分别选择 S 和 A；G 按附录 A 自动取两者较高等级"
                      />
                      <div className="cards3">
                        {["s", "a", "g"].map((key) => (
                          <label key={key}>
                            {key.toUpperCase()} 等级
                            <select
                              value={settings[key] || 3}
                              disabled={key === "g"}
                              onChange={(e) => {
                                const updated = {
                                  ...settings,
                                  [key]: Number(e.target.value),
                                };
                                setSettings({
                                  ...updated,
                                  g: Math.max(updated.s || 3, updated.a || 3),
                                });
                              }}
                            >
                              {[2, 3, 4].map((n) => (
                                <option key={n} value={n}>
                                  {n}级
                                </option>
                              ))}
                            </select>
                          </label>
                        ))}
                      </div>
                      <div className="field-label mt">扩展要求</div>
                      <div className="check-list">
                        {Object.entries(extNames).map(([k, v]) => (
                          <label key={k}>
                            <input
                              type="checkbox"
                              checked={(settings.extensions || []).includes(k)}
                              onChange={(e) =>
                                setSettings({
                                  ...settings,
                                  extensions: e.target.checked
                                    ? [...(settings.extensions || []), k]
                                    : (settings.extensions || []).filter(
                                        (x: string) => x !== k,
                                      ),
                                })
                              }
                            />
                            {String(v)}
                          </label>
                        ))}
                      </div>
                      <label className="field-label mt">
                        电力行业类别（二选一）
                        <select
                          value={settings.power_category || ""}
                          onChange={(e) =>
                            setSettings({
                              ...settings,
                              power_category: e.target.value || null,
                            })
                          }
                        >
                          <option value="">不使用电力扩展</option>
                          <option value="power_monitoring">电力监控系统安全要求</option>
                          <option value="power_management">电力管理信息系统安全要求</option>
                        </select>
                      </label>
                      <button
                        className="primary mt"
                        onClick={() =>
                          action(async () => {
                            const p = await api(
                              `/projects/${project.id}`,
                              "PATCH",
                              {
                                version: project.version,
                                s: settings.s,
                                a: settings.a,
                                g: settings.g,
                                extensions: settings.extensions || [],
                                power_category: settings.power_category || null,
                                redaction_terms: redactionDraft,
                              },
                            );
                            setProject(p);
                          }, "项目范围已保存")
                        }
                      >
                        保存项目范围
                      </button>
                    </section>
                    <section className="panel">
                      <SectionTitle
                        title="审核员协作"
                        subtitle="项目负责人可按用户名添加审核员"
                      />
                      <p className="muted">当前负责人：{user.display_name}</p>
                      <div className="inline">
                        <input placeholder="现有用户名" id="member-name" />
                        <button
                          onClick={() =>
                            action(async () => {
                              const name = (
                                document.getElementById(
                                  "member-name",
                                ) as HTMLInputElement
                              ).value;
                              await api(
                                `/projects/${project.id}/members`,
                                "POST",
                                { username: name },
                              );
                            }, "成员已添加")
                          }
                        >
                          添加成员
                        </button>
                      </div>
                      <div className="divider" />
                      <h4>项目脱敏词典</h4>
                      <input type="file" accept=".xlsx" onChange={(e) => {
                        const file = e.target.files?.[0];
                        if (!file) return;
                        action(async () => {
                          const form = new FormData(); form.append('file', file);
                          const updated = await api(`/projects/${project.id}/redaction-terms`, 'POST', form, true);
                          setProject(updated); setSettings(updated.config || {}); setRedactionDraft(updated.config?.redaction_terms || {});
                        }, '脱敏词典已导入');
                      }} />
                      {['name', 'organization', 'address', 'phone', 'ip', 'domain', 'url', 'identifier'].map((kind) => (
                        <label key={kind} className="field-label">
                          {kind}
                          <textarea rows={2} value={(redactionDraft[kind] || []).join("\n")} onChange={(e) => setRedactionDraft({ ...redactionDraft, [kind]: e.target.value.split(/\r?\n/).map((x: string) => x.trim()).filter(Boolean) })} />
                        </label>
                      ))}
                      <h4>对象别名与测评项匹配</h4>
                      <p className="muted">
                        资产同名或名称变化时，在一致性页面查阅来源；附录D待匹配记录可在“附录D审核”页面逐条确认测评项。
                      </p>
                    </section>
                  </div>
                </>
              )}
              {view === "model" && (
                <section className="panel form-panel">
                  <PageTitle kicker="MODEL PROFILES" title="个人模型配置" desc="管理员批准服务地址后，审核员只管理自己的密钥；密钥不会回显。" />
                  <label>服务<select value={modelProfileDraft.service_id} onChange={(e) => setModelProfileDraft({ ...modelProfileDraft, service_id: e.target.value, model: "" })}><option value="">请选择服务</option>{modelServices.filter((s) => s.enabled).map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}</select></label>
                  <label>模型<select value={modelProfileDraft.model} onChange={(e) => setModelProfileDraft({ ...modelProfileDraft, model: e.target.value })}><option value="">请选择模型</option>{(modelServices.find((s) => s.id === modelProfileDraft.service_id)?.models || []).map((name: string) => <option key={name} value={name}>{name}</option>)}</select></label>
                  <label>API Key<input type="password" value={modelProfileDraft.api_key} onChange={(e) => setModelProfileDraft({ ...modelProfileDraft, api_key: e.target.value })} /></label>
                  <button className="primary" onClick={() => action(async () => { await api("/me/model-profiles", "POST", modelProfileDraft); const profiles = await api("/me/model-profiles"); setModelProfiles(profiles); setSelectedModelProfile(profiles.at(-1)?.id || ""); setModelProfileDraft({ service_id: "", model: "", api_key: "" }); }, "个人模型档案已保存")}>保存个人档案</button>
                  {modelProfiles.map((profile) => <div className="list-row" key={profile.id}><b>{profile.model}</b><span>{modelServices.find((s) => s.id === profile.service_id)?.name || "服务已删除"} · {profile.has_key ? "Key 已加密" : "未配置 Key"} · v{profile.version}</span></div>)}
                </section>
              )}
              {view === "model" && modelProfiles.length > 0 && (
                <section className="panel form-panel mt">
                  <SectionTitle title="管理个人模型档案" subtitle="更新已选档案的服务、模型或 API Key；密钥不回显。" />
                  <label>选择档案<select value={modelProfileEditId} onChange={(e) => { const selected = modelProfiles.find((profile: Any) => profile.id === e.target.value); setModelProfileEditId(e.target.value); if (selected) setModelProfileDraft({ service_id: selected.service_id, model: selected.model, api_key: "" }); }}><option value="">请选择档案</option>{modelProfiles.map((profile: Any) => <option key={profile.id} value={profile.id}>{profile.model} · v{profile.version}</option>)}</select></label>
                  {modelProfileEditId && <>
                    <label>服务<select value={modelProfileDraft.service_id} onChange={(e) => setModelProfileDraft({ ...modelProfileDraft, service_id: e.target.value, model: "" })}>{modelServices.filter((service: Any) => service.enabled).map((service: Any) => <option key={service.id} value={service.id}>{service.name}</option>)}</select></label>
                    <label>模型<select value={modelProfileDraft.model} onChange={(e) => setModelProfileDraft({ ...modelProfileDraft, model: e.target.value })}>{(modelServices.find((service: Any) => service.id === modelProfileDraft.service_id)?.models || []).map((name: string) => <option key={name} value={name}>{name}</option>)}</select></label>
                    <label>替换 API Key<input type="password" value={modelProfileDraft.api_key} onChange={(e) => setModelProfileDraft({ ...modelProfileDraft, api_key: e.target.value })} placeholder="仅需替换时填写" /></label>
                    <div className="inline"><button className="primary" onClick={() => action(async () => { const body: Any = { service_id: modelProfileDraft.service_id, model: modelProfileDraft.model }; if (modelProfileDraft.api_key) body.api_key = modelProfileDraft.api_key; await api(`/me/model-profiles/${modelProfileEditId}`, "PATCH", body); setModelProfiles(await api("/me/model-profiles")); setModelProfileDraft({ service_id: "", model: "", api_key: "" }); setModelProfileEditId(""); }, "模型档案已更新")}>保存修改</button><button onClick={() => action(async () => { const current = modelProfiles.find((profile: Any) => profile.id === modelProfileEditId); await api(`/me/model-profiles/${modelProfileEditId}`, "PATCH", { enabled: !current?.enabled }); setModelProfiles(await api("/me/model-profiles")); }, "模型档案状态已更新")}>{modelProfiles.find((profile: Any) => profile.id === modelProfileEditId)?.enabled ? "停用" : "启用"}</button></div>
                  </>}
                </section>
              )}
              {view === "model" && user.admin && (
                <section className="panel form-panel mt">
                  <SectionTitle title="审核模型服务" subtitle="管理员维护允许使用的模型服务和模型名称，不保存审核人员的 API Key。" />
                  <label>服务名称<input value={modelServiceDraft.name} onChange={(e) => setModelServiceDraft({ ...modelServiceDraft, name: e.target.value })} /></label>
                  <label>OpenAI 兼容接口地址<input value={modelServiceDraft.base_url} onChange={(e) => setModelServiceDraft({ ...modelServiceDraft, base_url: e.target.value })} /></label>
                  <label>允许模型，每行一个<textarea value={modelServiceDraft.models} onChange={(e) => setModelServiceDraft({ ...modelServiceDraft, models: e.target.value })} /></label>
                  <button className="primary" onClick={() => action(async () => {
                    await api("/model-services", "POST", { ...modelServiceDraft, models: modelServiceDraft.models.split(/\r?\n/).map((name: string) => name.trim()).filter(Boolean) });
                    setModelServices(await api("/model-services"));
                    setModelServiceDraft({ name: "", base_url: "", models: "", enabled: true });
                  }, "模型服务已加入白名单")}>添加服务</button>
                  {modelServices.map((service) => <div className="list-row" key={service.id}><b>{service.name}</b><span>{service.base_url} · {service.models.join(", ")}</span></div>)}
                </section>
              )}
              {view === "model" && user.admin && false && (
                <>
                  <PageTitle
                    kicker="AI CONFIGURATION"
                    title="模型接口配置"
                    desc="只有管理员可更改模型地址和密钥。附录D任务在模型未配置时不会产生虚假审核结果。"
                  />
                  <section className="panel form-panel">
                    <label>
                      OpenAI 兼容接口地址
                      <input
                        placeholder="http://model.internal/v1"
                        value={model.base_url || ""}
                        onChange={(e) =>
                          setModel({ ...model, base_url: e.target.value })
                        }
                      />
                    </label>
                    <label>
                      模型名称
                      <input
                        placeholder="机构内网模型名称"
                        value={model.model || ""}
                        onChange={(e) =>
                          setModel({ ...model, model: e.target.value })
                        }
                      />
                    </label>
                    <label>
                      API 密钥（留空保持已有密钥）
                      <input
                        type="password"
                        value={model.api_key || ""}
                        onChange={(e) =>
                          setModel({ ...model, api_key: e.target.value })
                        }
                      />
                    </label>
                    <label>
                      超时秒数
                      <input
                        type="number"
                        min="10"
                        max="300"
                        value={model.timeout || 120}
                        onChange={(e) =>
                          setModel({
                            ...model,
                            timeout: Number(e.target.value),
                          })
                        }
                      />
                    </label>
                    <label className="checkbox">
                      <input
                        type="checkbox"
                        checked={!!model.external}
                        onChange={(e) =>
                          setModel({ ...model, external: e.target.checked })
                        }
                      />{" "}
                      允许将文档内容发送到外部模型服务
                    </label>
                    <label className="checkbox">
                      <input
                        type="checkbox"
                        checked={model.enabled !== false}
                        onChange={(e) =>
                          setModel({ ...model, enabled: e.target.checked })
                        }
                      />{" "}
                      启用模型审核
                    </label>
                    <button
                      className="primary"
                      onClick={() =>
                        action(async () => {
                          setModel(await api("/model", "PUT", model));
                        }, "模型配置已保存")
                      }
                    >
                      保存配置
                    </button>
                  </section>
                </>
              )}
              {view === "users" && user.admin && (
                <>
                  <PageTitle
                    kicker="TEAM MANAGEMENT"
                    title="用户管理"
                    desc="管理员创建审核员账号，再将其加入对应项目。"
                  />
                  <div className="grid2">
                    <section className="panel form-panel">
                      <SectionTitle
                        title="新建账号"
                        subtitle="初始密码至少12位"
                      />
                      <label>
                        用户名
                        <input
                          value={newUser.username}
                          onChange={(e) =>
                            setNewUser({ ...newUser, username: e.target.value })
                          }
                        />
                      </label>
                      <label>
                        显示名称
                        <input
                          value={newUser.display_name}
                          onChange={(e) =>
                            setNewUser({
                              ...newUser,
                              display_name: e.target.value,
                            })
                          }
                        />
                      </label>
                      <label>
                        初始密码
                        <input
                          type="password"
                          value={newUser.password}
                          onChange={(e) =>
                            setNewUser({ ...newUser, password: e.target.value })
                          }
                        />
                      </label>
                      <button
                        className="primary"
                        onClick={() =>
                          action(async () => {
                            await api("/users", "POST", newUser);
                            setUsers(await api("/users"));
                            setNewUser({
                              username: "",
                              display_name: "",
                              password: "",
                            });
                          }, "用户已创建")
                        }
                      >
                        创建审核员
                      </button>
                    </section>
                    <section className="panel">
                      <SectionTitle
                        title="现有用户"
                        subtitle="账号权限按项目单独分配"
                      />
                      {users.map((u) => (
                        <div className="source-row" key={u.id}>
                          <div className="avatar">
                            {u.display_name.slice(0, 1)}
                          </div>
                          <div>
                            <b>{u.display_name}</b>
                            <small>{u.username}</small>
                          </div>
                          <Badge
                            text={u.admin ? "管理员" : "审核员"}
                            tone={u.admin ? "good" : "soft"}
                          />
                        </div>
                      ))}
                    </section>
                  </div>
                </>
              )}
              {view === "account" && (
                <>
                  <PageTitle
                    kicker="MY ACCOUNT"
                    title="我的账号"
                    desc="为账号设置独立密码，避免共用初始凭据。"
                  />
                  <section className="panel form-panel">
                    <SectionTitle
                      title={user.display_name}
                      subtitle={`用户名：${user.username}`}
                    />
                    <label>
                      当前密码
                      <input
                        type="password"
                        value={passwords.old}
                        onChange={(e) =>
                          setPasswords({ ...passwords, old: e.target.value })
                        }
                      />
                    </label>
                    <label>
                      新密码（至少 12 位）
                      <input
                        type="password"
                        value={passwords.new}
                        onChange={(e) =>
                          setPasswords({ ...passwords, new: e.target.value })
                        }
                      />
                    </label>
                    <button
                      className="primary"
                      onClick={() =>
                        action(async () => {
                          await api("/me/password", "POST", passwords);
                          setPasswords({ old: "", new: "" });
                        }, "密码已更新")
                      }
                    >
                      更新密码
                    </button>
                  </section>
                </>
              )}
              {view === "audit" && (
                <>
                  <PageTitle
                    kicker="ACTIVITY LOG"
                    title="操作记录"
                    desc="保留上传、配置、审核和问题复核等关键操作。"
                  />
                  <div className="panel table-panel">
                    <table>
                      <thead>
                        <tr>
                          <th>时间</th>
                          <th>操作</th>
                          <th>详情</th>
                        </tr>
                      </thead>
                      <tbody>
                        {auditRows.map((a) => (
                          <tr key={a.id}>
                            <td>
                              {new Date(a.created_at * 1000).toLocaleString()}
                            </td>
                            <td>{a.action}</td>
                            <td>{JSON.stringify(a.detail)}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                    {!auditRows.length && <Empty text="暂无操作记录" />}
                  </div>
                </>
              )}
            </>
          )}
        </div>
      </main>
    </div>
  );
}

function PageTitle({
  kicker,
  title,
  desc,
}: {
  kicker: string;
  title: string;
  desc: string;
}) {
  return (
    <div className="page-heading">
      <div>
        <span className="eyebrow">{kicker}</span>
        <h1>{title}</h1>
        <p>{desc}</p>
      </div>
    </div>
  );
}
function SectionTitle({
  title,
  subtitle,
}: {
  title: string;
  subtitle: string;
}) {
  return (
    <div className="section-title">
      <h2>{title}</h2>
      <p>{subtitle}</p>
    </div>
  );
}
function Stat({
  label,
  value,
  hint,
}: {
  label: string;
  value: any;
  hint: string;
}) {
  return (
    <div className="stat">
      <span>{label}</span>
      <strong>{value}</strong>
      <small>{hint}</small>
    </div>
  );
}
function Badge({ text, tone = "soft" }: { text: string; tone?: string }) {
  return <span className={"badge " + tone}>{text}</span>;
}
function Empty({ text }: { text: string }) {
  return (
    <div className="empty">
      <span>◇</span>
      <p>{text}</p>
    </div>
  );
}
function Notice({ text }: { text: string }) {
  return (
    <div className="notice">
      <b>提示</b> {text}
    </div>
  );
}
function RequirementPicker({
  record,
  current,
  candidates,
  requirements,
  onPick,
}: {
  record: Any;
  current?: Any;
  candidates: Any[];
  requirements: Any[];
  onPick: (key: string) => void;
}) {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const pool = requirements.filter(
    (r) => r.domain === record.domain && r.family === record.extension,
  );
  const term = query.trim().toLocaleLowerCase();
  const found = pool.filter(
    (r) =>
      !term ||
      `${r.control} ${r.text} ${r.source}`.toLocaleLowerCase().includes(term),
  );
  return (
    <details
      className="requirement-picker"
      open={open}
      onToggle={(event) => setOpen(event.currentTarget.open)}
    >
      <summary>{current ? "查看或更改核查项" : "人工选择核查项"}</summary>
      {open && (
        <div className="requirement-picker-body">
          {current && (
            <small>
              当前：{current.control} · {current.text}
            </small>
          )}
          {!!candidates.length && (
            <div className="requirement-candidates">
              <small>相似候选（需人工确认）</small>
              {candidates.map((item) => (
                <button key={item.key} onClick={() => onPick(item.key)}>
                  {item.text} · 相似度 {Math.round(item.score * 100)}%
                </button>
              ))}
            </div>
          )}
          <input
            aria-label={`搜索${record.object}的核查项`}
            placeholder="搜索控制点、测评项或来源"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
          />
          <small>
            同一安全域与扩展下共 {pool.length} 项，当前找到 {found.length} 项
          </small>
          <div className="requirement-options">
            {found.slice(0, 30).map((item) => (
              <button key={item.key} onClick={() => onPick(item.key)}>
                <b>{item.control}</b> · {item.text}
                <small>{item.source}</small>
              </button>
            ))}
          </div>
          {found.length > 30 && (
            <small>仅显示前 30 项，请继续输入关键词缩小范围。</small>
          )}
          {!pool.length && (
            <small>
              当前级别和扩展下没有该安全域的核查项，请先检查项目配置与知识库。
            </small>
          )}
        </div>
      )}
    </details>
  );
}

createRoot(document.getElementById("root")!).render(<App />);
