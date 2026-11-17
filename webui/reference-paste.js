function onReferencePaste(upload) {
  document.addEventListener('paste', (event) => {
    if (event.target instanceof Element && event.target.closest('input:not([type=file]), textarea, [contenteditable], dialog')) return;
    const image = Array.from(event.clipboardData?.files || []).find(file => /^image\/(png|jpeg|webp|tiff)$/.test(file.type));
    if (!image) return;
    const extension = image.type.split('/')[1];
    event.preventDefault();
    upload(new File([image], `reference-screenshot.${extension}`, { type: image.type }));
  });
}
