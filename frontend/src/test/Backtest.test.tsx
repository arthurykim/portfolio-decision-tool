import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import Chart, { Sparkline } from "../components/Chart";
import { fmtYears, pct, renderMarkdown } from "../lib/format";
import Backtest from "../views/Backtest";

const TICKERS = [
  { ticker: "SPY", name: "S&P 500 (US Large Cap)" },
  { ticker: "AGG", name: "US Aggregate Bonds" },
];

const METRICS = {
  start: "2003-09-30", end: "2026-07-23",
  total_return: 5.164, cagr: 0.083, real_cagr: 0.0557,
  volatility: 0.1134, sharpe: 0.6112, sortino: 0.752, calmar: 0.2391,
  max_drawdown: -0.347, longest_drawdown_days: 1119,
  risk_free_rate: 0.0137, inflation_rate: 0.0259,
};

const RESULT = {
  metrics: METRICS,
  benchmark: {
    ticker: "SPY", name: "S&P 500",
    metrics: { ...METRICS, cagr: 0.1118 },
    equity_curve: { dates: ["2003-09-30", "2026-07-23"], values: [1, 11.2] },
  },
  inflation_estimated: true,
  equity_curve: { dates: ["2003-09-30", "2026-07-23"], values: [1, 6.16] },
  drawdown: { dates: ["2003-09-30", "2026-07-23"], values: [0, -0.05] },
};

function mockApi(result: unknown = RESULT) {
  const fetchMock = vi.fn((url: string) => {
    const body = String(url).includes("/api/tickers") ? TICKERS : result;
    return Promise.resolve({ ok: true, json: () => Promise.resolve(body) } as Response);
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

describe("Backtest", () => {
  beforeEach(() => mockApi());

  it("starts on the 60/40 preset totalling 100%", async () => {
    render(<Backtest />);
    expect(await screen.findByText("Total: 100.0%")).toBeInTheDocument();
  });

  it("flags an allocation that does not total 100%", async () => {
    const user = userEvent.setup();
    render(<Backtest />);
    await screen.findByText("Total: 100.0%");

    const spy = screen.getByLabelText("SPY weight %");
    await user.clear(spy);
    await user.type(spy, "10");
    expect(screen.getByText("Total: 50.0%")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: /Run backtest/ }));
    expect(await screen.findByText(/must total 100%/)).toBeInTheDocument();
  });

  it("normalizes weights back to 100%", async () => {
    const user = userEvent.setup();
    render(<Backtest />);
    await screen.findByText("Total: 100.0%");

    const spy = screen.getByLabelText("SPY weight %");
    await user.clear(spy);
    await user.type(spy, "20");
    await user.click(screen.getByRole("button", { name: /Normalize/ }));

    await waitFor(() => expect(screen.getByText("Total: 100.0%")).toBeInTheDocument());
  });

  it("renders the risk panel and benchmark comparison after a run", async () => {
    const user = userEvent.setup();
    render(<Backtest />);
    await screen.findByText("Total: 100.0%");

    await user.click(screen.getByRole("button", { name: /Run backtest/ }));

    expect(await screen.findByText("Sortino")).toBeInTheDocument();
    expect(screen.getByText("Calmar")).toBeInTheDocument();
    expect(screen.getByText("Longest recovery")).toBeInTheDocument();
    expect(screen.getByText("Real CAGR")).toBeInTheDocument();
    // 8.3% portfolio vs 11.18% benchmark => trailing by 2.9 points
    expect(screen.getByText("vs S&P 500")).toBeInTheDocument();
    expect(screen.getByText("-2.9%")).toBeInTheDocument();
  });

  it("writes a plain-English summary and flags estimated inflation", async () => {
    const user = userEvent.setup();
    render(<Backtest />);
    await screen.findByText("Total: 100.0%");
    await user.click(screen.getByRole("button", { name: /Run backtest/ }));

    expect(await screen.findByText(/would have become/)).toBeInTheDocument();
    // Appears twice: once in the summary prose, once in the metrics tile.
    expect(screen.getAllByText("3.1 years").length).toBeGreaterThanOrEqual(2);
    expect(screen.getByText(/Inflation for the most recent period is estimated/))
      .toBeInTheDocument();
  });

  it("surfaces a server rejection", async () => {
    vi.stubGlobal("fetch", vi.fn((url: string) =>
      Promise.resolve(String(url).includes("/api/tickers")
        ? { ok: true, json: () => Promise.resolve(TICKERS) } as Response
        : { ok: false, statusText: "err",
            json: () => Promise.resolve({ detail: "Not enough overlapping price data" }) } as Response)));

    const user = userEvent.setup();
    render(<Backtest />);
    await screen.findByText("Total: 100.0%");
    await user.click(screen.getByRole("button", { name: /Run backtest/ }));

    expect(await screen.findByText("Not enough overlapping price data")).toBeInTheDocument();
  });
});

describe("Chart", () => {
  it("draws a line and axis labels", () => {
    const { container } = render(
      <Chart dates={["2020-01-01", "2021-01-01", "2022-01-01"]} values={[1, 2, 1.5]}
             color="var(--series-1)" fmt={(v) => `$${v.toFixed(2)}`} />,
    );
    expect(container.querySelectorAll("path")).toHaveLength(1);
    expect(container.querySelectorAll("text.axis-label").length).toBeGreaterThan(3);
  });

  it("adds a dashed overlay line for the benchmark", () => {
    const { container } = render(
      <Chart dates={["a", "b"]} values={[1, 2]} color="var(--series-1)"
             fmt={String} overlay={{ values: [1, 3], color: "var(--muted)" }} />,
    );
    const dashed = [...container.querySelectorAll("path")]
      .filter((p) => p.getAttribute("stroke-dasharray"));
    expect(dashed).toHaveLength(1);
  });

  it("survives a flat series without dividing by zero", () => {
    const { container } = render(
      <Chart dates={["a", "b"]} values={[5, 5]} color="c" fmt={String} />,
    );
    expect(container.querySelector("path")?.getAttribute("d")).not.toContain("NaN");
  });

  it("renders nothing for an empty series", () => {
    render(<Chart dates={[]} values={[]} color="c" fmt={String} />);
    expect(screen.getByText("No data.")).toBeInTheDocument();
  });

  it("sparkline colors by direction", () => {
    const { container: up } = render(<Sparkline values={[1, 2, 3]} />);
    expect(up.querySelector("path")?.getAttribute("stroke")).toContain("delta-up");
    const { container: down } = render(<Sparkline values={[3, 2, 1]} />);
    expect(down.querySelector("path")?.getAttribute("stroke")).toContain("delta-down");
  });
});

describe("formatting helpers", () => {
  it("formats percentages and durations", () => {
    expect(pct(0.083)).toBe("8.3%");
    expect(fmtYears(1119)).toBe("3.1 years");
    expect(fmtYears(60)).toBe("2 months");
  });

  it("renders markdown and escapes HTML", () => {
    expect(renderMarkdown("# Title")).toBe("<h1>Title</h1>");
    expect(renderMarkdown("- a\n- b")).toBe("<ul><li>a</li><li>b</li></ul>");
    expect(renderMarkdown("**bold**")).toContain("<strong>bold</strong>");
    expect(renderMarkdown("<script>alert(1)</script>")).not.toContain("<script>");
  });

  it("joins soft-wrapped lines into flowing paragraphs", () => {
    expect(renderMarkdown("one\ntwo")).toBe("<p>one two</p>");
  });
});
