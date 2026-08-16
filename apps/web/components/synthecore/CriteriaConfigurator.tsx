"use client";

import { useState } from "react";
import {
  OPERATOR_LABELS,
  UNARY_OPERATORS,
  type Criterion,
  type CriterionOperator,
} from "@pretrial/shared-types";

import { cn } from "@/lib/utils";

/**
 * Inclusion and exclusion criteria editor.
 *
 * Criteria are ordered and the order is preserved end to end, because the
 * attrition funnel SyntheCore returns is computed in this order. A director
 * reading "eGFR at least 60 removed 61 percent of remaining candidates"
 * needs that percentage to be against the same denominator the protocol
 * implies, which means the list here has to match the protocol's own
 * sequence.
 */

const OPERATORS = Object.keys(OPERATOR_LABELS) as CriterionOperator[];

const NUMERIC_OPERATORS: CriterionOperator[] = ["gt", "gte", "lt", "lte", "between"];

export interface CriteriaConfiguratorProps {
  features: string[];
  criteria: Criterion[];
  onChange: (criteria: Criterion[]) => void;
  className?: string;
}

export function CriteriaConfigurator({
  features,
  criteria,
  onChange,
  className,
}: CriteriaConfiguratorProps) {
  const [draft, setDraft] = useState<Criterion>(() => emptyCriterion(features[0]));

  function add() {
    if (!draft.feature) return;
    onChange([...criteria, normalise(draft)]);
    setDraft(emptyCriterion(features[0]));
  }

  function remove(index: number) {
    onChange(criteria.filter((_, i) => i !== index));
  }

  function move(index: number, direction: -1 | 1) {
    const target = index + direction;
    if (target < 0 || target >= criteria.length) return;
    const next = [...criteria];
    const [item] = next.splice(index, 1);
    if (item) next.splice(target, 0, item);
    onChange(next);
  }

  const needsValue = !UNARY_OPERATORS.includes(draft.operator);
  const isRange = draft.operator === "between";

  return (
    <div className={cn("panel", className)}>
      <div className="panel-header">
        <span className="label-micro">inclusion and exclusion criteria</span>
        <span className="tabular text-xs text-ink-dim">{criteria.length}</span>
      </div>

      {criteria.length > 0 && (
        <ol className="divide-y divide-edge-faint">
          {criteria.map((criterion, index) => (
            <li key={index} className="flex items-center gap-3 px-4 py-2.5">
              <span className="tabular w-6 shrink-0 text-xs text-ink-dim">
                {String(index + 1).padStart(2, "0")}
              </span>

              <span
                className={cn(
                  "shrink-0 border px-1.5 py-0.5 font-mono text-[10px] uppercase tracking-[0.1em]",
                  criterion.kind === "inclusion"
                    ? "border-accent text-accent-bright"
                    : "border-signal-fail text-signal-fail",
                )}
              >
                {criterion.kind === "inclusion" ? "incl" : "excl"}
              </span>

              <span className="min-w-0 flex-1 truncate font-mono text-[13px] text-ink">
                {describe(criterion)}
              </span>

              <div className="flex shrink-0 items-center gap-1">
                <IconButton label="Move up" onClick={() => move(index, -1)} disabled={index === 0}>
                  ↑
                </IconButton>
                <IconButton
                  label="Move down"
                  onClick={() => move(index, 1)}
                  disabled={index === criteria.length - 1}
                >
                  ↓
                </IconButton>
                <IconButton label="Remove" onClick={() => remove(index)} destructive>
                  ×
                </IconButton>
              </div>
            </li>
          ))}
        </ol>
      )}

      <div className="border-t border-edge bg-surface-sunken p-3">
        <div className="grid grid-cols-1 gap-2 md:grid-cols-[minmax(0,1fr)_minmax(0,1fr)_minmax(0,1fr)_auto]">
          <select
            className="field"
            value={draft.feature}
            onChange={(event) => setDraft({ ...draft, feature: event.target.value })}
            aria-label="Feature"
          >
            {features.length === 0 && <option value="">no features available</option>}
            {features.map((feature) => (
              <option key={feature} value={feature}>
                {feature}
              </option>
            ))}
          </select>

          <select
            className="field"
            value={draft.operator}
            onChange={(event) =>
              setDraft({ ...draft, operator: event.target.value as CriterionOperator, value: "" })
            }
            aria-label="Operator"
          >
            {OPERATORS.map((operator) => (
              <option key={operator} value={operator}>
                {OPERATOR_LABELS[operator]}
              </option>
            ))}
          </select>

          {needsValue ? (
            isRange ? (
              <div className="flex gap-2">
                <input
                  className="field-mono"
                  placeholder="low"
                  value={rangePart(draft.value, 0)}
                  onChange={(event) =>
                    setDraft({
                      ...draft,
                      value: [event.target.value, rangePart(draft.value, 1)],
                    })
                  }
                  aria-label="Range lower bound"
                />
                <input
                  className="field-mono"
                  placeholder="high"
                  value={rangePart(draft.value, 1)}
                  onChange={(event) =>
                    setDraft({
                      ...draft,
                      value: [rangePart(draft.value, 0), event.target.value],
                    })
                  }
                  aria-label="Range upper bound"
                />
              </div>
            ) : (
              <input
                className="field-mono"
                placeholder={
                  draft.operator === "in" || draft.operator === "not_in"
                    ? "comma separated"
                    : "value"
                }
                value={String(draft.value ?? "")}
                onChange={(event) => setDraft({ ...draft, value: event.target.value })}
                aria-label="Value"
              />
            )
          ) : (
            <div className="flex items-center px-1 text-xs text-ink-dim">
              no value needed
            </div>
          )}

          <div className="flex gap-2">
            <button
              type="button"
              onClick={() =>
                setDraft({
                  ...draft,
                  kind: draft.kind === "inclusion" ? "exclusion" : "inclusion",
                })
              }
              className={cn(
                "btn",
                draft.kind === "inclusion"
                  ? "border-accent text-accent-bright"
                  : "border-signal-fail text-signal-fail",
              )}
            >
              {draft.kind === "inclusion" ? "include" : "exclude"}
            </button>
            <button
              type="button"
              onClick={add}
              disabled={!draft.feature}
              className="btn btn-primary"
            >
              add
            </button>
          </div>
        </div>

        {NUMERIC_OPERATORS.includes(draft.operator) && (
          <p className="mt-2 text-xs text-ink-dim">
            Patients with a missing value for this feature are treated as not meeting
            the criterion. An unscreenable patient is not an eligible one.
          </p>
        )}
      </div>
    </div>
  );
}

