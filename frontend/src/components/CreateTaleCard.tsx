export default function CreateTaleCard({
  onCreate,
}: {
  onCreate: () => void;
}) {
  return (
    <section className="panel tales-panel" aria-label="Create new tale">
      <button
        type="button"
        className="tale-row create-tale-card"
        onClick={onCreate}
      >
        <span className="tale-info">
          <span className="tale-title">Create new tale</span>
        </span>
      </button>
    </section>
  );
}