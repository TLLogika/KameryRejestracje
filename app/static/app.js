const $ = s => document.querySelector(s);
let csrf = '',
  cameras = [],
  page = 0,
  editing = null,
  zones = {},
  start = null,
  pending = false,
  zoneSelection = 'new',
  zoneDraft = null;
let currentView = ['database', 'settings'].includes(location.hash.slice(1)) ? location.hash.slice(
    1) : 'cameras',
  parkingData = null;
async function api(path, options = {}) {
  const r = await fetch('/api' + path, {
    ...options,
    headers: {
      'Content-Type': 'application/json',
      'X-CSRF-Token': csrf,
      ...options.headers
    }
  });
  if (!r.ok) {
    let e = await r.json().catch(() => ({
      detail: 'Błąd połączenia'
    }));
    if (r.status === 401 && path != '/login') showLogin();
    throw Error(typeof e.detail === 'string' ? e.detail : 'Sprawdź wprowadzone dane')
  }
  return r.json()
}

function showLogin() {
  csrf = '';
  $('#dashboard').hidden = true;
  $('#login').hidden = false;
  $('#grid').replaceChildren();
  $('#editor').close();
  $('#editorImage').removeAttribute('src')
}
async function showDashboard() {
  $('#login').hidden = true;
  $('#dashboard').hidden = false;
  setView(currentView, false);
  await refresh()
}
$('#loginForm').onsubmit = async e => {
  e.preventDefault();
  try {
    const data = Object.fromEntries(new FormData(e.target));
    csrf = (await api('/login', {
      method: 'POST',
      body: JSON.stringify(data)
    })).csrf;
    e.target.password.value = '';
    $('#loginError').textContent = '';
    await showDashboard()
  } catch (e) {
    $('#loginError').textContent = e.message
  }
};
$('#logout').onclick = async () => {
  await api('/logout', {
    method: 'POST'
  });
  showLogin()
};

function zoneGroups(values) {
  return {
    arrival: values.arrival ? (Array.isArray(values.arrival) ? values.arrival : [values.arrival]) :
      [],
    departure: values.departure ? (Array.isArray(values.departure) ? values.departure : [values
      .departure
    ]) : [],
    motion: values.motion ? (Array.isArray(values.motion) ? values.motion : [values.motion]) : []
  }
}

function draw(canvas, values, detections = []) {
  const r = canvas.getBoundingClientRect();
  canvas.width = Math.max(1, r.width * devicePixelRatio);
  canvas.height = Math.max(1, r.height * devicePixelRatio);
  const ctx = canvas.getContext('2d'),
    w = canvas.width,
    h = canvas.height;
  ctx.font = `${12*devicePixelRatio}px system-ui`;
  const groups = structuredClone(zoneGroups(values));
  if (canvas.id === 'editorCanvas' && zoneDraft) {
    const list = groups[$('#zoneKind').value];
    if (zoneSelection === 'new') list.push(zoneDraft);
    else list[Number(zoneSelection)] = zoneDraft
  }
  for (const [kind, list] of Object.entries(groups)) {
    for (const [i, z] of list.entries()) {
      ctx.lineWidth = (canvas.id === 'editorCanvas' && kind === $('#zoneKind').value && String(
        i) === zoneSelection ? 4 : 2) * devicePixelRatio;
      ctx.strokeStyle = kind === 'arrival' ? '#22c96c' : kind === 'motion' ? '#31bced' : '#f46565';
      ctx.fillStyle = kind === 'arrival' ? '#22c96c14' : kind === 'motion' ? '#31bced14' :
        '#f4656514';
      ctx.fillRect(z.x * w, z.y * h, z.w * w, z.h * h);
      ctx.strokeRect(z.x * w, z.y * h, z.w * w, z.h * h);
      ctx.fillStyle = ctx.strokeStyle;
      ctx.fillText(`${kind==='arrival'?'Z':kind==='motion'?'N':'C'}${i+1}`, z.x * w + 4 *
        devicePixelRatio, Math.min(h -
          4 * devicePixelRatio, z.y * h + 16 * devicePixelRatio))
    }
  }
  ctx.lineWidth = 2 * devicePixelRatio;
  for (const d of detections) {
    ctx.strokeStyle = '#31bced';
    ctx.fillStyle = '#31bced';
    ctx.strokeRect(d.x * w, d.y * h, d.w * w, d.h * h);
    ctx.fillText(`${d.text} ${Math.round(d.confidence*100)}%`, d.x * w, Math.max(14 *
      devicePixelRatio, d.y * h - 5))
  }
}

