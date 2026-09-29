import { RangeSetBuilder } from "@codemirror/state";
import { Decoration, DecorationSet } from "@codemirror/view";

/** A mark-only decoration: it neither changes the document nor calls focus(). */
export const nudgeMark = (from: number, to: number): DecorationSet => {
  const ranges = new RangeSetBuilder<Decoration>();
  if (to > from) ranges.add(from, to, Decoration.mark({ class: "invisible-companion-nudge", attributes: { "aria-label": "Companion nudge available" } }));
  return ranges.finish();
};
