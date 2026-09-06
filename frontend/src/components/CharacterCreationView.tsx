import { type FormEvent, useEffect, useState } from "react";

import {
  type CharacterCreationPayload,
  type CharacterSheet,
  type ClassDefinition,
  createCharacter,
  generateClass,
  refineCharacter,
  type RefineResponse,
} from "../api";
import {
  clearCharDraft,
  loadCharDraft,
  saveCharDraft,
} from "../characterDraft";

type StepKey =
  | "name"
  | "race"
  | "class_concept"
  | "backstory"
  | "personality"
  | "appearance"
  | "motivation";

interface WizardStep {
  key: StepKey;
  title: string;
  hint: string;
  placeholder: string;
  textarea: boolean;
}

const STEPS: WizardStep[] = [
  {
    key: "name",
    title: "Name",
    hint: "What shall the world call you?",
    placeholder: "Elowen Ashveil",
    textarea: false,
  },
  {
    key: "race",
    title: "Race",
    hint: "Lineage shapes body and outlook.",
    placeholder: "Half-orc, elf, tiefling, dragonborn...",
    textarea: false,
  },
  {
    key: "class_concept",
    title: "Class Concept",
    hint: "Your calling — an archetype, a trade, a path.",
    placeholder: "Ranger, rogue, arcane trickster...",
    textarea: true,
  },
  {
    key: "backstory",
    title: "Backstory",
    hint: "Where do you come from? What scars, what joys?",
    placeholder:
      "A scarred half-orc ranger hunting the wyrm that burned her village...",
    textarea: true,
  },
  {
    key: "personality",
    title: "Personality",
    hint: "How do you speak, act, and react?",
    placeholder: "Gruff with strangers, fiercely loyal, slow to trust...",
    textarea: true,
  },
  {
    key: "appearance",
    title: "Appearance",
    hint: "What do others see when you walk in?",
    placeholder: "Tall, green-skinned, a fresh scar across one eye...",
    textarea: true,
  },
  {
    key: "motivation",
    title: "Motivation",
    hint: "Why do you adventure? What drives you?",
    placeholder: "To avenge the village the wyrm burned...",
    textarea: true,
  },
];

const PROSE_KEYS = [
  "backstory",
  "personality",
  "appearance",
  "motivation",
] as const;

const PROSE_LABELS: Record<(typeof PROSE_KEYS)[number], string> = {
  backstory: "Backstory",
  personality: "Personality",
  appearance: "Appearance",
  motivation: "Motivation",
};

function proseUnchanged(
  refined: RefineResponse,
  current: Record<StepKey, string>,
): boolean {
  return PROSE_KEYS.every((key) => refined[key].trim() === current[key].trim());
}

function toMessage(err: unknown): string {
  return err instanceof Error ? err.message : String(err);
}

interface CharacterCreationViewProps {
  sessionId: string;
  onCharacterCreated: (character: CharacterSheet) => void;
}

