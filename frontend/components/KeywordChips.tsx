"use client";

import { useState } from "react";

// Individually removable pills instead of one comma-separated text field — matches how
// MentionCatch (the competitor this product's Reddit-discovery flow is modeled on) presents
// AI-suggested keywords: scannable at a glance, and removing one bad suggestion doesn't risk
// mangling the ones around it in a shared text string.
export function KeywordChips({
  keywords,
  onChange,
  placeholder,
  id,
}: {
  keywords: string[];
  onChange: (keywords: string[]) => void;
  placeholder?: string;
  id?: string;
}) {
  const [draft, setDraft] = useState("");

  function commitDraft() {
    const value = draft.trim();
    if (!value) return;
    if (!keywords.includes(value)) {
      onChange([...keywords, value]);
    }
    setDraft("");
  }

  function handleKeyDown(e: React.KeyboardEvent<HTMLInputElement>) {
    if (e.key === "Enter" || e.key === ",") {
      e.preventDefault();
      commitDraft();
    } else if (e.key === "Backspace" && draft === "" && keywords.length > 0) {
      onChange(keywords.slice(0, -1));
    }
  }

  function removeAt(index: number) {
    onChange(keywords.filter((_, i) => i !== index));
  }

  return (
    <div className="chip-input" onClick={(e) => e.currentTarget.querySelector("input")?.focus()}>
      {keywords.map((keyword, i) => (
        <span className="chip" key={`${keyword}-${i}`}>
          {keyword}
          <button
            type="button"
            className="chip-remove"
            onClick={(e) => {
              e.stopPropagation();
              removeAt(i);
            }}
            aria-label={`Remove ${keyword}`}
          >
            ×
          </button>
        </span>
      ))}
      <input
        id={id}
        value={draft}
        onChange={(e) => setDraft(e.target.value)}
        onKeyDown={handleKeyDown}
        onBlur={commitDraft}
        placeholder={keywords.length === 0 ? placeholder : ""}
      />
    </div>
  );
}
