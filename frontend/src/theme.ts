// Chart series palette — 10 distinguishable colors that sit well on cream.
// Order is stable so each style factor always gets the same color.
export const chartColors = [
  "#1a3d36", // forest
  "#c8424a", // brick red
  "#d97c2e", // warm orange
  "#2d8659", // green
  "#4a6b8a", // slate blue
  "#8b4789", // muted purple
  "#b89324", // mustard
  "#5a7a3a", // olive
  "#a04545", // rust
  "#3a6b7a", // teal blue
];

export const colorForIndex = (i: number) =>
  chartColors[i % chartColors.length];