function renderZoneSelect() {
  const list = zones[$('#zoneKind').value] || [];
  const select = $('#zoneSelect');
  select.replaceChildren();
  const fresh = document.createElement('option');
  fresh.value = 'new';
  fresh.textContent = 'Nowy obszar';
  select.append(fresh);
  for (const [i] of list.entries()) {
    const option = document.createElement('option');
    option.value = i;
    option.textContent =
      `${$('#zoneKind').value==='arrival'?'Zielony':$('#zoneKind').value==='motion'?'Niebieski':'Czerwony'} ${i+1}`;
    select.append(option)
  }
  if (zoneSelection !== 'new' && Number(zoneSelection) >= list.length) zoneSelection = 'new';
  select.value = zoneSelection;
  $('#clearZone').disabled = zoneSelection === 'new';
  $('#addZone').disabled = list.length >= 32;
  draw($('#editorCanvas'), zones)
}

function render() {
  if (currentView !== 'cameras') return;
  const max = Math.max(1, Math.ceil(cameras.length / 4));
  page = Math.min(page, max - 1);
  $('#page').textContent = `${page+1} / ${max}`;
  $('#prev').disabled = page === 0;
  $('#next').disabled = page >= max - 1;
  $('#cameraCount').textContent = `Kamery: ${cameras.length}`;
  const visible = cameras.slice(page * 4, page * 4 + 4),
    grid = $('#grid');
  if (!visible.length) {
    grid.innerHTML =
      '<div class="empty">Dodaj podłączoną kamerę USB lub kamerę IP, aby rozpocząć monitoring.</div>';
    return
  }
  for (const child of [...grid.children])
    if (!visible.some(c => String(c.id) === child.dataset.id)) child.remove();
  for (const c of visible) {
    let card = grid.querySelector(`[data-id="${c.id}"]`);
    if (!card) {
      card = document.createElement('article');
      card.className = 'camera';
      card.dataset.id = c.id;
      card.innerHTML =
        '<header><div class="cameraHeading"><h2></h2><label class="cameraMotionToggle"><input type="checkbox" class="motionToggle"> Oszczędny · zmiana obrazu</label><small class="cameraMotionState"></small></div><span class="status"></span></header><div class="stage"><img alt="Podgląd kamery"><canvas></canvas><div class="waiting"></div></div><footer><button class="edit">Powiększ / obszary</button><button class="remove">Usuń kamerę</button></footer>';
      grid.append(card);
      if (c.metrics?.preview_enabled !== false) card.querySelector('img').src =
        `/api/cameras/${c.id}/stream`;
      card.querySelector('.edit').onclick = () => openEditor(c.id);
      card.querySelector('.motionToggle').onchange = async e => {
        const toggle = e.target,
          desired = toggle.checked;
        toggle.dataset.pending = '1';
        toggle.disabled = true;
        try {
          await api(`/cameras/${c.id}/motion`, {
            method: 'PUT',
            body: JSON.stringify({
              enabled: desired
            })
          });
          await refresh();
        } catch (e) {
          toggle.checked = !desired;
          $('#message').textContent = e.message;
        } finally {
          delete toggle.dataset.pending;
          render();
        }
      };
      card.querySelector('.remove').onclick = async () => {
        if (confirm('Usunąć tę kamerę z panelu?')) {
          try {
            await api(`/cameras/${c.id}`, {
              method: 'DELETE'
            });
            await refresh()
          } catch (e) {
            $('#message').textContent = e.message
          }
        }
      }
    }
    card.querySelector('.cameraMotionState').textContent = !c.motion?.enabled ? '' :
      `${motionActivity(c)} · ${c.metrics?.motion?.changed_percent || 0}%`;
    const image = card.querySelector('img');
    if (c.metrics?.preview_enabled === false) image.removeAttribute('src');
    else if (!image.hasAttribute('src')) image.src = `/api/cameras/${c.id}/stream`;
    card.querySelector('h2').textContent = c.name;
    const toggle = card.querySelector('.motionToggle');
    if (!toggle.dataset.pending) {
      toggle.checked = Boolean(c.motion?.enabled);
      toggle.disabled = !zoneGroups(c.zones).motion.length && !toggle.checked;
      toggle.title = toggle.disabled ?
        'Najpierw narysuj i zapisz niebieski obszar w powiększonym podglądzie' :
        'OCR po zmianie obrazu w niebieskim obszarze';
    }

    const status = card.querySelector('.status');
    status.textContent = c.status;
    status.classList.toggle('ok', c.status === 'Działa');
    status.classList.toggle('paused', c.status.startsWith('Wstrzymana'));
    card.querySelector('.waiting').classList.toggle('paused', c.status.startsWith('Wstrzymana'));
    card.querySelector('.waiting').hidden = c.status === 'Działa' && c.metrics?.preview_enabled !==
      false;
    card.querySelector('.waiting').textContent = c.metrics?.preview_enabled === false ?
      'Podgląd wyłączony w ustawieniach' : c.status;
    draw(card.querySelector('canvas'), c.zones, c.detections)
  }
}
$('#prev').onclick = () => {
  page--;
  render()
};
$('#next').onclick = () => {
  page++;
  render()
};

