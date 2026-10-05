import React, { useState, useMemo } from "react";
import { api, useResource } from "./useResource";
import SourceStatus from "./SourceStatus";
export default function Insights({
  code,
  start,
  end,
  mode,
  setMode,
  hasPrevious,
  nonce,
}) {
  const [type, setType] = useState("all"),
    [period, setPeriod] = useState("period"),
    [mentions, setMentions] = useState(false),
    [category, setCategory] = useState("全部"),
    [other, setOther] = useState(false),
    [localNonce, setLocalNonce] = useState(0),
    [message, setMessage] = useState(""),
    [filter, setFilter] = useState(""),
    [limit, setLimit] = useState(20);
  const eventUrl =
    start && end
      ? `/api/stocks/${code}/events?start=${start}&end=${end}`
      : null;
  const newsUrl =
    period === "latest"
      ? `/api/stocks/${code}/news?mode=latest`
      : start && end
        ? `/api/stocks/${code}/news?mode=period&start=${start}&end=${end}`
        : null;
  const events = useResource(eventUrl, `${nonce}:${localNonce}`),
    news = useResource(newsUrl, `${nonce}:${localNonce}`);
  const latestScope = period === "latest";
  const items = useMemo(() => {
    const announcements = latestScope
      ? []
      : (events.data?.items || []).filter(
          (r) =>
            (other || r.category !== "其他公告") &&
            (category === "全部" || r.category === category),
        );
    const reports = (news.data?.items || []).filter(
      (r) => mentions || r.relation === "direct",
    );
    return [
      ...(type === "media" ? [] : announcements),
      ...(type === "official" ? [] : reports),
    ]
      .filter(
        (r) => !filter || r.title.toLowerCase().includes(filter.toLowerCase()),
      )
      .sort((a, b) =>
        (b.published_at || b.published_date).localeCompare(
          a.published_at || a.published_date,
        ),
      );
  }, [
    events.data,
    news.data,
    type,
    category,
    other,
    mentions,
    latestScope,
    filter,
  ]);
  async function retry(which) {
    try {
      const url =
        which === "news"
          ? `/api/stocks/${code}/news/refresh`
          : `/api/stocks/${code}/events/refresh?start=${start}&end=${end}`;
      const r = await api(url, { method: "POST" });
      setMessage(r.message || "");
      if (r.queued) setLocalNonce((n) => n + 1);
    } catch (e) {
      setMessage(e.message);
    }
  }
  return (
    <section className="panel events" id="insights-panel">
      <div className="section-heading">
        <div>
          <span className="number">02</span>
          <h3>公告与媒体报道</h3>
        </div>
        <span className="source-label">原文阅读 ↗</span>
      </div>
      <div className="insight-tabs">
        <div className="segmented">
          {[
            ["all", "全部"],
            ["official", "正式公告"],
            ["media", "媒体报道"],
          ].map(([v, t]) => (
            <button
              key={v}
              className={type === v ? "active" : ""}
              onClick={() => {
                setType(v);
                if (v === "official") setPeriod("period");
              }}
            >
              {t}
            </button>
          ))}
        </div>
        <div className="segmented">
          <button
            className={period === "period" ? "active" : ""}
            onClick={() => setPeriod("period")}
          >
            所选期间
          </button>
          <button
            className={period === "latest" ? "active" : ""}
            onClick={() => {
              setPeriod("latest");
              setType("media");
            }}
          >
            最新媒体资讯
          </button>
        </div>
      </div>
      {!latestScope ? (
        <>
          <div className="event-controls">
            <div className="segmented">
              <button
                className={mode === "interval" ? "active" : ""}
                onClick={() => setMode("interval")}
              >
                相邻统计日之间
              </button>
              <button
                className={mode === "disclosure" ? "active" : ""}
                onClick={() => setMode("disclosure")}
              >
                披露日前后 30 天
              </button>
            </div>
            <span className="date-range">
              {start && end ? `${start} — ${end}` : "选择一个披露点"}
            </span>
          </div>
          {!hasPrevious && mode === "interval" && (
            <p className="footnote">没有更早统计日，暂仅查询当前统计日当天。</p>
          )}
        </>
      ) : (
        <div className="latest-banner">
          最新媒体资讯，与图中所选历史期间分开显示。
        </div>
      )}
      {type !== "media" && !latestScope && (
        <>
          <div className="filters">
            {[
              "全部",
              "业绩",
              "重组并购",
              "增减持",
              "回购",
              "重大合同",
              "诉讼处罚",
            ].map((c) => (
              <button
                key={c}
                className={category === c ? "active" : ""}
                onClick={() => setCategory(c)}
              >
                {c}
              </button>
            ))}
            <label>
              <input
                type="checkbox"
                checked={other}
                onChange={(e) => setOther(e.target.checked)}
              />
              包括其他公告
            </label>
          </div>
          <SourceStatus
            label="公告"
            status={events.data?.status}
            error={events.error}
            onRetry={() => retry("events")}
          />
        </>
      )}
      {type !== "official" && (
        <>
          <label className="mention-toggle">
            <input
              type="checkbox"
              checked={mentions}
              onChange={(e) => setMentions(e.target.checked)}
            />
            包括行业 / 市场中提及本公司的报道
          </label>
          <SourceStatus
            label="新闻"
            status={news.data?.status}
            error={news.error}
            onRetry={() => retry("news")}
          />
          <p className="footnote">
            本次检索覆盖 {news.data?.status.coverage_start || "未取得"} —{" "}
            {news.data?.status.coverage_end || "未取得"} ·
            每次最多100条候选报道，不代表完整历史。按平台标注发布时间筛选，发生日期未提取。
          </p>
        </>
      )}
      {message && <p className="warning">{message}</p>}
      <div className="timeline-tools">
        <span>{items.length} 条符合筛选</span>
        <input
          aria-label="筛选资讯标题"
          placeholder="筛选已取得的标题"
          value={filter}
          onChange={(e) => {
            setFilter(e.target.value);
            setLimit(20);
          }}
        />
      </div>
      <div className="timeline" data-testid="timeline">
        {items.length ? (
          items.slice(0, limit).map((e) => (
            <article key={e.id}>
              <time>{e.published_at || e.published_date}</time>
              <div>
                <div className="event-tags">
                  <span>{e.kind}</span>
                  <span>
                    {e.kind === "媒体报道"
                      ? e.relation === "direct"
                        ? "公司直接相关"
                        : "行业 / 市场提及"
                      : e.category}
                  </span>
                  {e.source_role === "mirror" && <span>备用公告转载</span>}
                </div>
                <h4>
                  <a
                    href={e.source_url}
                    target="_blank"
                    rel="noopener noreferrer"
                  >
                    {e.title} ↗
                  </a>
                </h4>
                {e.kind === "媒体报道" && (
                  <p className="news-excerpt">
                    {e.excerpt || "来源未提供摘要，请打开报道阅读。"}
                  </p>
                )}
                <p>
                  {e.kind === "媒体报道"
                    ? `平台标注媒体：${e.media} · 转载平台阅读`
                    : `${e.source} · 公告标题摘录`}{" "}
                  · 发生日期未提取
                </p>
                {e.sources?.length > 1 && (
                  <details className="more-sources">
                    <summary>其他来源 / 转载（{e.sources.length}）</summary>
                    {e.sources.map((s, i) => (
                      <a
                        key={s.url + i}
                        href={s.url}
                        target="_blank"
                        rel="noopener noreferrer"
                      >
                        {s.media || s.source} {s.published_at || ""} ↗
                      </a>
                    ))}
                  </details>
                )}
              </div>
            </article>
          ))
        ) : (
          <div className="empty">
            {filter
              ? "已取得的资讯中没有匹配标题。"
              : events.data?.status.refreshing || news.data?.status.refreshing
                ? "正在查询，已有结果会逐步显示…"
                : latestScope
                  ? "当前筛选下未检索到报道，可勾选行业 / 市场提及。"
                  : "当前筛选下未检索到该期间资讯，不代表当时没有事件。"}
            {!filter && !latestScope && type !== "official" && (
              <button
                onClick={() => {
                  setPeriod("latest");
                  setType("media");
                }}
              >
                改看最新媒体资讯
              </button>
            )}
          </div>
        )}
      </div>
      {items.length > limit && (
        <button className="load-more" onClick={() => setLimit((n) => n + 20)}>
          再显示 {Math.min(20, items.length - limit)} 条 ↓
        </button>
      )}
      <div className="context-note">
        <b>对照时间，不推断因果。</b>{" "}
        正式公告与媒体报道分别标注。登录要求会跳转至原站，由你完成登录；不会读取浏览器密码或将登录状态自动交给后台。
      </div>
    </section>
  );
}
