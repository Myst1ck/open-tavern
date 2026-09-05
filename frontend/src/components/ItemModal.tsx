import type { Item } from "../api";

interface ItemModalProps {
  item: Item;
  onClose: () => void;
  onEquip: (item: Item) => void;
  onUnequip: (item: Item) => void;
  onUse: (item: Item) => void;
  onDrop: (item: Item) => void;
}

export default function ItemModal({
  item,
  onClose,
  onEquip,
  onUnequip,
  onUse,
  onDrop,
}: ItemModalProps) {
  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="item-modal panel" onClick={(e) => e.stopPropagation()}>
        <header className="modal-header">
          <h2>{item.name}</h2>
          <button className="modal-close" onClick={onClose} type="button">
            ✕
          </button>
        </header>

        <p className="modal-type">{item.type}</p>

        <div className="modal-stats">
          {item.stats.damage > 0 ? (
            <div className="modal-stat">
              <span className="modal-stat-label">Damage</span>
              <span className="modal-stat-value">{item.stats.damage}</span>
            </div>
          ) : null}
          {item.stats.armor > 0 ? (
            <div className="modal-stat">
              <span className="modal-stat-label">Armor</span>
              <span className="modal-stat-value">{item.stats.armor}</span>
            </div>
          ) : null}
          <div className="modal-stat">
            <span className="modal-stat-label">Value</span>
            <span className="modal-stat-value">{item.stats.value}</span>
          </div>
          <div className="modal-stat">
            <span className="modal-stat-label">Weight</span>
            <span className="modal-stat-value">{item.stats.weight}</span>
          </div>
          {item.stats.extra && Object.keys(item.stats.extra).length > 0
            ? Object.entries(item.stats.extra).map(([key, val]) => (
                <div className="modal-stat" key={key}>
                  <span className="modal-stat-label">{key}</span>
                  <span className="modal-stat-value">{String(val)}</span>
                </div>
              ))
            : null}
        </div>

        {item.description ? (
          <p className="modal-desc">{item.description}</p>
        ) : null}

        {item.tags.length > 0 ? (
          <div className="modal-tags">
            {item.tags.map((tag) => (
              <span key={tag} className="chip">
                {tag}
              </span>
            ))}
          </div>
        ) : null}

        <div className="modal-actions">
          {item.equipped ? (
            <button onClick={() => onUnequip(item)} type="button">
              Unequip
            </button>
          ) : (
            <button onClick={() => onEquip(item)} type="button">
              Equip
            </button>
          )}
          {item.type === "consumable" ? (
            <button onClick={() => onUse(item)} type="button">
              Use
            </button>
          ) : null}
          <button
            className="modal-drop-btn"
            onClick={() => onDrop(item)}
            type="button"
          >
            Drop
          </button>
        </div>
      </div>
    </div>
  );
}