function rows(data) {
  parkingData = data;
  const query = currentView === 'database' ? $('#plateFilter').value.toUpperCase().replace(
    /[^A-Z0-9]/g, '') : '';
  for (const kind of ['arrival', 'current', 'departure']) {
    const container = $('#' + kind);
    container.replaceChildren();
    const matches = data[kind].filter(r => r.plate.toUpperCase().includes(query));
    $('#' + kind + 'Count').textContent = matches.length;
    if (!matches.length) {
      container.textContent = query ? 'Brak pasujących wpisów' : 'Brak wpisów';
      continue
    }
    for (const r of matches) {
      const row = document.createElement('div');
      row.className = 'plateRow';
      const info = document.createElement('div');
      info.className = 'plateInfo';
      const plate = document.createElement('strong');
      plate.textContent = r.plate;
      const detail = document.createElement('small');
      detail.textContent = (cameras.find(c => c.id === r.camera_id)?.name ||
        `Kamera ${r.camera_id}`) + (r.confidence === undefined ? '' :
        ` · Pewność ${Math.round(r.confidence*100)}%`);
      info.append(plate, detail);
      const time = document.createElement('span');
      time.textContent = new Date(r.at || r.entered_at).toLocaleString('pl-PL');
      row.append(info, time);
      container.append(row)
    }
  }
}

function closeStreams() {
  for (const img of $('#grid').querySelectorAll('img')) img.removeAttribute('src');
  $('#grid').replaceChildren();
  $('#editor').close();
  $('#editorImage').removeAttribute('src')
}

function setView(view, changeHash = true) {
  currentView = ['database', 'settings'].includes(view) ? view : 'cameras';
  const database = currentView === 'database',
    settings = currentView === 'settings';
  if (currentView !== 'cameras') closeStreams();
  if (settings) editing = null;
  $('#cameraToolbar').hidden = currentView !== 'cameras';
  $('#grid').hidden = currentView !== 'cameras';
  $('#databaseTools').hidden = !database;
  $('#cameraPreferences').hidden = !settings;
  $('.parking').hidden = settings;
  $('#dashboard main').classList.toggle('databaseOnly', database);
  $('#viewTitle').textContent = settings ? 'Ustawienia kamer' : database ? 'Baza danych parkingu' :
    'Kamery i parking';
  $('#viewEyebrow').textContent = settings ? 'PRZEŁĄCZANIE I PARAMETRY' : database ?
    'REJESTRACJE I ZDARZENIA' : 'PODGLĄD NA ŻYWO';
  for (const name of ['cameras', 'database', 'settings']) $('#' + name + 'View').setAttribute(
    'aria-pressed', String(currentView === name));
  if (changeHash) history.replaceState(null, '', '#' + currentView);
  if (parkingData) rows(parkingData);
  if (csrf) {
    render();
    refresh();
    if (settings) loadPerformance();
    if (settings) api('/camera-switching').then(data => {
      $('#rotationEnabled').checked = data.enabled;
    }).catch(e => $('#rotationMessage').textContent = e.message);
  }
}
$('#camerasView').onclick = () => setView('cameras');
$('#databaseView').onclick = () => setView('database');
$('#settingsView').onclick = () => setView('settings');
$('#rotationEnabled').onchange = async () => {
  const el = $('#rotationEnabled'),
    desired = el.checked;
  el.disabled = true;
  $('#rotationMessage').textContent = 'Zmiana trybu pracy…';
  try {
    const data = await api('/camera-switching', {
      method: 'PUT',
      body: JSON.stringify({
        enabled: desired
      })
    });
    el.checked = data.enabled;
    $('#rotationMessage').textContent = data.enabled ? 'Włączono pracę naprzemienną USB.' :
      'Kamery pracują równocześnie.';
    await refresh();
    const c = cameras.find(c => c.id === editing);
    if (c) await loadCameraSettings(c);
  } catch (e) {
    el.checked = !desired;
    $('#rotationMessage').textContent = e.message;
  } finally {
    el.disabled = false;
  }
};

function renderCameraPreferences() {
  if (currentView !== 'settings') return;
  const selector = $('#settingsCamera'),
    previous = selector.value;
  selector.replaceChildren();
  for (const c of cameras) {
    const option = document.createElement('option');
    option.value = c.id;
    option.textContent = c.name;
    selector.append(option);
  }
  if (cameras.some(c => String(c.id) === previous)) selector.value = previous;
  const c = cameras.find(c => String(c.id) === selector.value);
  $('#cameraParameters').hidden = !c;
  $('#noSettingsCamera').hidden = Boolean(c);
  if (!c) {
    editing = null;
    return;
  }
  if (editing !== c.id) {
    editing = c.id;
    loadCameraSettings(c);
    fillMotionSettings(c);
  }
  renderMotionState(c);
  renderCameraMetrics(c);
}
$('#settingsCamera').onchange = () => {
  const c = cameras.find(c => String(c.id) === $('#settingsCamera').value);
  if (!c) return;
  editing = c.id;
  renderCameraMetrics(c);
  loadCameraSettings(c);
  fillMotionSettings(c);
  renderMotionState(c);
};
$('#plateFilter').oninput = () => {
  if (parkingData) rows(parkingData)
};
window.addEventListener('hashchange', () => setView(location.hash.slice(1), false));

