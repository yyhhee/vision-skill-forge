"""Original CSS and annotation JavaScript, preserved byte-for-byte."""

from __future__ import annotations

CSS = """
    @import url('https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;700&family=Space+Grotesk:wght@400;500;600;700&display=swap');
    :root {
      --color-primary: #7C3AED;
      --color-on-primary: #FFFFFF;
      --color-secondary: #6366F1;
      --color-accent: #EC4899;
      --color-background: #FAF5FF;
      --color-foreground: #0F172A;
      --color-muted-bg: #F7F3FD;
      --color-border: #EFE7FC;
      --color-destructive: #DC2626;
      --color-ring: #7C3AED;
      --vs-ink: #0F172A;
      --vs-muted: #5F5470;
      --vs-border: #EFE7FC;
      --vs-surface: #ffffff;
      --vs-canvas: #FAF5FF;
      --vs-primary: #7C3AED;
      --vs-primary-strong: #5B21B6;
      --vs-secondary: #6366F1;
      --vs-accent: #EC4899;
      --vs-destructive: #DC2626;
      --vs-shadow: 0 1px 2px rgba(15, 23, 42, .05);
      --vs-shadow-md: 0 4px 6px rgba(76, 29, 149, .08);
      --vs-shadow-raised: 0 10px 15px rgba(76, 29, 149, .10);
      --vs-shadow-xl: 0 20px 25px rgba(76, 29, 149, .15);
      --vs-font-heading: "Space Grotesk", "Microsoft YaHei UI", "Microsoft YaHei", sans-serif;
      --vs-font-body: "DM Sans", "Microsoft YaHei UI", "Microsoft YaHei", sans-serif;
    }
    body, .gradio-container {
      background: var(--vs-canvas) !important;
      color: var(--vs-ink) !important;
      font-family: var(--vs-font-body) !important;
    }
    .gradio-container {
      max-width: 1540px !important;
      padding: 22px clamp(16px, 3.2vw, 48px) 56px !important;
    }
    .vs-hero {
      position: relative; overflow: hidden; padding: 30px 32px;
      border-radius: 16px; color: #fdfaff;
      background: linear-gradient(112deg, #3B0764 0%, #6D28D9 46%, #C026D3 78%, #EC4899 100%);
      box-shadow: var(--vs-shadow-xl);
    }
    .vs-hero:before {content:""; position:absolute; width:220px; height:220px; left:-90px; bottom:-150px; background:rgba(255,255,255,.07); border-radius:36px; transform:rotate(24deg);}
    .vs-hero:after {content:""; position:absolute; width:410px; height:410px; right:-150px; top:-280px; border:1px solid rgba(249, 168, 212, .28); border-radius:50%; box-shadow:0 0 0 44px rgba(249,168,212,.07),0 0 0 88px rgba(249,168,212,.04);}
    .vs-kicker {margin:0 0 6px; font-family:var(--vs-font-heading); font-size:11px; font-weight:700; letter-spacing:.14em; color:#F0ABFC !important;}
    .vs-hero h1 {position:relative; z-index:1; margin:0; color:#fff !important; font-family:var(--vs-font-heading); font-weight:700; font-size:clamp(28px,3.2vw,40px); line-height:1.2; letter-spacing:-.01em;}
    .vs-hero p {position:relative; z-index:1; max-width:780px; margin:10px 0 0; color:#EDE9FE !important; font-size:15px; line-height:1.6;}
    .vs-hero .vs-badges {position:relative; z-index:1; display:flex; flex-wrap:wrap; gap:8px; margin-top:16px;}
    .vs-badge {display:inline-flex; align-items:center; border:1px solid rgba(255,255,255,.28); border-radius:999px; padding:4px 12px; background:rgba(255,255,255,.12); color:#fdfaff !important; font-size:12px; font-weight:600; backdrop-filter:blur(4px);}
    .vs-workflow {display:grid; grid-template-columns:repeat(5, minmax(0, 1fr)); gap:0; margin:20px 0; border:1px solid var(--vs-border); border-radius:12px; overflow:hidden; background:#fff; box-shadow:var(--vs-shadow-md);}
    .vs-step {min-height:76px; padding:14px 16px; border-right:1px solid var(--vs-border); background:#fff; transition:background .2s ease;}
    .vs-step:hover {background:var(--color-muted-bg);}
    .vs-step:last-child {border-right:0;}
    .vs-step-index {display:block; margin-bottom:5px; font-family:var(--vs-font-heading); background:linear-gradient(90deg, var(--vs-primary), var(--vs-accent)); -webkit-background-clip:text; background-clip:text; color:transparent; font-size:11px; font-weight:700; letter-spacing:.1em;}
    .vs-step strong {display:block; color:var(--vs-ink); font-family:var(--vs-font-heading); font-size:14px; font-weight:600;}
    .vs-step span {display:block; margin-top:3px; color:var(--vs-muted); font-size:12px; line-height:1.4;}
    .vs-source-card {margin:0 0 16px; padding:13px 15px; border:1px solid #DDD6FE; border-left:4px solid var(--vs-primary); border-radius:8px; background:#F3EFFF; color:#4C1D95; line-height:1.55;}
    .vs-source-card strong {color:#3B0764;}
    .status-card {margin:0 0 16px; padding:12px 15px; border:1px solid #FBCFE8; border-left:4px solid var(--vs-accent); border-radius:8px; background:#fff; box-shadow:var(--vs-shadow);}
    .status-card h3 {margin:0 0 2px !important; color:var(--vs-ink) !important; font-family:var(--vs-font-heading); font-size:14px !important;}
    .status-card p {margin:0 !important; color:var(--vs-muted);}
    .tab-nav {gap:0 !important; padding:0 !important; border:1px solid var(--vs-border) !important; border-radius:12px !important; background:var(--color-muted-bg) !important; overflow:hidden !important;}
    .tab-nav button {min-height:48px !important; border-radius:0 !important; border-right:1px solid var(--vs-border) !important; color:#6B5E85 !important; font-family:var(--vs-font-heading); font-weight:600 !important; cursor:pointer !important; transition:background .2s ease, color .2s ease, box-shadow .2s ease !important;}
    .tab-nav button:hover {color:var(--vs-primary) !important;}
    .tab-nav button:last-child {border-right:0 !important;}
    .tab-nav button.selected {background:#fff !important; color:var(--vs-primary-strong) !important; box-shadow:inset 0 -3px 0 var(--vs-accent) !important;}
    .tabitem {padding-top:20px !important;}
    .vs-section {padding:24px; border:1px solid var(--vs-border); border-radius:12px; background:var(--vs-surface); box-shadow:var(--vs-shadow-md);}
    .vs-section h2, .vs-section h3 {color:var(--vs-ink); font-family:var(--vs-font-heading);}
    .vs-section-copy {margin:0 0 16px; color:var(--vs-muted); line-height:1.6;}
    .vs-guide {display:grid; grid-template-columns:repeat(4, minmax(0, 1fr)); gap:10px; margin:0 0 16px;}
    .vs-guide-item {padding:12px; border:1px solid var(--vs-border); border-radius:8px; background:var(--color-muted-bg); transition:box-shadow .2s ease, transform .2s ease;}
    .vs-guide-item:hover {box-shadow:var(--vs-shadow-md); transform:translateY(-2px);}
    .vs-guide-item b {display:block; color:var(--vs-primary-strong); font-size:12px;}
    .vs-guide-item span {display:block; margin-top:4px; color:var(--vs-muted); font-size:12px; line-height:1.4;}
    .vs-quick-path {display:grid; grid-template-columns:repeat(3, minmax(0, 1fr)); gap:12px; margin:0 0 16px;}
    .vs-path {padding:16px; border:1px solid var(--vs-border); border-radius:12px; background:var(--color-muted-bg); transition:box-shadow .2s ease, transform .2s ease, border-color .2s ease;}
    .vs-path:hover {box-shadow:var(--vs-shadow-raised); transform:translateY(-2px); border-color:#DDD6FE;}
    .vs-path b {color:var(--vs-primary-strong); font-family:var(--vs-font-heading); font-size:14px;}
    .vs-path p {margin:6px 0 0; color:var(--vs-muted); font-size:12px; line-height:1.45;}
    .vs-source-mode {margin:0 0 16px !important;}
    .vs-source-mode .wrap {display:grid !important; grid-template-columns:repeat(3,minmax(0,1fr)) !important; gap:10px !important; border:0 !important; background:transparent !important;}
    .vs-source-mode label {min-height:58px !important; margin:0 !important; padding:12px !important; border:1px solid var(--vs-border) !important; border-radius:8px !important; background:#fff !important; color:#5F5470 !important; font-weight:600 !important; cursor:pointer !important; transition:border-color .2s ease, background .2s ease, box-shadow .2s ease !important;}
    .vs-source-mode label:has(input:checked) {border-color:var(--vs-primary) !important; background:#F3EFFF !important; box-shadow:inset 3px 0 0 var(--vs-primary) !important; color:var(--vs-primary-strong) !important;}
    .vs-source-mode label:hover {border-color:#C4B5FD !important; box-shadow:var(--vs-shadow-md) !important;}
    .vs-status-output textarea {min-height:72px !important; background:var(--color-muted-bg) !important; color:#4C1D95 !important;}
    .vs-tool-hint {margin:0 0 10px; padding:10px 14px; border:1px dashed #C4B5FD; border-radius:8px; background:#FBF8FF; color:#5B21B6 !important; font-size:13px;}
    .vs-tool-hint p {margin:0 !important; color:#5B21B6 !important;}
    .gr-group, .gr-form, .gr-box {border-radius:12px !important;}
    .gradio-container .styler {background: transparent !important;}
    .gr-button-primary, button.primary {background:var(--vs-accent) !important; border:0 !important; color:#fff !important; box-shadow:0 4px 10px rgba(236,72,153,.25) !important;}
    .gr-button-primary:hover, button.primary:hover {opacity:.92 !important; transform:translateY(-1px); box-shadow:0 8px 16px rgba(236,72,153,.3) !important;}
    button.secondary {background:transparent !important; border:2px solid var(--vs-primary) !important; color:var(--vs-primary) !important;}
    button.secondary:hover {background:#F3EFFF !important;}
    button.stop {border-radius:10px !important; border-color:var(--vs-destructive) !important; color:var(--vs-destructive) !important;}
    .gr-button, button {min-height:42px !important; border-radius:8px !important; font-weight:600 !important; cursor:pointer !important; transition:box-shadow .2s ease, background .2s ease, border-color .2s ease, transform .2s ease, opacity .2s ease !important;}
    .gr-button:hover, button:hover {box-shadow:var(--vs-shadow-md);}
    textarea, input, .wrap {border-radius:8px !important;}
    textarea:focus, input:focus {border-color:var(--color-ring) !important; box-shadow:0 0 0 3px rgba(124,58,237,.15) !important;}
    .gradio-container label span {color:#3B3650; font-weight:600;}
    .prose h1, .prose h2, .prose h3 {color:var(--vs-ink); font-family:var(--vs-font-heading);}
    .prose p {color:var(--vs-muted);}
    .gr-accordion {border:1px solid var(--vs-border) !important; border-radius:12px !important; background:var(--color-muted-bg) !important;}
    .gr-accordion .label-wrap {font-weight:700 !important; color:var(--vs-primary-strong) !important; cursor:pointer !important;}
    .vs-condition-card {margin:0 0 12px !important; padding:14px !important; border:1px solid #DDD6FE !important; border-left:4px solid var(--vs-primary) !important; border-radius:8px !important; background:#FFF !important; box-shadow:var(--vs-shadow) !important;}
    .vs-condition-card:nth-of-type(even) {border-left-color:var(--vs-secondary) !important;}
    .vs-condition-card .prose {margin-bottom:0 !important;}
    .vs-condition-card .prose p {margin:0 !important; color:var(--vs-primary-strong) !important; font-family:var(--vs-font-heading) !important; font-size:14px !important; font-weight:700 !important;}
    .vs-condition-delete {min-width:40px !important; width:40px !important; color:var(--vs-destructive) !important; border-color:#FECACA !important; background:#FFF7F7 !important;}
    .vs-event-policy {margin-top:14px !important; padding:14px !important; border:1px solid var(--vs-border) !important; border-radius:8px !important; background:#FBF8FF !important;}
    .vs-card-state {display:none !important;}
    .vs-branch-grid {display:grid; grid-template-columns:repeat(auto-fit,minmax(240px,1fr)); gap:10px; margin:10px 0 16px;}
    .vs-branch-summary {padding:13px 14px; border:1px solid var(--vs-border); border-radius:10px; background:#fff; box-shadow:var(--vs-shadow); color:inherit; font:inherit; text-align:left; cursor:pointer; width:100%;}
    .vs-branch-summary:hover {border-color:var(--vs-primary);}
    .vs-branch-summary.is-selected {border-color:var(--vs-primary); box-shadow:inset 4px 0 0 var(--vs-primary),var(--vs-shadow);}
    .vs-branch-summary b,.vs-branch-summary span {display:block;}
    .vs-branch-summary b {color:var(--vs-ink);}
    .vs-branch-summary span {margin-top:3px; color:var(--vs-primary); font-size:12px; font-weight:700;}
    .vs-branch-summary p {margin:7px 0 0; color:var(--vs-muted); font-size:12px; line-height:1.45;}
    .vs-rule-tree {display:flex; flex-direction:column; gap:8px; margin:8px 0 16px;}
    .vs-rule-formula {display:grid; gap:6px; margin:8px 0 12px; padding:12px 14px; border:1px solid #C4B5FD; border-radius:10px; background:#F5F3FF;}
    .vs-rule-formula code {display:block; white-space:normal; overflow-wrap:anywhere; color:#5B21B6; font-size:14px; font-weight:700;}
    .vs-rule-formula span {color:var(--vs-muted); font-size:12px;}
    .vs-rule-node {margin-left:calc(var(--rule-depth) * 22px); padding:11px 13px; border:1px solid var(--vs-border); border-left:4px solid #A78BFA; border-radius:8px; background:#fff;}
    .vs-rule-node.is-ready {border-left-color:#10B981;}
    .vs-rule-node.is-pending {border-left-color:#F59E0B; background:#FFFBEB;}
    .vs-rule-node.is-disabled {opacity:.58; border-left-color:#94A3B8;}
    .vs-rule-node-head {display:flex; align-items:center; gap:7px; margin-bottom:5px;}
    .vs-rule-category,.vs-logic-badge,.vs-condition-badge,.vs-step-badge,.vs-rule-status {display:inline-flex; padding:2px 7px; border-radius:999px; font-size:11px; font-weight:700;}
    .vs-rule-category {background:#F3E8FF; color:#6B21A8;}
    .vs-logic-badge {background:#DBEAFE; color:#1D4ED8;}
    .vs-condition-badge {background:#ECFDF5; color:#047857;}
    .vs-step-badge {background:#ECFDF5; color:#047857;}
    .vs-rule-status {margin-left:auto; background:#F1F5F9; color:#475569;}
    .vs-rule-node strong {display:block; color:var(--vs-ink);}
    .vs-rule-node p {margin:3px 0 0; color:var(--vs-muted); font-size:12px;}
    .vs-rule-node.is-logic-group {border-color:#93C5FD; border-left-color:#2563EB; background:#EFF6FF;}
    .vs-logic-members {display:flex; flex-wrap:wrap; align-items:center; gap:8px; margin-top:10px; padding:10px; border:1px solid #BFDBFE; border-radius:8px; background:#fff;}
    .vs-logic-member {display:grid; gap:2px; min-width:180px; padding:7px 9px; border-radius:7px; background:#F8FAFC; color:#0F172A; font-size:12px; font-weight:650;}
    .vs-logic-member i {color:#64748B; font-size:10px; font-style:normal; font-weight:700;}
    .vs-logic-connector {padding:3px 7px; border-radius:999px; background:#2563EB; color:#fff; font-size:11px;}
    .vs-empty-card {display:flex; flex-direction:column; gap:4px; padding:16px; border:1px dashed #C4B5FD; border-radius:10px; background:#FBF8FF; color:#5B21B6;}
    .vs-editor-subnav {padding:12px 14px; border:1px solid var(--vs-border); border-radius:10px; background:#FBF8FF;}
    .gr-json, .gr-code {border-radius:12px !important; overflow:hidden !important;}
    .gr-json, .gr-code, .cm-editor {font-family:"Cascadia Code", Consolas, monospace !important;}
    .vs-annotation-canvas {position:relative !important; user-select:none !important;}
    .vs-annotation-canvas.vs-dragging {cursor:crosshair !important;}
    .vs-annotation-canvas .image-container, .vs-annotation-canvas img {touch-action:none !important;}
    .vs-result-media {max-width:960px !important; margin:0 auto !important;}
    .vs-result-media img, .vs-result-media video {max-height:560px !important; width:100% !important; object-fit:contain !important;}
    .vs-result-media img, .vs-result-media video {cursor:zoom-in !important;}
    .vs-business-results {display:grid; gap:18px;}
    .vs-result-nav {position:sticky; top:0; z-index:3; padding:10px 14px; border:1px solid var(--vs-border); border-radius:8px; background:#fff; color:var(--vs-primary-strong); font-weight:700;}
    .vs-final-result {padding:24px; border:1px solid #C4B5FD; border-left:6px solid var(--vs-primary); border-radius:12px; background:linear-gradient(135deg,#FBF8FF,#FFF); box-shadow:var(--vs-shadow-md);}
    .vs-final-result h2 {margin:4px 0 8px; color:var(--vs-ink);}
    .vs-final-status {display:inline-flex; padding:4px 10px; border-radius:999px; background:#EDE9FE; color:#5B21B6; font-weight:700;}
    .vs-final-value {font-size:26px; font-weight:700; color:var(--vs-primary-strong);}
    .vs-result-grid {display:grid; grid-template-columns:repeat(auto-fit,minmax(220px,1fr)); gap:12px;}
    .vs-result-card {padding:16px; border:1px solid var(--vs-border); border-radius:10px; background:#fff; box-shadow:var(--vs-shadow);}
    .vs-result-card-title {font-weight:700; color:var(--vs-ink);}
    .vs-result-card-value {margin:10px 0 4px; font-size:24px; font-weight:700; color:var(--vs-primary-strong); overflow-wrap:anywhere;}
    .vs-result-card-status {color:#5B21B6; font-weight:600;}
    .vs-branch-card {margin:8px 0; padding:10px 12px; border:1px solid var(--vs-border); border-radius:8px; background:#fff;}
    #vs-result-media-modal {display:none; position:fixed; inset:0; z-index:10000; padding:24px; background:rgba(20,16,31,.78); overflow:auto;}
    #vs-result-media-modal.is-open {display:flex; align-items:flex-start; justify-content:center;}
    #vs-result-media-modal .vs-media-modal-shell {position:relative; width:max-content; min-width:min(92vw,720px); max-width:none; margin:auto; padding:48px 18px 18px; border-radius:8px; background:#171221; box-shadow:0 20px 60px rgba(0,0,0,.45);}
    #vs-result-media-modal img, #vs-result-media-modal video {display:block; width:auto; height:auto; max-width:none; max-height:none; margin:auto;}
    #vs-result-media-modal .vs-media-modal-close {position:absolute; top:10px; right:12px; min-height:34px !important; padding:6px 12px; border:1px solid #E9D5FF; border-radius:6px; background:#fff; color:#4C1D95; cursor:pointer;}
    button:focus-visible, input:focus-visible, textarea:focus-visible, [role="tab"]:focus-visible, .label-wrap:focus-visible {outline:3px solid rgba(124,58,237,.4) !important; outline-offset:2px !important;}
    ::selection {background:rgba(124,58,237,.18);}
    @media (max-width: 980px) {
      .vs-workflow {grid-template-columns:repeat(2,minmax(0,1fr));}
      .vs-step {border-bottom:1px solid var(--vs-border);}
      .vs-step:nth-child(2n) {border-right:0;}
      .vs-guide {grid-template-columns:repeat(2,minmax(0,1fr));}
      .vs-quick-path {grid-template-columns:1fr;}
      .vs-source-mode .wrap {grid-template-columns:1fr !important;}
      .gradio-container {padding:16px !important;}
      .vs-hero {padding:24px 22px;}
    }
    @media (max-width: 560px) {
      .vs-workflow, .vs-guide {grid-template-columns:1fr;}
      .vs-step {border-right:0;}
      .vs-hero h1 {font-size:30px;}
    }
    @media (prefers-reduced-motion: reduce) {
      *, *:before, *:after {scroll-behavior:auto !important; transition:none !important; animation:none !important;}
    }
    """

