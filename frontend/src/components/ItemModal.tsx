import { useEffect, useRef } from "react";

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
  const dialogRef = useRef<HTMLDivElement>(null);
  const onCloseRef = useRef(onClose);
  onCloseRef.current = onClose;

  useEffect(() => {
    const previouslyFocused = document.activeElement as HTMLElement | null;
    const dialog = dialogRef.current;

    const focusableSelector = [
      "button",
      "input",
      "select",
      "textarea",
      'a[href]',
      '[tabindex]:not([tabindex="-1"])',
    ].join(", ");

    const getFocusable = () => {
      if (!dialog) return [];
      return Array.from(
        dialog.querySelectorAll<HTMLElement>(focusableSelector)
      ).filter((el) => !el.hasAttribute("disabled"));
    };

    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        onCloseRef.current();
        return;
      }
      if (e.key !== "Tab") return;
      const focusable = getFocusable();
      if (focusable.length === 0) {
        e.preventDefault();
        return;
      }
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      const active = document.activeElement;
      if (e.shiftKey) {
        if (active === first || !dialog?.contains(active)) {
          e.preventDefault();
          last.focus();
        }
      } else if (active === last || !dialog?.contains(active)) {
        e.preventDefault();
        first.focus();
      }
    };

    const focusable = getFocusable();
    (focusable[0] ?? dialog)?.focus();

    document.addEventListener("keydown", handleKeyDown);
    return () => {
      document.removeEventListener("keydown", handleKeyDown);
      previouslyFocused?.focus();
    };
  }, []);

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div
        ref={dialogRef}
        className="item-modal panel"
        role="dialog"
        aria-modal="true"
        aria-label={item.name}
        onClick={(e) => e.stopPropagation()}
      >
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
