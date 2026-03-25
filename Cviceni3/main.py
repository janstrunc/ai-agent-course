"""
StockAdvisor AI - Investicni poradce a portfolio tracker
Framework: OpenAI Agent SDK
Agent type: ReAct (reason + act)
Tools: SQLite databaze (portfolio, watchlist), Web Search (fundamenty, zpravy)
"""

import asyncio
import sqlite3
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv
from agents import Agent, Runner, WebSearchTool, function_tool

load_dotenv()

DB_PATH = Path(__file__).parent / "portfolio.db"


# ─── Database setup ───────────────────────────────────────────────

def init_database():
    """Initialize SQLite database with portfolio and watchlist."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS portfolio (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ticker TEXT NOT NULL,
            name TEXT NOT NULL,
            shares REAL NOT NULL,
            buy_price REAL NOT NULL,
            buy_date TEXT NOT NULL,
            sector TEXT,
            notes TEXT
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS watchlist (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ticker TEXT NOT NULL UNIQUE,
            name TEXT NOT NULL,
            target_price REAL,
            reason TEXT,
            added_date TEXT NOT NULL
        )
    """)

    # Seed with sample portfolio
    cursor.execute("SELECT COUNT(*) FROM portfolio")
    if cursor.fetchone()[0] == 0:
        positions = [
            ("AAPL", "Apple Inc.", 15, 178.50, "2024-03-15", "Technology", "Core holding, strong ecosystem"),
            ("MSFT", "Microsoft Corp.", 10, 410.20, "2024-01-20", "Technology", "Cloud + AI growth play"),
            ("GOOGL", "Alphabet Inc.", 8, 141.80, "2024-05-10", "Technology", "Search dominance + YouTube"),
            ("JNJ", "Johnson & Johnson", 20, 156.30, "2023-11-05", "Healthcare", "Dividend aristocrat, defensive"),
            ("V", "Visa Inc.", 12, 275.40, "2024-02-28", "Financials", "Payment network moat"),
            ("NVDA", "NVIDIA Corp.", 5, 480.00, "2024-04-01", "Technology", "AI/GPU leader"),
            ("KO", "Coca-Cola Co.", 30, 58.90, "2023-08-15", "Consumer Staples", "Dividend king, brand value"),
            ("AMZN", "Amazon.com Inc.", 6, 178.25, "2024-06-12", "Technology", "E-commerce + AWS"),
            ("PG", "Procter & Gamble", 18, 162.70, "2023-09-22", "Consumer Staples", "Defensive, steady dividends"),
            ("JPM", "JPMorgan Chase", 10, 195.80, "2024-03-01", "Financials", "Largest US bank, well managed"),
        ]
        cursor.executemany(
            "INSERT INTO portfolio (ticker, name, shares, buy_price, buy_date, sector, notes) VALUES (?, ?, ?, ?, ?, ?, ?)",
            positions,
        )

        watchlist_items = [
            ("TSLA", "Tesla Inc.", 200.00, "High volatility, wait for pullback", "2024-07-01"),
            ("AMD", "Advanced Micro Devices", 140.00, "CPU/GPU competitor to NVDA, cheaper entry", "2024-06-15"),
            ("COST", "Costco Wholesale", 700.00, "Great business but expensive valuation", "2024-05-20"),
        ]
        cursor.executemany(
            "INSERT INTO watchlist (ticker, name, target_price, reason, added_date) VALUES (?, ?, ?, ?, ?)",
            watchlist_items,
        )

        conn.commit()
        print(f"Database initialized: {len(positions)} positions + {len(watchlist_items)} watchlist items.")

    conn.close()


# ─── Portfolio Tools ──────────────────────────────────────────────

@function_tool
def get_portfolio() -> str:
    """Show all positions in the investment portfolio with details.

    Returns:
        Complete portfolio overview grouped by sector with buy prices and notes.
    """
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute(
        "SELECT id, ticker, name, shares, buy_price, buy_date, sector, notes FROM portfolio ORDER BY sector, ticker"
    )
    rows = cursor.fetchall()
    conn.close()

    if not rows:
        return "Portfolio je prazdne. Pouzij add_position pro pridani akcie."

    sectors: dict[str, list] = {}
    total_invested = 0.0
    for r in rows:
        sectors.setdefault(r[6] or "Other", []).append(r)
        total_invested += r[3] * r[4]

    lines = [f"Portfolio ({len(rows)} pozic, investovano ${total_invested:,.2f}):\n"]
    for sector in sorted(sectors):
        items = sectors[sector]
        sector_value = sum(r[3] * r[4] for r in items)
        lines.append(f"--- {sector} (${sector_value:,.2f}) ---")
        for r in items:
            value = r[3] * r[4]
            lines.append(
                f"  [{r[1]}] {r[2]} | {r[3]}x @ ${r[4]:.2f} = ${value:,.2f} | nakup: {r[5]} | {r[7]}"
            )
        lines.append("")

    return "\n".join(lines)


