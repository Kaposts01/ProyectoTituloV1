import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'

type ActivityPoint = { label: string; count: number; amount: number }

export default function ChannelActivityChart({ data, mode }: { data: ActivityPoint[]; mode: 'count' | 'amount' }) {
  return <ResponsiveContainer width="100%" height={280}><BarChart data={data} margin={{ top: 8, right: 8, left: 0, bottom: 0 }}><CartesianGrid stroke="#e1e7e5" vertical={false} /><XAxis dataKey="label" tickLine={false} axisLine={false} /><YAxis tickLine={false} axisLine={false} width={45} /><Tooltip formatter={(value) => mode === 'amount' ? `$${Number(value).toLocaleString('es-CL')}` : Number(value).toLocaleString('es-CL')} /><Bar dataKey={mode} fill="#527f76" radius={[6, 6, 0, 0]} /></BarChart></ResponsiveContainer>
}
