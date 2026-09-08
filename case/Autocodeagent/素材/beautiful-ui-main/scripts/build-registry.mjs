// Generates a self-hosted shadcn registry into public/r/*.json.
// Consume with:  npx shadcn add https://www.beautifului.dev/r/<name>.json
import fs from "node:fs";
import path from "node:path";

const ROOT = process.cwd();
const OUT = path.join(ROOT, "public", "r");
const BASE = "https://www.beautifului.dev/r";
const read = (p) => fs.readFileSync(path.join(ROOT, p), "utf8");

/* ── split globals.css: generic foundation vs. the two big per-component blocks ── */
const globals = read("app/globals.css").split("\n");
const slice = (a, b) => globals.slice(a, b).join("\n"); // 0-indexed, [a,b)
const sidebarCss = slice(423, 505); // lines 424–505
const recordsCss = slice(505, 1331); // lines 506–1331 (~55% of the old file)
const foundationCss = [...globals.slice(0, 423), ...globals.slice(1331)].join("\n");

const IMPORT_NOTE = (file) =>
  ` Then add \`@import "./${file}";\` to your app's globals.css.`;

/* ── the shared building blocks (no gallery card of their own) ── */
const INTERNAL = {
  button: { title: "Button", path: "components/atoms/Button.tsx", type: "registry:ui" },
  "glide-menu": { title: "GlideMenu", path: "components/primitives/GlideMenu.tsx", type: "registry:ui" },
  "entity-chip": { title: "EntityChip", path: "components/atoms/EntityChip.tsx", type: "registry:ui" },
  "value-pill": { title: "ValuePill", path: "components/atoms/ValuePill.tsx", type: "registry:ui" },
  shimmer: { title: "Shimmer", path: "components/atoms/Shimmer.tsx", type: "registry:ui" },
  "stream-text": { title: "StreamText", path: "components/atoms/StreamText.tsx", type: "registry:ui" },
};

/* ── the 20 gallery primitives (title, file, internal deps, npm deps, extra css) ── */
const PRIMITIVES = [
  ["loading-state", "Loading State", "LoadingState.tsx", [], []],
  ["thinking-state", "Thinking", "ThinkingState.tsx", [], []],
  ["streaming-text", "Streaming Text", "StreamingText.tsx", [], []],
  ["approval-card", "Approval Card", "ApprovalCard.tsx", ["button", "glide-menu"], []],
  ["tool-chips", "Tool Chips", "ToolChips.tsx", [], []],
  ["task-rows", "Task Rows", "TaskRows.tsx", [], []],
  ["chat-composer", "Chat", "ChatComposer.tsx", [], ["posthog-js"]],
  ["prompt-bar", "Prompt Bar", "PromptBar.tsx", [], ["glimm"]],
  ["recommendation-card", "Recommendation Card", "RecommendationCard.tsx", ["button", "entity-chip", "value-pill"], []],
  ["context-cards", "Context Cards", "ContextCards.tsx", [], []],
  ["diff-table", "Diff Table", "DiffTable.tsx", ["button"], []],
  ["records-table", "Records Table", "RecordsTable.tsx", ["glide-menu"], [], recordsCss],
  ["filter-table", "Filter Table", "FilterTable.tsx", [], []],
  ["sidebar-nav", "Sidebar Nav", "SidebarNav.tsx", ["glide-menu"], ["@central-icons-react/round-outlined-radius-2-stroke-2"], sidebarCss],
  ["search", "Search", "SearchList.tsx", ["glide-menu"], []],
  ["flowchart", "Flowchart", "Flowchart.tsx", [], []],
  ["insight-cards", "Insight Cards", "InsightCards.tsx", [], ["liveline"]],
  ["code-block", "Code Block", "CodeBlock.tsx", [], []],
  ["fine-tune-card", "Fine-tune Card", "FineTuneCard.tsx", ["glide-menu"], []],
  ["selection-actions", "Selection Actions", "SelectionActions.tsx", ["shimmer", "stream-text"], ["iconoir-react"]],
];

const CAPTION = Object.fromEntries(
  read("lib/meta.ts")
    .split("{")
    .flatMap((b) => {
      const id = b.match(/id: "([^"]+)"/)?.[1];
      const cap = b.match(/caption: "([^"]+)"/)?.[1];
      return id && cap ? [[id, cap]] : [];
    })
);

const SCHEMA_ITEM = "https://ui.shadcn.com/schema/registry-item.json";
const foundationDep = `${BASE}/foundation.json`;

fs.rmSync(OUT, { recursive: true, force: true });
fs.mkdirSync(OUT, { recursive: true });

const write = (name, json) =>
  fs.writeFileSync(path.join(OUT, `${name}.json`), JSON.stringify(json, null, 2) + "\n");

/* foundation — tokens, base, primitive utilities, shared keyframes (generic) */
write("foundation", {
  $schema: SCHEMA_ITEM,
  name: "foundation",
  type: "registry:style",
  title: "Beautiful UI foundation",
  description:
    "Design tokens (:root/.dark), the @theme mapping, base rules, the primitive-* spacing utilities, and shared keyframes every component needs." +
    IMPORT_NOTE("beautifui/foundation.css"),
  files: [
    {
      path: "app/beautifui/foundation.css",
      content: foundationCss,
      type: "registry:file",
      target: "app/beautifui/foundation.css",
    },
  ],
});

/* internal building blocks */
for (const [name, meta] of Object.entries(INTERNAL)) {
  write(name, {
    $schema: SCHEMA_ITEM,
    name,
    type: meta.type,
    title: meta.title,
    description: `Shared building block used by other Beautiful UI components.`,
    registryDependencies: [foundationDep],
    files: [
      { path: meta.path, content: read(meta.path), type: meta.type, target: meta.path },
    ],
  });
}

/* gallery primitives */
const indexItems = [];
for (const [name, title, file, deps, npm, extraCss] of PRIMITIVES) {
  const src = `components/primitives/${file}`;
  const files = [
    { path: src, content: read(src), type: "registry:component", target: src },
  ];
  let description = CAPTION[name] ?? title;
  if (extraCss) {
    const cssTarget = `app/beautifui/${name}.css`;
    files.push({ path: cssTarget, content: extraCss, type: "registry:file", target: cssTarget });
    description += IMPORT_NOTE(`beautifui/${name}.css`);
  }
  const registryDependencies = [foundationDep, ...deps.map((d) => `${BASE}/${d}.json`)];
  const item = {
    $schema: SCHEMA_ITEM,
    name,
    type: "registry:component",
    title,
    description,
    ...(npm.length ? { dependencies: npm } : {}),
    registryDependencies,
    files,
  };
  write(name, item);
  indexItems.push({ name, type: "registry:component", title, description });
}

/* the registry index */
write("registry", {
  $schema: "https://ui.shadcn.com/schema/registry.json",
  name: "beautifui",
  homepage: "https://www.beautifului.dev",
  items: [
    { name: "foundation", type: "registry:style", title: "Beautiful UI foundation" },
    ...Object.entries(INTERNAL).map(([name, m]) => ({ name, type: m.type, title: m.title })),
    ...indexItems.map(({ name, type, title }) => ({ name, type, title })),
  ],
});

console.log(`Wrote ${fs.readdirSync(OUT).length} registry files to public/r/`);
