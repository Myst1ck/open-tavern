import type { BaseType, Item } from "../api";

const TYPE_EMOJI: Record<BaseType, string> = {
  weapon: "🗡️",
  armor: "🛡️",
  consumable: "🧪",
  quest: "📜",
  loot: "💰",
  key: "🔑",
};

interface InventoryGridProps {
  items: Item[];
  onItemClick: (item: Item) => void;
  onItemHover: (item: Item | null) => void;
}

export default function InventoryGrid({
  items,
  onItemClick,
  onItemHover,
}: InventoryGridProps) {
  if (items.length === 0) {
    return <p className="muted">Inventory empty</p>;
  }

  return (
    <div className="inventory-grid">
      {items.map((item) => (
        <button
          key={item.id}
          className="inventory-card"
          onClick={() => onItemClick(item)}
          onMouseEnter={() => onItemHover(item)}
          onMouseLeave={() => onItemHover(null)}
          onFocus={() => onItemHover(item)}
          onBlur={() => onItemHover(null)}
          type="button"
        >
          <span className="item-emoji">{TYPE_EMOJI[item.type]}</span>
          <span className="item-name">{item.name}</span>
          {item.equipped ? (
            <span className="equipped-badge">Equipped</span>
          ) : null}
        </button>
      ))}
    </div>
  );
}