function stats(data) {
  availableCpuThreads = data.cpu_threads || 1;
  for (const option of $('#performanceForm').elements.ocr_threads.options) option.disabled = Number(
    option.value) > availableCpuThreads;
  $('#databaseSource').textContent = data.test_mode ? 'Baza testowa' : 'Baza parkingu';
  $('#ocrState').textContent = 'Odczyt tablic: ' + data.ocr + (data.test_mode ?
    ' · TEST — osobna baza parkingu' : '');
  const gb = v => (v / 1024 ** 3).toFixed(2),
    mb = v => (v / 1024 ** 2).toFixed(1);
  const values = [
    ['Procesor', `${data.cpu.toFixed(1)}%`, data.cpu],
    ['Pamięć RAM', `${data.ram_percent.toFixed(1)}%`, data.ram_percent,
      `${gb(data.ram_used)} / ${gb(data.ram_total)} GB`
    ],
    ['Temperatura CPU', data.temperature === null ? 'Brak czujnika' :
      `${data.temperature.toFixed(1)}°C`
    ],
    ['Load average 1 / 5 / 15 min', data.load.map(v => v.toFixed(2)).join(' / ')],
    ['RAM procesu kamer', `${mb(data.process_ram)} MB`],
    ['CPU aplikacji · 100% = 1 rdzeń', `${(data.process_cpu || 0).toFixed(1)}%`],
    ['Wątki CPU', data.cpu_threads]
  ];
  $('#stats').replaceChildren();
  for (const [label, value, percent, detail] of values) {
    const el = document.createElement('div');
    el.className = 'metric';
    const small = document.createElement('small');
    small.textContent = label;
    const strong = document.createElement('strong');
    strong.textContent = value;
    el.append(small, strong);
    if (detail) {
      const text = document.createElement('small');
      text.textContent = detail;
      el.append(text)
    }
    if (percent !== undefined) {
      const p = document.createElement('progress');
      p.max = 100;
      p.value = percent;
      el.append(p)
    }
    $('#stats').append(el)
  }
}
async function refresh() {
  if (!csrf || pending) return;
  pending = true;
  try {
    const [cs, ps, ss] = await Promise.all([api('/cameras'), api('/parking'), api('/server')]);
    cameras = cs;
    render();
    renderCameraPreferences();
    updateEditorState();
    rows(ps);
    stats(ss);
    $('#message').textContent = ''
  } catch (e) {
    $('#message').textContent = e.message
  } finally {
    pending = false
  }
}
async function refreshUsbDevices() {
  const devices = await api('/devices');
  $('#usbSource').replaceChildren();
  for (const d of devices) {
    const option = document.createElement('option');
    option.value = d.source;
    option.disabled = d.available === false;
    option.textContent = `${d.name} (${d.device})${d.reason?' — '+d.reason:''}`;
    $('#usbSource').append(option)
  }
  const available = devices.filter(d => d.available !== false);
  if (available.length) $('#usbSource').value = available[0].source;
  $('#cameraAddSubmit').disabled = $('#kind').value === 'usb' && !available.length;
  $('#cameraError').textContent = $('#kind').value !== 'usb' || available.length ? '' : devices
    .length ?
    'Urządzenia są widoczne, ale niedostępne. Sprawdź uprawnienia.' :
    'Brak kamer USB dostępnych dla serwera. Na Windowsie uruchom mostek USB i panel z opcją UsbBridge.'
}
$('#addOpen').onclick = async () => {
  try {
    $('#addDialog').showModal();
    await refreshUsbDevices()
  } catch (e) {
    $('#cameraError').textContent = e.message
  }
};
$('#refreshUsb').onclick = () => refreshUsbDevices().catch(e => $('#cameraError').textContent = e
  .message);

