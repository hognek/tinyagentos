import { useState, useEffect, useCallback, useRef } from "react";
import {
  ListChecks,
  Plus,
  Clock,
  Square,
  CheckSquare,
  Pencil,
  Trash2,
  X,
  Check,
  AlertCircle,
  ChevronLeft,
} from "lucide-react";
import { Button, Textarea } from "@/components/ui";

// ---- Types ----

interface TodoList {
  id: string;
  owner_user_id: string;
  title: string;
  created_at: string;
  updated_at: string;
  archived_at: string | null;
}

interface TodoItem {
  id: string;
  list_id: string;
  text: string;
  done: boolean;
  position: number;
  due_at: number | null;
  remind_at: number | null;
  author: string | null;
  created_at: string;
  updated_at: string;
}

interface TodoDetail {
  id: string;
  owner_user_id: string;
  title: string;
  created_at: string;
  updated_at: string;
  items: TodoItem[];
}

// ---- Helpers ----

function relativeTime(ts: string): string {
  const diff = Date.now() - Date.parse(ts);
  const mins = Math.floor(diff / 60_000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  const days = Math.floor(hrs / 24);
  return `${days}d ago`;
}

const API_BASE = "/api/todo";
const APP_NAME = "Todo";
const NOUN = "list";
const Icon = ListChecks;
const TITLE_PLACEHOLDER = "List title...";
const ADD_PLACEHOLDER = "Add a task...";
const EMPTY_DOCS = "No lists yet.";
const EMPTY_ENTRIES = "Nothing here yet. Add your first task above.";
const SELECT_PROMPT = "Select a list to get started.";

// ---- Sub-components ----

function TodoItemRow({
  item,
  onDelete,
  onEditSave,
  onToggleDone,
}: {
  item: TodoItem;
  onDelete: (id: string) => void;
  onEditSave: (id: string, text: string) => Promise<void>;
  onToggleDone: (id: string, done: boolean) => void;
}) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(item.text);
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);

  async function save() {
    if (!draft.trim() || draft === item.text) {
      setEditing(false);
      return;
    }
    setSaving(true);
    setSaveError(null);
    try {
      await onEditSave(item.id, draft.trim());
      setEditing(false);
    } catch (e) {
      setSaveError(e instanceof Error ? e.message : "Could not save the edit.");
    } finally {
      setSaving(false);
    }
  }

  return (
    <li className="group flex flex-col gap-1">
      <div className="flex items-start gap-2 rounded-lg border border-shell-border bg-shell-surface px-3 py-2.5">
        {editing ? (
          <div className="flex flex-1 flex-col gap-2">
            <Textarea
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              rows={2}
              maxLength={20000}
              aria-label="Edit item text"
              autoFocus
              className="resize-none border-shell-border bg-shell-bg-deep text-shell-text placeholder:text-shell-text-tertiary"
            />
            <div className="flex justify-end gap-2">
              <Button type="button" variant="ghost" size="sm"
                onClick={() => { setDraft(item.text); setSaveError(null); setEditing(false); }}
                disabled={saving} aria-label="Cancel edit">
                <X size={13} /> Cancel
              </Button>
              <Button type="button" size="sm" onClick={save}
                disabled={saving || !draft.trim()} aria-label="Save edit">
                <Check size={13} /> {saving ? "Saving..." : "Save"}
              </Button>
            </div>
            {saveError && <p className="text-xs text-red-400" role="alert">{saveError}</p>}
          </div>
        ) : (
          <>
            <button type="button" onClick={() => onToggleDone(item.id, !item.done)}
              aria-label={item.done ? "Mark task not done" : "Mark task done"}
              aria-pressed={item.done}
              className="mt-0.5 shrink-0 text-shell-text-tertiary transition-colors hover:text-accent">
              {item.done ? <CheckSquare size={16} className="text-accent" /> : <Square size={16} />}
            </button>
            <p className={["min-w-0 flex-1 whitespace-pre-wrap text-sm",
              item.done ? "text-shell-text-tertiary line-through" : "text-shell-text"].join(" ")}>
              {item.text}
            </p>
            <div className="flex shrink-0 items-center gap-1 opacity-0 transition-opacity group-hover:opacity-100 focus-within:opacity-100">
              <button type="button" onClick={() => setEditing(true)}
                aria-label="Edit item"
                className="rounded-md p-1 text-shell-text-tertiary transition-colors hover:text-shell-text">
                <Pencil size={14} />
              </button>
              <button type="button" onClick={() => onDelete(item.id)}
                aria-label="Delete item"
                className="rounded-md p-1 text-shell-text-tertiary transition-colors hover:text-red-400">
                <Trash2 size={14} />
              </button>
            </div>
          </>
        )}
      </div>
      {item.author && (
        <span className="pl-1 text-[11px] text-shell-text-tertiary">
          {item.author} · {relativeTime(item.created_at)}
        </span>
      )}
    </li>
  );
}

