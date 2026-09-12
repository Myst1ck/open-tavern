import { useEffect, useRef, useState } from "react";

import type { Item } from "../api";

interface ItemTooltipProps {
  item: Item;
  visible: boolean;
}

const MARGIN = 8;
const OFFSET = 12;

export default function ItemTooltip({ item, visible }: ItemTooltipProps) {
  const ref = useRef<HTMLDivElement>(null);
  // Default to viewport center so keyboard focus shows the tooltip in a
  // sensible spot before any mouse movement; mousemove overrides it.
  const [pos, setPos] = useState(() => ({
    x: window.innerWidth / 2,
    y: window.innerHeight / 2,
  }));

  useEffect(() => {
    if (!visible) return;
    const onMove = (e: MouseEvent) => setPos({ x: e.clientX, y: e.clientY });
    window.addEventListener("mousemove", onMove);
    return () => window.removeEventListener("mousemove", onMove);
  }, [visible]);

  if (!visible) return null;

  const truncate = (text: string, max: number): string =>
    text.length > max ? text.slice(0, max) + "…" : text;

  const el = ref.current;
  const width = el?.offsetWidth ?? 260;
  const height = el?.offsetHeight ?? 120;
  const left = Math.min(
    Math.max(pos.x + OFFSET, MARGIN),
    window.innerWidth - width - MARGIN,
  );
  const top = Math.min(
    Math.max(pos.y + OFFSET, MARGIN),
    window.innerHeight - height - MARGIN,
  );

  return (
    <div
      ref={ref}
      className="item-tooltip"
      style={{
        left,
        top,
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
