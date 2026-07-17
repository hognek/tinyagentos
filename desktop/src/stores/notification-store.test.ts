import { beforeEach, describe, expect, it, vi } from "vitest";
import { useNotificationStore, type Notification } from "./notification-store";

// Mock the backend archive call so the store's fire-and-forget fetch doesn't
// leak into the test environment (the store calls it optimistically and best-
// effort, never awaiting; here we verify the calls are made for srv-* ids).
vi.mock("@/lib/server-notifications", () => ({
  archiveServerNotification: vi.fn(),
}));

function srv(id: number, ts: number, read = false): Notification {
  return {
    id: `srv-${id}`,
    source: "system",
    title: `t${id}`,
    body: `b${id}`,
    level: "info",
    read,
    timestamp: ts,
  };
}

beforeEach(() => {
  useNotificationStore.setState({ notifications: [], centreOpen: false });
});

describe("mergeServerNotifications", () => {
  it("upserts server items newest-first without duplicates across two polls", () => {
    const store = useNotificationStore.getState();

    store.mergeServerNotifications([srv(1, 100), srv(2, 200)]);
    let ids = useNotificationStore.getState().notifications.map((n) => n.id);
    expect(ids).toEqual(["srv-2", "srv-1"]);

    // Second poll returns the same two plus a newer one. No dupes.
    store.mergeServerNotifications([srv(1, 100), srv(2, 200), srv(3, 300)]);
    ids = useNotificationStore.getState().notifications.map((n) => n.id);
    expect(ids).toEqual(["srv-3", "srv-2", "srv-1"]);
    expect(new Set(ids).size).toBe(ids.length);
  });

  it("preserves a server item marked read locally even if the poll says unread", () => {
    const store = useNotificationStore.getState();
    store.mergeServerNotifications([srv(1, 100, false)]);

    // User reads it locally (optimistic), backend write may not have landed.
    store.markRead("srv-1");
    expect(useNotificationStore.getState().notifications[0].read).toBe(true);

    // Next poll still reports it unread; local read must survive.
    store.mergeServerNotifications([srv(1, 100, false)]);
    expect(useNotificationStore.getState().notifications[0].read).toBe(true);
  });

  it("keeps client-origin (notif-) items untouched", () => {
    const store = useNotificationStore.getState();
    const clientId = store.addNotification({ source: "system", title: "welcome", body: "hi", level: "info" });

    store.mergeServerNotifications([srv(1, 50)]);

    const ids = useNotificationStore.getState().notifications.map((n) => n.id);
    expect(ids).toContain(clientId);
    expect(ids).toContain("srv-1");
  });

  it("replaces stale server items with the fresh list (removed ones drop out)", () => {
    const store = useNotificationStore.getState();
    store.mergeServerNotifications([srv(1, 100), srv(2, 200)]);

    // A later poll no longer includes srv-2.
    store.mergeServerNotifications([srv(1, 100)]);
    const ids = useNotificationStore.getState().notifications.map((n) => n.id);
    expect(ids).toEqual(["srv-1"]);
  });

  it("does not resurrect a dismissed server item on the next poll", () => {
    const store = useNotificationStore.getState();
    // Unique id: dismissedServerIds is module-scoped and persists across tests.
    store.mergeServerNotifications([srv(901, 100)]);
    expect(useNotificationStore.getState().notifications.map((n) => n.id)).toContain("srv-901");

    store.dismiss("srv-901");
    // Dismissed item is archived, not removed from the store.
    const all = useNotificationStore.getState().notifications;
    const dismissed = all.find((n) => n.id === "srv-901");
    expect(dismissed).toBeDefined();
    expect(dismissed?.archived).toBe(true);

    // Backend still reports it (no server-side dismiss); it must stay hidden from active.
    store.mergeServerNotifications([srv(901, 100)]);
    const afterPoll = useNotificationStore.getState().notifications;
    const stillArchived = afterPoll.find((n) => n.id === "srv-901");
    expect(stillArchived?.archived).toBe(true);
  });

  it("caps the merged list at 100 items", () => {
    const store = useNotificationStore.getState();
    const many = Array.from({ length: 150 }, (_, i) => srv(i, i));
    store.mergeServerNotifications(many);
    expect(useNotificationStore.getState().notifications).toHaveLength(100);
  });
});