$('#addClose').onclick = () => $('#addDialog').close();
$('#kind').onchange = () => {
  $('#usbLabel').hidden = $('#kind').value !== 'usb';
  $('#ipLabel').hidden = $('#kind').value !== 'ip';
  $('#testLabel').hidden = $('#kind').value !== 'test';
  $('#cameraError').textContent = '';
  $('#refreshUsb').hidden = $('#kind').value !== 'usb';
  $('#cameraAddSubmit').disabled = $('#kind').value === 'usb' && ![...$('#usbSource').options]
    .some(o => !o.disabled)
};
$('#cameraForm').onsubmit = async e => {
  e.preventDefault();
  try {
    const f = new FormData(e.target),
      kind = f.get('kind');
    await api('/cameras', {
      method: 'POST',
      body: JSON.stringify({
        name: f.get('name'),
        kind,
        source: kind === 'usb' ? $('#usbSource').value : kind === 'test' ? $(
          '#testSource').value : $('#ipSource').value
      })
    });
    $('#ipSource').value = '';
    $('#addDialog').close();
    await refresh()
  } catch (e) {
    $('#cameraError').textContent = e.message
  }
};
let editorModes = [];

function updateEditorState() {
  if (!$('#editor').open) return;
  const c = cameras.find(c => c.id === editing);
  if (!c) return;
  const el = $('#editorState');
  el.textContent = c.status;
  el.classList.toggle('ok', c.status === 'Działa');
  el.classList.toggle('paused', c.status.startsWith('Wstrzymana'));
  $('#editorPreviewNotice').hidden = c.metrics?.preview_enabled !== false;
  if (c.metrics?.preview_enabled === false) $('#editorImage').removeAttribute('src');
  else if (!$('#editorImage').hasAttribute('src')) $('#editorImage').src =
    `/api/cameras/${c.id}/stream`;
  renderCameraMetrics(c)
}

function openEditor(id) {
  editing = id;
  const c = cameras.find(c => c.id === id);
  zones = structuredClone(zoneGroups(c.zones));
  zoneSelection = 'new';
  zoneDraft = null;
  start = null;
  $('#editorName').textContent = c.name;
  if (c.metrics?.preview_enabled !== false) $('#editorImage').src = `/api/cameras/${id}/stream`;
  else $('#editorImage').removeAttribute('src');
  $('#zoneError').textContent = '';
  $('#editor').showModal();
  updateEditorState();
  renderZoneSelect();
}

$('#editorClose').onclick = () => {
  $('#editor').close();
  $('#editorImage').removeAttribute('src')
};
$('#editor').addEventListener('close', () => $('#editorImage').removeAttribute('src'));

function point(e) {
  const r = $('#editorCanvas').getBoundingClientRect();
  return {
    x: Math.max(0, Math.min(1, (e.clientX - r.left) / r.width)),
    y: Math.max(0, Math.min(1, (e.clientY - r.top) / r.height))
  }
}
$('#editorCanvas').onpointerdown = e => {
  if (zoneSelection === 'new' && (zones[$('#zoneKind').value] || []).length >= 32) {
    $('#zoneError').textContent = 'Limit: 32 obszary każdego koloru';
    return
  }
  start = point(e);
  zoneDraft = null;
  e.target.setPointerCapture(e.pointerId)
};
$('#editorCanvas').onpointermove = e => {
  if (!start) return;
  const p = point(e);
  zoneDraft = {
    x: Math.min(start.x, p.x),
    y: Math.min(start.y, p.y),
    w: Math.abs(p.x - start.x),
    h: Math.abs(p.y - start.y)
  };
  draw(e.target, zones)
};
$('#editorCanvas').onpointerup = e => {
  if (!start) return;
  if (zoneDraft && zoneDraft.w > .01 && zoneDraft.h > .01) {
    const kind = $('#zoneKind').value;
    zones[kind] ??= [];
    if (zoneSelection === 'new') zones[kind].push(zoneDraft);
    else zones[kind][Number(zoneSelection)] = zoneDraft;
    $('#zoneError').textContent = 'Zmiany oczekują na zapis'
  }
  start = null;
  zoneDraft = null;
  renderZoneSelect()
};
$('#editorCanvas').onpointercancel = () => {
  start = null;
  zoneDraft = null;
  draw($('#editorCanvas'), zones)
};
$('#zoneKind').onchange = () => {
  zoneSelection = 'new';
  zoneDraft = null;
  start = null;
  renderZoneSelect()
};
$('#zoneSelect').onchange = e => {
  zoneSelection = e.target.value;
  zoneDraft = null;
  start = null;
  renderZoneSelect()
};
$('#addZone').onclick = () => {
  zoneSelection = 'new';
  zoneDraft = null;
  start = null;
  renderZoneSelect()
};
$('#clearZone').onclick = () => {
  if (zoneSelection === 'new') return;
  zones[$('#zoneKind').value].splice(Number(zoneSelection), 1);
  zoneSelection = 'new';
  zoneDraft = null;
  renderZoneSelect();
  $('#zoneError').textContent = 'Usunięto obszar. Zapisz zmiany'
};
$('#saveZones').onclick = async () => {
  try {
    const result = await api(`/cameras/${editing}/zones`, {
      method: 'PUT',
      body: JSON.stringify(zones)
    });
    $('#zoneError').textContent = result.motion_disabled ?
      'Obszary zapisane. Tryb oszczędny wyłączony: usunięto niebieskie obszary.' :
      'Obszary zapisane';
    await refresh()
  } catch (e) {
    $('#zoneError').textContent = e.message
  }
};
window.addEventListener('resize', () => {
  render();
  if ($('#editor').open) draw($('#editorCanvas'), zones)
});
setInterval(refresh, 1000);
api('/session').then(s => {
  csrf = s.csrf;
  showDashboard()
}).catch(() => showLogin());

