# Servo UI concept prompts

Generated with the built-in ImageGen tool. Each concept was produced in a separate generation.

## 01 - Graphite Failure Investigation

```text
Use case: ui-mockup
Asset type: shippable desktop application main workspace, 16:10 landscape screenshot
Primary request: Design the main "Failure Investigation" workspace for Servo - Simulation Environment for Robotic Validation and Optimization, an autonomous CI and simulation product for physical AI.
Scene/backdrop: straight-on full-window desktop software screenshot, no monitor or device frame.
Subject: a dark graphite operator workstation. A narrow left navigation rail and workspace tree; a large central photorealistic driving-simulation viewport showing an autonomous car approaching an urban intersection as a pedestrian emerges from behind a parked van; a compact synchronized event timeline below the viewport; a right-side evidence inspector with causal hypotheses, selected root cause, confidence, and next action; a thin status bar for simulator, cloud, agent, and GPU health.
Style/medium: realistic production UI, precise desktop-native Qt/QML workbench, dense but calm, Swiss information hierarchy, crisp 1px dividers, restrained 4-6px corner radius, compact toolbar, excellent alignment and spacing.
Color palette: charcoal and graphite surfaces, cool gray text, teal selection, safety orange for warnings, red only for the collision marker, green only for verified state. Flat colors, no gradient.
Text (verbatim): "SERVO", "Failure Investigation", "Run 0247", "Occluded Pedestrian", "Detection 0.72 s late", "Causal root cause", "Partial occlusion", "Confidence 91%", "Generate curriculum", "Reality Debt 18.4%".
Constraints: dominant usable viewport; clear selected states; readable concise English only; all charts and telemetry must look functional; strong keyboard-and-mouse desktop affordances; plausible to implement in Qt 6 QML; no logos other than the plain SERVO wordmark; no watermark.
Avoid: concept art, sci-fi HUD, glassmorphism, floating translucent cards, neon purple, decorative glow, excessive pills, oversized rounded cards, huge empty margins, fake AI chat bubbles, mobile layout, illegible microtext, gibberish, lorem ipsum.
```

## 02 - Polar Reality Debt

```text
Use case: ui-mockup
Asset type: shippable desktop application overview, 16:10 landscape screenshot
Primary request: Design Servo's "Reality Debt" home workspace, the evidence-backed capability map for an autonomous vehicle or robot policy.
Scene/backdrop: straight-on full-window desktop software screenshot, no monitor or device frame.
Subject: a light scientific operations dashboard. A compact top command bar with modes Mission, Diagnose, Train, Examine, Deploy; a slim left project navigator; a large central capability matrix with clearly aligned capability rows, confidence bars, last-run sparklines, and status labels; a right evidence drawer for the selected capability; a lower horizontal agent activity strip showing completed and upcoming workflow steps. Show a small clean simulation preview, but make the capability matrix the primary object.
Style/medium: realistic production UI, quiet editorial desktop design, lab-instrument clarity, disciplined 8px grid, square-to-4px corners, thin rules instead of card soup, generous but efficient whitespace, excellent typography, accessible contrast.
Color palette: warm off-white canvas, white panels, deep ink text, cobalt blue selection, emerald verified states, coral risk states, amber pending states. No gradient and no shadows beyond one subtle elevation level.
Text (verbatim): "SERVO", "Reality Debt", "Mission", "Diagnose", "Train", "Examine", "Deploy", "Lane following 98%", "Occluded pedestrians 94% VERIFIED", "Heavy rain 41% AT RISK", "Construction zones NOT TESTED", "Next experiment", "Run hidden exam".
Constraints: real dense desktop productivity software, immediately scannable status semantics that do not rely on color alone, concise English only, visible row selection and focus states, plausible in Qt 6 QML, no external logos, no watermark.
Avoid: generic SaaS dashboard, giant KPI cards, bubbly cards, excessive rounding, gradients, purple, glassmorphism, confetti, chatbot UI, stock illustrations, fake 3D icons, mobile layout, illegible microtext, gibberish, lorem ipsum.
```

