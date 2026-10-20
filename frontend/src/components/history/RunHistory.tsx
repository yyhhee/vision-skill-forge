import { useEffect, useRef, useState } from "react";
import {
  ArrowLeftIcon,
  MagnifyingGlassIcon,
  CalendarBlankIcon,
  ImageIcon,
  ArrowClockwiseIcon,
  DownloadSimpleIcon,
} from "@phosphor-icons/react";
import { AppShell } from "../AppShell";
import { Button, Modal } from "../ui";
import { RunHistoryDetail } from "./RunHistoryDetail";
import {
  dateRangeError,
  emptyHistoryFilter,
  filterHistory,
  fixtureHistory,
  historyDate,
  historyExport,
  historyRoute,
  historyStatusNames,
  readRunArchive,
  rowFromRun,
  type DateRange,
  type HistoryFilter,
  type HistoryRow,
} from "../../data/runHistory";
import { downloadJson, RUN_STORAGE_KEY } from "../../data/runs";
const PAGE_SIZE = 5;
export function RunHistory({
  fixture,
  navigate,
}: {
  fixture: string;
  navigate: (url: string) => void;
}) {
  const [rows, setRows] = useState<HistoryRow[]>([]),
    [loading, setLoading] = useState(true),
    [error, setError] = useState("");
  const [initialRoute] = useState(() => historyRoute(location.search));
  const [filter, setFilter] = useState<HistoryFilter>(initialRoute.filter);
  const [page, setPage] = useState(initialRoute.page),
    [selected, setSelected] = useState<string | null>(null),
    [checked, setChecked] = useState<string[]>([]);
  const [info, setInfo] = useState(""),
    [dateOpen, setDateOpen] = useState(false),
    [range, setRange] = useState<DateRange>(emptyHistoryFilter().range);
  const allCheck = useRef<HTMLInputElement>(null),
    detailAnchor = useRef<HTMLDivElement>(null),
    userSelected = useRef(false);
  const now = fixture ? Date.parse("2026-10-17T10:26:00+08:00") : Date.now();
  const reload = (initial = false) => {
    try {
      const next = fixture
        ? fixtureHistory()
        : readRunArchive().runs.map(rowFromRun);
      setRows(next);
      setError("");
      const first =
        filterHistory(next, filter, now).find(
          (r) => r.id === initialRoute.selected,
        ) ??
        filterHistory(next, filter, now)[(initialRoute.page - 1) * PAGE_SIZE];
      setSelected((old) =>
        initial
          ? (first?.id ?? null)
          : next.some((r) => r.id === old)
            ? old
            : null,
      );
      setChecked((old) =>
        initial && first
          ? [first.id]
          : old.filter((id) => next.some((r) => r.id === id)),
      );
    } catch (e) {
      setRows([]);
      setSelected(null);
      setChecked([]);
      setError((e as Error).message);
    }
    setLoading(false);
  };
  useEffect(() => {
    const title = document.title;
    document.title = "Vision Skill Forge · 运行记录";
    reload(true);
    return () => {
      document.title = title;
    };
  }, [fixture]);
  useEffect(() => {
    if (fixture) return;
    const sync = (e: StorageEvent) => {
      if (e.key === null || e.key === RUN_STORAGE_KEY) reload();
    };
    const focus = () => reload();
    window.addEventListener("storage", sync);
    window.addEventListener("focus", focus);
    return () => {
      window.removeEventListener("storage", sync);
      window.removeEventListener("focus", focus);
    };
  }, [fixture]);
  const filtered = filterHistory(rows, filter, now),
    pages = Math.max(1, Math.ceil(filtered.length / PAGE_SIZE)),
    currentPage = Math.min(page, pages),
    visible = filtered.slice(
      (currentPage - 1) * PAGE_SIZE,
      currentPage * PAGE_SIZE,
    );
  const detail = filtered.find((r) => r.id === selected);
  useEffect(() => {
    if (loading) return;
    const p = new URLSearchParams(location.search);
    for (const key of [
      "q",
      "status",
      "media",
      "skill",
      "range",
      "from",
      "to",
      "page",
      "selected",
    ])
      p.delete(key);
    if (filter.search) p.set("q", filter.search);
    if (filter.skillId) p.set("skill", filter.skillId);
    if (filter.status !== "all") p.set("status", filter.status);
    if (filter.media !== "all") p.set("media", filter.media);
    if (filter.range.mode !== "all") p.set("range", filter.range.mode);
    if (filter.range.mode === "custom") {
      p.set("from", filter.range.from);
      p.set("to", filter.range.to);
    }
    if (currentPage > 1) p.set("page", String(currentPage));
    if (detail) p.set("selected", detail.id);
    const query = p.toString();
    history.replaceState(history.state, "", `/runs${query ? `?${query}` : ""}`);
  }, [loading, JSON.stringify(filter), currentPage, detail?.id]);
  useEffect(() => {
    if (allCheck.current)
      allCheck.current.indeterminate =
        visible.some((r) => checked.includes(r.id)) &&
        !visible.every((r) => checked.includes(r.id));
  }, [checked, visible]);
  useEffect(() => {
    if (userSelected.current && detail && innerWidth <= 1100)
      detailAnchor.current?.scrollIntoView({
        block: "start",
        behavior: "instant",
      });
    userSelected.current = false;
  }, [selected, detail?.id]);
  const changeFilter = (patch: Partial<HistoryFilter>) => {
    setFilter((f) => ({ ...f, ...patch }));
    setPage(1);
    setChecked([]);
  };
  const choose = (id: string) => {
    userSelected.current = true;
    setSelected(id);
  };
  const fresh = (id: string) => {
    const current = fixture
      ? fixtureHistory()
      : readRunArchive().runs.map(rowFromRun);
    const row = current.find((r) => r.id === id);
    if (!row)
      throw new Error("这条记录已不在归档中，请刷新列表；不会替换为其它运行。");
    return row;
  };
  const view = (id: string) => {
    try {
      const row = fresh(id);
      if (!row.run)
        return setInfo(
          "此条仅有参考摘要，未提供完整配置与结果详情；不会跳转到区域告警结果冒充。",
        );
      if (row.run.snapshot.mediaRef !== "construction-poster")
        return setInfo(
          "这条记录的素材尚未接入，可导出运行记录与快照；不会用施工海报冒充原素材。",
        );
      navigate(
        `/runs/${encodeURIComponent(id)}${fixture ? "?fixture=11" : ""}`,
      );
    } catch (e) {
      setInfo((e as Error).message);
      reload();
    }
  };
  const exportRows = (ids: string[]) => {
    try {
      const current = fixture
        ? fixtureHistory()
        : readRunArchive().runs.map(rowFromRun);
      const selectedRows = ids.map((id) => {
        const row = current.find((r) => r.id === id);
        if (!row)
          throw new Error(
            "所选记录已变化，请重新选择后导出；不会导出其它运行。",
          );
        return row;
      });
      if (selectedRows.length === 1)
        downloadJson(
          historyExport(selectedRows[0]),
          `${selectedRows[0].id}-run-record.json`,
        );
      else if (selectedRows.length)
        downloadJson(
          {
            format: "vsf-run-records",
            schemaVersion: 1,
            demo: true,
            records: selectedRows.map(historyExport),
          },
          "selected-run-records.json",
        );
    } catch (e) {
      setInfo((e as Error).message);
      reload();
    }
  };
  return (
    <AppShell
      className="history-shell"
      activeNavigation="运行记录"
      title="历史记录"
      dirty={false}
      revision={0}
      showRevision={false}
      onApply={() => {}}
      onRun={() => {}}
      onMenu={() => {}}
      onNavigate={(label) => {
        if (label === "技能库")
          navigate(`/skills${fixture ? "?fixture=01" : ""}`);
        else if (label === "模型接入")
          navigate(`/settings/models${fixture ? "?fixture=models" : ""}`);
        else if (label === "能力管理")
          navigate(
            `/settings/capabilities${fixture ? "?fixture=capabilities" : ""}`,
          );
      }}
      actions={
        <>
          <Button
            icon={ArrowLeftIcon}
            onClick={() => navigate(`/skills${fixture ? "?fixture=01" : ""}`)}
          >
            返回技能库
          </Button>
          <Button
            variant="primary"
            disabled={checked.length !== 1 || !!error || loading}
            onClick={() => view(checked[0])}
          >
            查看所选结果
          </Button>
        </>
      }
    >
      <main className={`history-page ${detail ? "with-detail" : ""}`}>
        <div className="history-main">
          <header className="history-heading">
            <div>
              <h1>运行记录</h1>
              <p>每次模拟运行保留所用版本、素材引用、结果与证据。</p>
            </div>
            <Button
              variant="subtle"
              icon={CalendarBlankIcon}
              onClick={() => {
                setRange({ ...filter.range });
                setDateOpen(true);
              }}
            >
              日期：
              {filter.range.mode === "all"
                ? "全部"
                : filter.range.mode === "today"
                  ? "今天"
                  : filter.range.mode === "week"
                    ? "最近7天"
                    : "自定义"}
            </Button>
          </header>
          <section className="panel history-list" aria-label="运行记录列表">
            <div className="history-filters">
              <label>
                <MagnifyingGlassIcon size={23} />
                <input
                  type="search"
                  aria-label="搜索运行记录"
                  placeholder="技能名称或素材"
                  value={filter.search}
                  onChange={(e) => changeFilter({ search: e.target.value })}
                />
              </label>
              <select
                aria-label="运行状态"
                value={filter.status}
                onChange={(e) =>
                  changeFilter({
                    status: e.target.value as HistoryFilter["status"],
                  })
                }
              >
                <option value="all">全部状态</option>
                {Object.entries(historyStatusNames).map(([id, name]) => (
                  <option key={id} value={id}>
                    {name}
                  </option>
                ))}
              </select>
              <select
                aria-label="媒体类型"
                value={filter.media}
                onChange={(e) =>
                  changeFilter({
                    media: e.target.value as HistoryFilter["media"],
                  })
                }
              >
                <option value="all">图片与视频</option>
                <option value="image">图片模拟</option>
                <option value="video_demo">视频模拟</option>
                <option value="unknown">素材未接入</option>
              </select>
            </div>
            {filter.skillId && (
              <div className="history-filter-context">
                仅显示所选技能的运行记录
                <Button
                  variant="subtle"
                  onClick={() => changeFilter({ skillId: "" })}
                >
                  查看全部技能
                </Button>
              </div>
            )}
            {filter.range.mode !== "all" && (
              <div className="history-filter-context">
                日期按北京时间：
                {filter.range.mode === "custom"
                  ? `${filter.range.from} 至 ${filter.range.to}`
                  : filter.range.mode === "today"
                    ? "今天"
                    : "最近7天（含今天）"}
              </div>
            )}
            {loading ? (
              <p className="history-empty" role="status">
                正在读取本地运行归档…
              </p>
            ) : error ? (
              <div className="history-error">
                <p role="alert">{error}</p>
                <Button icon={ArrowClockwiseIcon} onClick={() => reload()}>
                  重新读取记录
                </Button>
                <Button
                  icon={DownloadSimpleIcon}
                  onClick={() => {
                    try {
                      const raw = localStorage.getItem(RUN_STORAGE_KEY);
                      downloadJson(
                        { format: "vsf-raw-run-cache", schemaVersion: 1, raw },
                        "run-cache-backup.json",
                      );
                    } catch {
                      setInfo(
                        "浏览器不允许读取本地存储，当前无法备份；未清空或替换原数据。",
                      );
                    }
                  }}
                >
                  导出原始缓存备份
                </Button>
              </div>
            ) : (
              <>
                <div className="history-table-scroll">
                  <table>
                    <thead>
                      <tr>
                        <th>
                          <input
                            ref={allCheck}
                            type="checkbox"
                            aria-label="选择本页全部记录"
                            disabled={!visible.length}
                            checked={
                              !!visible.length &&
                              visible.every((r) => checked.includes(r.id))
                            }
                            onChange={(e) => {
                              const ids = visible.map((r) => r.id);
                              setChecked((old) =>
                                e.target.checked
                                  ? [...new Set([...old, ...ids])]
                                  : old.filter((id) => !ids.includes(id)),
                              );
                            }}
                          />
                        </th>
                        {[
                          "技能与素材",
                          "使用版本",
                          "状态",
                          "运行时间",
                          "操作",
                        ].map((t) => (
                          <th key={t}>{t}</th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      {visible.map((row) => {
                        const date = historyDate(row.createdAt);
                        return (
                          <tr
                            key={row.id}
                            className={selected === row.id ? "selected" : ""}
                          >
                            <td>
                              <input
                                type="checkbox"
                                aria-label={`选择记录：${row.name} ${date.day} ${date.time}`}
                                checked={checked.includes(row.id)}
                                onChange={(e) => {
                                  setChecked((old) =>
                                    e.target.checked
                                      ? [...old, row.id]
                                      : old.filter((id) => id !== row.id),
                                  );
                                  if (e.target.checked) choose(row.id);
                                }}
                              />
                            </td>
                            <td>
                              <button
                                className="history-record"
                                title={`${row.name} · ${date.day} ${date.time}`}
                                onClick={() => choose(row.id)}
                              >
                                {row.thumbnail ? (
                                  <img
                                    src={row.thumbnail}
                                    alt="示例海报缩略图"
                                  />
                                ) : (
                                  <span className="history-no-thumb">
                                    <ImageIcon size={27} />
                                  </span>
                                )}
                                <span>
                                  <strong>{row.name}</strong>
                                  <small title={row.mediaLabel}>
                                    {row.media === "unknown"
                                      ? "素材未接入"
                                      : `海报 · ${row.media === "image" ? "图片" : "视频"}${row.run ? "模拟" : "示例"}`}
                                  </small>
                                </span>
                              </button>
                            </td>
                            <td>
                              {row.revision ? (
                                `R${row.revision}`
                              ) : (
                                <span className="history-no-version">
                                  未提供
                                </span>
                              )}
                            </td>
                            <td>
                              <span className={`history-state ${row.status}`}>
                                {historyStatusNames[row.status]}
                              </span>
                            </td>
                            <td>
                              <time dateTime={row.createdAt}>
                                {date.day}
                                <br />
                                {date.time}
                              </time>
                            </td>
                            <td>
                              <button
                                className="history-view"
                                onClick={() => view(row.id)}
                              >
                                {row.status === "failed"
                                  ? "查看原因"
                                  : row.status === "running"
                                    ? "查看进度"
                                    : "查看结果"}
                              </button>
                            </td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
                {!filtered.length && (
                  <div className="history-empty">
                    <h3>
                      {rows.length
                        ? "没有符合筛选条件的记录"
                        : "还没有本地运行记录"}
                    </h3>
                    <p>
                      {rows.length
                        ? "可调整搜索、状态、媒体或日期范围。"
                        : "请从技能中校验并应用，再开始模拟验证。这里不会自动添加演示记录。"}
                    </p>
                    {rows.length > 0 && (
                      <Button
                        onClick={() => {
                          setFilter(emptyHistoryFilter());
                          setChecked([]);
                          setPage(1);
                        }}
                      >
                        清除筛选
                      </Button>
                    )}
                    {!rows.length && !fixture && (
                      <Button
                        onClick={() => navigate("/runs?fixture=run-history")}
                      >
                        查看隔离演示记录
                      </Button>
                    )}
                  </div>
                )}
                <footer className="history-pagination">
                  <span>
                    共 {filtered.length} 条
                    {checked.length > 0 ? ` · 已选 ${checked.length} 条` : ""}
                  </span>
                  {checked.length > 1 && (
                    <>
                      <Button
                        icon={DownloadSimpleIcon}
                        onClick={() => exportRows(checked)}
                      >
                        导出所选 {checked.length} 条
                      </Button>
                      <small>查看详情时请仅勾选1条</small>
                    </>
                  )}
                  {pages > 1 && (
                    <nav aria-label="记录分页">
                      <Button
                        disabled={currentPage === 1}
                        onClick={() => {
                          setPage(currentPage - 1);
                          setSelected(null);
                        }}
                      >
                        上一页
                      </Button>
                      <span>
                        {currentPage} / {pages}
                      </span>
                      <Button
                        disabled={currentPage === pages}
                        onClick={() => {
                          setPage(currentPage + 1);
                          setSelected(null);
                        }}
                      >
                        下一页
                      </Button>
                    </nav>
                  )}
                </footer>
              </>
            )}
          </section>
        </div>
        {detail && (
          <div ref={detailAnchor} className="history-detail-anchor">
            <RunHistoryDetail
              row={detail}
              close={() => setSelected(null)}
              view={() => view(detail.id)}
              exportRow={() => exportRows([detail.id])}
            />
          </div>
        )}
      </main>
      {info && (
        <Modal
          title="运行记录说明"
          onClose={() => setInfo("")}
          footer={<Button onClick={() => setInfo("")}>知道了</Button>}
        >
          <p>{info}</p>
        </Modal>
      )}
      {dateOpen && (
        <Modal
          title="筛选运行日期"
          onClose={() => setDateOpen(false)}
          footer={
            <>
              <Button onClick={() => setDateOpen(false)}>取消</Button>
              <Button
                variant="primary"
                disabled={!!dateRangeError(range)}
                onClick={() => {
                  changeFilter({ range });
                  setDateOpen(false);
                }}
              >
                应用日期筛选
              </Button>
            </>
          }
        >
          <p>按运行开始日期筛选，使用北京时间；结束日期包含当天。</p>
          <label className="history-date-field">
            日期范围
            <select
              aria-label="日期范围"
              value={range.mode}
              onChange={(e) =>
                setRange((r) => ({
                  ...r,
                  mode: e.target.value as DateRange["mode"],
                }))
              }
            >
              <option value="all">全部日期</option>
              <option value="today">今天</option>
              <option value="week">最近7天</option>
              <option value="custom">自定义日期</option>
            </select>
          </label>
          {range.mode === "custom" && (
            <div className="history-custom-date">
              <label>
                开始日期
                <input
                  type="date"
                  value={range.from}
                  onChange={(e) =>
                    setRange((r) => ({ ...r, from: e.target.value }))
                  }
                />
              </label>
              <label>
                结束日期
                <input
                  type="date"
                  value={range.to}
                  onChange={(e) =>
                    setRange((r) => ({ ...r, to: e.target.value }))
                  }
                />
              </label>
            </div>
          )}
          {dateRangeError(range) && (
            <p className="history-date-error" role="alert">
              {dateRangeError(range)}
            </p>
          )}
        </Modal>
      )}
    </AppShell>
  );
}
