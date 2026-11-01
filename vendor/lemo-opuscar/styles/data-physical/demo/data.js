// Global cumulative installed capacity (GW), IRENA (2026) Renewable Energy Statistics, processed by Our World in Data (CC BY 4.0)
// Solar = PV + solar thermal, on-grid + off-grid; wind = onshore + offshore. Raw CSVs are in data/, downloaded 2026-10-16.
export const YEARS = [2014, 2015, 2016, 2017, 2018, 2019, 2020, 2021, 2022, 2023, 2024, 2025];
export const SOLAR = [178.84773, 226.5979, 298.50723, 392.3427, 487.84647, 590.1197, 721.2222, 865.921, 1057.8683, 1423.988, 1883.1776, 2396.7092];
export const WIND = [349.49323, 416.38437, 467.3158, 514.97186, 563.5159, 623.076, 733.2712, 824.1905, 903.0115, 1018.3177, 1132.5869, 1291.015];
export const GW_PER_SHEET = 10;     // one sheet = 10 GW (both materials use the same unit, so the ratio is comparable)
export const BRASS_EVERY = 10;      // every 10th sheet is brass = one tick mark every 100 GW
export const fmt = v => v.toLocaleString('en-US', { minimumFractionDigits: 1, maximumFractionDigits: 1 });
