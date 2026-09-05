"use client";

import { useEffect, useState } from "react";
import { createMemory, deleteMemory, listMemories } from "@/lib/api/memory";
import type { Memory, MemoryType } from "@/lib/types/memory";

const MEMORY_TYPE_LABELS: Record<MemoryType, string> = {
  preference: "Preference",
  interest: "Interest",
  goal: "Goal",
  context: "Context",
  instruction: "Instruction",
  fact: "Fact",
};

const MEMORY_TYPE_COLORS: Record<MemoryType, string> = {
  preference: "memory-tag-preference",
  interest: "memory-tag-interest",
  goal: "memory-tag-goal",
  context: "memory-tag-context",
  instruction: "memory-tag-instruction",
  fact: "memory-tag-fact",
};

export function MemoryPanel() {
  const [memories, setMemories] = useState<Memory[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [newContent, setNewContent] = useState("");
  const [newType, setNewType] = useState<MemoryType>("context");
  const [submitting, setSubmitting] = useState(false);

  const load = async () => {
    try {
      setLoading(true);
      const res = await listMemories();
      setMemories(res.memories);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load memories.");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    load();
  }, []);

  const handleAdd = async (e: React.FormEvent) => {
    e.preventDefault();
    const content = newContent.trim();
    if (!content) return;
    try {
      setSubmitting(true);
      await createMemory({ content, memory_type: newType });
      setNewContent("");
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to add memory.");
    } finally {
      setSubmitting(false);
    }
  };

  const handleDelete = async (id: string) => {
    try {
      await deleteMemory(id);
      setMemories((prev) => prev.filter((m) => m.id !== id));
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to delete memory.");
    }
  };

  return (
    <div className="memory-panel">
      <div className="memory-header">
        <h2>Memory</h2>
        <p className="memory-subtitle">
          Facts the assistant remembers across conversations.
        </p>
      </div>

      <form className="memory-add-form" onSubmit={handleAdd}>
        <input
          type="text"
          className="memory-input"
          placeholder="Remember that I prefer concise answers…"
          value={newContent}
          onChange={(e) => setNewContent(e.target.value)}
          maxLength={2000}
          disabled={submitting}
        />
        <select
          className="memory-type-select"
          value={newType}
          onChange={(e) => setNewType(e.target.value as MemoryType)}
          disabled={submitting}
        >
          {Object.entries(MEMORY_TYPE_LABELS).map(([value, label]) => (
            <option key={value} value={value}>
              {label}
            </option>
          ))}
        </select>
        <button type="submit" className="memory-add-btn" disabled={submitting || !newContent.trim()}>
          {submitting ? "Adding…" : "Add"}
        </button>
      </form>

      {error && <div className="memory-error">{error}</div>}

      {loading ? (
        <div className="memory-empty">Loading…</div>
      ) : memories.length === 0 ? (
        <div className="memory-empty">
          No memories yet. Add one above to personalize your assistant.
        </div>
      ) : (
        <ul className="memory-list">
          {memories.map((m) => (
            <li key={m.id} className="memory-item">
              <div className="memory-item-top">
                <span className={`memory-tag ${MEMORY_TYPE_COLORS[m.memory_type]}`}>
                  {MEMORY_TYPE_LABELS[m.memory_type]}
                </span>
                <button
                  className="memory-delete-btn"
                  onClick={() => handleDelete(m.id)}
                  aria-label="Delete memory"
                  title="Delete memory"
                >
                  ×
                </button>
              </div>
              <p className="memory-content">{m.content}</p>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
