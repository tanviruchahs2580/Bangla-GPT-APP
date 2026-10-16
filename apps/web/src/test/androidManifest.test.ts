/**
 * Android release-safety guards (SEC-005, BUG-007).
 *
 * The APK ships the SPA in a WebView whose localStorage holds the session
 * JWT and, during an admin support session, a full-power admin JWT. These
 * assertions are about the native manifest, which no other test touches --
 * the vitest suite runs in jsdom and never parses `AndroidManifest.xml`.
 *
 * SEC-005: `android:allowBackup="true"` let Android Auto Backup copy the
 *   WebView's localStorage off the device in the clear.
 * BUG-007: the manifest declared only INTERNET, so the WebView's
 *   `SpeechRecognition` (src/lib/voice.ts) failed the audio capture and the
 *   Bengali dictation button silently did nothing in the installed app.
 */
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

// vitest runs with cwd = the package root (apps/web), which is where
// package.json and the vite config live. import.meta.url is not a file: URL
// under the jsdom environment, so it cannot be used to locate the manifest.
const ANDROID = join(process.cwd(), "android", "app", "src", "main");

function manifest(): string {
  return readFileSync(join(ANDROID, "AndroidManifest.xml"), "utf8");
}

describe("AndroidManifest security posture", () => {
  it("disables cloud backup and device transfer", () => {
    const xml = manifest();
    expect(xml).toMatch(/android:allowBackup="false"/);
    // API 31+ transport rules: without these, a re-enable of allowBackup
    // would silently start shipping WebView storage again.
    expect(xml).toMatch(
      /android:dataExtractionRules="@xml\/data_extraction_rules"/,
    );
  });

  it("excludes every storage domain from backup and transfer", () => {
    const rules = readFileSync(
      join(ANDROID, "res", "xml", "data_extraction_rules.xml"),
      "utf8",
    );
    // Both blocks must be present, and neither may omit a domain.
    for (const block of ["cloud-backup", "device-transfer"]) {
      expect(rules).toContain(`<${block}`);
    }
    for (const domain of [
      "root",
      "file",
      "database",
      "sharedpref",
      "external",
    ]) {
      const exclusions = rules.match(
        new RegExp(`<exclude domain="${domain}"\\s*/>`, "g"),
      );
      expect(
        exclusions,
        `domain ${domain} must be excluded in both blocks`,
      ).toHaveLength(2);
    }
  });

  it("declares RECORD_AUDIO so dictation can actually capture", () => {
    const xml = manifest();
    expect(xml).toContain("android.permission.RECORD_AUDIO");
    // The recogniser is optional: the app must still install on devices with
    // no microphone, where typing is the fallback (see lib/voice.ts).
    expect(xml).toMatch(
      /<uses-feature android:name="android\.hardware\.microphone" android:required="false"/,
    );
  });

  it("keeps the file provider unexported", () => {
    expect(manifest()).toMatch(/android:exported="false"/);
  });
});
