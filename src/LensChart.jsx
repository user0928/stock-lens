import React, { useEffect, useRef, useState, useMemo } from "react";
import * as echarts from "echarts/core";
import { LineChart, BarChart } from "echarts/charts";
import {
  GridComponent,
  DataZoomComponent,
  MarkLineComponent,
  MarkPointComponent,
  AxisPointerComponent,
  TooltipComponent,
} from "echarts/components";
import { CanvasRenderer } from "echarts/renderers";
import { atOrBefore, priceAt } from "./chartData";
echarts.use([
  LineChart,
  BarChart,
  GridComponent,
  DataZoomComponent,
  MarkLineComponent,
  MarkPointComponent,
  AxisPointerComponent,
  TooltipComponent,
  CanvasRenderer,
]);
const dayMs = 86400000;
const ms = (d) => Date.parse(d + "T00:00:00Z");
const iso = (t) => new Date(t).toISOString().slice(0, 10);
const number = (n) =>
  n == null ? "未取得" : Number(n).toLocaleString("zh-CN");
function PriceRead({ rows, day, label }) {
  const { exact, previous } = priceAt(rows, day || "");
  return (
    <div className="price-read">
      <span>
        {label}
        {day && ` · ${day}`}
      </span>
      <b>
        {exact && !exact.conflict
          ? `¥ ${exact.close.toFixed(2)}`
          : exact?.conflict
            ? "来源数值冲突"
            : "当日行情未取得"}
      </b>
      {previous && (
        <small>
          最近此前记录 {previous.date} ·{" "}
          {previous.conflict
            ? "来源数值冲突"
            : "¥ " + previous.close.toFixed(2)}
        </small>
      )}
      {exact && <small>{exact.source} · 不复权</small>}
    </div>
  );
}

