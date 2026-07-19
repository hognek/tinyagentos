import { StickyNote } from "lucide-react";
import { DocsApp, type DocKindConfig } from "./notes-shared-base";

/**
 * Notes-only configuration for the DocsApp component.
 *
 * Notes are free-text documents with rich text, diagram, link, and embed
 * capabilities. They do not show done checkboxes — that affordance belongs
 * to the Todo (list) variant.
 *
 * Data migration note:
 *   Existing docs with kind="note" continue to work without changes.
 *   Docs previously created with kind="list" are handled by TodoApp
 *   (see TodoApp.tsx), which uses the dedicated /api/todo store.
 *   No database migration is required for Notes.
 */

const NOTES_CONFIG: DocKindConfig = {
  kind: "note",
  appName: "Notes",
  icon: StickyNote,
  noun: "note",
  titlePlaceholder: "Note title...",
  addPlaceholder: "Add a note...",
  emptyDocs: "No notes yet.",
  emptyEntries: "Nothing here yet. Add your first note above.",
  selectPrompt: "Select a note to get started.",
  showDone: false,
};

export function NotesApp({ windowId: _windowId }: { windowId: string }) {
  return <DocsApp config={NOTES_CONFIG} />;
}
