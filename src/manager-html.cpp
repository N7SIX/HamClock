/* HamClock manager page C string file */

#include "HamClock.h"

const char manager_html[] = R"HCDB(
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover" />
  <title>HamClock Manager</title>
  <style>
    :root{--bg:#0a0a0a;--panel:#141414;--text:#e0e0e0;--good:#2e7d32;--bad:#c62828}
    *{box-sizing:border-box}
    body{margin:0;background:var(--bg);color:var(--text);font-family:system-ui}
    .wrap{width:min(520px,100%);margin:0 auto;padding:20px}
    .card{background:#1a1a1a;border:1px solid #333;border-radius:12px;padding:20px;margin:12px 0;box-shadow:0 2px 8px rgba(0,0,0,.3)}
    h1{font-size:24px;margin:0 0 8px}
    h2{font-size:18px;margin:0 0 12px}
    .grid{display:grid;grid-template-columns:1fr 1fr;gap:12px}
    .btn{display:block;width:100%;margin-top:12px;background:#d32f2f;color:#fff;border:0;border-radius:8px;padding:14px;font-size:18px;font-weight:700;cursor:pointer}
    .btn:active{transform:translateY(1px)}
    .btn:disabled{background:#999;cursor:not-allowed;transform:none}
    .msg{color:var(--good);font-size:14px;font-weight:700;margin-top:10px;display:none}
    .msg.err{color:var(--bad);display:none}
    .pwrow{margin-top:12px}
    .pwrow label{color:#888;font-size:14px}
    .pwinput{width:100%;padding:12px;font-size:16px;background:#222;color:#e0e0e0;border:2px solid #555;border-radius:6px;margin-top:8px}
  </style>
</head>
<body>
  <main class="wrap">
    <section class="card">
      <h1><span id="call">HamClock</span> Manager</h1>
      <div class="grid">
        <div class="card">
          <h2>Status</h2>
          <p id="where">Loading...</p>
          <p id="time">--:-- UTC</p>
          <p id="version" style="color:#888;font-size:13px">Ver: --</p>
        </div>
        <div class="card">
          <h2>Manager</h2>
          <p>Use this page to reset HamClock to factory defaults.</p>
          <div class="pwrow">
            <label for="pw_in">Password (required)</label>
            <input class="pwinput" type="password" id="pw_in" placeholder="Enter password" />
          </div>
          <button class="btn" id="reset_btn" onclick="doReset()">Factory Reset</button>
          <div class="msg" id="msg">Reset confirmed. Device will restart in 2 seconds.</div>
          <div class="msg err" id="msg_err">Incorrect password or reset cancelled.</div>
        </div>
      </div>
    </section>
  </main>
  <script>
    const base = location.pathname.replace(/\/[^/]*$/, '/');
    function $(id){ return document.getElementById(id); }
    async function refresh(){
      try{
        const [s, t, v] = await Promise.allSettled([fetch(`${base}get_sys.txt`), fetch(`${base}get_time.txt`), fetch(`${base}get_version.txt`)]);
        const sys = s.status==='fulfilled' ? s.value : {};
        const ver = v.status==='fulfilled' ? v.value : {};
        $('call').textContent = sys.Call || 'HamClock';
        $('where').textContent = (sys.DE_grid||sys.DE_lat) ? `${sys.DE_grid||''}, ${sys.DE_lat||''}` : 'HamClock Manager';
        $('time').textContent = t.status==='fulfilled' ? t.value.trim().split(/[\r\n]/)[0] : '--:-- UTC';
        $('version').textContent = 'Ver: ' + (ver.hc_version || '--');
      } catch(e){ $('where').textContent = 'Error loading data'; }
    }
    refresh();
    function doReset(){
      const btn = $('reset_btn');
      const pw = $('pw_in').value;
      if(!pw){ $('msg_err').style.display='block'; return; }
      btn.disabled=true; btn.textContent='Resetting...';
      const xhr = new XMLHttpRequest();
      xhr.open('POST', '/command?cfgreset=true', false);
      xhr.setRequestHeader('Content-Type','application/json');
      xhr.send(JSON.stringify({pw:pw}));
      if(xhr.status===200) location.reload();
      else { $('msg_err').style.display='block'; btn.disabled=false; btn.textContent='Factory Reset'; }
    }
  </script>
</body>
</html>
)HCDB");