function TodoDetailPane({ listId, onBack }: { listId: string; onBack: () => void }) {
  const [doc, setDoc] = useState<TodoDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [newText, setNewText] = useState("");
  const [adding, setAdding] = useState(false);

  const loadReqRef = useRef(0);
  const loadDoc = useCallback(async () => {
    const myReq = ++loadReqRef.current;
    if (loadReqRef.current === myReq) setError(null);
    try {
      const r = await fetch(`${API_BASE}/${listId}`);
      if (!r.ok) throw new Error("Could not load list.");
      const data = await r.json();
      if (loadReqRef.current === myReq) setDoc(data);
    } catch (e) {
      if (loadReqRef.current === myReq) setError(e instanceof Error ? e.message : "Could not load list.");
    } finally {
      if (loadReqRef.current === myReq) setLoading(false);
    }
  }, [listId]);

  useEffect(() => { setLoading(true); setError(null); setDoc(null); loadDoc(); }, [loadDoc]);

  async function addItem() {
    if (!newText.trim() || !doc) return;
    setAdding(true);
    try {
      const r = await fetch(`${API_BASE}/${doc.id}/items`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text: newText.trim() }),
      });
      if (!r.ok) throw new Error("Could not add item.");
      setNewText(""); await loadDoc();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not add item.");
    } finally { setAdding(false); }
  }

  async function deleteItem(itemId: string) {
    if (!doc) return;
    try {
      const r = await fetch(`${API_BASE}/${doc.id}/items/${itemId}`, { method: "DELETE" });
      if (!r.ok) throw new Error("Could not delete item.");
      setDoc((prev) => prev ? { ...prev, items: prev.items.filter((i) => i.id !== itemId) } : prev);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not delete item.");
    }
  }

  async function editItem(itemId: string, text: string) {
    if (!doc) return;
    const r = await fetch(`${API_BASE}/${doc.id}/items/${itemId}`, {
      method: "PATCH", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text }),
    });
    if (!r.ok) throw new Error("Could not edit item.");
    setDoc((prev) => prev ? { ...prev, items: prev.items.map((i) => (i.id === itemId ? { ...i, text } : i)) } : prev);
  }

  async function toggleDone(itemId: string, done: boolean) {
    if (!doc) return;
    setDoc((prev) => prev ? { ...prev, items: prev.items.map((i) => (i.id === itemId ? { ...i, done } : i)) } : prev);
    try {
      const r = await fetch(`${API_BASE}/${doc.id}/items/${itemId}`, {
        method: "PATCH", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ done }),
      });
      if (!r.ok) throw new Error("Could not update task.");
    } catch (e) {
      setDoc((prev) => prev ? { ...prev, items: prev.items.map((el) => el.id === itemId ? { ...el, done: !done } : el) } : prev);
      setError(e instanceof Error ? e.message : "Could not update task.");
    }
  }

  if (loading) return <div className="flex h-full items-center justify-center"><p className="text-sm text-shell-text-tertiary">Loading...</p></div>;
  if (!doc) return <div className="flex h-full items-center justify-center"><p className="text-sm text-red-400" role="alert">List not found.</p></div>;

  const items = doc.items ?? [];
  return (
    <div className="flex h-full flex-col overflow-hidden">
      <div className="flex items-center gap-2 border-b border-shell-border px-4 py-3">
        <button type="button" onClick={onBack} aria-label="Back to lists"
          className="flex items-center gap-1 rounded-md text-shell-text-secondary transition-colors hover:text-shell-text md:hidden">
          <ChevronLeft size={16} />
        </button>
        <h2 className="flex-1 truncate text-sm font-semibold text-shell-text">{doc.title}</h2>
      </div>
      <div className="flex-1 overflow-y-auto px-4 py-4">
        <div className="flex flex-col gap-4">
          {error && (<div className="flex items-center justify-between gap-2 rounded-lg border border-red-500/20 bg-red-500/10 px-3 py-2 text-xs text-red-400" role="alert"><div className="flex items-center gap-2"><AlertCircle size={13} className="shrink-0" />{error}</div><button type="button" onClick={() => setError(null)} aria-label="Dismiss error" className="shrink-0 text-red-400 transition-opacity hover:opacity-70"><X size={13} /></button></div>)}
          <div className="flex flex-col gap-2">
            <Textarea value={newText} onChange={(e) => setNewText(e.target.value)}
              placeholder={ADD_PLACEHOLDER} rows={2} maxLength={20000} aria-label="New item text"
              onKeyDown={(e) => { if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) { e.preventDefault(); void addItem(); }}}
              className="resize-none border-shell-border bg-shell-surface text-shell-text placeholder:text-shell-text-tertiary" />
            <div className="flex justify-end">
              <Button type="button" size="sm" onClick={addItem} disabled={adding || !newText.trim()} aria-label="Add item">
                <Plus size={13} /> {adding ? "Adding..." : "Add"}
              </Button>
            </div>
          </div>
          {items.length > 0 ? (
            <ul className="flex flex-col gap-2" aria-label="List items">
              {items.map((item) => (<TodoItemRow key={item.id} item={item} onDelete={deleteItem} onEditSave={editItem} onToggleDone={toggleDone} />))}
            </ul>
          ) : (
            <div className="flex flex-col items-center gap-2 py-10 text-center">
              <Icon size={28} className="text-shell-text-tertiary" />
              <p className="text-sm text-shell-text-secondary">{EMPTY_ENTRIES}</p>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

function TodoListItem({ list, selected, onClick }: { list: TodoList; selected: boolean; onClick: () => void }) {
  return (
    <li>
      <button type="button" onClick={onClick} aria-selected={selected}
        className={["flex w-full flex-col gap-1 rounded-xl border px-3.5 py-3 text-left transition-colors",
          selected ? "border-accent bg-accent/10" : "border-shell-border bg-shell-surface hover:border-shell-border-strong"].join(" ")}>
        <span className="truncate text-sm font-medium text-shell-text">{list.title}</span>
        <span className="flex items-center gap-1 text-xs text-shell-text-tertiary"><Clock size={10} className="shrink-0" />{relativeTime(list.updated_at)}</span>
      </button>
    </li>
  );
}

function CreateTodoForm({ onCreated, onCancel }: { onCreated: (list: TodoList) => void; onCancel: () => void }) {
  const [title, setTitle] = useState("");
  const [creating, setCreating] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  useEffect(() => { inputRef.current?.focus(); }, []);

  async function create() {
    if (!title.trim()) return;
    setCreating(true); setError(null);
    try {
      const r = await fetch(API_BASE, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ title: title.trim() }) });
      if (!r.ok) throw new Error(`Could not create ${NOUN}.`);
      const doc: TodoList = await r.json();
      onCreated(doc);
      setCreating(false);
      setTitle("");
    } catch (e) {
      setError(e instanceof Error ? e.message : `Could not create ${NOUN}.`);
      setCreating(false);
    }
  }

  return (
    <div className="flex flex-col gap-2 rounded-xl border border-shell-border bg-shell-bg-deep p-3">
      <input ref={inputRef} type="text" value={title} onChange={(e) => setTitle(e.target.value)}
        placeholder={TITLE_PLACEHOLDER} aria-label={`New ${NOUN} title`} maxLength={255}
        onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); void create(); } if (e.key === "Escape") onCancel(); }}
        className="w-full rounded-lg border border-shell-border bg-shell-surface px-3 py-2 text-sm text-shell-text placeholder:text-shell-text-tertiary focus:outline-none focus:ring-2 focus:ring-accent/40" />
      {error && <p className="text-xs text-red-400" role="alert">{error}</p>}
      <div className="flex justify-end gap-2">
        <Button type="button" variant="ghost" size="sm" onClick={onCancel} disabled={creating} aria-label="Cancel">Cancel</Button>
        <Button type="button" size="sm" onClick={create} disabled={creating || !title.trim()} aria-label={`Create ${NOUN}`}>{creating ? "Creating..." : "Create"}</Button>
      </div>
    </div>
  );
}

