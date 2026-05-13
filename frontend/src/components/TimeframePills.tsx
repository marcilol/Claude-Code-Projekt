import type { Timeframe } from "../api";

const ALL: Timeframe[] = ["1D", "1W", "1M", "3M", "6M", "1Y"];

interface Props {
  value: Timeframe;
  onChange: (tf: Timeframe) => void;
}

export function TimeframePills({ value, onChange }: Props) {
  return (
    <div className="inline-flex rounded-full bg-cream-200 p-1 gap-0.5">
      {ALL.map((tf) => {
        const active = tf === value;
        return (
          <button
            key={tf}
            onClick={() => onChange(tf)}
            className={`px-3 py-1 text-xs font-medium rounded-full transition-colors ${
              active
                ? "bg-forest-800 text-cream-50"
                : "text-ink-700 hover:text-ink-900"
            }`}
          >
            {tf}
          </button>
        );
      })}
    </div>
  );
}
