import assert from "node:assert/strict";
import { after, before, test } from "node:test";
import React from "react";
import renderer from "react-test-renderer";
import { createServer } from "vite";

let vite;
let AnalysisView;

before(async () => {
  vite = await createServer({ server: { middlewareMode: true, hmr: false }, appType: "custom" });
  ({ AnalysisView } = await vite.ssrLoadModule("/src/AnalysisView.tsx"));
});
after(async () => vite?.close());

test("formularz używa limitu z API i liczy znaki po usunięciu skrajnych spacji", () => {
  const view = renderer.create(React.createElement(AnalysisView, { minChars: 30 }));
  try {
    const textarea = view.root.findByType("textarea");
    const submit = () => view.root.findAllByType("button").find(b => b.children.includes("Analizuj inwestycję"));
    const enter = text => renderer.act(() => textarea.props.onChange({ target: { value: text } }));
    enter(" " + "🦦".repeat(29) + " ");
    assert.equal(submit().props.disabled, true);
    enter("ą".repeat(30));
    assert.equal(submit().props.disabled, false);
    view.update(React.createElement(AnalysisView, { minChars: 31 }));
    assert.equal(submit().props.disabled, true);
  } finally {
    view.unmount();
  }
});

test("flaga ryzyka pokazuje cytat z opisu", async (t) => {
  const quote = "Na trasie występują kolizje z istniejącą siecią.";
  const response = {
    input_text: quote,
    features: { conflicts: {}, scale: {} },
    comparison: {},
    similar: [],
    missing_inputs: [],
    flags: [{
      code: "R03", name: "Kolizje", strength: "średnia",
      from_description: [{ value: "kolizje i istniejące uzbrojenie", source: quote }],
    }],
  };
  t.mock.method(globalThis, "fetch", async () => ({ ok: true, json: async () => response }));
  const view = renderer.create(React.createElement(AnalysisView, { minChars: 30 }));
  try {
    const submit = view.root.findAllByType("button").find(b => b.children.includes("Analizuj inwestycję"));
    await renderer.act(() => submit.props.onClick());
    assert.deepEqual(view.root.findByType("q").children, [quote]);
    assert.equal(JSON.stringify(view.toJSON()).includes("[object Object]"), false);
  } finally {
    view.unmount();
  }
});
