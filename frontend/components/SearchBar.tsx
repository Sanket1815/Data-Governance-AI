"use client";

import { Loader2, Search, Sparkles } from "lucide-react";
import { FormEvent, useState } from "react";
import clsx from "clsx";

const EXAMPLE_PROMPTS: readonly string[] = [
  "What are the top 10 highest-cost insurance claims this year?",
  "Show average claim amount grouped by policy type",
  "How many claims were denied in the last quarter?",
  "List patients with more than 3 claims in the last 6 months",
];

interface SearchBarProps {
  onSubmit: (prompt: string) => void;
  isLoading: boolean;
}

export default function SearchBar({ onSubmit, isLoading }: SearchBarProps) {
  const [prompt, setPrompt] = useState("");

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const trimmed = prompt.trim();
    if (!trimmed || isLoading) return;
    onSubmit(trimmed);
  }

  function handleExampleClick(example: string) {
    if (isLoading) return;
    setPrompt(example);
    onSubmit(example);
  }

  return (
    <div className="w-full">
      <form onSubmit={handleSubmit} className="relative">
        <Search
          className="pointer-events-none absolute left-4 top-1/2 h-5 w-5 -translate-y-1/2 text-gray-500"
          aria-hidden="true"
        />
        <input
          type="text"
          value={prompt}
          onChange={(event) => setPrompt(event.target.value)}
          placeholder="Ask a question about the healthcare_insurance dataset..."
          disabled={isLoading}
          className={clsx(
            "w-full rounded-xl border border-surface-border bg-surface-raised py-4 pl-12 pr-32",
            "text-base text-gray-100 placeholder:text-gray-500",
            "outline-none ring-0 transition focus:border-indigo-500 focus:ring-2 focus:ring-indigo-500/30",
            "disabled:cursor-not-allowed disabled:opacity-60"
          )}
          aria-label="Natural language query"
        />
        <button
          type="submit"
          disabled={isLoading || !prompt.trim()}
          className={clsx(
            "absolute right-2 top-1/2 flex -translate-y-1/2 items-center gap-2 rounded-lg px-4 py-2.5",
            "bg-indigo-600 text-sm font-medium text-white transition hover:bg-indigo-500",
            "disabled:cursor-not-allowed disabled:bg-gray-700 disabled:text-gray-400"
          )}
        >
          {isLoading ? (
            <>
              <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
              Running
            </>
          ) : (
            "Ask"
          )}
        </button>
      </form>

      <div className="mt-3 flex flex-wrap items-center gap-2">
        <span className="flex items-center gap-1 text-xs font-medium text-gray-500">
          <Sparkles className="h-3.5 w-3.5" aria-hidden="true" />
          Try:
        </span>
        {EXAMPLE_PROMPTS.map((example) => (
          <button
            key={example}
            type="button"
            onClick={() => handleExampleClick(example)}
            disabled={isLoading}
            className={clsx(
              "rounded-full border border-surface-border bg-surface-raised px-3 py-1 text-xs text-gray-300",
              "transition hover:border-indigo-500/60 hover:text-white",
              "disabled:cursor-not-allowed disabled:opacity-50"
            )}
          >
            {example}
          </button>
        ))}
      </div>
    </div>
  );
}
