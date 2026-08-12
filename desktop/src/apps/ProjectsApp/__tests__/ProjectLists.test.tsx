import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, act, fireEvent, waitFor } from "@testing-library/react";
import type { Project } from "@/lib/projects";
import { ProjectLists } from "../ProjectLists";

const fakeProject: Project = {
  id: "p1",
  slug: "p1",
  name: "P1",
  description: "",
  status: "active",
  created_by: "u1",
  created_at: 0,
  updated_at: 0,
};

function ok(data: unknown) {
  return { ok: true, status: 200, json: async () => data };
}

describe("ProjectLists", () => {
  let fetchMock: ReturnType<typeof vi.fn>;
  let listsData: { id: string; project_id: string; title: string; description: string; status: string; created_by: string; created_at: number; updated_at: number }[];
  let entriesData: { id: string; list_id: string; project_id: string; text: string; original_text: string; category: string | null; status: string; done: number; author_kind: string; author_id: string; edited_by: string | null; position: number; created_at: number; updated_at: number }[];

  beforeEach(() => {
    listsData = [
      { id: "lst-1", project_id: "p1", title: "Shopping", description: "", status: "active", created_by: "u1", created_at: 0, updated_at: 0 },
    ];
    entriesData = [
      { id: "ent-1", list_id: "lst-1", project_id: "p1", text: "Milk", original_text: "Milk", category: "groceries", status: "new", done: 0, author_kind: "user", author_id: "u1", edited_by: null, position: 0, created_at: 0, updated_at: 0 },
      { id: "ent-2", list_id: "lst-1", project_id: "p1", text: "Bread", original_text: "Whole grain bread", category: null, status: "actioned", done: 1, author_kind: "user", author_id: "u1", edited_by: "u1", position: 1, created_at: 0, updated_at: 0 },
      { id: "ent-3", list_id: "lst-1", project_id: "p1", text: "Call plumber", original_text: "Call plumber", category: null, status: "discuss", done: 0, author_kind: "user", author_id: "u1", edited_by: null, position: 2, created_at: 0, updated_at: 0 },
      { id: "ent-4", list_id: "lst-1", project_id: "p1", text: "Review PR", original_text: "Review PR", category: null, status: "seen", done: 0, author_kind: "user", author_id: "u1", edited_by: null, position: 3, created_at: 0, updated_at: 0 },
    ];

    fetchMock = vi.fn((url: string, init?: RequestInit) => {
      if (url === "/api/projects/p1/lists") {
        if (init?.method === "POST") {
          // The mock has to behave like the server: a created list is in the
          // NEXT list response. It used to return a fixed array, so a test
          // could not tell a refreshed rail from a stale one.
          const created = { id: "lst-new", project_id: "p1", title: "New list", description: "", status: "active", created_by: "u1", created_at: 0, updated_at: 0 };
          listsData.push(created);
          return Promise.resolve(ok(created));
        }
        return Promise.resolve(ok({ items: [...listsData] }));
      }
      // A freshly created list serves an empty entry set, like the real route.
      if (url === "/api/projects/p1/lists/lst-new/entries") {
        return Promise.resolve(ok({ items: [] }));
      }
      if (url === "/api/projects/p1/lists/lst-1/entries") {
        if (init?.method === "POST") {
          const newEntry = { id: "ent-new", list_id: "lst-1", project_id: "p1", text: "new entry", original_text: "new entry", category: null as string | null, status: "new" as string, done: 0 as number, author_kind: "user" as string, author_id: "u1" as string, edited_by: null as string | null, position: entriesData.length as number, created_at: 0 as number, updated_at: 0 as number };
          entriesData.push(newEntry);
          return Promise.resolve(ok(newEntry));
        }
        return Promise.resolve(ok({ items: [...entriesData] }));
      }
      if (url.startsWith("/api/projects/p1/lists/lst-1/entries/") && init?.method === "PATCH") {
        const entryId = url.split("/").pop()!;
        const entry = entriesData.find((e) => e.id === entryId);
        if (!entry) return Promise.resolve(ok({}));
        const patch = JSON.parse(init.body as string);
        Object.assign(entry, patch);
        return Promise.resolve(ok({ ...entry }));
      }
      if (url === "/api/projects/p1/lists/lst-1" && init?.method === "DELETE") {
        listsData = listsData.filter((l) => l.id !== "lst-1");
        return Promise.resolve(ok({ ok: true }));
      }
      if (url.startsWith("/api/projects/p1/lists/lst-1/entries/") && init?.method === "DELETE") {
        const entryId = url.split("/").pop()!;
        entriesData = entriesData.filter((e) => e.id !== entryId);
        return Promise.resolve(ok({ ok: true }));
      }
      return Promise.resolve(ok({}));
    });
    vi.stubGlobal("fetch", fetchMock);
  });

  it("renders lists rail and entries for the first list", async () => {
    await act(async () => {
      render(<ProjectLists project={fakeProject} />);
    });
    const shoppingItems = screen.getAllByText("Shopping");
    expect(shoppingItems.length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText("Milk")).toBeInTheDocument();
    expect(screen.getByText("Bread")).toBeInTheDocument();
  });

  it("renders status pills with correct colors", async () => {
    await act(async () => {
      render(<ProjectLists project={fakeProject} />);
    });
    const newPills = screen.getAllByText("new");
    expect(newPills.length).toBeGreaterThanOrEqual(1);
    expect(newPills[0]!.className).toContain("bg-blue-500/15");
    const actionedPills = screen.getAllByText("actioned");
    expect(actionedPills.length).toBeGreaterThanOrEqual(1);
    const discussPills = screen.getAllByText("discuss");
    expect(discussPills.length).toBeGreaterThanOrEqual(1);
    const seenPills = screen.getAllByText("seen");
    expect(seenPills.length).toBeGreaterThanOrEqual(1);
  });

  it("shows the original text indicator when text is tidied", async () => {
    await act(async () => {
      render(<ProjectLists project={fakeProject} />);
    });
    expect(screen.getByText("original")).toBeInTheDocument();
  });

  it("quick-add creates a new entry on Enter", async () => {
    await act(async () => {
      render(<ProjectLists project={fakeProject} />);
    });
    const input = screen.getByLabelText(/quick add/i);
    fireEvent.change(input, { target: { value: "new entry" } });
    await act(async () => {
      fireEvent.submit(input.closest("form")!);
    });
    await waitFor(() => expect(screen.getByText("new entry")).toBeInTheDocument());
  });

  it("done toggle marks entry as done and strikes through text", async () => {
    await act(async () => {
      render(<ProjectLists project={fakeProject} />);
    });
    const checkbox = screen.getByLabelText(/mark milk as done/i);
    fireEvent.click(checkbox);
    await waitFor(() => expect(screen.getByText("Milk").className).toContain("line-through"));
  });

  // The rail is what the user reads to know their list exists. Both of these
  // failed before the fix: refreshLists() fetched and threw the result away
  // (only the mount effect ever called setLists), so a created list never
  // appeared and a deleted one never left.
  it("a created list appears in the rail", async () => {
    vi.stubGlobal("prompt", vi.fn(() => "New list"));
    await act(async () => {
      render(<ProjectLists project={fakeProject} />);
    });
    await act(async () => {
      fireEvent.click(screen.getByLabelText("Create new list"));
    });
    await waitFor(() => expect(screen.getAllByText("New list").length).toBeGreaterThanOrEqual(1));
  });

  it("a deleted list disappears from the rail", async () => {
    vi.stubGlobal("confirm", vi.fn(() => true));
    await act(async () => {
      render(<ProjectLists project={fakeProject} />);
    });
    expect(screen.getAllByText("Shopping").length).toBeGreaterThanOrEqual(1);
    await act(async () => {
      fireEvent.click(screen.getByLabelText("Delete Shopping"));
    });
    await waitFor(() => expect(screen.queryByText("Shopping")).not.toBeInTheDocument());
  });
});
