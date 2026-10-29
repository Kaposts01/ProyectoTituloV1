export type PerformanceMonth = {
  period: string; year: number; month: number; revenue: number | null; rejected_amount: number | null;
  collection_rate: number | null; opening: number | null; active: number | null; activations: number | null;
  cancellations: number | null; net_growth: number | null; churn: number | null;
  channels: Record<string, number | null>; partial_month: boolean;
};
export type PerformanceSnapshot = {
  as_of: string; currency: string; monthly: PerformanceMonth[]; default_period: string;
  coverage: string; excluded: Record<string, number>;
};
export const channels = ['VirtualPOS', 'Toku', 'Payku', 'TCH'];
export const monthNames = ['Ene', 'Feb', 'Mar', 'Abr', 'May', 'Jun', 'Jul', 'Ago', 'Sep', 'Oct', 'Nov', 'Dic'];
export function annualSeries(months: PerformanceMonth[], period: string, annualGoal: number | null) {
  const year = Number(period.slice(0, 4));
  const selectedMonth = Number(period.slice(5));
  const byMonth = new Map(months.filter(m => m.year === year).map(m => [m.month, m]));
  let accumulated = 0;
  let missing = false;
  const historical = Array.from({ length: selectedMonth }, (_, i) => byMonth.get(i + 1));
  const completed = historical.filter((m): m is PerformanceMonth => !!m && m.revenue != null && !m.partial_month);
  const canProject = completed.length === selectedMonth && !historical.some(m => !m || m.revenue == null);
  const average = canProject ? completed.reduce((sum, m) => sum + m.revenue!, 0) / selectedMonth : null;
  return Array.from({ length: 12 }, (_, i) => {
    const month = i + 1;
    const row = byMonth.get(month);
    if (month <= selectedMonth) {
      accumulated += row?.revenue ?? 0;
      missing ||= row?.revenue == null;
    }
    return {
      month, label: monthNames[i], actual: month <= selectedMonth && row?.revenue != null ? accumulated : null,
      projected: average != null && month >= selectedMonth ? accumulated + average * (month - selectedMonth) : null,
      target: annualGoal != null ? annualGoal * month / 12 : null,
      incomplete: missing,
    };
  });
}
export function historyWindow(months: PerformanceMonth[], period: string, range: '12m' | 'year' | 'all') {
  const eligible = months.filter(m => m.period <= period);
  return range === '12m' ? eligible.slice(-12) : range === 'year' ? eligible.filter(m => m.year === Number(period.slice(0, 4))) : eligible;
}
