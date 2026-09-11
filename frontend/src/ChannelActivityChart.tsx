import { Bar, BarChart, CartesianGrid, LabelList, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'

type ActivityPoint = { label: string; count: number; amount: number }

const formatValue = (value: number | string, mode: 'count' | 'amount') =>
  mode === 'amount' ? `$${Number(value).toLocaleString('es-CL')}` : Number(value).toLocaleString('es-CL')

export default function ChannelActivityChart({ data, mode, color = "#527f76" }: { data: ActivityPoint[]; mode: 'count' | 'amount'; color?: string }) {
  return <ResponsiveContainer width="100%" height={280}><BarChart data={data} margin={{ top: 24, right: 8, left: 0, bottom: 0 }}><CartesianGrid stroke="#e1e7e5" vertical={false} /><XAxis dataKey="label" tickLine={false} axisLine={false} /><YAxis tickLine={false} axisLine={false} width={45} /><Tooltip formatter={(value) => formatValue(value as number, mode)} /><Bar dataKey={mode} fill={color} radius={[6, 6, 0, 0]}><LabelList dataKey={mode} position="top" offset={6} formatter={(value) => formatValue(value as number, mode)} fill="#4a5b60" fontSize={11} fontWeight={700} /></Bar></BarChart></ResponsiveContainer>
}
