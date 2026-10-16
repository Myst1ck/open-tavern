import { useEffect, useRef, useState } from "react";

import type { RollOutcome } from "../api/types";
import Die from "./Die";

// Minimum time the die tumbles before the result is shown. Card-level only:
// sequencing a whole roll set is the caller's job (useTurnStream).
const MIN_ROLL_MS = 2000;

const REDUCED_MOTION_QUERY = "(prefers-reduced-motion: reduce)";

function usePrefersReducedMotion(): boolean {
  const [reduced, setReduced] = useState(
    () => window.matchMedia(REDUCED_MOTION_QUERY).matches,
  );

  useEffect(() => {
    const query = window.matchMedia(REDUCED_MOTION_QUERY);
    const onChange = () => setReduced(query.matches);
    onChange();
    query.addEventListener("change", onChange);
    return () => query.removeEventListener("change", onChange);
  }, []);

  return reduced;
}

interface RollCardProps {
  roll: RollOutcome;
  onRevealed: () => void;
  /** Born in Phase B (resumed transcripts): no tumble, no onRevealed call. */
  initialRevealed?: boolean;
}

export default function RollCard({
  roll,
  onRevealed,
  initialRevealed = false,
}: RollCardProps) {
  const reducedMotion = usePrefersReducedMotion();
  const [revealed, setRevealed] = useState(reducedMotion || initialRevealed);
  const notified = useRef(initialRevealed);
  const onRevealedRef = useRef(onRevealed);
  onRevealedRef.current = onRevealed;

  // Phase A -> Phase B: timer, or instantly when motion is reduced.
  useEffect(() => {
    if (revealed) {
      return;
    }
    if (reducedMotion) {
      setRevealed(true);
      return;
    }
    const timer = window.setTimeout(() => setRevealed(true), MIN_ROLL_MS);
    return () => window.clearTimeout(timer);
  }, [revealed, reducedMotion]);

  useEffect(() => {
    if (!revealed || notified.current) {
      return;
    }
    notified.current = true;
    onRevealedRef.current();
  }, [revealed]);

  const modifier =
    roll.modifier >= 0 ? `+${roll.modifier}` : `${roll.modifier}`;
  const badge = roll.crit_success
    ? { className: "roll-card-badge--crit", label: "Critical success" }
    : roll.crit_fail
      ? { className: "roll-card-badge--fail", label: "Critical failure" }
      : roll.success
        ? { className: "roll-card-badge--success", label: "Success" }
        : { className: "roll-card-badge--fail", label: "Failure" };

  // Spans, not divs: the pending phase renders this inside a <button>.
  const heading = (
    <span className="roll-card-head">
      <Die value={roll.d20} rolling={!revealed} />
      <span className="roll-card-heading">
        <span className="roll-card-name">{roll.name}</span>
        <span className="roll-card-dc">DC {roll.dc}</span>
      </span>
      {revealed && (
        <span className={`roll-card-badge ${badge.className}`}>
          {badge.label}
        </span>
      )}
    </span>
  );

  if (!revealed) {
    return (
      <button
        type="button"
        className="roll-card roll-card--pending"
        onClick={() => setRevealed(true)}
        aria-label={`Rolling ${roll.name}, DC ${roll.dc}. Activate to reveal the result.`}
      >
        {heading}
        <span className="roll-card-hint">Rolling&hellip;</span>
      </button>
    );
  }

  return (
    <div className="roll-card roll-card--revealed">
      {heading}
      <dl className="roll-card-breakdown">
        <div className="roll-card-stat">
          <dt>d20</dt>
          <dd>{roll.d20}</dd>
        </div>
        <div className="roll-card-stat">
          <dt>Modifier</dt>
          <dd>{modifier}</dd>
        </div>
        <div className="roll-card-stat">
          <dt>Total</dt>
          <dd className="roll-card-total">{roll.total}</dd>
        </div>
        <div className="roll-card-stat">
          <dt>Outcome</dt>
          <dd>{roll.success ? "Success" : "Failure"}</dd>
        </div>
      </dl>
    </div>
  );
}