## 03 - Navy Causal Lab

```text
Use case: ui-mockup
Asset type: shippable desktop application causal-diagnosis lab, 16:10 landscape screenshot
Primary request: Design Servo's causal experiment workspace where an autonomous validation agent isolates why a simulated crash occurred.
Scene/backdrop: straight-on full-window desktop software screenshot, no monitor or device frame.
Subject: an ink-blue engineering workbench centered on a large simulation replay. Left pane contains a compact run filmstrip with synchronized camera and LiDAR thumbnails. Center shows a clear urban driving replay with a parked van occluding a pedestrian and minimal overlays for trajectory, detection, and braking. Right pane contains a rigorous causal experiment graph with hypotheses H1-H5 and test results; the selected path proves perception under partial occlusion is the root cause. Bottom pane contains synchronized plots for detection confidence, brake command, speed, and time-to-collision with a shared playhead. Top toolbar has run, pause, step, compare, and reset controls.
Style/medium: realistic production UI, serious aerospace/robotics tooling, compact dockable panes, crisp typography, restrained details, visible resize handles, 3-5px radius, no decorative elements.
Color palette: deep navy and desaturated steel surfaces, parchment-white text, muted cyan data, amber experiment highlight, scarlet failure event. Flat color, no gradient.
Text (verbatim): "SERVO", "Causal Lab", "Run 0247", "H1 Not detected", "H2 Detected late", "H3 Planner failed", "H4 Braking limit", "H5 Partial occlusion", "ROOT CAUSE", "Oracle perception: SAFE", "Create 300 variants".
Constraints: evidence-first layout; graph nodes and plots must communicate a believable experiment sequence; concise real English only; desktop keyboard/mouse affordances; plausible in Qt 6 QML with a custom renderer; no logos besides SERVO; no watermark.
Avoid: futuristic hologram HUD, cyberpunk, glowing neon, purple, glassmorphism, floating cards, chatbot, marketing page, massive hero title, excessive pills, overly rounded panels, illegible microtext, gibberish, lorem ipsum.
```

## 04 - Monochrome Hidden Exam

```text
Use case: ui-mockup
Asset type: shippable desktop application checkpoint review workspace, 16:10 landscape screenshot
Primary request: Design Servo's hidden-exam and checkpoint promotion screen for an autonomous policy after targeted retraining.
Scene/backdrop: straight-on full-window desktop software screenshot, no monitor or device frame.
Subject: a high-contrast precision monochrome desktop interface. Use a strong modular grid with almost no cards: left vertical navigation and checkpoint list, center split comparison of BEFORE and CANDIDATE simulation frames of the same occluded-pedestrian scenario, a prominent but restrained exam verdict band, a regression table beneath, and a narrow right decision record showing who/what ran each test and why the checkpoint may be promoted. Include a thin timeline and small metric plots. Make accept/reject consequences unmistakable.
Style/medium: realistic production UI, modern technical editorial design, square controls, hairline dividers, bold typographic hierarchy, tabular numbers, compact status marks, sophisticated and understated, accessible.
Color palette: soft white and pale gray surfaces, near-black typography, one electric blue navigation accent, one signal red regression color, one forest green pass color. No gradient; no colored background wash.
Text (verbatim): "SERVO", "Hidden Exam", "Checkpoint v18", "BEFORE 27%", "CANDIDATE 96%", "Generalization 91% PASS", "Regression suite 48/48 PASS", "Promote checkpoint", "Decision record", "Reality Debt 18.4% -> 11.2%".
Constraints: clear irreversible-action hierarchy with a secondary Reject action; no reliance on color alone; concise English only; plausible in Qt 6 QML; desktop-native focus and selection states; no external logos; no watermark.
Avoid: generic admin dashboard, card soup, glassmorphism, gradients, purple, soft 3D blobs, excessive rounding, excessive whitespace, chatbot UI, marketing copy, mobile layout, illegible microtext, gibberish, lorem ipsum.
```
