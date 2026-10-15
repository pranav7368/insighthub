import { useEffect, useState } from "react";
import { errorText, exportRowsCsv, getRows } from "../api";
import { formatNumber, humanLabel } from "../format";

const PAGE_SIZE = 50;

function cellText(value, col) {
  if (value === null || value === undefined || value === "") return "—";
  if (col.role === "measure" && typeof value === "number") return formatNumber(value, col.subtype);
  if (col.role === "date") return String(value).slice(0, 10);
  return String(value);
}

/** The actual rows behind a slice — the bottom of every drill. */
export default function RecordsTable({ datasetId, slice, name }) {
  const [sort, setSort] = useState(null);
  const [desc, setDesc] = useState(true);
  const [page, setPage] = useState(1);
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const sliceKey = JSON.stringify([slice.filters, slice.date_from, slice.date_to]);

  useEffect(() => { setPage(1); }, [sliceKey]);

  useEffect(() => {
    let live = true;
    setError(null);
    getRows(datasetId, slice, { sort, desc, page, pageSize: PAGE_SIZE })
      .then((d) => { if (live) setData(d); })
      .catch((e) => { if (live) setError(errorText(e, "Could not load the rows.")); });
    return () => { live = false; };
    // slice is captured through sliceKey
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [datasetId, sliceKey, sort, desc, page]);

  if (error) return <div className="empty-panel">{error}</div>;
  if (!data) return <div className="skeleton skeleton--table" aria-busy="true" aria-label="Loading rows" />;

  const activeSort = data.sort;
  const onSort = (col) => {
    if (activeSort === col) setDesc((d) => !d);
    else { setSort(col); setDesc(true); }
    setPage(1);
  };
  const first = data.total === 0 ? 0 : (data.page - 1) * data.page_size + 1;
  const last = Math.min(data.total, data.page * data.page_size);
  const pages = Math.max(1, Math.ceil(data.total / data.page_size));

  return (
    <div className="records">
      <div className="records__bar">
        <span className="records__count">
          {data.total === 0 ? "No rows"
            : data.total === 1 ? "1 row"
            : `${first.toLocaleString("en-IN")}–${last.toLocaleString("en-IN")} of ${data.total.toLocaleString("en-IN")} rows`}
        </span>
        <button className="views-btn" disabled={data.total === 0}
          onClick={() => exportRowsCsv(datasetId, slice, { sort: activeSort, desc }, name || "rows")}>
          Download CSV
        </button>
      </div>
      {data.total > 0 && (
        <div className="records__scroll" tabIndex={0} role="region" aria-label="Rows">
          <table className="records__table">
            <thead>
              <tr>
                {data.columns.map((c) => {
                  const on = activeSort === c.name;
                  return (
                    <th key={c.name} scope="col" className={c.role === "measure" ? "num" : ""}
                      aria-sort={on ? (data.desc ? "descending" : "ascending") : "none"}>
                      <button onClick={() => onSort(c.name)}>
                        {humanLabel(c.name)}<span aria-hidden className="records__sort">{on ? (data.desc ? "↓" : "↑") : ""}</span>
                      </button>
                    </th>
                  );
                })}
              </tr>
            </thead>
            <tbody>
              {data.rows.map((r, i) => (
                <tr key={i}>
                  {data.columns.map((c, j) => (
                    <td key={c.name} className={c.role === "measure" ? "num" : ""}>{cellText(r[j], c)}</td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {pages > 1 && (
        <div className="records__pager">
          <button className="views-btn" disabled={data.page <= 1} onClick={() => setPage((p) => p - 1)}>‹ Previous</button>
          <span>Page {data.page} of {pages}</span>
          <button className="views-btn" disabled={data.page >= pages} onClick={() => setPage((p) => p + 1)}>Next ›</button>
        </div>
      )}
    </div>
  );
}
