/**
 * PWA-02: the page-side update lifecycle. The service worker itself is tested
 * in serviceWorker.test.ts; this file drives the registration object the
 * browser would hand back, so the waiting/accept/reload contract is pinned.
 *
 * Each test imports a fresh module copy (the module keeps process-wide state:
 * the registration, the waiting flag and the accepted flag), the same pattern
 * installPrompt.test.ts uses.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

type StateChange = () => void;

class FakeWorker {
  state = "installing";
  postMessage = vi.fn();
  private listeners = new Set<StateChange>();
  addEventListener(_type: string, fn: StateChange) {
    this.listeners.add(fn);
  }
  to(state: string) {
    this.state = state;
    this.listeners.forEach((fn) => fn());
  }
}

class FakeRegistration {
  waiting: FakeWorker | null = null;
  installing: FakeWorker | null = null;
  private listeners = new Set<StateChange>();
  addEventListener(type: string, fn: StateChange) {
    if (type === "updatefound") this.listeners.add(fn);
  }
  fireUpdateFound() {
    this.listeners.forEach((fn) => fn());
  }
}

function installFakeServiceWorker() {
  const registration = new FakeRegistration();
  const swListeners = new Set<StateChange>();
  const serviceWorker = {
    controller: {} as unknown,
    register: vi.fn(async () => registration),
    addEventListener: (type: string, fn: StateChange) => {
      if (type === "controllerchange") swListeners.add(fn);
    },
  };
  Object.defineProperty(navigator, "serviceWorker", {
    configurable: true,
    value: serviceWorker,
  });
  return {
    registration,
    fireControllerChange: () => swListeners.forEach((fn) => fn()),
    setNoController: () => {
      serviceWorker.controller = null;
    },
  };
}

async function freshModule() {
  vi.resetModules();
  return import("../lib/serviceWorkerUpdate");
}

let reload: ReturnType<typeof vi.fn>;

beforeEach(() => {
  reload = vi.fn();
  Object.defineProperty(window, "location", {
    configurable: true,
    value: { ...window.location, reload },
  });
});

afterEach(() => {
  // Drop the fake service worker so a later test file sees the real absence.
  Object.defineProperty(navigator, "serviceWorker", {
    configurable: true,
    value: undefined,
  });
});

describe("serviceWorkerUpdate", () => {
  it("reports no waiting update before anything installs", async () => {
    installFakeServiceWorker();
    const mod = await freshModule();
    expect(mod.updateWaiting()).toBe(false);
  });

  it("an update over a live session becomes a waiting update", async () => {
    const fake = installFakeServiceWorker();
    const mod = await freshModule();
    const seen: boolean[] = [];
    mod.subscribeUpdate((w) => seen.push(w));

    await mod.registerServiceWorker();
    fake.registration.installing = new FakeWorker();
    fake.registration.fireUpdateFound();
    fake.registration.installing.to("installed");

    expect(mod.updateWaiting()).toBe(true);
    expect(seen).toContain(true);
  });

  it("a first install (no controller) is not announced as an update", async () => {
    const fake = installFakeServiceWorker();
    fake.setNoController();
    const mod = await freshModule();
    await mod.registerServiceWorker();
    fake.registration.installing = new FakeWorker();
    fake.registration.fireUpdateFound();
    fake.registration.installing.to("installed");

    expect(mod.updateWaiting()).toBe(false);
  });

  it("accepting the update posts SKIP_WAITING and reloads on controllerchange", async () => {
    const fake = installFakeServiceWorker();
    const mod = await freshModule();
    const waiting = new FakeWorker();
    await mod.registerServiceWorker();
    fake.registration.waiting = waiting;

    mod.applyUpdate();
    expect(waiting.postMessage).toHaveBeenCalledWith({ type: "SKIP_WAITING" });
    // Taking over fires controllerchange; only then does the page reload.
    expect(reload).not.toHaveBeenCalled();
    fake.fireControllerChange();
    expect(reload).toHaveBeenCalledTimes(1);
  });

  it("a controllerchange nobody accepted does not reload the page", async () => {
    const fake = installFakeServiceWorker();
    const mod = await freshModule();
    await mod.registerServiceWorker();
    fake.fireControllerChange();
    expect(reload).not.toHaveBeenCalled();
  });

  it("applying with nothing waiting falls back to a plain reload", async () => {
    installFakeServiceWorker();
    const mod = await freshModule();
    await mod.registerServiceWorker();
    mod.applyUpdate();
    expect(reload).toHaveBeenCalledTimes(1);
  });
});
