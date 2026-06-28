"""Minimal HTML+JS UI served by the FastAPI app.

This is what gets served at ``/`` on Render (since Render only exposes one port
and we chose FastAPI as the primary). It's deliberately minimal — it talks to
``/v1/*`` and renders results. Streamlit remains the local-development UI.

Why both? Render gives us one port. FastAPI is more useful (programmable,
matches the API the user asked us to expose), and Streamlit needs a server
that holds WebSocket connections which is awkward to put behind uvicorn.
"""
from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import HTMLResponse


router = APIRouter()


_INDEX_HTML = r"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>JoyCAD — AI-driven CAD/CAM</title>
  <style>
    :root { color-scheme: light dark; }
    body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
           max-width: 1100px; margin: 0 auto; padding: 1.5rem;
           background: #fafafa; color: #1a1a1a; }
    @media (prefers-color-scheme: dark) {
      body { background: #15181c; color: #e6e6e6; }
      pre, code, .card { background: #1e2128 !important; }
      input, select, textarea { background: #1e2128; color: #e6e6e6; border-color: #333; }
      a { color: #6aa9ff; }
    }
    h1 { margin: 0 0 .25rem 0; font-size: 1.8rem; }
    h2 { margin: 2rem 0 .5rem; font-size: 1.2rem; border-bottom: 1px solid #ddd; padding-bottom: .25rem; }
    .tagline { color: #666; margin: 0 0 1.5rem 0; font-size: .95rem; }
    .layout { display: grid; grid-template-columns: 1fr 1fr; gap: 1.5rem; }
    @media (max-width: 800px) { .layout { grid-template-columns: 1fr; } }
    .card { background: white; border: 1px solid #e0e0e0; border-radius: 8px;
            padding: 1rem; }
    label { display: block; font-weight: 600; margin-top: .75rem; font-size: .9rem; }
    select, input, textarea { width: 100%; padding: .5rem; border: 1px solid #ccc;
                              border-radius: 6px; font-size: .9rem; box-sizing: border-box; }
    textarea { min-height: 70px; font-family: inherit; }
    button { padding: .6rem 1.2rem; background: #2563eb; color: white;
             border: none; border-radius: 6px; font-size: 1rem;
             cursor: pointer; margin-top: 1rem; }
    button:hover { background: #1d4ed8; }
    button:disabled { background: #9ca3af; cursor: not-allowed; }
    pre { background: #f5f5f5; padding: .75rem; border-radius: 6px;
          overflow: auto; font-size: .8rem; max-height: 400px; }
    .links a { margin-right: 1rem; font-size: .9rem; }
    .status { padding: .5rem .75rem; border-radius: 6px; margin-bottom: 1rem; }
    .status.ok { background: #d1fae5; color: #065f46; }
    .status.err { background: #fee2e2; color: #991b1b; }
    .status.run { background: #dbeafe; color: #1e40af; }
    .dl a { display: inline-block; padding: .25rem .5rem; background: #2563eb;
            color: white; border-radius: 4px; text-decoration: none;
            margin: .25rem .25rem 0 0; font-size: .8rem; }
    .dl a:hover { background: #1d4ed8; }
    details { margin: .25rem 0; }
    summary { cursor: pointer; font-weight: 600; font-size: .9rem; }
    .preset-grid { display: grid; grid-template-columns: repeat(2, 1fr); gap: .5rem;
                   margin-top: .5rem; }
    .preset-btn { padding: .5rem; background: #f3f4f6; border: 1px solid #d1d5db;
                  border-radius: 6px; cursor: pointer; text-align: left;
                  font-size: .8rem; }
    .preset-btn:hover { background: #e5e7eb; }
    .preset-btn small { color: #666; display: block; font-size: .7rem; }
  </style>
</head>
<body>
  <h1>🛠️ JoyCAD</h1>
  <p class="tagline">AI-driven CAD/CAM bundle — natural language → STEP + STL + G-code + BOM + notes</p>

  <div class="links">
    <a href="/docs">📘 API docs (Swagger)</a>
    <a href="/v1/info">🔍 /v1/info</a>
    <a href="/v1/capabilities">⚙ /v1/capabilities</a>
    <a href="/v1/presets">📦 /v1/presets</a>
    <a href="/v1/examples">💡 /v1/examples</a>
  </div>

  <div class="layout">
    <div class="card">
      <h2>1. Pick a preset</h2>
      <div id="presets" class="preset-grid"></div>

      <h2>2. Describe the part</h2>
      <label>Design intent</label>
      <textarea id="intent" placeholder="e.g. a 50 mm L-bracket, 6 mm thick, four M6 clearance holes, 6061-T6 aluminum">a 50 mm L-bracket, 6 mm thick, four M6 clearance holes, 6061-T6 aluminum</textarea>

      <label>Preset</label>
      <select id="preset">
        <option value="mvp-mock">mvp-mock — works offline, no API key</option>
      </select>

      <h2>3. Advanced (optional)</h2>
      <details>
        <summary>Machine, material, process, tools</summary>
        <label>Machine</label>
        <select id="machine">
          <option value="linuxcnc_3axis">linuxcnc_3axis</option>
          <option value="grbl_3018">grbl_3018</option>
          <option value="marlin_fdm">marlin_fdm</option>
        </select>
        <label>Material</label>
        <select id="material">
          <option value="6061-T6">6061-T6</option>
          <option value="1018">1018</option>
          <option value="316">316</option>
          <option value="ABS">ABS</option>
          <option value="PETG">PETG</option>
          <option value="PLA">PLA</option>
        </select>
        <label>Process</label>
        <select id="process">
          <option value="cnc_mill">cnc_mill</option>
          <option value="cnc_lathe">cnc_lathe</option>
          <option value="3d_print_fdm">3d_print_fdm</option>
          <option value="laser_cut">laser_cut</option>
          <option value="plasma_cut">plasma_cut</option>
        </select>
        <label>CAD engine</label>
        <select id="cad_engine">
          <option value="cadquery">cadquery</option>
          <option value="freecad">freecad</option>
          <option value="onshape">onshape</option>
          <option value="fusion">fusion</option>
        </select>
        <label>CAM backend</label>
        <select id="cam_backend">
          <option value="cadquery_cam">cadquery_cam (no CLI)</option>
          <option value="freecad_path">freecad_path</option>
          <option value="opencamlib">opencamlib</option>
          <option value="blendercam">blendercam</option>
        </select>
        <label>Safe Z (mm)</label>
        <input id="safe_z_mm" type="number" value="5" min="1" max="20" step="0.5">
        <label>Spindle RPM</label>
        <input id="spindle_rpm" type="number" value="12000" min="1000" max="30000" step="500">
        <label>Coolant</label>
        <select id="coolant">
          <option value="flood">flood</option>
          <option value="mist">mist</option>
          <option value="off">off</option>
        </select>
      </details>

      <button id="run">🚀 Build</button>
    </div>

    <div class="card">
      <h2>Result</h2>
      <div id="status" class="status run" style="display:none"></div>
      <div id="downloads"></div>
      <details>
        <summary>Steps</summary>
        <pre id="steps">no run yet</pre>
      </details>
      <details>
        <summary>curl equivalent</summary>
        <pre id="curl">click Build to generate</pre>
      </details>
      <details>
        <summary>Full response</summary>
        <pre id="raw">no run yet</pre>
      </details>
    </div>
  </div>

<script>
const $ = id => document.getElementById(id);

async function loadPresets() {
  const r = await fetch('/v1/presets').then(r => r.json());
  const sel = $('preset'); sel.innerHTML = '';
  $('presets').innerHTML = '';
  r.presets.forEach(p => {
    const o = document.createElement('option');
    o.value = p.name; o.textContent = p.label;
    sel.appendChild(o);
    const btn = document.createElement('button');
    btn.className = 'preset-btn';
    btn.innerHTML = `<strong>${p.label}</strong><small>${p.description}</small>`;
    btn.onclick = () => {
      sel.value = p.name;
      $('intent').focus();
      fetch('/v1/presets/' + p.name).then(r => r.json()).then(s => {
        if (s.machine) $('machine').value = s.machine;
        if (s.material) $('material').value = s.material;
        if (s.process) $('process').value = s.process;
        if (s.safe_z_mm) $('safe_z_mm').value = s.safe_z_mm;
        if (s.spindle_rpm) $('spindle_rpm').value = s.spindle_rpm;
        if (s.coolant) $('coolant').value = s.coolant;
      });
    };
    $('presets').appendChild(btn);
  });
}
loadPresets();

function buildPayload() {
  return {
    preset: $('preset').value,
    intent: $('intent').value,
    machine: $('machine').value,
    material: $('material').value,
    process: $('process').value,
    cad_engine: $('cad_engine').value,
    cam_backend: $('cam_backend').value,
    safe_z_mm: parseFloat($('safe_z_mm').value),
    spindle_rpm: parseInt($('spindle_rpm').value),
    coolant: $('coolant').value,
  };
}

$('run').onclick = async () => {
  const btn = $('run'); btn.disabled = true;
  const status = $('status'); status.style.display = 'block';
  status.className = 'status run'; status.textContent = '⏳ Building… this takes ~10-30 s';
  $('steps').textContent = 'building…';
  $('raw').textContent = '';
  $('downloads').innerHTML = '';
  const payload = buildPayload();
  $('curl').textContent = 'curl -X POST ' + location.origin + '/v1/pipeline \\\n'
    + '  -H "Content-Type: application/json" \\\n'
    + '  -d \'' + JSON.stringify(payload, null, 2) + '\'';
  try {
    const r = await fetch('/v1/pipeline', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify(payload),
    });
    const data = await r.json();
    if (!r.ok) {
      status.className = 'status err';
      status.textContent = '✗ ' + (data.detail || JSON.stringify(data));
      $('raw').textContent = JSON.stringify(data, null, 2);
      return;
    }
    if (data.ok) {
      status.className = 'status ok';
      status.textContent = '✓ Built in ' + data.result.elapsed + 's';
      $('steps').textContent = JSON.stringify(data.result.steps, null, 2);
      $('raw').textContent = JSON.stringify(data, null, 2);
      const dl = $('downloads'); dl.innerHTML = '<strong>Downloads:</strong><br>';
      const outs = data.result.outputs || {};
      for (const [k, p] of Object.entries(outs)) {
        const a = document.createElement('a');
        a.href = p; a.textContent = '⬇ ' + k;
        a.target = '_blank';
        dl.appendChild(a);
      }
    }
  } catch (e) {
    status.className = 'status err';
    status.textContent = '✗ ' + e.message;
  } finally {
    btn.disabled = false;
  }
};
</script>
</body>
</html>
"""


@router.get("/", response_class=HTMLResponse)
async def index():
    return _INDEX_HTML


@router.get("/ui", response_class=HTMLResponse)
async def ui_alias():
    return _INDEX_HTML
