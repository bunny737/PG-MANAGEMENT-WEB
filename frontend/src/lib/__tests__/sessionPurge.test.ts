import { afterEach, describe, expect, test, vi } from "vitest";
import { awaitPendingPurge, registerSessionCleanup, runSessionCleanups } from "../sessionPurge";

describe("sessionPurge", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  test("runs every registered step even when one rejects", async () => {
    const consoleError = vi.spyOn(console, "error").mockImplementation(() => {});
    const first = vi.fn(() => Promise.reject(new Error("boom")));
    const second = vi.fn(() => undefined);
    registerSessionCleanup(first);
    const unregisterSecond = registerSessionCleanup(second);

    await runSessionCleanups();

    expect(first).toHaveBeenCalledTimes(1);
    expect(second).toHaveBeenCalledTimes(1);
    expect(consoleError).toHaveBeenCalled();
    unregisterSecond();
  });

  test("concurrent calls share one in-flight promise", async () => {
    let resolveStep: () => void = () => {};
    const slow = vi.fn(
      () =>
        new Promise<void>((resolve) => {
          resolveStep = resolve;
        })
    );
    const unregister = registerSessionCleanup(slow);

    const first = runSessionCleanups();
    const second = runSessionCleanups();
    expect(first).toBe(second);

    resolveStep();
    await first;
    expect(slow).toHaveBeenCalledTimes(1); // not called again by the second call
    unregister();
  });

  test("awaitPendingPurge resolves only after the purge finishes", async () => {
    let resolveStep: () => void = () => {};
    const slow = vi.fn(
      () =>
        new Promise<void>((resolve) => {
          resolveStep = resolve;
        })
    );
    const unregister = registerSessionCleanup(slow);

    const purge = runSessionCleanups();
    let awaited = false;
    const waiter = awaitPendingPurge().then(() => {
      awaited = true;
    });

    // Still pending: nothing has resolved yet.
    await Promise.resolve();
    expect(awaited).toBe(false);

    resolveStep();
    await purge;
    await waiter;
    expect(awaited).toBe(true);
    unregister();
  });

  test("awaitPendingPurge resolves immediately when nothing is running", async () => {
    await expect(awaitPendingPurge()).resolves.toBeUndefined();
  });
});