function renderCameraMetrics(c) {
  const m = c.metrics || {},
    value = (v, suffix = '') => v === null || v === undefined ? 'Zbieram pomiar' : `${v}${suffix}`;
  const resolution = m.resolution ? `${m.resolution.width} × ${m.resolution.height}` :
    'Brak klatki';
  const rows = [
    ['Rzeczywista rozdzielczość', resolution],
    ['Obszar analizy', m.analysis_roi ?
      `Droga · ${Math.round(m.analysis_roi.w*100)}% szerokości / ${Math.round(m.analysis_roi.h*100)}% wysokości` :
      'Cały obraz'
    ],
    ['Wejście detektora', `${m.detector_input_size||384} × ${m.detector_input_size||384}`],
    ['Rozdzielczość podglądu', m.preview_resolution ?
      `${m.preview_resolution.width} × ${m.preview_resolution.height}` : resolution
    ],
    ['Potwierdzenia z ≥3 klatek', m.confirmed_reads || 0, m.last_confirmation ?
      `Ostatnio: ${m.last_confirmation.plate}` : 'Oczekiwanie na zgodne odczyty'
    ],
    ['Tryb zmiany obrazu', c.motion?.enabled ? (m.motion?.active ? 'OCR aktywny' :
      'Czeka na zmianę') : 'Wyłączony'],
    ['Zmiana w niebieskim obszarze', `${m.motion?.changed_percent || 0}%`],
    ['FPS zgłoszony przez kamerę', value(m.device_fps)],
    ['FPS podglądu', value(m.preview_fps), `Limit ${value(m.preview_fps_limit)} FPS`],
    ['Widzowie podglądu', m.preview_viewers || 0],
    ['Kodowanie podglądu', value(m.preview_ms, ' ms')],
    ['Limit OCR / sekundę', value(m.ocr_fps_limit)],
    ['FPS przechwytywania', value(m.capture_fps), c.status === 'Działa' ? 'Na żywo' :
      `Pauza; ostatnio ${value(m.last_capture_fps)} FPS`
    ],
    ['Analizy OCR / sekundę', value(m.ocr_fps), `Ostatnio ${value(m.last_ocr_fps)} / s`],
    ['Średni czas analizy', value(m.ocr_ms, ' ms')],
    ['Format obrazu', m.format || 'Brak pomiaru'],
    ['Wiek ostatniej klatki', value(m.frame_age, ' s')],
    ['Pozostało w turze', m.rotation_enabled && c.kind === 'usb' ? value(m.turn_remaining, ' s') :
      'Praca ciągła'
    ]
  ];
  $('#cameraMetrics').replaceChildren();
  $('#extraCameraMetrics').replaceChildren();
  const basic = new Set(['Rzeczywista rozdzielczość', 'Potwierdzenia z ≥3 klatek',
    'FPS przechwytywania', 'Analizy OCR / sekundę'
  ]);
  for (const [label, text, detail] of rows) {
    const box = document.createElement('div');
    box.className = 'metric';
    const small = document.createElement('small');
    small.textContent = label;
    const strong = document.createElement('strong');
    strong.textContent = text;
    box.append(small, strong);
    if (detail) {
      const note = document.createElement('small');
      note.textContent = detail;
      box.append(note)
    }
    $('#extraCameraMetrics').append(box);
    if (basic.has(label)) $('#cameraMetrics').append(box.cloneNode(true));
  }
  if (c.kind === 'usb' && m.rotation_enabled) {
    const minimum = m.minimum_seconds || 3;
    $('#rotationSeconds').min = minimum;
    $('#settingsHint').textContent =
      `Minimum: ${minimum} s; zalecane co najmniej ${m.recommended_seconds||5} s. Minimum uwzględnia cztery próby analizy i zapas czasu, ale nie gwarantuje odczytu tablicy. Zmiana parametrów obowiązuje od kolejnej tury. Po zmianie rozdzielczości sprawdź zaznaczone obszary.`
  }
}

