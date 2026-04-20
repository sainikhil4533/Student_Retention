import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import { Card, SectionTitle } from "./ui";

const palette = ["#2563eb", "#64748b", "#3b82f6", "#94a3b8", "#1d4ed8"];

export function BarChartCard({
  title,
  description,
  data,
  xKey,
  dataKey,
}: {
  title: string;
  description: string;
  data: Array<Record<string, string | number>>;
  xKey: string;
  dataKey: string;
}) {
  return (
    <Card className="space-y-4">
      <SectionTitle title={title} description={description} />
      {data.length ? (
        <>
          <div className="h-72 w-full">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={data}>
                <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="#dbe4f0" />
                <XAxis dataKey={xKey} tick={{ fill: "#64748b", fontSize: 12 }} axisLine={false} tickLine={false} />
                <YAxis tick={{ fill: "#64748b", fontSize: 12 }} axisLine={false} tickLine={false} />
                <Tooltip />
                <Bar dataKey={dataKey} radius={[12, 12, 0, 0]}>
                  {data.map((_, index) => (
                    <Cell key={index} fill={palette[index % palette.length]} />
                  ))}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          </div>
          <ChartLegend data={data} labelKey={xKey} valueKey={dataKey} />
        </>
      ) : (
        <ChartEmptyState />
      )}
    </Card>
  );
}

export function PieChartCard({
  title,
  description,
  data,
  nameKey,
  dataKey,
}: {
  title: string;
  description: string;
  data: Array<Record<string, string | number>>;
  nameKey: string;
  dataKey: string;
}) {
  return (
    <Card className="space-y-4">
      <SectionTitle title={title} description={description} />
      {data.length ? (
        <>
          <div className="h-72 w-full">
            <ResponsiveContainer width="100%" height="100%">
              <PieChart>
                <Tooltip />
                <Pie data={data} nameKey={nameKey} dataKey={dataKey} innerRadius={52} outerRadius={90} paddingAngle={3}>
                  {data.map((_, index) => (
                    <Cell key={index} fill={palette[index % palette.length]} />
                  ))}
                </Pie>
              </PieChart>
            </ResponsiveContainer>
          </div>
          <ChartLegend data={data} labelKey={nameKey} valueKey={dataKey} />
        </>
      ) : (
        <ChartEmptyState />
      )}
    </Card>
  );
}

function ChartLegend({
  data,
  labelKey,
  valueKey,
}: {
  data: Array<Record<string, string | number>>;
  labelKey: string;
  valueKey: string;
}) {
  return (
    <div className="grid gap-2 sm:grid-cols-2">
      {data.slice(0, 6).map((item, index) => (
        <div key={`${item[labelKey]}-${index}`} className="flex items-center justify-between rounded-2xl border border-slate-200 bg-white px-3 py-2">
          <div className="flex min-w-0 items-center gap-2">
            <span className="h-3 w-3 shrink-0 rounded-full" style={{ backgroundColor: palette[index % palette.length] }} />
            <span className="truncate text-sm text-slate-600">{String(item[labelKey])}</span>
          </div>
          <span className="text-sm font-semibold text-slate-900">{String(item[valueKey])}</span>
        </div>
      ))}
    </div>
  );
}

function ChartEmptyState() {
  return (
    <div className="rounded-3xl border border-dashed border-slate-200 bg-slate-50 px-4 py-10 text-center">
      <p className="text-sm font-semibold text-slate-900">No chart data available yet</p>
      <p className="mt-2 text-sm leading-6 text-slate-600">
        This is still a valid state. Once the backend returns chart-ready values, the graph and legend will render here automatically.
      </p>
    </div>
  );
}
