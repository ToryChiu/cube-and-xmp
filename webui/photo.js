{
  const get = id => document.getElementById(id);
  const status = get('photo-status');
  const editors = get('photo-editors');
  const form = get('photo-controls');
  const before = get('photo-show-original');
  const band = get('photo-band');
  const result = get('photo-result');
  const basic = [
    ['strength', '追色强度', 0, 100, 1, 90], ['exposure', '曝光（EV）', -4, 4, .1, 0],
    ['contrast', '对比度', -100, 100, 1, 0], ['highlights', '高光', -100, 100, 1, 0],
    ['shadows', '阴影', -100, 100, 1, 0], ['sharpen', '锐化', 0, 100, 1, 0],
  ];
  const hsl = ['色相', '饱和度', '明度'];
  let edits = [];
  let reference;
  let original;
  let previewURL;
  let timer;
  let previewing = false;
  let revision = 0;
  let renderedRevision = -1;

  function slider(parent, [key, label, min, max, step, value]) {
    const row = document.createElement('div');
    row.className = 'photo-slider';
    const name = document.createElement('label');
    name.htmlFor = `photo-${key}`;
    name.textContent = label;
    const output = document.createElement('output');
    name.append(output);
    const input = document.createElement('input');
    input.id = name.htmlFor;
    input.type = 'range';
    Object.assign(input, { min, max, step, defaultValue: value, value });
    row.append(name, input);
    parent.append(row);
    return { input, output };
  }

  const controls = Object.fromEntries(basic.map(spec => [spec[0], slider(get('photo-basic'), spec)]));
  const hslSliders = hsl.map((label, i) => slider(get('photo-hsl'), [`hsl-${i}`, label, -100, 100, 1, 0]));
  ['红', '橙', '黄', '绿', '青', '蓝', '紫', '洋红'].forEach((name, i) => band.add(new Option(name, i)));

  function readControls() {
    return {
      ...Object.fromEntries(Object.entries(controls).map(([key, { input }]) => [key, Number(input.value)])),
      hsl: edits,
    };
  }

  function refreshControls() {
    editors.disabled = !(original && reference);
    before.disabled = !original;
    Object.values(controls).forEach(({ input, output }) => { output.value = input.value; });
    hslSliders.forEach(({ input, output }, i) => { input.value = output.value = edits[band.value][i]; });
  }

  function queuePreview() {
    revision++;
    clearTimeout(timer);
    timer = setTimeout(renderPreview, 140);
  }

  async function request(path, options) {
    const response = await fetch(path, options);
    if (!response.ok) {
      const data = await response.json().catch(() => ({}));
      throw new Error(data.error || '本地处理失败。');
    }
    return response;
  }

  function renderRequest(extra = {}) {
    return request('/api/photo/render', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ photoId: original.id, referenceId: reference?.id, controls: readControls(), ...extra }),
    });
  }

  async function renderPreview() {
    if (!original || previewing || renderedRevision === revision) return;
    const snapshot = revision;
    const showOriginal = before.checked || !reference;
    previewing = true;
    status.textContent = '正在更新预览…';
    try {
      const response = await renderRequest({ original: showOriginal });
      const blob = await response.blob();
      if (snapshot !== revision) return;
      if (previewURL) URL.revokeObjectURL(previewURL);
      previewURL = URL.createObjectURL(blob);
      result.src = previewURL;
      result.hidden = false;
      get('photo-result-empty').hidden = true;
      status.textContent = !reference ? '请选择参考图。' : showOriginal ? '正在查看原片。' : '追色预览已更新。';
    } catch (error) {
      if (snapshot === revision) status.textContent = error.message;
    } finally {
      previewing = false;
      renderedRevision = snapshot;
      if (snapshot !== revision) renderPreview();
    }
  }

  const uploadGeneration = { reference: 0, original: 0 };
  async function upload(kind, file) {
    if (!file) return;
    const generation = ++uploadGeneration[kind];
    status.textContent = kind === 'reference' ? '正在打开参考图…' : '正在读取原片…';
    const body = new FormData();
    body.append('file', file, file.name);
    try {
      const response = await request(kind === 'reference' ? '/api/upload/reference' : '/api/photo', { method: 'POST', body });
      const data = await response.json();
      if (generation !== uploadGeneration[kind]) return;
      if (kind === 'reference') {
        reference = data;
        const image = get('photo-reference');
        image.src = data.url;
        image.hidden = false;
        get('photo-reference-empty').hidden = true;
      } else {
        original = data;
      }
      get(`photo-${kind}-name`).textContent = file.name;
      before.checked = false;
      refreshControls();
      if (original) queuePreview();
      else status.textContent = '请选择原片。';
    } catch (error) {
      if (generation === uploadGeneration[kind]) status.textContent = error.message;
    }
  }

  onReferencePaste(file => upload('reference', file));
  for (const kind of ['reference', 'original']) {
    const fileInput = get(`photo-${kind}-file`);
    get(`photo-${kind}-choose`).onclick = () => fileInput.click();
    fileInput.onchange = () => { upload(kind, fileInput.files[0]); fileInput.value = ''; };
    const drop = get(`photo-${kind}-drop`);
    drop.ondragover = event => event.preventDefault();
    drop.ondrop = event => { event.preventDefault(); upload(kind, event.dataTransfer.files[0]); };
  }
  for (const { input } of Object.values(controls)) {
    input.oninput = () => { refreshControls(); queuePreview(); };
  }
  hslSliders.forEach(({ input }, i) => {
    input.oninput = () => { edits[band.value][i] = Number(input.value); refreshControls(); queuePreview(); };
  });
  band.onchange = refreshControls;
  before.onchange = queuePreview;

  function reset() {
    edits = Array.from({ length: band.options.length }, () => [0, 0, 0]);
    refreshControls();
    queuePreview();
  }
  form.onreset = () => setTimeout(reset, 0);
  form.onsubmit = async event => {
    event.preventDefault();
    if (!original || !reference) return;
    const button = form.querySelector('button[type=submit]');
    button.disabled = true;
    status.textContent = '正在导出全分辨率 JPG…';
    try {
      const response = await renderRequest({ export: true });
      const { url } = await response.json();
      const download = document.createElement('a');
      download.href = url;
      download.click();
      status.textContent = '全分辨率 JPG 已导出。';
    } catch (error) {
      status.textContent = error.message;
    } finally {
      button.disabled = false;
    }
  };
  reset();
}
