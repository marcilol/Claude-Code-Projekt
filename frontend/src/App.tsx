import { useState } from "react";

import { BasketChart } from "./components/BasketChart";
import { FactorChart } from "./components/FactorChart";
import { PortfolioPage } from "./components/PortfolioPage";
import { RotationQuadrant } from "./components/RotationQuadrant";
import { ZScoreTable } from "./components/ZScoreTable";

type Tab = "markets" | "portfolio";

export default function App() {
  const [tab, setTab] = useState<Tab>("markets");

  return (
    <div className="min-h-screen">
      <header className="border-b border-cream-300 bg-cream-50">
        <div className="max-w-7xl mx-auto px-6 py-4 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="w-7 h-7 rounded-full bg-forest-800" />
            <h1 className="text-base font-semibold tracking-tight">
              Portfolio X-Ray
            </h1>
          </div>
          <nav className="text-sm flex gap-6">
            <button
              onClick={() => setTab("markets")}
              className={`transition-colors ${
                tab === "markets"
                  ? "font-medium text-ink-900"
                  : "text-ink-500 hover:text-ink-900"
              }`}
            >
              Markets
            </button>
            <button
              onClick={() => setTab("portfolio")}
              className={`transition-colors ${
                tab === "portfolio"
                  ? "font-medium text-ink-900"
                  : "text-ink-500 hover:text-ink-900"
              }`}
            >
              Portfolio
            </button>
          </nav>
        </div>
      </header>

      <main className="max-w-7xl mx-auto px-6 py-8 space-y-6">
        {tab === "markets" && (
          <>
            <FactorChart />
            <BasketChart />
            <ZScoreTable />
            <RotationQuadrant />
          </>
        )}
        {tab === "portfolio" && <PortfolioPage />}
      </main>
    </div>
  );
}
