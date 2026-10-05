import React, {
  useEffect,
  useMemo,
  useState,
  useRef,
  lazy,
  Suspense,
} from "react";
import { createRoot } from "react-dom/client";
import "./style.css";
import "./v2.css";
const LensChart = lazy(() => import("./LensChart"));
import Insights from "./Insights";
import SourceStatus from "./SourceStatus";
import { api, useResource } from "./useResource";

const fmt = (n) => (n == null ? "未取得" : Number(n).toLocaleString("zh-CN"));
const EMPTY = [];
const today = () =>
  new Intl.DateTimeFormat("sv-SE", { timeZone: "Asia/Shanghai" }).format(
    new Date(),
  );
const shift = (d, days) => {
  const x = new Date(d + "T12:00:00Z");
  x.setUTCDate(x.getUTCDate() + days);
  return x.toISOString().slice(0, 10);
};
const yearStart = (years) => {
  const d = today();
  return `${Number(d.slice(0, 4)) - years}${d.slice(4)}`;
};
function readWatch() {
  try {
    const x = JSON.parse(localStorage.getItem("stock-lens-watch") || "[]");
    return Array.isArray(x)
      ? x
          .filter(
            (s) => s && /^\d{6}$/.test(s.code) && typeof s.name === "string",
          )
          .slice(0, 100)
      : [];
  } catch {
    return [];
  }
}
function Source({ href, children }) {
  return href ? (
    <a href={href} target="_blank" rel="noopener noreferrer">
      {children} ↗
    </a>
  ) : (
    <span>未取得</span>
  );
}
function Status({ status, empty }) {
  return (
    <div className={"status " + (status?.error ? "warn" : "")} role="status">
      <span className={"dot " + (status?.refreshing ? "pulse" : "")} />
      {status?.refreshing
        ? "正在更新披露记录"
        : status?.error
          ? "更新失败，保留已有记录"
          : empty
            ? "尚无可用记录"
            : "披露记录可用"}
      <span className="muted">
        {status?.success_at
          ? "更新 " +
            status.success_at.slice(0, 16).replace("T", " ") +
            " UTC+8"
          : ""}
      </span>
      {status?.error && (
        <details>
          <summary>查看原因</summary>
          {status.error}
        </details>
      )}
    </div>
  );
}
function exportRows(rows, code) {
  const quote = (s) => {
    const value =
      typeof s === "string" && /^[=+@-]/.test(s) ? "'" + s : String(s ?? "");
    return '"' + value.replaceAll('"', '""') + '"';
  };
  const header = [
    "股票代码",
    "统计截止日",
    "股东户数",
    "变化户数",
    "变化率(%)",
    "披露日",
    "统计口径",
    "来源",
    "原文链接",
  ];
  const lines = rows.map((r) => [
    code,
    r.end_date,
    r.holders,
    r.change_count,
    r.change_pct,
    r.disclosure_date,
    r.scope,
    r.source,
    r.original_url || r.page_url,
  ]);
  const blob = new Blob(
    [
      "\ufeff" +
        [header, ...lines].map((row) => row.map(quote).join(",")).join("\r\n"),
    ],
    { type: "text/csv;charset=utf-8" },
  );
  const url = URL.createObjectURL(blob),
    a = document.createElement("a");
  a.href = url;
  a.download = `${code}-股东户数.csv`;
  a.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
function App() {
  const searchRef = useRef(null),
    helpRef = useRef(null),
    watchSync = useRef(Promise.resolve());
  const [query, setQuery] = useState(""),
    [suggest, setSuggest] = useState([]),
    [searchWarning, setSearchWarning] = useState(""),
    [searching, setSearching] = useState(true),
    [option, setOption] = useState(-1);
  const [code, setCode] = useState(() =>
    /^#\d{6}$/.test(location.hash) ? location.hash.slice(1) : "600000",
  );
  const [nonce, setNonce] = useState(0),
    [priceNonce, setPriceNonce] = useState(0),
    [watch, setWatch] = useState(readWatch);
  const [history, setHistory] = useState("3y"),
    [scope, setScope] = useState(""),
    [selectedId, setSelectedId] = useState(null),
    [mode, setMode] = useState("interval"),
    [notice, setNotice] = useState(""),
    [volume, setVolume] = useState(false),
    [install, setInstall] = useState(null);
  const stockResource = useResource("/api/stocks/" + code, nonce),
    data = stockResource.data,
    error = stockResource.error;
  const priceStart = data?.holders.length
    ? shift(data.holders[0].end_date, -14)
    : null;
  const priceData = useResource(
    priceStart
      ? `/api/stocks/${code}/prices?start=${priceStart}&end=${today()}`
      : null,
    priceNonce,
  );
  const priceRows = priceData.data?.items || EMPTY;
  useEffect(() => {
    setSelectedId(null);
    setScope("");
    setMode("interval");
    setNotice("");
  }, [code]);
  useEffect(() => {
    if (data && !scope) setScope(data.holders.at(-1)?.scope || "");
  }, [data, scope]);
  useEffect(() => {
    const h = () => {
      if (/^#\d{6}$/.test(location.hash)) setCode(location.hash.slice(1));
    };
    addEventListener("hashchange", h);
    return () => removeEventListener("hashchange", h);
  }, []);
  useEffect(() => {
    const controller = new AbortController();
    let alive = true;
    setSearching(true);
    setSuggest([]);
    setOption(-1);
    const t = setTimeout(async () => {
      try {
        const r = await api("/api/search?q=" + encodeURIComponent(query), {
          signal: controller.signal,
        });
        if (alive) {
          setSuggest(r.items);
          setSearchWarning(r.warning || "");
        }
      } catch (e) {
        if (alive) setSearchWarning("搜索暂不可用，请检查网络或后台连接");
      } finally {
        if (alive) setSearching(false);
      }
    }, 280);
    return () => {
      alive = false;
      clearTimeout(t);
      controller.abort();
    };
  }, [query]);
  useEffect(() => {
    const h = (e) => {
      if (
        (e.key === "/" &&
          !["INPUT", "TEXTAREA", "SELECT"].includes(e.target.tagName)) ||
        ((e.ctrlKey || e.metaKey) && e.key === "k")
      ) {
        e.preventDefault();
        searchRef.current?.focus();
        searchRef.current?.scrollIntoView({
          block: "center",
          behavior: "smooth",
        });
      }
    };
    addEventListener("keydown", h);
    return () => removeEventListener("keydown", h);
  }, []);
  useEffect(() => {
    try {
      localStorage.setItem("stock-lens-watch", JSON.stringify(watch));
    } catch {
      setNotice("浏览器未允许保存关注列表");
    }
    watchSync.current = watchSync.current
      .catch(() => {})
      .then(() =>
        api("/api/watchlist", {
          method: "PUT",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ codes: watch.map((s) => s.code) }),
        }),
      )
      .catch(() => setNotice("关注已保存；后台更新同步暂不可用"));
  }, [watch]);
  useEffect(() => {
    const h = (e) => {
      e.preventDefault();
      setInstall(e);
    };
    addEventListener("beforeinstallprompt", h);
    return () => removeEventListener("beforeinstallprompt", h);
  }, []);
  const scopes = useMemo(
    () => [...new Set((data?.holders || []).map((r) => r.scope))],
    [data],
  );
  const allRows = useMemo(() => {
    const map = new Map();
    for (const r of data?.holders || [])
      if (r.scope === scope) map.set(r.conflict ? r.id : r.end_date, r);
    return [...map.values()].sort((a, b) =>
      a.end_date.localeCompare(b.end_date),
    );
  }, [data, scope]);
  const rows = useMemo(
    () =>
      allRows.filter(
        (r) =>
          history === "all" ||
          r.end_date >= yearStart(history === "1y" ? 1 : 3),
      ),
    [allRows, history],
  );
  const selected = allRows.find((r) => r.id === selectedId) || allRows.at(-1);
  const prev = selected
    ? allRows.filter((r) => r.end_date < selected.end_date).at(-1)
    : null;
  const range = useMemo(() => {
    if (!selected) return null;
    if (mode === "disclosure") {
      if (!selected.disclosure_date) return null;
      return {
        start: shift(selected.disclosure_date, -30),
        end: shift(selected.disclosure_date, 30),
      };
    }
    return {
      start: prev ? shift(prev.end_date, 1) : selected.end_date,
      end: selected.end_date,
    };
  }, [selected, prev, mode]);
  const choose = (s) => {
    location.hash = s.code;
    setCode(s.code);
    setQuery("");
    setSearchWarning("");
    setOption(-1);
    searchRef.current?.blur();
  };
  const isWatched = watch.some((s) => s.code === code),
    latest = allRows.at(-1),
    lastPrice = priceRows.at(-1);
  function toggleWatch() {
    if (!data) return;
    if (!isWatched && watch.length >= 100) {
      setNotice("关注列表最多100只");
      return;
    }
    setWatch((w) =>
      isWatched ? w.filter((s) => s.code !== code) : [...w, data.stock],
    );
  }
  async function refresh() {
    try {
      const r = await api(`/api/stocks/${code}/refresh`, { method: "POST" });
      setNotice(r.message || "已请求更新，已有数据仍可查看");
      if (r.queued) setNonce((n) => n + 1);
    } catch (e) {
      setNotice(e.message);
    }
  }
  async function retryPrices() {
    if (!priceStart) return;
    try {
      const r = await api(
        `/api/stocks/${code}/prices/refresh?start=${priceStart}&end=${today()}`,
        { method: "POST" },
      );
      setNotice(r.message || "已请求更新行情");
      if (r.queued) setPriceNonce((n) => n + 1);
    } catch (e) {
      setNotice(e.message);
    }
  }
  return (
    <>
      <a className="skip-link" href="#workspace">
        跳至股票数据
      </a>
      <header>
        <div className="brand">
          <span className="logo">股</span>
          <div>
            股东观察<small>STOCK LENS</small>
          </div>
        </div>
        <nav aria-label="页面导航">
          <a href="#chart-panel">数据对照</a>
          <a href="#insights-panel">公司资讯</a>
          <button onClick={() => helpRef.current.showModal()}>使用指南</button>
        </nav>
        <button
          className="install"
          onClick={async () => {
            if (install) {
              await install.prompt();
              setInstall(null);
            } else
              setNotice(
                "浏览器菜单 → 添加到主屏幕。手机安装需 HTTPS；局域网 HTTP 可直接浏览。",
              );
          }}
        >
          添加到主屏幕 ↗
        </button>
      </header>
      <main>
        <section className="intro">
          <div>
            <div className="eyebrow">
              A 股研究工作台 <span className="intro-dot">/</span> 沪 · 深 · 北
            </div>
            <h1>把股东变化，放回时间里。</h1>
            <p>披露记录、历史股价与公司资讯，在同一条时间线上读懂。</p>
          </div>
          <div className="edition">
            <span className="dot" />
            公开数据 · 原文可追溯<small>SHAREHOLDERS / PRICE / NEWS</small>
          </div>
        </section>
        <section className="search-panel" aria-label="股票搜索">
          <label htmlFor="search">
            查找公司 <span>输入名称或 6 位代码</span>
          </label>
          <div className="search-wrap">
            <svg
              width="22"
              height="22"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="1.8"
              aria-hidden="true"
            >
              <circle cx="10.5" cy="10.5" r="6.5" />
              <path d="m16 16 5 5" />
            </svg>
            <input
              ref={searchRef}
              id="search"
              role="combobox"
              aria-autocomplete="list"
              aria-controls="search-results"
              aria-expanded={Boolean(suggest.length)}
              aria-activedescendant={
                option >= 0 ? `search-option-${option}` : undefined
              }
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "ArrowDown") {
                  e.preventDefault();
                  setOption((i) => Math.min(suggest.length - 1, i + 1));
                } else if (e.key === "ArrowUp") {
                  e.preventDefault();
                  setOption((i) => Math.max(0, i - 1));
                } else if (e.key === "Enter" && suggest.length) {
                  e.preventDefault();
                  choose(suggest[Math.max(0, option)]);
                } else if (e.key === "Escape") {
                  setQuery("");
                  e.target.blur();
                }
              }}
              placeholder="如：浦发银行 / 600000"
              autoComplete="off"
            />
            <kbd>Ctrl K</kbd>
          </div>
          <div
            id="search-results"
            className="suggestions"
            role="listbox"
            aria-label={query ? "搜索结果" : "快捷查询"}
            aria-live="polite"
          >
            {searching ? (
              <span className="search-progress">正在查找公司…</span>
            ) : (
              suggest.map((s, i) => (
                <button
                  id={`search-option-${i}`}
                  role="option"
                  aria-selected={option === i}
                  key={s.code}
                  onClick={() => choose(s)}
                  className={option === i || s.code === code ? "active" : ""}
                >
                  {s.name}
                  <small>{s.code}</small>
                  <span className="exchange-chip">{s.exchange}</span>
                </button>
              ))
            )}
            {!searching && !suggest.length && (
              <span className="search-progress">
                没有匹配结果，试试完整名称或代码
              </span>
            )}
          </div>
          {searchWarning && <p className="warning">{searchWarning}</p>}
        </section>
        <section className="watch-strip" aria-label="我的关注">
          <span>
            我的关注 <b>{watch.length}</b>
          </span>
          {watch.length ? (
            watch.map((s) => (
              <button
                key={s.code}
                onClick={() => choose(s)}
                className={s.code === code ? "active" : ""}
              >
                {s.name}
                <small>{s.code}</small>
              </button>
            ))
          ) : (
            <span className="muted">点击“关注”，保存常看的公司</span>
          )}
          <span className="local-label">仅此浏览器</span>
        </section>
        {notice && (
          <div className="notice" role="status">
            {notice}
            <button aria-label="关闭提示" onClick={() => setNotice("")}>
              ×
            </button>
          </div>
        )}
        {error && (
          <div className="error" role="alert">
            {data ? "连接失败，当前显示已有记录。" : error}
            <button onClick={() => setNonce((n) => n + 1)}>重新连接</button>
          </div>
        )}
        {!data && !error ? (
          <div className="loading" role="status">
            <span className="loader" />
            正在读取 {code} 的披露记录…
          </div>
        ) : (
          data && (
            <div id="workspace">
              <section className="stock-heading">
                <div>
                  <span className="eyebrow">
                    {
                      {
                        SH: "上海证券交易所",
                        SZ: "深圳证券交易所",
                        BJ: "北京证券交易所",
                      }[data.stock.exchange]
                    }
                  </span>
                  <h2>
                    {data.stock.name}
                    <span>{code}</span>
                  </h2>
                </div>
                <div className="actions">
                  <button
                    onClick={toggleWatch}
                    aria-pressed={isWatched}
                    className={isWatched ? "selected" : ""}
                  >
                    {isWatched ? "★ 已关注" : "☆ 关注"}
                  </button>
                  <button disabled={data.status.refreshing} onClick={refresh}>
                    ↻ 刷新
                  </button>
                </div>
              </section>
              <div className="metrics">
                <div>
                  <span>最近披露的股东户数</span>
                  <strong>
                    {latest?.conflict ? "存在冲突" : fmt(latest?.holders)}
                    <small>户</small>
                  </strong>
                  <p>统计截止 {latest?.end_date || "未取得"}</p>
                </div>
                <div>
                  <span>较上次披露变化</span>
                  <strong className={latest?.change_pct > 0 ? "red" : "green"}>
                    {latest?.change_pct == null
                      ? "—"
                      : `${latest.change_pct > 0 ? "+" : ""}${latest.change_pct.toFixed(2)}%`}
                  </strong>
                  <p>
                    {latest?.change_count != null
                      ? `${latest.change_count > 0 ? "+" : ""}${fmt(latest.change_count)} 户`
                      : "同来源、同口径对照"}
                  </p>
                </div>
                <div>
                  <span>最近可用收盘价</span>
                  <strong>
                    {lastPrice && !lastPrice.conflict
                      ? lastPrice.close.toFixed(2)
                      : "未取得"}
                    <small>元</small>
                  </strong>
                  <p>{lastPrice?.date || "行情仍在获取"} · 不复权</p>
                </div>
                <div>
                  <span>已取得历史记录</span>
                  <strong>
                    {allRows.length}
                    <small>条</small>
                  </strong>
                  <p>
                    {allRows[0]?.end_date || "未取得"} —{" "}
                    {latest?.end_date || "未取得"}
                  </p>
                </div>
              </div>
              <div className="workspace-grid">
                <section className="panel" id="chart-panel">
                  <div className="section-heading">
                    <div>
                      <span className="number">01</span>
                      <h3>股东与股价对照</h3>
                    </div>
                    <div className="segmented" aria-label="历史时间范围">
                      {[
                        ["1y", "近一年"],
                        ["3y", "近三年"],
                        ["all", "全部历史"],
                      ].map(([v, t]) => (
                        <button
                          key={v}
                          aria-pressed={history === v}
                          className={history === v ? "active" : ""}
                          onClick={() => setHistory(v)}
                        >
                          {t}
                        </button>
                      ))}
                    </div>
                  </div>
                  <Status status={data.status} empty={!rows.length} />
                  <div className="scope">
                    <label>
                      统计口径{" "}
                      <select
                        aria-label="统计口径"
                        value={scope}
                        onChange={(e) => {
                          setScope(e.target.value);
                          setSelectedId(null);
                        }}
                      >
                        {scopes.length ? (
                          scopes.map((s) => <option key={s}>{s}</option>)
                        ) : (
                          <option value="">未取得</option>
                        )}
                      </select>
                    </label>
                    <label>
                      <input
                        type="checkbox"
                        checked={volume}
                        onChange={(e) => setVolume(e.target.checked)}
                      />
                      展开成交量
                    </label>
                  </div>
                  <SourceStatus
                    label="行情"
                    status={priceData.data?.status}
                    error={priceData.error}
                    onRetry={retryPrices}
                  />
                  <Suspense
                    fallback={<div className="loading">正在准备联动图表…</div>}
                  >
                    <LensChart
                      key={code}
                      rows={allRows}
                      prices={priceRows}
                      selected={selected}
                      onSelect={setSelectedId}
                      range={history}
                      showVolume={volume}
                      today={today()}
                    />
                  </Suspense>
                  <details className="records">
                    <summary>
                      历史明细与来源 <span>{rows.length} 条 ↓</span>
                    </summary>
                    <div className="table-toolbar">
                      <span>点击日期，在图中选中对应记录</span>
                      <button
                        onClick={() => exportRows(rows, code)}
                        disabled={!rows.length}
                      >
                        导出 CSV ↓
                      </button>
                    </div>
                    <div className="table-scroll">
                      <table>
                        <thead>
                          <tr>
                            <th>统计截止日</th>
                            <th>股东户数</th>
                            <th>较上次</th>
                            <th>披露日</th>
                            <th>来源 / 核验</th>
                          </tr>
                        </thead>
                        <tbody>
                          {[...rows].reverse().map((r) => (
                            <tr
                              key={r.id}
                              className={
                                r.id === selected?.id ? "row-selected" : ""
                              }
                            >
                              <td>
                                <button onClick={() => setSelectedId(r.id)}>
                                  {r.end_date}
                                </button>
                              </td>
                              <td>
                                {fmt(r.holders)}
                                {r.conflict && <em> 冲突</em>}
                              </td>
                              <td>
                                {r.change_pct == null
                                  ? "—"
                                  : r.change_pct + "%"}
                              </td>
                              <td>{r.disclosure_date || "未取得"}</td>
                              <td>
                                <Source href={r.original_url || r.page_url}>
                                  {r.verified
                                    ? "报告原文 ✓"
                                    : "东方财富 · 待核对"}
                                </Source>
                                {r.verified_scope && (
                                  <small className="scope-note">
                                    {r.verified_scope}
                                  </small>
                                )}
                              </td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  </details>
                  <p className="footnote">{data.coverage}</p>
                </section>
                <Insights
                  key={code}
                  code={code}
                  start={range?.start}
                  end={range?.end}
                  mode={mode}
                  setMode={setMode}
                  hasPrevious={Boolean(prev)}
                  nonce={nonce}
                />
              </div>
            </div>
          )
        )}
        <footer>
          <span>
            股东观察 <small>STOCK LENS / OPEN SOURCE</small>
          </span>
          <p>
            公开披露 · 来源可追溯 · 不构成买卖建议
            <br />
            关注仅保存在当前浏览器；后台维护匿名更新订阅。
          </p>
          <Source href="https://github.com/user0928/stock-lens">GitHub</Source>
        </footer>
      </main>
      <dialog
        ref={helpRef}
        className="help-dialog"
        aria-labelledby="help-title"
      >
        <div className="section-heading">
          <h3 id="help-title">让每一次查询有据可查</h3>
          <button
            onClick={() => helpRef.current.close()}
            aria-label="关闭使用指南"
          >
            ×
          </button>
        </div>
        <ol>
          <li>
            <b>找到公司</b>
            <p>
              输入名称或股票代码；方向键选择，Enter 确认。Ctrl K 快速回到搜索。
            </p>
          </li>
          <li>
            <b>选择披露点</b>
            <p>
              点击图中记录查看精确户数、变化和两种日期的股价。拖动只移动视窗；手机长按后拖动可查看读数。
            </p>
          </li>
          <li>
            <b>对照同期资讯</b>
            <p>
              右侧展示选中期间公告和报道，可切换披露日前后30天。最新新闻单独展示，不替代历史资讯。
            </p>
          </li>
        </ol>
        <p className="context-note">
          人数仅在披露点存在。非交易日不冒充当天行情。免费来源可能缺失、限流或失效；阅读时请核对原文。关注不会跨设备同步。
        </p>
        <button
          className="primary-button"
          onClick={() => helpRef.current.close()}
        >
          开始查看
        </button>
      </dialog>
    </>
  );
}
class AppBoundary extends React.Component {
  state = { error: false };
  static getDerivedStateFromError() {
    return { error: true };
  }
  render() {
    return this.state.error ? (
      <main className="empty">
        <h2>页面暂时无法显示</h2>
        <p>已保存的关注仍在浏览器中。</p>
        <button onClick={() => location.reload()}>重新加载</button>
      </main>
    ) : (
      this.props.children
    );
  }
}
createRoot(document.getElementById("root")).render(
  <AppBoundary>
    <App />
  </AppBoundary>,
);
if ("serviceWorker" in navigator && import.meta.env.PROD)
  navigator.serviceWorker.register("/sw.js").catch(() => {});
