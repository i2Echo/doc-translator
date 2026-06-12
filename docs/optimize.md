# AI Agent Progressive Implementation Blueprint: Industrial PDF Localizer

You are an advanced software engineering agent. Implement the following 5-phase iterative architecture sequentially. Maintain strict separation of concerns, handle data mutations outside the core BabelDOC source code, and treat BabelDOC strictly as an external package dependency.

---

## Phase 1: Global Font Routing (Base Infrastructure)
**Objective:** Establish a non-invasive multi-language vector rendering pipeline to eliminate character rendering blocks (`□`).

* **Task 1.1:** Create a global routing configuration (`languages_routing.json`) mapping target codes (`zh`, `en`, `ja`, `ko`, `ms`, `th`, `vi`) to specific TrueType/OpenType files. 
* **Task 1.2:** Implement an external wrapper that intercepts the parsed Intermediate Representation (IR JSON) from BabelDOC.
* **Task 1.3:** Override the default font registration system during the rendering execution phase, binding text blocks to their designated multi-language regular fonts.
* **Milestone:** A multi-language PDF is generated where all special characters render natively without style changes.

---

## Phase 2: Terminology Interception & Omission Guard (Semantic Layer)
**Objective:** Enforce 1:1 vocabulary locking and guarantee zero text segment dropping.

* **Task 2.1:** Build a text flattener that extracts all text fragments into a single-layer Key-Value dictionary (`block_id: src_text`).
* **Task 2.2:** Build a local prefix-tree matcher (`marisa-trie`) to scan keys against industry-specific dictionaries (PCB/Semiconductor).
* **Task 2.3:** Dynamically inject matched word-pairs directly into the LLM System Prompt under a strict compliance instruction block.
* **Task 2.4:** Implement a post-translation validation daemon (`Gatekeeper`) comparing input vs. output keys. If any block is missing or un-translated, intercept and trigger an isolated sub-batch repair loop.
* **Milestone:** Verified translation JSON output demonstrating 100% term compliance and zero omitted nodes.

---

## Phase 3: Structural Disambiguation (Layout Anchor Layer)
**Objective:** Restore horizontal alignment parity and visual text weight layers.

* **Task 3.1:** Implement an alignment sniffer calculating the center-axis ($X_{mid}$) of bounding rectangles. If $X_{mid}$ aligns with the page or column midpoint within $\pm 5.0\text{px}$, inject a metadata flag `"alignment": "CENTER"`.
* **Task 3.2:** Implement a font weight inspector. If the original block font name contains keywords like `Bold`, `Black`, or `Heavy`, inject a metadata flag `"font_style": "BOLD"`.
* **Task 3.3:** Configure the backend renderer to evaluate these custom flags: force-load corresponding `Bold.ttf` asset files for bold tokens, and explicitly push the keyword parameter `align=1` into downstream drawing primitives for center tokens.
* **Milestone:** Exported PDF where headers remain perfectly centered and critical parameters preserve bold states.

---

## Phase 4: Typography Shields & Matrix Recovery (Deep Rendering Layer)
**Objective:** Correct language-specific wrap breaking, rotation anomalies, and font scale discrepancies.

* **Task 4.1: Thai Word-Wrap Shield:** Integrate an external linguistic word segmenter (`pythainlp`). Tokenize Thai text chunks and rejoin them with zero-width space anchors (`\u200b`), giving the PDF engine invisible break targets to prevent single-character vertical cascading.
* **Task 4.2: Rotation Matrix Recovery:** Intercept the character-level orientation vector (`span["dir"]`) during extraction. If the vector matches vertical orientations, inject an explicit `"rotation"` angle property ($90^{\circ}$ or $270^{\circ}$). Pass this angle parameter directly to the final drawing box statement.
* **Task 4.3: Hierarchy Cascade Scaler:** Group text elements sharing spatial coordinates (e.g., table grids, headers). Identify the smallest calculated font size within the active group matrix, and uniformly overwrite all sibling font sizes to that minimum value.
* **Milestone:** Publishing-grade PDF output showcasing uniform table layouts, natural Thai sentence wrapping, and perfectly rotated vertical text.

---

## Phase 5: Draft State & Bounding Sandbox (Frontend Workspace Layer)
**Objective:** Deploy a Master-Detail web interface executing real-time layout风控 without database pollution.

* **Task 5.1:** Render a read-only visual viewport layer using `pdf.js` with an absolute HTML coordinate overlay. Connect it to an `ag-Grid` table for plain-text editing. Implement smooth bi-directional scrolling between matching blocks.
* **Task 5.2:** Isolate user keystrokes into a client-side memory state machine (`isDirty = true`), keeping the underlying backend database decoupled from active modifications.
* **Task 5.3: HTML Layout Sandbox:** Maintain an invisible, off-screen DOM sandbox mapping the exact bounding dimensions ($W_{max}$, $H_{max}$) of the target PDF block. On input, inject the editing string into the sandbox via `innerHTML` (converting `\n` to `<br/>`).
* **Task 5.4:** Read the sandboxed element's `BoundingClientRect`. If the measured box exceeds boundaries, trigger an iterative client-side font downsizing loop. If the size hits minimum caps ($7.5\text{pt}$), flag a layout overflow alarm on the UI.
* **Milestone:** Fully functional localization workbench providing instantaneous layout feedback, synchronized manual saves, and precise publishing fidelity.