// NOTE: The standalone TodoApp does not render the Share/members panel or
// per-entry revision history that the shared DocsApp provided for kind=list docs.
// The /api/todo endpoints do not yet support members or entry history; this is
// tracked as follow-up work.  (Kilo WARNING, PR #2037)
export function TodoApp({ windowId: _windowId }: { windowId: string }) {
  const [lists, setLists] = useState<TodoList[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [showCreate, setShowCreate] = useState(false);

  const loadLists = useCallback(async () => {
    try {
      const r = await fetch(API_BASE);
      if (r.ok) { const data: unknown = await r.json(); setLists(Array.isArray(data) ? (data as TodoList[]) : []); setLoadError(null); }
    } catch { setLoadError("Could not load lists. Try refreshing the page."); } finally { setLoading(false); }
  }, []);
  useEffect(() => { loadLists(); }, [loadLists]);

  function handleCreated(list: TodoList) { setLists((prev) => [list, ...prev]); setSelectedId(list.id); setShowCreate(false); }

  return (
    <div className="flex h-full overflow-hidden bg-shell-bg">
      <div className={["flex flex-col border-r border-shell-border",
        selectedId ? "hidden md:flex md:w-72 lg:w-80" : "flex w-full md:w-72 lg:w-80"].join(" ")}>
        <div className="flex items-center gap-2 border-b border-shell-border px-4 py-4">
          <Icon size={17} className="text-accent" />
          <h1 className="flex-1 text-base font-semibold text-shell-text">{APP_NAME}</h1>
          <button type="button" onClick={() => setShowCreate((v) => !v)} aria-label={`New ${NOUN}`} aria-expanded={showCreate}
            className={["flex h-8 w-8 items-center justify-center rounded-lg border transition-colors",
              showCreate ? "border-accent bg-accent/10 text-accent" : "border-shell-border text-shell-text-secondary hover:border-shell-border-strong hover:text-shell-text"].join(" ")}>
            <Plus size={16} />
          </button>
        </div>
        {showCreate && (<div className="border-b border-shell-border px-3 py-3"><CreateTodoForm onCreated={handleCreated} onCancel={() => setShowCreate(false)} /></div>)}
        <div className="flex-1 overflow-y-auto px-3 py-3">
          {loadError ? (
            <div className="flex flex-col items-center gap-2 py-12 text-center" role="alert">
              <AlertCircle size={24} className="text-red-400" />
              <p className="text-sm text-red-400">{loadError}</p>
              <button type="button" onClick={() => { setLoadError(null); loadLists(); }} className="text-xs text-accent transition-opacity hover:opacity-80">Retry</button>
            </div>
          ) : loading ? (<p className="text-sm text-shell-text-tertiary">Loading...</p>) : lists.length === 0 ? (
            <div className="flex flex-col items-center gap-2 py-16 text-center">
              <Icon size={28} className="text-shell-text-tertiary" />
              <p className="text-sm text-shell-text-secondary">{EMPTY_DOCS}</p>
              <button type="button" onClick={() => setShowCreate(true)} className="text-sm text-accent transition-opacity hover:opacity-80">Create one</button>
            </div>
          ) : (
            <ul className="flex flex-col gap-2" aria-label={APP_NAME}>
              {lists.map((list) => (<TodoListItem key={list.id} list={list} selected={selectedId === list.id} onClick={() => setSelectedId(list.id)} />))}
            </ul>
          )}
        </div>
      </div>
      <div className={["flex-1 overflow-hidden", selectedId ? "flex flex-col" : "hidden md:flex md:flex-col"].join(" ")}>
        {selectedId ? (<TodoDetailPane key={selectedId} listId={selectedId} onBack={() => setSelectedId(null)} />) : (
          <div className="flex h-full flex-col items-center justify-center gap-2 text-center">
            <Icon size={32} className="text-shell-text-tertiary" />
            <p className="text-sm text-shell-text-secondary">{SELECT_PROMPT}</p>
          </div>
        )}
      </div>
    </div>
  );
}
