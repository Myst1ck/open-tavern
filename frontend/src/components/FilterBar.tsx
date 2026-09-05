import type { BaseType } from "../api";

export interface FilterState {
  type?: BaseType;
  tag?: string;
  sortBy: "name" | "type" | "value" | "weight";
  sortDir: "asc" | "desc";
}

const BASE_TYPES: BaseType[] = [
  "weapon",
  "armor",
  "consumable",
  "quest",
  "loot",
  "key",
];

interface FilterBarProps {
  currentFilter: FilterState;
  onFilterChange: (filter: FilterState) => void;
}

export default function FilterBar({
  currentFilter,
  onFilterChange,
}: FilterBarProps) {
  const update = (patch: Partial<FilterState>) =>
    onFilterChange({ ...currentFilter, ...patch });

  return (
    <div className="filter-bar">
      <label>
        Type
        <select
          value={currentFilter.type ?? ""}
          onChange={(e) =>
            update({
              type: (e.target.value || undefined) as BaseType | undefined,
            })
          }
        >
          <option value="">All</option>
          {BASE_TYPES.map((t) => (
            <option key={t} value={t}>
              {t}
            </option>
          ))}
        </select>
      </label>

      <label>
        Tag
        <input
          type="text"
          placeholder="Filter by tag…"
          value={currentFilter.tag ?? ""}
          onChange={(e) => update({ tag: e.target.value || undefined })}
        />
      </label>

      <label>
        Sort
        <select
          value={`${currentFilter.sortBy}-${currentFilter.sortDir}`}
          onChange={(e) => {
            const [sortBy, sortDir] = e.target.value.split("-") as [
              FilterState["sortBy"],
              FilterState["sortDir"],
            ];
            update({ sortBy, sortDir });
          }}
        >
          <option value="name-asc">Name ↑</option>
          <option value="name-desc">Name ↓</option>
          <option value="type-asc">Type ↑</option>
          <option value="type-desc">Type ↓</option>
          <option value="value-asc">Value ↑</option>
          <option value="value-desc">Value ↓</option>
          <option value="weight-asc">Weight ↑</option>
          <option value="weight-desc">Weight ↓</option>
        </select>
      </label>
    </div>
  );
}
