import { beforeEach, describe, expect, it, vi } from "vitest";
import {
  getLowData,
  initLowData,
  onLowDataChange,
  setLowData,
  toggleLowData,
} from "../lib/lowData";

beforeEach(() => {
  localStorage.clear();
  delete document.documentElement.dataset.lowdata;
});

describe("lowData", () => {
  it("defaults to off", () => {
    expect(getLowData()).toBe(false);
    expect(document.documentElement.dataset.lowdata).toBeUndefined();
  });

  it("persists the flag and marks <html> when on", () => {
    setLowData(true);
    expect(localStorage.getItem("bgpt-lowdata")).toBe("1");
    expect(getLowData()).toBe(true);
    expect(document.documentElement.dataset.lowdata).toBe("1");
    setLowData(false);
    expect(getLowData()).toBe(false);
    expect(document.documentElement.dataset.lowdata).toBeUndefined();
  });

  it("toggle returns and applies the new state", () => {
    expect(toggleLowData()).toBe(true);
    expect(toggleLowData()).toBe(false);
  });

  it("notifies listeners until unsubscribed", () => {
    const fn = vi.fn();
    const off = onLowDataChange(fn);
    setLowData(true);
    expect(fn).toHaveBeenCalledTimes(1);
    off();
    setLowData(false);
    expect(fn).toHaveBeenCalledTimes(1);
  });

  it("initLowData restores persistence across reloads", () => {
    localStorage.setItem("bgpt-lowdata", "1");
    initLowData();
    expect(document.documentElement.dataset.lowdata).toBe("1");
  });
});
