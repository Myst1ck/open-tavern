import type { Item } from "../api";

interface ItemTooltipProps {
  item: Item;
  position: { x: number; y: number };
  visible: boolean;
}

export default function ItemTooltip({
  item,
  position,
  visible,
}: ItemTooltipProps) {
  if (!visible) return null;

  const truncate = (text: string, max: number): string =>
    text.length > max ? text.slice(0, max) + "…" : text;

  return (
    <div
      className="item-tooltip"
      style={{
        left: position.x + 12,
        top: position.y + 12,
      }}
    >
      <div className="tooltip-header">
        <span className="tooltip-name">{item.name}</span>
        <span className="tooltip-type">{item.type}</span>
      </div>
      <div className="tooltip-stats">
        {item.stats.damage > 0 ? (
          <span className="tooltip-stat">DMG {item.stats.damage}</span>
        ) : null}
        {item.stats.armor > 0 ? (
          <span className="tooltip-stat">ARM {item.stats.armor}</span>
        ) : null}
        <span className="tooltip-stat">Val {item.stats.value}</span>
        <span className="tooltip-stat">Wt {item.stats.weight}</span>
      </div>
      {item.description ? (
        <p className="tooltip-desc">{truncate(item.description, 80)}</p>
      ) : null}
    </div>
  );
}
