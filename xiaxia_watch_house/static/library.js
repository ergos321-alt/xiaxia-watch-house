(() => {
  const csrf = document.querySelector('meta[name="csrf-token"]')?.content || '';
  const panel = document.getElementById('create-panel');
  const form = document.getElementById('create-film');
  const toast = document.getElementById('toast');
  const showToast = (message) => {
    toast.textContent = message;
    toast.classList.add('show');
    setTimeout(() => toast.classList.remove('show'), 2600);
  };
  document.getElementById('show-create')?.addEventListener('click', () => panel.classList.remove('hidden'));
  document.getElementById('hide-create')?.addEventListener('click', () => panel.classList.add('hidden'));
  form?.addEventListener('submit', async (event) => {
    event.preventDefault();
    const values = new FormData(form);
    const payload = {
      title: values.get('title'),
      source_type: values.get('source_type'),
      source_url: values.get('source_url') || null,
      duration_seconds: values.get('duration_seconds') || null,
    };
    try {
      const response = await fetch('/api/web/films', {
        method: 'POST',
        headers: {'Content-Type': 'application/json', 'X-CSRF-Token': csrf},
        body: JSON.stringify(payload),
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.error?.message || '创建失败');
      window.location.assign(`/watch/${data.film.film_id}`);
    } catch (error) {
      showToast(error.message);
    }
  });
})();
