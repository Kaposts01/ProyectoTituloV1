import { useState } from "react";
import type { PermGroup } from "../shared/types";

export function PermCheckboxes({ groups, checkedCodes }: { groups: PermGroup[]; checkedCodes?: string[] }) {
  const [expanded, setExpanded] = useState<string | null>(null);
  return (
    <div>
      {groups.map((g) => (
        <div key={g.group} style={{ marginBottom: "0.4rem" }}>
          <button
            type="button"
            className="channel-btn"
            style={{ width: "100%", textAlign: "left" }}
            onClick={() => setExpanded((e) => (e === g.group ? null : g.group))}
          >
            {expanded === g.group ? "▾" : "▸"} {g.group} ({g.permissions.length})
          </button>
          {expanded === g.group ? (
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "0.25rem 1.5rem", padding: "0.5rem 0.75rem" }}>
              {g.permissions.map((p) => (
                <label key={p.code} style={{ display: "flex", alignItems: "center", gap: "0.4rem", fontSize: "0.85rem", cursor: "pointer" }}>
                  <input type="checkbox" name="permission_codes" value={p.code} defaultChecked={checkedCodes?.includes(p.code)} />
                  {p.description}
                </label>
              ))}
            </div>
          ) : null}
        </div>
      ))}
    </div>
  );
}
