onReferencePaste(file => uploadImage('reference', file).catch(error => setStatus(error.message, true)));

{
  const dialog = document.querySelector('#video-picker');
  const file = document.querySelector('#video-file');
  const slider = document.querySelector('#video-position');
  const seconds = document.querySelector('#video-seconds');
  const range = document.querySelector('#video-range');
  const preview = document.querySelector('#video-frame-preview');
  const info = document.querySelector('#video-status');
  const previewButton = document.querySelector('#read-video-frame');
  const useButton = document.querySelector('#use-video-frame');
  let video;
  let frame;
  let reading = false;

  function controls() {
    slider.disabled = seconds.disabled = previewButton.disabled = !video || reading;
    range.disabled = !video || reading;
    useButton.disabled = !frame || reading;
  }

  function invalidate(message = '选择时间后，点击「预览这一帧」。') {
    frame = undefined;
    if (!reading) info.textContent = message;
    controls();
  }

  document.querySelector('#choose-video').onclick = () => file.click();
  file.onchange = async () => {
    const source = file.files[0];
    file.value = '';
    if (!source || reading) return;
    video = undefined;
    frame = undefined;
    range.value = '';
    preview.hidden = true;
    dialog.showModal();
    info.textContent = '正在读取原片，请稍候…';
    reading = true;
    controls();
    try {
      video = await api('/api/video', { method: 'POST', body: source, headers: {
        'Content-Type': 'application/octet-stream', 'X-Filename': encodeURIComponent(source.name),
      } });
      slider.value = seconds.value = 0;
      slider.max = seconds.max = Math.max(0, (Math.ceil(video.duration * 1000) - 1) / 1000);
      info.textContent = video.range
        ? `识别到原片范围 ${video.range === 'full' ? 'Full' : 'Video'}，请选择时间。`
        : '原片未标注数据范围。请选择 Full 或 Video 后再预览。';
    } catch (error) {
      info.textContent = error.message;
    } finally {
      reading = false;
      controls();
    }
  };
  slider.oninput = () => { seconds.value = slider.value; invalidate(); };
  seconds.oninput = () => { slider.value = seconds.value; invalidate(); };
  range.onchange = () => invalidate();
  previewButton.onclick = async () => {
    if (!seconds.reportValidity() || seconds.value === '') return;
    reading = true;
    invalidate();
    info.textContent = '正在取帧…';
    try {
      const result = await api('/api/video/frame', { method: 'POST', body: JSON.stringify({
        videoId: video.id, seconds: Number(seconds.value), range: range.value,
      }) });
      preview.src = result.url;
      await preview.decode();
      preview.hidden = false;
      frame = result;
      info.textContent = '静帧已就绪。使用后，LUT 输入范围为 Full。';
    } catch (error) {
      info.textContent = error.message;
    } finally {
      reading = false;
      controls();
    }
  };
  useButton.onclick = async () => {
    if (!frame) return;
    try {
      state.content = frame;
      state.slog3.inputRange = 'full';
      document.querySelector('#slog3-input-range').value = 'full';
      resetCachedResult();
      selectWorkingSpace('slog3');
      await displayImage('content', frame);
      updateMatchButton();
      setStatus('已从原片取帧。请选择与相机录制一致的 S-Log3 输入色域。');
      dialog.close();
    } catch (error) {
      info.textContent = error.message;
    }
  };
}
