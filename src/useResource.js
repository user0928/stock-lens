import { useEffect, useState } from "react";
export async function api(url, options = {}) {
  const response = await fetch(url, {
    ...options,
    signal: options.signal || AbortSignal.timeout(35000),
  });
  if (!response.ok) {
    let body;
    try {
      body = await response.json();
    } catch {}
    const detail = body?.detail;
    throw Error(
      typeof detail === "string" ? detail : `请求失败 ${response.status}`,
    );
  }
  return response.json();
}
export function useResource(url, nonce = 0) {
  const [state, setState] = useState({ url: null, data: null, error: "" });
  useEffect(() => {
    if (!url) {
      setState({ url: null, data: null, error: "" });
      return;
    }
    let alive = true,
      timer;
    const controller = new AbortController();
    setState((previous) => ({
      url,
      data: previous.url === url ? previous.data : null,
      error: "",
    }));
    async function load() {
      try {
        const data = await api(url, {
          signal: AbortSignal.any([
            controller.signal,
            AbortSignal.timeout(35000),
          ]),
        });
        if (!alive) return;
        setState((previous) => {
          if (
            previous.url === url &&
            previous.data?.items &&
            JSON.stringify(previous.data.items) === JSON.stringify(data.items)
          )
            data.items = previous.data.items;
          return { url, data, error: "" };
        });
        if (data.status?.refreshing) timer = setTimeout(load, 1600);
      } catch (e) {
        if (alive)
          setState((previous) => ({
            url,
            data: previous.url === url ? previous.data : null,
            error:
              e.name === "TimeoutError" ? "连接超时，请稍后重试" : e.message,
          }));
      }
    }
    load();
    return () => {
      alive = false;
      clearTimeout(timer);
      controller.abort();
    };
  }, [url, nonce]);
  return state.url === url ? state : { data: null, error: "" };
}
