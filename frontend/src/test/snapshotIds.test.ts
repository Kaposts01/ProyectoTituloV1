import { describe, expect, it } from "vitest";
import { normalizeReactIds } from "./snapshotIds";

describe("stable snapshot IDs", () => {
  it("normalizes run-dependent IDs without breaking accessibility references", () => {
    const html = '<button aria-controls="_r_26_"></button><div id="_r_26_" aria-describedby="_r_27_"></div><p id="_r_27_"></p>';
    expect(normalizeReactIds(html)).toBe('<button aria-controls="react-id-1"></button><div id="react-id-1" aria-describedby="react-id-2"></div><p id="react-id-2"></p>');
    expect(normalizeReactIds(html.replaceAll("_r_26_", "_r_1_").replaceAll("_r_27_", "_r_2_"))).toBe(normalizeReactIds(html));
  });
  it("still exposes incorrect reference relationships", () => {
    expect(normalizeReactIds('<div id="_r_1_" aria-controls="_r_1_"></div>')).not.toBe(normalizeReactIds('<div id="_r_1_" aria-controls="_r_2_"></div>'));
  });
  it("preserves ordinary identifiers", () => {
    expect(normalizeReactIds('<div id="client-42"></div>')).toBe('<div id="client-42"></div>');
  });
});
