import { type KeyboardEvent } from "react";

export type PlayTabId = "campaign" | "character" | "inventory" | "dm-style";

interface PlayTabsProps {
  active: PlayTabId;
  onChange: (id: PlayTabId) => void;
}

const TABS: { id: PlayTabId; label: string }[] = [
  { id: "campaign", label: "Campaign" },
  { id: "character", label: "Character" },
  { id: "inventory", label: "Inventory" },
  { id: "dm-style", label: "DM Style" },
];

/** Segmented control switching the single play-view content area. */
export default function PlayTabs({ active, onChange }: PlayTabsProps) {
  const handleKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    const index = TABS.findIndex((tab) => tab.id === active);
    let nextIndex: number;
    switch (event.key) {
      case "ArrowRight":
        nextIndex = (index + 1) % TABS.length;
        break;
      case "ArrowLeft":
        nextIndex = (index - 1 + TABS.length) % TABS.length;
        break;
      case "Home":
        nextIndex = 0;
        break;
      case "End":
        nextIndex = TABS.length - 1;
        break;
      default:
        return;
    }
    event.preventDefault();
    const next = TABS[nextIndex];
    onChange(next.id);
    const nextEl = document.getElementById(`play-tab-${next.id}`);
    nextEl?.focus();
    // Keep the focused tab visible when the bar overflows and scrolls
    // horizontally, without shifting the page vertically.
    nextEl?.scrollIntoView({ block: "nearest", inline: "nearest" });
  };

  return (
    <div
      className="play-tabs"
      role="tablist"
      aria-label="Play sections"
      onKeyDown={handleKeyDown}
    >
      {TABS.map((tab) => {
        const selected = active === tab.id;
        return (
          <button
            key={tab.id}
            type="button"
            role="tab"
            id={`play-tab-${tab.id}`}
            className={`play-tab${selected ? " active" : ""}`}
            aria-selected={selected}
            // Inactive panels unmount (the campaign panel only hides), so
            // keep aria-controls on the active tab whose panel is guaranteed
            // to exist in the DOM.
            aria-controls={selected ? `play-panel-${tab.id}` : undefined}
            tabIndex={selected ? 0 : -1}
            onClick={() => onChange(tab.id)}
          >
            {tab.label}
          </button>
        );
      })}
    </div>
  );
}