@function_tool
def search_portfolio(query: str) -> str:
    """Search for a specific stock in the portfolio by ticker or company name.

    Args:
        query: Ticker symbol (e.g. 'AAPL') or part of company name (e.g. 'Apple').

    Returns:
        Matching positions with details.
    """
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    search = f"%{query}%"
    cursor.execute(
        """SELECT id, ticker, name, shares, buy_price, buy_date, sector, notes
           FROM portfolio
           WHERE ticker LIKE ? OR name LIKE ? OR sector LIKE ?
           ORDER BY ticker""",
        (search, search, search),
    )
    rows = cursor.fetchall()
    conn.close()

    if not rows:
        return f"Zadna pozice pro '{query}' v portfoliu."

    lines = [f"Nalezeno {len(rows)} pozic:"]
    for r in rows:
        value = r[3] * r[4]
        lines.append(
            f"  [ID:{r[0]}] {r[1]} ({r[2]}) | {r[3]} akcii @ ${r[4]:.2f} = ${value:,.2f} | {r[6]} | nakup: {r[5]} | {r[7]}"
        )
    return "\n".join(lines)


@function_tool
def add_position(ticker: str, name: str, shares: float, buy_price: float, sector: str, notes: str) -> str:
    """Add a new stock position to the portfolio.

    Args:
        ticker: Stock ticker symbol (e.g. 'AAPL', 'MSFT').
        name: Full company name (e.g. 'Apple Inc.').
        shares: Number of shares bought.
        buy_price: Price per share at purchase in USD.
        sector: Sector (Technology, Healthcare, Financials, Consumer Staples, Energy, Industrials, etc.).
        notes: Why you bought this stock / investment thesis.

    Returns:
        Confirmation with position details.
    """
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    buy_date = datetime.now().strftime("%Y-%m-%d")
    cursor.execute(
        "INSERT INTO portfolio (ticker, name, shares, buy_price, buy_date, sector, notes) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (ticker.upper(), name, shares, buy_price, buy_date, sector, notes),
    )
    new_id = cursor.lastrowid
    total = shares * buy_price
    conn.commit()
    conn.close()
    return f"Pozice pridana: [ID:{new_id}] {ticker.upper()} ({name}) | {shares}x @ ${buy_price:.2f} = ${total:,.2f} | {sector}"


@function_tool
def remove_position(position_id: int) -> str:
    """Remove (sell) a stock position from the portfolio by its ID.

    Args:
        position_id: The numeric ID of the position to remove. Use get_portfolio or search_portfolio to find IDs.

    Returns:
        Confirmation of the removed position.
    """
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT ticker, name, shares, buy_price FROM portfolio WHERE id = ?", (position_id,))
    row = cursor.fetchone()
    if not row:
        conn.close()
        return f"Pozice s ID {position_id} nebyla nalezena."
    cursor.execute("DELETE FROM portfolio WHERE id = ?", (position_id,))
    conn.commit()
    conn.close()
    value = row[2] * row[3]
    return f"Prodana pozice: [ID:{position_id}] {row[0]} ({row[1]}) | {row[2]}x @ ${row[3]:.2f} = ${value:,.2f}"


@function_tool
def portfolio_summary() -> str:
    """Get a summary of the portfolio: total value, sector allocation, number of positions.

    Returns:
        Portfolio statistics and sector breakdown as percentages.
    """
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT ticker, shares, buy_price, sector FROM portfolio")
    rows = cursor.fetchall()
    conn.close()

    if not rows:
        return "Portfolio je prazdne."

    total = sum(r[1] * r[2] for r in rows)
    sectors: dict[str, float] = {}
    for r in rows:
        sectors[r[3] or "Other"] = sectors.get(r[3] or "Other", 0) + r[1] * r[2]

    lines = [
        f"Portfolio Summary:",
        f"  Pocet pozic: {len(rows)}",
        f"  Celkova investice: ${total:,.2f}",
        f"  Prumerna velikost pozice: ${total / len(rows):,.2f}",
        f"\nSektorova alokace:",
    ]
    for sector in sorted(sectors, key=sectors.get, reverse=True):
        pct = sectors[sector] / total * 100
        bar = "#" * int(pct / 2)
        lines.append(f"  {sector:20s} ${sectors[sector]:>10,.2f}  ({pct:5.1f}%)  {bar}")

    top = max(rows, key=lambda r: r[1] * r[2])
    lines.append(f"\nNejvetsi pozice: {top[0]} (${top[1] * top[2]:,.2f})")

    return "\n".join(lines)


# ─── Watchlist Tools ──────────────────────────────────────────────

