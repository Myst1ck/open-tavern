import type { GameState } from "../api";

interface StateViewProps {
  state: GameState | null;
}

export default function StateView({ state }: StateViewProps) {
  if (state === null) {
    return (
      <section className="panel state-panel">
        <h2>Adventure State</h2>
        <p className="muted">No state yet — take your first action.</p>
      </section>
    );
  }

  const hpPercent =
    state.max_hp > 0 ? Math.round((state.current_hp / state.max_hp) * 100) : 0;

  return (
    <section className="panel state-panel">
      <h2>Adventure State</h2>
      <div className="hp-block">
        <div className="hp-label">
          <span>Hit Points</span>
          <span>
            {state.current_hp} / {state.max_hp}
          </span>
        </div>
        <div className="hp-bar">
          <div
            className="hp-fill"
            style={{ width: `${Math.min(100, Math.max(0, hpPercent))}%` }}
          />
        </div>
      </div>
      <div className="state-scene">
        <h3>Scene</h3>
        <p>{state.scene}</p>
      </div>
      <h3>Conditions</h3>
      {state.conditions.length === 0 ? (
        <p className="muted">None</p>
      ) : (
        <ul className="chip-list">
          {state.conditions.map((condition, index) => (
            <li key={`${condition}-${index}`} className="chip">
              {condition}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
