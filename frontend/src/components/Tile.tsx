export default function Tile({ label, value, sub, cls = "" }: {
  label: string; value: string | number; sub?: string; cls?: string;
}) {
  return (
    <div className="tile">
      <div className="label">{label}</div>
      <div className={`value ${cls}`}>{value}</div>
      {sub && <div className="sub">{sub}</div>}
    </div>
  );
}