ANNOTATION_DRAG_JS = """
    () => {
      const tool = () => document.querySelector('#vs-annotation-tool input:checked')?.value;
      const bind = () => {
        const root = document.querySelector('#vs-annotation-canvas');
        if (!root || root.dataset.dragBound === 'true') return;
        root.dataset.dragBound = 'true';
        let start = null;
        let preview = null;
        const imageBox = () => root.querySelector('img')?.getBoundingClientRect();
        const point = (event) => {
          const box = imageBox();
          if (!box) return null;
          return [
            Math.max(0, Math.min(box.width, event.clientX - box.left)),
            Math.max(0, Math.min(box.height, event.clientY - box.top)),
          ];
        };
        const clearPreview = () => {
          if (!preview) return;
          const node = preview.svg || preview;
          if (node && typeof node.remove === 'function') node.remove();
          preview = null;
        };
        const makeArrowPreview = () => {
          const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
          svg.style.cssText = 'position:absolute;pointer-events:none;z-index:5;overflow:visible;';
          const line = document.createElementNS('http://www.w3.org/2000/svg', 'line');
          line.setAttribute('stroke', '#EC4899');
          line.setAttribute('stroke-width', '3');
          line.setAttribute('stroke-linecap', 'round');
          const head = document.createElementNS('http://www.w3.org/2000/svg', 'polygon');
          head.setAttribute('fill', '#EC4899');
          svg.appendChild(line);
          svg.appendChild(head);
          return { svg, line, head };
        };
        root.addEventListener('pointerdown', (event) => {
          if (!['rectangle', 'direction'].includes(tool())) return;
          start = point(event);
          if (!start) return;
          event.preventDefault();
          event.stopPropagation();
          root.classList.add('vs-dragging');
          const box = root.getBoundingClientRect();
          if (tool() === 'direction') {
            preview = makeArrowPreview();
            const image = imageBox();
            const host = root.getBoundingClientRect();
            preview.svg.style.left = `${image.left - host.left}px`;
            preview.svg.style.top = `${image.top - host.top}px`;
            preview.svg.style.width = `${image.width}px`;
            preview.svg.style.height = `${image.height}px`;
            root.appendChild(preview.svg);
          } else {
            preview = document.createElement('div');
            preview.style.cssText = 'position:absolute;pointer-events:none;border:2px solid #EC4899;background:rgba(236,72,153,.10);z-index:5;border-radius:4px;';
            preview.dataset.rootLeft = String(box.left);
            preview.dataset.rootTop = String(box.top);
            root.appendChild(preview);
          }
          root.setPointerCapture?.(event.pointerId);
        }, true);
        root.addEventListener('pointermove', (event) => {
          if (!start || !preview) return;
          const end = point(event);
          if (!end) return;
          if (tool() === 'direction') {
            preview.line.setAttribute('x1', start[0]);
            preview.line.setAttribute('y1', start[1]);
            preview.line.setAttribute('x2', end[0]);
            preview.line.setAttribute('y2', end[1]);
            const dx = end[0] - start[0];
            const dy = end[1] - start[1];
            const len = Math.hypot(dx, dy) || 1;
            const ux = dx / len;
            const uy = dy / len;
            const headLen = 14;
            const spread = 7;
            const bx = end[0] - ux * headLen;
            const by = end[1] - uy * headLen;
            const lx = bx - uy * spread;
            const ly = by + ux * spread;
            const rx = bx + uy * spread;
            const ry = by - ux * spread;
            preview.head.setAttribute('points', `${end[0]},${end[1]} ${lx},${ly} ${rx},${ry}`);
          } else {
            const image = imageBox();
            const host = root.getBoundingClientRect();
            const left = Math.min(start[0], end[0]) + image.left - host.left;
            const top = Math.min(start[1], end[1]) + image.top - host.top;
            preview.style.left = `${left}px`;
            preview.style.top = `${top}px`;
            preview.style.width = `${Math.abs(end[0] - start[0])}px`;
            preview.style.height = `${Math.abs(end[1] - start[1])}px`;
          }
        }, true);
        root.addEventListener('pointerup', (event) => {
          if (!start || !['rectangle', 'direction'].includes(tool())) return;
          const end = point(event);
          event.preventDefault();
          event.stopPropagation();
          root.classList.remove('vs-dragging');
          clearPreview();
          if (end) {
            const target = document.querySelector('#vs-annotation-drag textarea');
            const image = imageBox();
            if (target && image) {
              target.value = JSON.stringify({
                start,
                end,
                canvas_size: [image.width, image.height],
              });
              target.dispatchEvent(new Event('input', {bubbles: true}));
            }
          }
          start = null;
        }, true);
      };
      new MutationObserver(bind).observe(document.body, {childList: true, subtree: true});
      bind();
      const modal = document.querySelector('#vs-result-media-modal');
      const modalImage = document.querySelector('#vs-result-media-original-image');
      const modalVideo = document.querySelector('#vs-result-media-original-video');
      const closeModal = () => {
        if (!modal) return;
        modal.classList.remove('is-open');
        if (modalVideo) { modalVideo.pause(); modalVideo.removeAttribute('src'); modalVideo.load(); }
        if (modalImage) modalImage.removeAttribute('src');
      };
      const openModal = (media) => {
        if (!modal || !modalImage || !modalVideo) return;
        const source = media.currentSrc || media.src;
        if (!source) return;
        const isVideo = media.tagName === 'VIDEO';
        modalImage.style.display = isVideo ? 'none' : 'block';
        modalVideo.style.display = isVideo ? 'block' : 'none';
        if (isVideo) { modalVideo.src = source; modalVideo.controls = true; }
        else modalImage.src = source;
        modal.classList.add('is-open');
      };
      document.addEventListener('click', (event) => {
        const branchCard = event.target.closest?.('[data-vs-branch-id]');
        if (branchCard) {
          event.preventDefault();
          const branchIndex = Number(branchCard.dataset.vsBranchIndex);
          const branchRoot = document.querySelector('#vs-business-branch');
          const input = branchRoot?.querySelector('input');
          if (input && Number.isInteger(branchIndex) && branchIndex >= 0) {
            input.focus();
            for (const eventName of ['pointerdown', 'mousedown', 'pointerup', 'mouseup', 'click']) {
              input.dispatchEvent(new MouseEvent(eventName, {bubbles: true, cancelable: true, view: window}));
            }
            window.setTimeout(() => {
              const options = Array.from(
                document.querySelectorAll('[data-testid="dropdown-option"]')
              ).filter((item) => {
                const rect = item.getBoundingClientRect();
                return rect.width > 0 && rect.height > 0;
              });
              const option = options[branchIndex];
              if (option) {
                for (const eventName of ['pointerdown', 'mousedown', 'pointerup', 'mouseup', 'click']) {
                  option.dispatchEvent(new MouseEvent(eventName, {bubbles: true, cancelable: true, view: window}));
                }
              }
            }, 0);
          }
          return;
        }
        const close = event.target.closest?.('[data-vs-close-media-modal]');
        if (close || event.target === modal) { closeModal(); return; }
        const media = event.target.closest?.('.vs-result-media img, .vs-result-media video');
        if (media) { event.preventDefault(); openModal(media); }
      }, true);
      document.addEventListener('keydown', (event) => { if (event.key === 'Escape') closeModal(); });
    }
    """
