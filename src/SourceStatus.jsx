import React from "react";
export default function SourceStatus({
  status,
  error,
  label = "数据",
  onRetry,
}) {
  const state = status?.state,
    failed = Boolean(error || status?.error),
    time = status?.success_at || status?.cached_at;
  const message = status?.refreshing
    ? "更新中，已有记录可查看"
    : status?.busy && !status?.success_at
      ? "采集队列繁忙，请稍后刷新"
      : failed
        ? status?.has_cache
          ? "更新失败 · 使用已有缓存"
          : "本次未取得数据"
        : state === "fallback"
          ? "使用备用来源"
          : state === "partial"
            ? "部分数据已取得"
            : state === "empty"
              ? "来源返回空结果"
              : status?.success_at
                ? "数据可用"
                : "等待查询";
  const detail = [
    error || status?.error || status?.primary_issue?.message,
    ...(status?.warnings || []),
  ]
    .filter(Boolean)
    .join("；");
  return (
    <div
      className={
        "source-state " +
        (failed || ["fallback", "partial"].includes(state)
          ? "source-warning"
          : "")
      }
      role="status"
    >
      <div>
        <b>{label}</b>
        <span>{message}</span>
        {status?.source && <span>{status.source}</span>}
      </div>
      {time && <small>更新 {time.slice(0, 16).replace("T", " ")} UTC+8</small>}
      {detail && (
        <details>
          <summary>查看来源状态与缺口</summary>
          <p>
            {detail}
            {status?.primary_issue && " · 巨潮优先来源暂不可用"}
          </p>
        </details>
      )}
      <div className="source-actions">
        {(failed || state === "partial") && onRetry && (
          <button disabled={status?.refreshing} onClick={onRetry}>
            重试{label}
          </button>
        )}
        {status?.reading_url && (failed || state === "fallback") && (
          <a
            href={status.reading_url}
            target="_blank"
            rel="noopener noreferrer"
          >
            {state === "login_required"
              ? "前往原站登录阅读"
              : state === "restricted"
                ? "前往原站查看访问要求"
                : "打开来源网站"}{" "}
            ↗
          </a>
        )}
      </div>
    </div>
  );
}