@function_tool
def get_watchlist() -> str:
    """Show all stocks on the watchlist - stocks you're monitoring but haven't bought yet.

    Returns:
        Watchlist with target prices and reasons.
    """
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT id, ticker, name, target_price, reason, added_date FROM watchlist ORDER BY ticker")
    rows = cursor.fetchall()
    conn.close()

    if not rows:
        return "Watchlist je prazdny."

    lines = [f"Watchlist ({len(rows)} akcii):"]
    for r in rows:
        target = f"${r[3]:.2f}" if r[3] else "neurcena"
        lines.append(f"  [ID:{r[0]}] {r[1]} ({r[2]}) | cilova cena: {target} | {r[4]} | pridano: {r[5]}")
    return "\n".join(lines)


@function_tool
def add_to_watchlist(ticker: str, name: str, target_price: float, reason: str) -> str:
    """Add a stock to the watchlist for monitoring.

    Args:
        ticker: Stock ticker symbol (e.g. 'TSLA').
        name: Full company name.
        target_price: Target buy price in USD - the price at which you'd consider buying.
        reason: Why you're watching this stock / what you're waiting for.

    Returns:
        Confirmation that the stock was added to watchlist.
    """
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    added_date = datetime.now().strftime("%Y-%m-%d")
    try:
        cursor.execute(
            "INSERT INTO watchlist (ticker, name, target_price, reason, added_date) VALUES (?, ?, ?, ?, ?)",
            (ticker.upper(), name, target_price, reason, added_date),
        )
        conn.commit()
    except sqlite3.IntegrityError:
        conn.close()
        return f"{ticker.upper()} uz je na watchlistu."
    conn.close()
    return f"Pridano na watchlist: {ticker.upper()} ({name}) | cilova cena: ${target_price:.2f} | {reason}"


@function_tool
def remove_from_watchlist(watchlist_id: int) -> str:
    """Remove a stock from the watchlist by its ID.

    Args:
        watchlist_id: The numeric ID of the watchlist entry to remove.

    Returns:
        Confirmation of removal.
    """
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT ticker, name FROM watchlist WHERE id = ?", (watchlist_id,))
    row = cursor.fetchone()
    if not row:
        conn.close()
        return f"Watchlist polozka s ID {watchlist_id} nebyla nalezena."
    cursor.execute("DELETE FROM watchlist WHERE id = ?", (watchlist_id,))
    conn.commit()
    conn.close()
    return f"Odebrano z watchlistu: {row[0]} ({row[1]})"


# ─── Agent ────────────────────────────────────────────────────────

advisor_agent = Agent(
    name="StockAdvisor",
    instructions="""Jsi investicni poradce a analytik akcioveho trhu. Pomahas uzivateli spravovat jeho portfolio, sledovat akcie a analyzovat investicni prilezitosti.

Tve schopnosti:
- Sprava portfolia: zobrazeni, vyhledavani, pridavani a odstranovani pozic
- Analyza portfolia: sektorova alokace, celkova hodnota, statistiky
- Watchlist: sledovani potencialnich investic s cilovymi cenami
- Vyhledavani na webu: aktualni ceny, zpravy, fundamentalni data, analyzy

Jak pracujes:
1. Kdyz se uzivatel pta na jeho portfolio, pouzij nastroje pro databazi
2. Kdyz chce aktualni ceny nebo zpravy, pouzij web search
3. Kdyz chce analyzu, kombinuj data z portfolia s webovym vyhledavanim
4. Vzdy vysvetli sve uvazovani a doporuceni

Odpovidej cesky. Bud vecny a konkretni. U doporuceni vzdy zduraznni ze nejde o financni poradenstvi, ale o edukativni informace.

Sektory: Technology, Healthcare, Financials, Consumer Staples, Energy, Industrials, Real Estate, Utilities, Materials, Communication Services.""",
    tools=[
        get_portfolio,
        search_portfolio,
        add_position,
        remove_position,
        portfolio_summary,
        get_watchlist,
        add_to_watchlist,
        remove_from_watchlist,
        WebSearchTool(),
    ],
)


# ─── Main loop ────────────────────────────────────────────────────

async def main():
    init_database()

    print("=" * 60)
    print("  StockAdvisor AI - Investicni poradce")
    print("  Napis svuj dotaz nebo 'quit' pro ukonceni")
    print("=" * 60)
    print("\nPriklady:")
    print("  - 'Ukaz mi portfolio'")
    print("  - 'Jak je na tom NVDA? Najdi aktualni cenu'")
    print("  - 'Jaka je moje sektorova alokace?'")
    print("  - 'Pridej na watchlist META za $480'")
    print("  - 'Porovnej Apple a Microsoft jako investici'")

    while True:
        user_input = input("\nVy: ").strip()
        if not user_input or user_input.lower() in ("quit", "exit", "q"):
            print("Happy investing! Na shledanou.")
            break

        result = await Runner.run(advisor_agent, user_input)
        print(f"\nAdvisor: {result.final_output}")


if __name__ == "__main__":
    asyncio.run(main())