describe("dismiss archives instead of removing", () => {
  it("sets archived flag on dismiss", () => {
    const store = useNotificationStore.getState();
    const id = store.addNotification({ source: "system", title: "test", body: "body", level: "info" });

    store.dismiss(id);

    const all = useNotificationStore.getState().notifications;
    expect(all).toHaveLength(1);
    expect(all[0].archived).toBe(true);
    expect(all[0].id).toBe(id);
  });

  it("archiveRead archives AND marks read (resolved item lands in History)", () => {
    const store = useNotificationStore.getState();
    const id = store.addNotification({ source: "auth_requests", title: "Access request", body: "owl", level: "info" });

    store.archiveRead(id);

    const all = useNotificationStore.getState().notifications;
    const item = all.find((n) => n.id === id);
    expect(item?.archived).toBe(true);
    expect(item?.read).toBe(true);
    // It leaves the active inbox...
    expect(all.filter((n) => !n.archived)).toHaveLength(0);
    // ...and shows up in the History/archive view.
    expect(store.archivedNotifications().map((n) => n.id)).toContain(id);
  });

  it("excludes archived items from active notifications", () => {
    const store = useNotificationStore.getState();
    const id1 = store.addNotification({ source: "system", title: "keep", body: "active", level: "info" });
    const id2 = store.addNotification({ source: "system", title: "archive", body: "gone", level: "info" });

    store.dismiss(id2);

    const active = useNotificationStore.getState().notifications.filter((n) => !n.archived);
    expect(active).toHaveLength(1);
    expect(active[0].id).toBe(id1);
  });

  it("archivedNotifications returns archived items newest-first", () => {
    const store = useNotificationStore.getState();
    store.addNotification({ source: "system", title: "old", body: "b", level: "info" });
    const id2 = store.addNotification({ source: "system", title: "new", body: "b", level: "info" });

    store.dismiss(id2);

    const archived = store.archivedNotifications();
    expect(archived).toHaveLength(1);
    expect(archived[0].id).toBe(id2);
    expect(archived[0].archived).toBe(true);
  });

  it("clearAll archives all notifications", () => {
    const store = useNotificationStore.getState();
    store.addNotification({ source: "system", title: "a", body: "b", level: "info" });
    store.addNotification({ source: "system", title: "c", body: "d", level: "info" });

    store.clearAll();

    const all = useNotificationStore.getState().notifications;
    expect(all).toHaveLength(2);
    expect(all.every((n) => n.archived)).toBe(true);
  });

  it("clearArchived removes archived items permanently", () => {
    const store = useNotificationStore.getState();
    const id = store.addNotification({ source: "system", title: "test", body: "b", level: "info" });
    store.dismiss(id);

    store.clearArchived();

    expect(useNotificationStore.getState().notifications).toHaveLength(0);
  });

  it("unreadCount excludes archived items", () => {
    const store = useNotificationStore.getState();
    const id1 = store.addNotification({ source: "system", title: "unread", body: "b", level: "info" });
    store.addNotification({ source: "system", title: "to-archive", body: "b", level: "info" });

    expect(store.unreadCount()).toBe(2);

    store.dismiss(id1);
    expect(store.unreadCount()).toBe(1);
  });
});

describe("archive backend persistence", () => {
  let archiveMock: ReturnType<typeof vi.fn>;

  beforeEach(async () => {
    const mod = await import("@/lib/server-notifications");
    archiveMock = mod.archiveServerNotification as ReturnType<typeof vi.fn>;
    archiveMock.mockClear();
    useNotificationStore.setState({ notifications: [], centreOpen: false });
  });

  it("calls archiveServerNotification for srv-* ids on dismiss", () => {
    const store = useNotificationStore.getState();
    store.mergeServerNotifications([srv(1, 100)]);

    store.dismiss("srv-1");

    expect(archiveMock).toHaveBeenCalledTimes(1);
    expect(archiveMock).toHaveBeenCalledWith("srv-1");
  });

  it("calls archiveServerNotification for srv-* ids on archiveRead", () => {
    const store = useNotificationStore.getState();
    store.mergeServerNotifications([srv(1, 100)]);

    store.archiveRead("srv-1");

    expect(archiveMock).toHaveBeenCalledTimes(1);
    expect(archiveMock).toHaveBeenCalledWith("srv-1");
  });

  it("calls archiveServerNotification for each srv-* id on clearAll", () => {
    const store = useNotificationStore.getState();
    // Unique ids to avoid leaking into module-scoped dismissedServerIds from
    // earlier tests in this file.
    store.mergeServerNotifications([srv(8001, 100), srv(8002, 200)]);
    store.addNotification({ source: "system", title: "local", body: "b", level: "info" });

    store.clearAll();

    expect(archiveMock).toHaveBeenCalledTimes(2);
    expect(archiveMock).toHaveBeenCalledWith("srv-8001");
    expect(archiveMock).toHaveBeenCalledWith("srv-8002");
  });

  it("does NOT call archiveServerNotification for client-origin (notif-N) ids", () => {
    const store = useNotificationStore.getState();
    const id = store.addNotification({ source: "system", title: "local", body: "b", level: "info" });

    store.dismiss(id);

    expect(archiveMock).not.toHaveBeenCalled();
  });
});
