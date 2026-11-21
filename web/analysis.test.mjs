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
