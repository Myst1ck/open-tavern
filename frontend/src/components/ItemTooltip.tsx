import { useEffect, useRef, useState } from "react";

import type { Item } from "../api";

interface ItemTooltipProps {
  item: Item;
  visible: boolean;
  /**
   * Anchor supplied when a card is focused via keyboard; a later mouse move
   * overrides it while the tooltip stays open.
   */
  position?: { x: number; y: number } | null;
}

const MARGIN = 8;
const OFFSET = 12;

export default function ItemTooltip({
  item,
  visible,
  position,
}: ItemTooltipProps) {
  const ref = useRef<HTMLDivElement>(null);
  // Cursor position; null while a card is focused via keyboard (no cursor).
  const [cursor, setCursor] = useState<{ x: number; y: number } | null>(null);

  useEffect(() => {
    // A new anchor invalidates any cursor position from an earlier hover.
    setCursor(null);
  }, [position]);

  useEffect(() => {
    if (!visible) return;
    const onMove = (e: MouseEvent) => setCursor({ x: e.clientX, y: e.clientY });
    window.addEventListener("mousemove", onMove);
    return () => window.removeEventListener("mousemove", onMove);
  }, [visible]);

  if (!visible) return null;

  const truncate = (text: string, max: number): string =>
    text.length > max ? text.slice(0, max) + "…" : text;

  const el = ref.current;
  const width = el?.offsetWidth ?? 260;
  const height = el?.offsetHeight ?? 120;
  const point = cursor ??
    position ?? {
      x: window.innerWidth / 2,
      y: window.innerHeight / 2,
    };
  const left = Math.min(
    Math.max(point.x + OFFSET, MARGIN),
    window.innerWidth - width - MARGIN,
  );
  const top = Math.min(
    Math.max(point.y + OFFSET, MARGIN),
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
