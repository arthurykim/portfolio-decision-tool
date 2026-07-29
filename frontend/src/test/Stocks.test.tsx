import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import Stocks from "../views/Stocks";

const CATALOG = [
  { symbol: "AAPL", name: "Apple Inc.", sector: "Information Technology" },
  { symbol: "MSFT", name: "Microsoft", sector: "Information Technology" },
  { symbol: "JPM", name: "JPMorgan Chase", sector: "Financials" },
];

const HISTORY = {
  symbol: "AAPL", name: "Apple Inc.", sector: "Information Technology",
  range: "1Y", interval: "1d",
  ranges: ["1D", "1W", "1M", "6M", "YTD", "1Y", "5Y", "MAX"],
  fetched_at: "2026-07-25T18:00:00Z",
  points: [{ t: "2025-07-25", c: 210 }, { t: "2026-07-25", c: 321.66 }],
  stats: {
    price: 321.66, change: 108.63, change_pct: 50.99,
    high: 333.74, low: 201.58, open: 213.03, volume: 13_000_000_000, points: 250,
  },
};

/** Route each request the component makes to a canned payload. */
function mockApi(overrides: Record<string, unknown> = {}) {
  const fetchMock = vi.fn((url: string) => {
    const path = String(url);
    const body =
      path.includes("/data/sp500.json") ? { stocks: CATALOG }
      : path.includes("/data/ipos.json") ? { stocks: [] }
      : path.includes("/history") ? { ...HISTORY, ...(overrides.history ?? {}) }
      : path.includes("/news") ? { items: overrides.news ?? [] }
      : path.includes("/quotes") ? (overrides.quotes ?? [])
      : path.includes("/watchlist") ? { symbols: overrides.symbols ?? [] }
      : {};
    return Promise.resolve({ ok: true, json: () => Promise.resolve(body) } as Response);
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

const fetchCalls = () => (globalThis.fetch as unknown as ReturnType<typeof vi.fn>).mock.calls;

function renderStocks(props: Partial<React.ComponentProps<typeof Stocks>> = {}) {
  return render(
    <Stocks
      user={null}
      watchlist={[]}
      setWatchlist={() => {}}
      requireSignIn={() => {}}
      focusSymbol={null}
      onFocusHandled={() => {}}
      {...props}
    />,
  );
}

describe("Stocks catalog", () => {
  beforeEach(() => mockApi());

  it("lists companies from the catalog", async () => {
    renderStocks();
    expect(await screen.findByText("Apple Inc.")).toBeInTheDocument();
    expect(screen.getByText("JPMorgan Chase")).toBeInTheDocument();
  });

  it("filters by symbol or company name", async () => {
    const user = userEvent.setup();
    renderStocks();
    await screen.findByText("Apple Inc.");

    await user.type(screen.getByPlaceholderText(/search/i), "jpmorgan");
    await waitFor(() => expect(screen.queryByText("Apple Inc.")).not.toBeInTheDocument());
    expect(screen.getByText("JPMorgan Chase")).toBeInTheDocument();
  });

  it("prompts sign-in when pinning while signed out", async () => {
    const requireSignIn = vi.fn();
    const user = userEvent.setup();
    renderStocks({ requireSignIn });
    await screen.findByText("Apple Inc.");

    await user.click(screen.getByTitle("Pin AAPL"));
    expect(requireSignIn).toHaveBeenCalled();
  });

  it("pins without opening the detail panel", async () => {
    // The pin button lives inside a clickable row; the click must not bubble.
    const setWatchlist = vi.fn();
    const user = userEvent.setup();
    renderStocks({ user: { username: "arthur", is_admin: true }, setWatchlist });
    await screen.findByText("Apple Inc.");

    await user.click(screen.getByTitle("Pin AAPL"));
    await waitFor(() => expect(setWatchlist).toHaveBeenCalled());
    expect(screen.queryByRole("button", { name: /Close/ })).not.toBeInTheDocument();
  });
});

describe("Stock detail panel", () => {
  beforeEach(() => mockApi({ news: [{
    title: "Apple headline", publisher: "Yahoo Finance",
    published: "2026-07-25T12:00:00Z", url: "https://example.com/a",
  }] }));

  it("opens when a row is clicked and shows price, stats and news", async () => {
    const user = userEvent.setup();
    renderStocks();
    await user.click(await screen.findByText("Apple Inc."));

    expect(await screen.findByText("$321.66")).toBeInTheDocument();
    expect(screen.getByText(/\+108\.63 \(\+50\.99%\) 1Y/)).toBeInTheDocument();
    expect(screen.getByText("Apple headline")).toBeInTheDocument();

    // closest() is typed Element; within() needs HTMLElement.
    const stats = screen.getByText("Open").closest(".detail-stats") as HTMLElement;
    expect(within(stats).getByText("$213.03")).toBeInTheDocument();
  });

  it("closes when the close button is clicked", async () => {
    // Regression: the vanilla build shipped a Close button with no listener.
    const user = userEvent.setup();
    renderStocks();
    await user.click(await screen.findByText("Apple Inc."));
    expect(await screen.findByText("$321.66")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: /Close/ }));

    await waitFor(() => expect(screen.queryByText("$321.66")).not.toBeInTheDocument());
    expect(screen.queryByRole("button", { name: /Refresh/ })).not.toBeInTheDocument();
    // The catalog is still there underneath.
    expect(screen.getByText("Apple Inc.")).toBeInTheDocument();
  });

  it("refetches when a different range is selected", async () => {
    const user = userEvent.setup();
    renderStocks();
    await user.click(await screen.findByText("Apple Inc."));
    await screen.findByText("$321.66");

    await user.click(screen.getByRole("button", { name: "5Y" }));

    await waitFor(() =>
      expect(fetchCalls()
        .some((c) => String(c[0]).includes("range=5Y"))).toBe(true));
  });

  it("asks the API to bypass its cache when refresh is clicked", async () => {
    const user = userEvent.setup();
    renderStocks();
    await user.click(await screen.findByText("Apple Inc."));
    await screen.findByText("$321.66");

    await user.click(screen.getByRole("button", { name: /Refresh/ }));

    await waitFor(() =>
      expect(fetchCalls()
        .some((c) => String(c[0]).includes("refresh=true"))).toBe(true));
  });

  it("opens the symbol handed down from another view", async () => {
    const onFocusHandled = vi.fn();
    renderStocks({ focusSymbol: "AAPL", onFocusHandled });
    expect(await screen.findByText("$321.66")).toBeInTheDocument();
    expect(onFocusHandled).toHaveBeenCalled();
  });

  it("news links open at the publisher, safely", async () => {
    const user = userEvent.setup();
    renderStocks();
    await user.click(await screen.findByText("Apple Inc."));

    const link = await screen.findByRole("link", { name: /Apple headline/ });
    expect(link).toHaveAttribute("target", "_blank");
    expect(link.getAttribute("rel")).toContain("noopener");
  });
});