function IconButton({
  children,
  label,
  onClick,
  disabled,
  destructive,
}: {
  children: React.ReactNode;
  label: string;
  onClick: () => void;
  disabled?: boolean;
  destructive?: boolean;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      aria-label={label}
      title={label}
      className={cn(
        "h-6 w-6 border border-transparent font-mono text-xs transition-colors disabled:opacity-25",
        destructive
          ? "text-ink-dim hover:border-signal-fail hover:text-signal-fail"
          : "text-ink-dim hover:border-edge-strong hover:text-ink",
      )}
    >
      {children}
    </button>
  );
}

function emptyCriterion(feature: string | undefined): Criterion {
  return { feature: feature ?? "", operator: "gte", value: "", kind: "inclusion" };
}

function rangePart(value: unknown, index: 0 | 1): string {
  if (Array.isArray(value)) return String(value[index] ?? "");
  return "";
}

/**
 * Coerce the string values the inputs produce into the shapes the API
 * expects. Doing this at submit time rather than on every keystroke lets a
 * user type "6" on the way to "60" without the field fighting them.
 */
function normalise(criterion: Criterion): Criterion {
  const { operator, value } = criterion;

  if (UNARY_OPERATORS.includes(operator)) {
    return { ...criterion, value: null };
  }

  if (operator === "between" && Array.isArray(value)) {
    return { ...criterion, value: value.map((part) => toNumberIfPossible(String(part))) };
  }

  if (operator === "in" || operator === "not_in") {
    return {
      ...criterion,
      value: String(value ?? "")
        .split(",")
        .map((part) => part.trim())
        .filter(Boolean)
        .map(toNumberIfPossible),
    };
  }

  return { ...criterion, value: toNumberIfPossible(String(value ?? "")) };
}

function toNumberIfPossible(raw: string): string | number {
  const trimmed = raw.trim();
  if (trimmed === "") return trimmed;
  const parsed = Number(trimmed);
  return Number.isFinite(parsed) ? parsed : trimmed;
}

function describe(criterion: Criterion): string {
  if (criterion.label) return criterion.label;
  const operator = OPERATOR_LABELS[criterion.operator];
  if (UNARY_OPERATORS.includes(criterion.operator)) {
    return `${criterion.feature} ${operator}`;
  }
  if (criterion.operator === "between" && Array.isArray(criterion.value)) {
    return `${criterion.feature} ${operator} ${criterion.value[0]} and ${criterion.value[1]}`;
  }
  if (Array.isArray(criterion.value)) {
    return `${criterion.feature} ${operator} ${criterion.value.join(", ")}`;
  }
  return `${criterion.feature} ${operator} ${String(criterion.value ?? "")}`;
}