function fillVideoFps(desired) {
  const mode = editorModes[Number($('#videoMode').value)];
  $('#videoFps').replaceChildren();
  if (!mode) return;
  for (const rate of mode.fps) {
    const option = document.createElement('option');
    option.value = rate;
    option.textContent = rate;
    $('#videoFps').append(option)
  }
  if (mode.fps.some(r => Number(r) === Number(desired))) $('#videoFps').value = desired
}
async function loadCameraSettings(c) {
  $('#settingsMessage').textContent = '';
  editorModes = [];
  $('#videoMode').replaceChildren();
  $('#videoFps').replaceChildren();
  $('#rotationSeconds').value = c.settings?.rotation_seconds || 5;
  $('#rotationSeconds').disabled = c.kind !== 'usb' || !c.metrics?.rotation_enabled;
  $('#videoMode').disabled = true;
  $('#videoFps').disabled = true;
  $('#settingsSave').disabled = c.kind !== 'usb';
  if (c.kind === 'test') {
    $('#settingsHint').textContent =
      'Nagranie testowe odtwarzane w pętli. Odczyty zapisują zdarzenia w osobnej bazie testowej. Integracja korzysta z właściwej bazy parkingu. Parametry nagrania są stałe.';
    return
  }
  if (c.kind !== 'usb') {
    $('#settingsHint').textContent =
      'Parametry strumienia IP zmienisz w kamerze lub serwerze RTSP. Tutaj widzisz rzeczywiste parametry odbieranego obrazu.';
    return
  }
  try {
    const data = await api(`/cameras/${c.id}/capabilities`);
    if (editing !== c.id) return;
    if (data.settings_supported === false) {
      $('#settingsSave').disabled = !c.metrics?.rotation_enabled;
      $('#settingsHint').textContent =
        'Kamera USB Windows: rozdzielczość i FPS ustaw podczas uruchamiania mostka USB.';
      return
    }
    editorModes = data.modes;
    let chosen = 0;
    for (const [i, mode] of editorModes.entries()) {
      const option = document.createElement('option');
      option.value = i;
      option.textContent = `${mode.width} × ${mode.height} · ${mode.format}`;
      $('#videoMode').append(option);
      if (mode.width === c.settings.width && mode.height === c.settings.height && mode.format ===
        c.settings.format) chosen = i
    }
    $('#videoMode').value = chosen;
    fillVideoFps(c.settings.fps);
    $('#videoMode').disabled = !editorModes.length;
    $('#videoFps').disabled = !editorModes.length;
    if (!editorModes.length) $('#settingsMessage').textContent =
      'Nie odczytano trybów USB. Możesz zmienić czas tury; parametry obrazu są niedostępne.'
  } catch (e) {
    $('#settingsMessage').textContent = e.message
  }
}
$('#videoMode').onchange = () => fillVideoFps(15);
$('#cameraSettings').onsubmit = async e => {
  e.preventDefault();
  const id = editing;
  const body = {};
  if (!$('#rotationSeconds').disabled) body.rotation_seconds = Number($('#rotationSeconds')
    .value);
  const mode = editorModes[Number($('#videoMode').value)];
  if (mode) Object.assign(body, {
    width: mode.width,
    height: mode.height,
    format: mode.format,
    fps: Number($('#videoFps').value)
  });
  $('#settingsSave').disabled = true;
  try {
    await api(`/cameras/${id}/settings`, {
      method: 'PUT',
      body: JSON.stringify(body)
    });
    $('#settingsMessage').textContent =
      'Zapisano. Kamera ponownie otworzy strumień z nowymi parametrami.';
    await refresh()
  } catch (e) {
    $('#settingsMessage').textContent = e.message
  } finally {
    $('#settingsSave').disabled = false
  }
};


let availableCpuThreads = 8;
const performancePresets = {
  eco: {
    preview_enabled: true,
    preview_on_demand: true,
    preview_fps: 5,
    preview_width: 640,
    jpeg_quality: 55,
    ocr_enabled: true,
    ocr_fps: 2,
    ocr_threads: 1
  },
  balanced: {
    preview_enabled: true,
    preview_on_demand: true,
    preview_fps: 10,
    preview_width: 960,
    jpeg_quality: 70,
    ocr_enabled: true,
    ocr_fps: 4,
    ocr_threads: 2
  },
  smooth: {
    preview_enabled: true,
    preview_on_demand: true,
    preview_fps: 20,
    preview_width: 1280,
    jpeg_quality: 80,
    ocr_enabled: true,
    ocr_fps: 8,
    ocr_threads: 2
  }
};

function performanceHint() {
  const form = $('#performanceForm'),
    fps = Number(form.elements.ocr_fps.value);
  $('#performanceHint').textContent =
    `Potwierdzenie nadal wymaga 3 różnych klatek. Przy tym limicie odstęp między pierwszą i trzecią analizą wynosi co najmniej ${(2 / fps).toFixed(1)} s; wolniejszy sprzęt może go wydłużyć. Przy szybkich przejazdach zwiększ limit OCR.`;
}