export default function LensChart({
  rows,
  prices,
  selected,
  onSelect,
  range,
  showVolume,
  today,
}) {
  const mount = useRef(null),
    instance = useRef(null),
    live = useRef({}),
    gesture = useRef(null),
    timer = useRef(null),
    frame = useRef(null),
    lastSelected = useRef(null);
  const [hover, setHover] = useState(null),
    [dragging, setDragging] = useState(false),
    [view, setView] = useState(null);
  const ordered = useMemo(
    () =>
      rows
        .filter((r) => !r.conflict)
        .sort((a, b) => a.end_date.localeCompare(b.end_date)),
    [rows],
  );
  const domainStart = ordered[0]?.end_date || prices[0]?.date || today;
  const min = ms(domainStart) - 7 * dayMs,
    max = Math.max(ms(today), ms(ordered.at(-1)?.end_date || today)) + dayMs;
  const height = showVolume ? 555 : 440;
  live.current = { rows: ordered, prices, selected, onSelect, min, max };
  useEffect(() => {
    const chart = echarts.init(mount.current, null, { renderer: "canvas" });
    instance.current = chart;
    const resize = new ResizeObserver(() => chart.resize());
    resize.observe(mount.current);
    const zoom = () => {
      const z = chart.getOption().dataZoom?.[0];
      const { min, max } = live.current;
      if (z) {
        const start = min + ((max - min) * z.start) / 100,
          end = min + ((max - min) * z.end) / 100;
        setView({ start: iso(start), end: iso(end) });
      }
    };
    chart.on("datazoom", zoom);
    return () => {
      clearTimeout(timer.current);
      cancelAnimationFrame(frame.current);
      resize.disconnect();
      chart.dispose();
      instance.current = null;
    };
  }, []);
  useEffect(() => {
    const chart = instance.current;
    if (!chart) return;
    const start =
      range === "all"
        ? 0
        : Math.max(
            0,
            ((ms(today) - (range === "1y" ? 365 : 1096) * dayMs - min) /
              (max - min)) *
              100,
          );
    const grids = [
      { left: 82, right: 20, top: 38, height: 135 },
      { left: 82, right: 20, top: 235, height: 135 },
    ];
    if (showVolume) grids.push({ left: 82, right: 20, top: 430, height: 58 });
    const axes = grids.map((_, i) => ({
      type: "time",
      gridIndex: i,
      min,
      max,
      boundaryGap: false,
      axisLine: { lineStyle: { color: "#cfd9ce" } },
      axisTick: { show: false },
      splitNumber: mount.current.clientWidth < 500 ? 3 : 6,
      axisLabel: {
        fontSize: 10,
        color: "#71806f",
        formatter: (v) => iso(v).slice(0, 7),
      },
      axisPointer: {
        show: true,
        label: { show: i === 0, formatter: (p) => iso(p.value) },
        lineStyle: { color: "#94a78c", type: "dashed" },
      },
      splitLine: { show: false },
    }));
    const yAxes = [
      {
        type: "value",
        gridIndex: 0,
        name: "股东户数（户）",
        scale: true,
        splitNumber: 3,
        axisLabel: { fontSize: 10, formatter: (v) => number(Math.round(v)) },
      },
      {
        type: "value",
        gridIndex: 1,
        name: "不复权收盘价（元）",
        scale: true,
        splitNumber: 3,
        axisLabel: { fontSize: 10, formatter: (v) => v.toFixed(2) },
      },
    ];
    if (showVolume)
      yAxes.push({
        type: "value",
        gridIndex: 2,
        name: "成交量（股）",
        splitNumber: 2,
        axisLabel: {
          fontSize: 9,
          formatter: (v) =>
            v >= 1e8
              ? (v / 1e8).toFixed(1) + "亿"
              : v >= 1e4
                ? (v / 1e4).toFixed(0) + "万"
                : v,
        },
      });
    yAxes.forEach((y) => {
      y.nameTextStyle = { fontSize: 11, color: "#567254", align: "left" };
      y.nameLocation = "end";
      y.nameGap = 16;
      y.splitLine = { lineStyle: { color: "#e0e7db", type: "dashed" } };
    });
    const holderData = rows.map((r) => [
      ms(r.end_date),
      r.conflict ? null : r.holders,
      r.id,
    ]);
    const series = [
      {
        id: "holders",
        name: "股东户数",
        type: "line",
        xAxisIndex: 0,
        yAxisIndex: 0,
        data: holderData,
        symbol: "circle",
        symbolSize: 7,
        showSymbol: true,
        connectNulls: false,
        lineStyle: { width: 2, color: "#236754" },
        itemStyle: { color: "#236754" },
        animation: false,
      },
      {
        id: "price",
        name: "收盘价",
        type: "line",
        xAxisIndex: 1,
        yAxisIndex: 1,
        data: prices.map((p) => [ms(p.date), p.conflict ? null : p.close]),
        showSymbol: prices.length < 3,
        symbolSize: 7,
        connectNulls: false,
        lineStyle: { width: 1.5, color: "#a6743e" },
        areaStyle: { color: "#d3b787", opacity: 0.09 },
        animation: false,
      },
    ];
    if (showVolume)
      series.push({
        id: "volume",
        name: "成交量",
        type: "bar",
        xAxisIndex: 2,
        yAxisIndex: 2,
        data: prices.map((p) => [ms(p.date), p.volume]),
        itemStyle: { color: "#a7bba0" },
        animation: false,
      });
    chart.setOption(
      {
        useUTC: true,
        animation: false,
        grid: grids,
        xAxis: axes,
        yAxis: yAxes,
        axisPointer: { link: [{ xAxisIndex: "all" }], triggerOn: "none" },
        tooltip: { show: false, trigger: "axis" },
        series,
        dataZoom: [
          {
            type: "slider",
            xAxisIndex: grids.map((_, i) => i),
            filterMode: "filter",
            start,
            end: 100,
            bottom: 13,
            height: 23,
            showDetail: false,
            brushSelect: false,
            borderColor: "#d4dece",
            fillerColor: "#d5e2d180",
            handleStyle: { color: "#638f68" },
            dataBackground: {
              lineStyle: { color: "#9eaf95" },
              areaStyle: { color: "#eef2e9" },
            },
          },
        ],
      },
      true,
    );
    setView({ start: iso(min + ((max - min) * start) / 100), end: iso(max) });
    setHover(null);
  }, [rows, prices, range, showVolume, today, min, max]);
  useEffect(() => {
    if (!selected || !instance.current) return;
    const chart = instance.current,
      z = chart.getOption().dataZoom?.[0];
    const position = ((ms(selected.end_date) - min) / (max - min)) * 100;
    if (
      selected.id !== lastSelected.current &&
      z &&
      (position < z.start || position > z.end)
    ) {
      const span = z.end - z.start,
        start = Math.max(0, Math.min(100 - span, position - span / 2));
      chart.dispatchAction({ type: "dataZoom", start, end: start + span });
    }
    lastSelected.current = selected.id;
    const line = {
      silent: true,
      symbol: "none",
      animation: false,
      label: { show: false },
      lineStyle: { type: "dashed", color: "#236754", width: 1 },
      data: [{ xAxis: ms(selected.end_date) }],
    };
    instance.current.setOption({
      series: [
        {
          id: "holders",
          markLine: line,
          markPoint: {
            symbol: "circle",
            symbolSize: 12,
            label: { show: false },
            itemStyle: {
              color: "#fff",
              borderColor: "#236754",
              borderWidth: 3,
            },
            data: selected.conflict
              ? []
              : [{ coord: [ms(selected.end_date), selected.holders] }],
          },
        },
        { id: "price", markLine: line },
      ],
    });
  }, [selected, rows, prices, range, showVolume]);
  function locate(e) {
    const rect = mount.current.getBoundingClientRect();
    return { x: e.clientX - rect.left, y: e.clientY - rect.top };
  }
  function inspect(e) {
    const chart = instance.current;
    if (!chart) return;
    const { x, y } = locate(e);
    if (x < 80 || x > mount.current.clientWidth - 15 || y >= height - 42)
      return;
    const value = chart.convertFromPixel({ xAxisIndex: 0 }, x);
    if (!Number.isFinite(value)) return;
    const day = iso(Math.max(min, Math.min(max, value)));
    setHover(day);
    chart.dispatchAction({ type: "updateAxisPointer", x, y });
  }
  function choose(e) {
    cancelAnimationFrame(frame.current);
    const { x } = locate(e);
    const value = instance.current.convertFromPixel({ xAxisIndex: 0 }, x);
    if (!Number.isFinite(value) || !ordered.length) return;
    const nearest = ordered.reduce((a, b) =>
      Math.abs(ms(a.end_date) - value) < Math.abs(ms(b.end_date) - value)
        ? a
        : b,
    );
    onSelect(nearest.id);
    setHover(null);
  }
  function down(e) {
    if (e.pointerType === "mouse" && e.button !== 0) return;
    const p = locate(e);
    if (p.y >= height - 42 || p.x < 80) return;
    const z = instance.current.getOption().dataZoom[0];
    gesture.current = {
      x: e.clientX,
      y: e.clientY,
      start: z.start,
      end: z.end,
      moved: false,
      inspect: false,
      touch: e.pointerType !== "mouse",
    };
    if (e.pointerType === "mouse") mount.current.setPointerCapture(e.pointerId);
    else
      timer.current = setTimeout(() => {
        if (gesture.current && !gesture.current.moved) {
          gesture.current.inspect = true;
          mount.current.setPointerCapture(e.pointerId);
          inspect(e);
        }
      }, 380);
  }
  function move(e) {
    const g = gesture.current;
    if (!g) {
      if (e.pointerType === "mouse") {
        cancelAnimationFrame(frame.current);
        const p = { clientX: e.clientX, clientY: e.clientY };
        frame.current = requestAnimationFrame(() => inspect(p));
      }
      return;
    }
    const dx = e.clientX - g.x,
      dy = e.clientY - g.y;
    if (g.inspect) {
      e.preventDefault();
      inspect(e);
      return;
    }
    if (
      !g.moved &&
      Math.abs(dy) > Math.abs(dx) &&
      Math.abs(dy) > 6 &&
      g.touch
    ) {
      clearTimeout(timer.current);
      gesture.current = null;
      return;
    }
    if (Math.abs(dx) > 6) {
      g.moved = true;
      clearTimeout(timer.current);
      setDragging(true);
      mount.current.setPointerCapture(e.pointerId);
    }
    if (g.moved) {
      e.preventDefault();
      const span = g.end - g.start,
        delta = (-dx / Math.max(1, mount.current.clientWidth - 102)) * span;
      const start = Math.max(0, Math.min(100 - span, g.start + delta));
      instance.current.dispatchAction({
        type: "dataZoom",
        start,
        end: start + span,
      });
      inspect(e);
    }
  }
  function up(e) {
    const g = gesture.current;
    clearTimeout(timer.current);
    if (g && (!g.moved || g.inspect)) choose(e);
    gesture.current = null;
    setDragging(false);
    if (mount.current.hasPointerCapture(e.pointerId))
      mount.current.releasePointerCapture(e.pointerId);
    if (g?.moved && !g.inspect) setHover(null);
  }
  const activeDate = hover || selected?.end_date;
  const record = hover ? atOrBefore(ordered, hover, "end_date") : selected;
  const actual = record?.end_date === activeDate;
  return (
    <div className="lens-chart" data-testid="lens-chart">
      <div className="chart-info" data-testid="chart-info" aria-live="polite">
        <div className="card-top">
          <span>{hover ? "光标读数" : "已锁定披露点"}</span>
          <b>{activeDate || "尚无披露数据"}</b>
          <span>
            {dragging
              ? "拖动查看中"
              : record?.conflict
                ? "数值冲突 · 请核对明细"
                : actual
                  ? "统计截止日"
                  : "最近已披露记录"}
          </span>
        </div>
        {record ? (
          <>
            <div className="chart-facts">
              <div>
                <span>{actual ? "股东户数" : "最近已披露户数"}</span>
                <strong>
                  {number(record.holders)}
                  <small> 户</small>
                </strong>
                {!actual && <small>截至 {record.end_date}</small>}
              </div>
              <div>
                <span>较上次披露</span>
                <strong>
                  {record.change_count == null
                    ? "—"
                    : (record.change_count > 0 ? "+" : "") +
                      number(record.change_count)}
                  <small> 户</small>
                </strong>
                <small>
                  {record.change_pct == null
                    ? "变化率未取得"
                    : `${record.change_pct > 0 ? "+" : ""}${record.change_pct}%`}
                </small>
              </div>
              <PriceRead
                rows={prices}
                day={record.end_date}
                label="统计日收盘价"
              />
              <PriceRead
                rows={prices}
                day={record.disclosure_date}
                label="披露日收盘价"
              />
            </div>
            <div className="card-bottom">
              <span>
                披露日 {record.disclosure_date || "未取得"} ·{" "}
                {record.verified ? "原文已核对" : "聚合数据待核对"}
              </span>
              <a
                href={record.original_url || record.page_url}
                target="_blank"
                rel="noopener noreferrer"
              >
                {record.verified ? "报告原文" : "股东数据来源"} ↗
              </a>
            </div>
          </>
        ) : (
          <p>当前日期之前没有可用披露记录，不能推算股东人数。</p>
        )}
        <div className="hover-price">
          {hover && hover !== record?.end_date ? (
            <PriceRead rows={prices} day={hover} label="光标日收盘价" />
          ) : (
            <span className="muted">悬停或长按图表，查看其他日期读数。</span>
          )}
        </div>
      </div>
      <div className="chart-help">
        <span>悬停读数 · 点击锁定 · 按住拖动平移</span>
        <span>手机：横滑平移，长按查看</span>
      </div>
      <div className="legend" aria-label="图例">
        <span>
          <i />
          股东户数 · 实际披露点
        </span>
        <span>
          <i />
          历史收盘价 · 不复权
        </span>
      </div>
      <div
        ref={mount}
        className={"echart " + (dragging ? "dragging" : "")}
        style={{ height }}
        tabIndex="0"
        role="group"
        aria-label="股东户数与股价联动图，左右方向键选择披露点"
        onPointerDown={down}
        onPointerMove={move}
        onPointerUp={up}
        onPointerCancel={() => {
          clearTimeout(timer.current);
          gesture.current = null;
          setDragging(false);
        }}
        onPointerLeave={() => {
          if (!gesture.current) setHover(null);
        }}
        onKeyDown={(e) => {
          if (!["ArrowLeft", "ArrowRight"].includes(e.key)) return;
          e.preventDefault();
          const index = ordered.findIndex((r) => r.id === selected?.id);
          const r =
            ordered[
              Math.max(
                0,
                Math.min(
                  ordered.length - 1,
                  index + (e.key === "ArrowRight" ? 1 : -1),
                ),
              )
            ];
          if (r) onSelect(r.id);
        }}
      />
      <div className="chart-window" data-testid="chart-window">
        可见时间 {view ? `${view.start} — ${view.end}` : "—"} ·
        时间轴可拖动与缩放
      </div>
      {!prices.length && (
        <div className="price-gap">
          这只股票的日行情尚未取得。股东披露记录仍可独立查看。
        </div>
      )}
      <p className="footnote">
        折线仅连接披露记录；其间每日股东人数未知。价格为不复权收盘价，除权除息可能产生跳变。没有当天行情时，最近此前记录单独列示。
      </p>
    </div>
  );
}