export default function CharacterCreationView({
  sessionId,
  onCharacterCreated,
}: CharacterCreationViewProps) {
  const [values, setValues] = useState<Record<StepKey, string>>({
    name: "",
    race: "",
    class_concept: "",
    backstory: "",
    personality: "",
    appearance: "",
    motivation: "",
  });
  const [draft, setDraft] = useState<Record<string, string>>(() =>
    loadCharDraft(),
  );
  const [stepIndex, setStepIndex] = useState(0);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [freeMode, setFreeMode] = useState(false);
  const [description, setDescription] = useState("");
  const [generatedClass, setGeneratedClass] = useState<ClassDefinition | null>(
    null,
  );
  const [acceptedClass, setAcceptedClass] = useState<ClassDefinition | null>(
    null,
  );
  const [classBusy, setClassBusy] = useState(false);
  const [classError, setClassError] = useState<string | null>(null);
  const [refinedProse, setRefinedProse] = useState<RefineResponse | null>(null);
  const [refineBusy, setRefineBusy] = useState(false);
  const [refineError, setRefineError] = useState<string | null>(null);
  const [refineNote, setRefineNote] = useState<string | null>(null);

  // Persist draft with a short debounce instead of on every keystroke.
  useEffect(() => {
    const timer = setTimeout(() => {
      if (Object.keys(draft).length === 0) {
        return;
      }
      try {
        saveCharDraft(draft);
      } catch {
        // Draft is convenience data; ignore private-mode/storage failures.
      }
    }, 300);
    return () => clearTimeout(timer);
  }, [draft]);

  const step = STEPS[stepIndex];
  const isLastStep = stepIndex === STEPS.length - 1;
  // Name is the only required step; the rest may be skipped.
  const canNext = step.key !== "name" || values.name.trim() !== "";
  const hasProse = PROSE_KEYS.some((key) => values[key].trim() !== "");
  const hasDraft = Object.keys(draft).length > 0;

  const handleFillDraft = () => {
    // Restore each step from the draft, skipping stale or empty values.
    const next: Record<StepKey, string> = { ...values };
    for (const item of STEPS) {
      const value = draft[item.key];
      if (value.trim() !== "") {
        next[item.key] = value;
      }
    }
    setValues(next);
    // Filled values supersede the draft; drop it so the button disappears.
    setDraft({});
    clearCharDraft();
    // Restored prose invalidates any pending refine preview.
    if (refinedProse !== null) {
      setRefinedProse(null);
      setRefineNote(null);
    }
  };

  const handleValueChange = (value: string) => {
    // Editing after a refine invalidates the pending preview.
    if (refinedProse !== null) {
      setRefinedProse(null);
      setRefineNote(null);
    }
    setValues((prev) => ({ ...prev, [step.key]: value }));
    setDraft({ ...draft, [step.key]: value });
  };

  const handleNext = () => {
    if (stepIndex < STEPS.length - 1) {
      setStepIndex(stepIndex + 1);
    }
  };

  const handleBack = () => {
    if (stepIndex > 0) {
      setStepIndex(stepIndex - 1);
    }
  };

  const handleGenerateClass = async () => {
    const concept = values.class_concept.trim();
    if (classBusy || busy || concept === "") {
      return;
    }
    setClassBusy(true);
    setClassError(null);
    try {
      const response = await generateClass(sessionId, concept);
      setGeneratedClass(response.class_definition);
      // A fresh class invalidates any previously accepted one.
      setAcceptedClass(null);
    } catch (err) {
      setClassError(toMessage(err));
    } finally {
      setClassBusy(false);
    }
  };

  const handleAcceptClass = () => {
    if (generatedClass !== null) {
      setAcceptedClass(generatedClass);
    }
  };

  const handleRefine = async () => {
    if (refineBusy || busy || !hasProse) {
      return;
    }
    setRefineBusy(true);
    setRefineError(null);
    setRefineNote(null);
    try {
      const response = await refineCharacter(sessionId, {
        backstory: values.backstory.trim(),
        personality: values.personality.trim(),
        appearance: values.appearance.trim(),
        motivation: values.motivation.trim(),
      });
      setRefinedProse(response);
      if (proseUnchanged(response, values)) {
        setRefineNote(
          "The forge found nothing to change. Your words stand as written.",
        );
      }
    } catch (err) {
      setRefineError(toMessage(err));
    } finally {
      setRefineBusy(false);
    }
  };

  const handleAcceptRefine = () => {
    if (refinedProse === null) {
      return;
    }
    const accepted = refinedProse;
    const next: Record<StepKey, string> = {
      ...values,
      backstory: accepted.backstory,
      personality: accepted.personality,
      appearance: accepted.appearance,
      motivation: accepted.motivation,
    };
    setValues(next);
    setDraft(next);
    try {
      saveCharDraft(next);
    } catch {
      // Draft is convenience data; ignore private-mode/storage failures.
    }
    setRefinedProse(null);
    setRefineNote(null);
    setRefineError(null);
  };

  const handleKeepRefine = () => {
    setRefinedProse(null);
    setRefineNote(null);
    setRefineError(null);
  };

  const buildPayload = (): CharacterCreationPayload => {
    const payload: CharacterCreationPayload = {};
    for (const item of STEPS) {
      const value = values[item.key].trim();
      if (value !== "") {
        payload[item.key] = value;
      }
    }
    if (acceptedClass !== null) {
      payload.class_name = acceptedClass.name;
      payload.class_hit_die = acceptedClass.hit_die;
      payload.class_description = acceptedClass.description;
    }
    return payload;
  };

  const submitStructured = async () => {
    const payload = buildPayload();
    if (Object.keys(payload).length === 0) {
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const response = await createCharacter(sessionId, payload);
      onCharacterCreated(response.character);
    } catch (err) {
      setError(toMessage(err));
    } finally {
      setBusy(false);
    }
  };

  const submitFree = async () => {
    setBusy(true);
    setError(null);
    try {
      const response = await createCharacter(sessionId, description.trim());
      onCharacterCreated(response.character);
    } catch (err) {
      setError(toMessage(err));
    } finally {
      setBusy(false);
    }
  };

  const handleWizardSubmit = (event: FormEvent) => {
    event.preventDefault();
    if (busy || !canNext) {
      return;
    }
    if (!isLastStep) {
      handleNext();
      return;
    }
    // Decide on any pending refine before forging.
    if (refinedProse !== null || refineBusy) {
      return;
    }
    void submitStructured();
  };

  const handleFreeSubmit = (event: FormEvent) => {
    event.preventDefault();
    if (busy || description.trim().length < 20) {
      return;
    }
    void submitFree();
  };

  return (
    <section className="panel character-panel">
      <h2>Forge Your Hero</h2>
      {!freeMode ? (
        <>
          {hasDraft && (
            <button
              type="button"
              className="char-fill-btn"
              onClick={handleFillDraft}
              disabled={busy}
            >
              Fill with last values
            </button>
          )}
          <p className="muted">{step.hint}</p>
          <form onSubmit={handleWizardSubmit}>
            <label htmlFor={`character-${step.key}`}>{step.title}</label>
            {step.textarea ? (
              <textarea
                id={`character-${step.key}`}
                value={values[step.key]}
                onChange={(event) => handleValueChange(event.target.value)}
                placeholder={step.placeholder}
                maxLength={2000}
                disabled={busy}
              />
            ) : (
              <input
                id={`character-${step.key}`}
                value={values[step.key]}
                onChange={(event) => handleValueChange(event.target.value)}
                placeholder={step.placeholder}
                maxLength={step.key === "name" ? 100 : undefined}
                disabled={busy}
              />
            )}
            {values[step.key].trim() === "" &&
              draft[step.key]?.trim() !== "" && (
                <span className="char-last-hint">last: {draft[step.key]}</span>
              )}
            {step.key === "class_concept" && (
              <>
                <button
                  type="button"
                  className="wizard-switch"
                  onClick={() => void handleGenerateClass()}
                  disabled={
                    classBusy || busy || values.class_concept.trim() === ""
                  }
                >
                  {classBusy
                    ? "Summoning archetype..."
                    : generatedClass !== null
                      ? "Regenerate Class"
                      : "Generate Class"}
                </button>
                {generatedClass !== null && (
                  <div className="panel class-preview">
                    <h3>{generatedClass.name}</h3>
                    <p className="muted">{generatedClass.description}</p>
                    <p className="muted">Hit Die: d{generatedClass.hit_die}</p>
                    {acceptedClass === generatedClass ? (
                      <p className="muted">Class accepted.</p>
                    ) : (
                      <button
                        type="button"
                        onClick={handleAcceptClass}
                        disabled={classBusy || busy}
                      >
                        Accept Class
                      </button>
                    )}
                  </div>
                )}
                {classError !== null && <p className="error">{classError}</p>}
              </>
            )}
            {step.key === "motivation" && (
              <>
                <button
                  type="button"
                  className="wizard-switch"
                  onClick={() => void handleRefine()}
                  disabled={refineBusy || busy || !hasProse}
                >
                  {refineBusy ? "Polishing prose..." : "Refine Prose"}
                </button>
                {refineError !== null && <p className="error">{refineError}</p>}
                {refinedProse !== null && (
                  <div className="panel refine-preview">
                    <h3>Refined Prose</h3>
                    {refineNote !== null && (
                      <p className="muted">{refineNote}</p>
                    )}
                    {PROSE_KEYS.map((key) => (
                      <div key={key} className="sheet-persona-block">
                        <h3>{PROSE_LABELS[key]}</h3>
                        <p className="sheet-persona">
                          {refinedProse[key].trim() !== ""
                            ? refinedProse[key]
                            : "—"}
                        </p>
                      </div>
                    ))}
                    <div className="refine-actions">
                      <button
                        type="button"
                        onClick={handleAcceptRefine}
                        disabled={busy}
                      >
                        Accept
                      </button>
                      <button
                        type="button"
                        className="wizard-switch"
                        onClick={handleKeepRefine}
                        disabled={busy}
                      >
                        Keep Originals
                      </button>
                    </div>
                  </div>
                )}
              </>
            )}
            <div className="wizard-nav">
              <button
                type="button"
                onClick={handleBack}
                disabled={busy || stepIndex === 0}
              >
                Back
              </button>
              <span className="wizard-progress">
                Step {stepIndex + 1} of {STEPS.length}
              </span>
              <button
                type="submit"
                disabled={
                  busy ||
                  !canNext ||
                  (isLastStep && (refinedProse !== null || refineBusy))
                }
              >
                {isLastStep
                  ? busy
                    ? "Weaving fate..."
                    : "Forge Character"
                  : "Next"}
              </button>
            </div>
          </form>
          <button
            type="button"
            className="wizard-switch"
            onClick={() => setFreeMode(true)}
            disabled={busy}
          >
            Prefer to describe freely?
          </button>
        </>
      ) : (
        <>
          <p className="muted">Describe your adventurer in your own words.</p>
          <form onSubmit={handleFreeSubmit}>
            <label htmlFor="character-description">Character description</label>
            <textarea
              id="character-description"
              value={description}
              onChange={(event) => setDescription(event.target.value)}
              placeholder="A scarred half-orc ranger hunting the wyrm that burned her village..."
              maxLength={2000}
              minLength={20}
              disabled={busy}
            />
            <button
              type="submit"
              disabled={busy || description.trim().length < 20}
            >
              {busy ? "Weaving fate..." : "Forge Character"}
            </button>
          </form>
          <button
            type="button"
            className="wizard-switch"
            onClick={() => setFreeMode(false)}
            disabled={busy}
          >
            Back to guided steps
          </button>
        </>
      )}
      {error !== null && <p className="error">{error}</p>}
    </section>
  );
}
