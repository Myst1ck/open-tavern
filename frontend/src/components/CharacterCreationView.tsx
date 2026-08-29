import { useState, type FormEvent } from "react";
import {
  createCharacter,
  generateClass,
  type CharacterCreationPayload,
  type CharacterSheet,
  type ClassDefinition,
} from "../api";

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
  const [stepIndex, setStepIndex] = useState(0);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [freeMode, setFreeMode] = useState(false);
  const [description, setDescription] = useState("");
  const [generatedClass, setGeneratedClass] =
    useState<ClassDefinition | null>(null);
  const [acceptedClass, setAcceptedClass] =
    useState<ClassDefinition | null>(null);
  const [classBusy, setClassBusy] = useState(false);
  const [classError, setClassError] = useState<string | null>(null);

  const step = STEPS[stepIndex];
  const isLastStep = stepIndex === STEPS.length - 1;
  // Name is the only required step; the rest may be skipped.
  const canNext = step.key !== "name" || values.name.trim() !== "";

  const handleValueChange = (value: string) => {
    setValues((prev) => ({ ...prev, [step.key]: value }));
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
    void submitStructured();
  };

  const handleFreeSubmit = (event: FormEvent) => {
    event.preventDefault();
    if (busy || description.trim() === "") {
      return;
    }
    void submitFree();
  };

  return (
    <section className="panel character-panel">
      <h2>Forge Your Hero</h2>
      {!freeMode ? (
        <>
          <p className="muted">{step.hint}</p>
          <form onSubmit={handleWizardSubmit}>
            <label htmlFor={`character-${step.key}`}>{step.title}</label>
            {step.textarea ? (
              <textarea
                id={`character-${step.key}`}
                value={values[step.key]}
                onChange={(event) => handleValueChange(event.target.value)}
                placeholder={step.placeholder}
                disabled={busy}
              />
            ) : (
              <input
                id={`character-${step.key}`}
                value={values[step.key]}
                onChange={(event) => handleValueChange(event.target.value)}
                placeholder={step.placeholder}
                disabled={busy}
              />
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
                    <p className="muted">
                      Hit Die: d{generatedClass.hit_die}
                    </p>
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
              <button type="submit" disabled={busy || !canNext}>
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
              disabled={busy}
            />
            <button type="submit" disabled={busy || description.trim() === ""}>
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
