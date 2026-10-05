export function atOrBefore(rows, day, key = "date") {
  let lo = 0,
    hi = rows.length - 1,
    result = null;
  while (lo <= hi) {
    const mid = (lo + hi) >> 1;
    if (rows[mid][key] <= day) {
      result = rows[mid];
      lo = mid + 1;
    } else hi = mid - 1;
  }
  return result;
}
export function priceAt(rows, day) {
  const p = atOrBefore(rows, day);
  return {
    exact: p?.date === day ? p : null,
    previous: p?.date !== day ? p : null,
  };
}