function fillPerformance(data) {
  const form = $('#performanceForm');
  for (const [name, value] of Object.entries(data)) {
    const input = form.elements.namedItem(name);
    if (!input) continue;
    if (input.type === 'checkbox') input.checked = value;
    else {
      if (input.tagName === 'SELECT' && ![...input.options].some(o => Number(o.value) === Number(
          value))) {
        const option = new Option(String(value), String(value));
        input.add(option);
      }
      input.value = value;
    }
  }
  performanceHint();
}
let performanceLoad = 0;
async function loadPerformance() {
  const requestId = ++performanceLoad;
  $('#performanceFields').disabled = true;
  for (const button of $('#performanceProfiles').querySelectorAll('button')) button.disabled =
    true;
  $('#performanceMessage').textContent = 'Wczytywanie ustawień…';
  try {
    const data = await api('/performance');
    if (requestId !== performanceLoad) return;
    fillPerformance(data);
    $('#performanceMessage').textContent = '';
  } catch (e) {
    if (requestId === performanceLoad) $('#performanceMessage').textContent = e.message;
  } finally {
    if (requestId === performanceLoad) {
      $('#performanceFields').disabled = false;
      for (const button of $('#performanceProfiles').querySelectorAll('button')) button.disabled =
        false;
    }
  }
}
$('#performanceProfiles').onclick = e => {
  const button = e.target.closest('[data-profile]');
  if (!button) return;
  const preset = performancePresets[button.dataset.profile];
  fillPerformance({
    ...preset,
    ocr_threads: Math.min(preset.ocr_threads, availableCpuThreads)
  });
  $('#performanceMessage').textContent =
    'Wybrano profil. Kliknij „Zapisz wydajność”, aby zastosować.';
};
$('#performanceForm').oninput = performanceHint;
$('#performanceForm').onsubmit = async e => {
  e.preventDefault();
  const form = e.target,
    body = {};
  for (const name of Object.keys(performancePresets.eco)) {
    const input = form.elements.namedItem(name);
    body[name] = input.type === 'checkbox' ? input.checked : Number(input.value);
  }
  $('#performanceSave').disabled = true;
  try {
    fillPerformance(await api('/performance', {
      method: 'PUT',
      body: JSON.stringify(body)
    }));
    $('#performanceMessage').textContent =
      'Zapisano. Zmiana liczby wątków może chwilowo wstrzymać OCR.';
    await refresh();
  } catch (e) {
    $('#performanceMessage').textContent = e.message;
  } finally {
    $('#performanceSave').disabled = false;
  }
};


function fillMotionSettings(c) {
  const form = $('#motionSettings'),
    values = c.motion || {
      enabled: false,
      threshold_percent: 3,
      pixel_delta: 20,
      check_fps: 3,
      active_seconds: 5
    };
  for (const [name, value] of Object.entries(values)) {
    const input = form.elements.namedItem(name);
    if (!input) continue;
    if (input.type === 'checkbox') input.checked = value;
    else input.value = value;
  }
  form.elements.enabled.disabled = !zoneGroups(c.zones).motion.length && !values.enabled;
  $('#motionMessage').textContent = '';
}

function renderMotionState(c) {
  const state = c.metrics?.motion || {},
    hasRegions = zoneGroups(c.zones).motion.length;
  $('#motionState').textContent = !hasRegions ?
    'Najpierw zaznacz niebieski obszar w „Powiększ / obszary”. Może nakładać się na zielony lub czerwony.' :
    !c.motion?.enabled ? 'Tryb wyłączony — OCR pracuje zgodnie z limitami wydajności.' :
    `${motionActivity(c)} · zmiana ${state.changed_percent || 0}% · pozostało ${state.remaining_seconds || 0} s · okno co najmniej ${state.effective_seconds || c.motion.active_seconds} s`;
}
$('#motionSettings').onsubmit = async e => {
  e.preventDefault();
  const id = editing,
    form = e.target;
  if (!id) return;
  const body = {};
  for (const name of ['enabled', 'threshold_percent', 'pixel_delta', 'check_fps',
      'active_seconds'
    ]) {
    const input = form.elements.namedItem(name);
    body[name] = input.type === 'checkbox' ? input.checked : Number(input.value);
  }
  $('#motionSave').disabled = true;
  try {
    await api(`/cameras/${id}/motion`, {
      method: 'PUT',
      body: JSON.stringify(body)
    });
    $('#motionMessage').textContent =
      'Zapisano tryb zmiany obrazu. Nowy wzorzec powstanie z najbliższej klatki.';
    await refresh();
  } catch (e) {
    $('#motionMessage').textContent = e.message;
  } finally {
    $('#motionSave').disabled = false;
  }
};

function motionActivity(c) {
  if (c.metrics?.motion?.ocr_enabled === false) return 'OCR wstrzymany globalnie';
  return c.metrics?.motion?.active ? 'OCR aktywny' : 'Czeka na zmianę obrazu';
}
