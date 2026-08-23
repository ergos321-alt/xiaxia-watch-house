(() => {
  const film = JSON.parse(document.getElementById('film-data').textContent);
  const csrf = document.querySelector('meta[name="csrf-token"]')?.content || '';
  const player = document.getElementById('local-player');
  const fileInput = document.getElementById('local-video-file');
  const toggle = document.getElementById('sync-toggle');
  const currentTimeLabel = document.getElementById('current-time');
  const durationLabel = document.getElementById('duration-time');
  const subtitleLabel = document.getElementById('current-subtitle');
  const cueLabel = document.getElementById('cue-anchor');
  const annotationTime = document.getElementById('annotation-time');
  const annotationCue = document.getElementById('annotation-cue');
  const timeline = document.getElementById('timeline');
  const toast = document.getElementById('toast');
  let virtualSeconds = film.user_progress?.current_seconds || 0;
  let durationSeconds = film.duration_seconds || film.user_progress?.duration_seconds || null;
  let virtualPlaying = false;
  let lastTick = performance.now();
  let lastSavedAt = 0;
  let currentCue = null;
  let timelineCursor = null;
  const rendered = new Set();
  let objectUrl = null;

  const showToast = (message) => {
    toast.textContent = message;
    toast.classList.add('show');
    setTimeout(() => toast.classList.remove('show'), 2800);
  };
  const formatTime = (value) => {
    const total = Math.max(0, Math.floor(Number(value) || 0));
    const hours = Math.floor(total / 3600);
    const minutes = Math.floor((total % 3600) / 60);
    const seconds = total % 60;
    return hours > 0
      ? `${String(hours).padStart(2, '0')}:${String(minutes).padStart(2, '0')}:${String(seconds).padStart(2, '0')}`
      : `${String(minutes).padStart(2, '0')}:${String(seconds).padStart(2, '0')}`;
  };
  const activeSeconds = () => player && !player.classList.contains('hidden') ? player.currentTime : virtualSeconds;
  const activeState = () => player && !player.classList.contains('hidden')
    ? (player.ended ? 'ended' : (player.paused ? 'paused' : 'playing'))
    : (virtualPlaying ? 'playing' : 'paused');

  const api = async (url, options = {}) => {
    const headers = {...(options.headers || {})};
    if (options.method && options.method !== 'GET') headers['X-CSRF-Token'] = csrf;
    const response = await fetch(url, {...options, headers});
    const data = await response.json();
    if (!response.ok) throw new Error(data.error?.message || `请求失败 (${response.status})`);
    return data;
  };

  const saveProgress = async (force = false, stateOverride = null) => {
    const now = Date.now();
    if (!force && now - lastSavedAt < 12000) return;
    lastSavedAt = now;
    try {
      await api(`/api/web/films/${film.film_id}/progress`, {
        method: 'PUT',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({
          current_seconds: Number(activeSeconds().toFixed(3)),
          duration_seconds: durationSeconds ? Number(durationSeconds.toFixed(3)) : null,
          playback_state: stateOverride || activeState(),
        }),
        keepalive: force,
      });
    } catch (error) {
      if (!force) showToast(`进度暂未保存：${error.message}`);
    }
  };

  const updateClock = () => {
    const now = performance.now();
    if (virtualPlaying && (player.classList.contains('hidden'))) {
      virtualSeconds += (now - lastTick) / 1000;
      if (durationSeconds && virtualSeconds >= durationSeconds) {
        virtualSeconds = durationSeconds;
        virtualPlaying = false;
        toggle.textContent = '继续同步';
        saveProgress(true, 'ended');
      }
    }
    lastTick = now;
    const value = activeSeconds();
    currentTimeLabel.textContent = formatTime(value);
    annotationTime.textContent = formatTime(value);
    durationLabel.textContent = durationSeconds ? formatTime(durationSeconds) : '--:--';
    if (currentCue && value >= currentCue.start_seconds && value <= currentCue.end_seconds) {
      annotationCue.textContent = `cue ${currentCue.sequence_number}`;
    } else {
      annotationCue.textContent = '未绑定 cue';
    }
    saveProgress(false);
    requestAnimationFrame(updateClock);
  };

  let lastSubtitleFetch = -999;
  const refreshSubtitle = async () => {
    const value = activeSeconds();
    if (Math.abs(value - lastSubtitleFetch) < 1.5) return;
    lastSubtitleFetch = value;
    try {
      const data = await api(`/api/web/films/${film.film_id}/subtitles?around_seconds=${encodeURIComponent(value)}`);
      currentCue = data.cues.find((cue) => cue.start_seconds <= value && cue.end_seconds >= value) || null;
      subtitleLabel.textContent = currentCue ? currentCue.text : (film.subtitle_status === 'ready' ? '这一秒没有字幕。' : '请先上传 SRT / VTT 字幕。');
      cueLabel.textContent = currentCue ? `cue ${currentCue.sequence_number} · ${formatTime(currentCue.start_seconds)}` : '无 cue';
    } catch (error) {
      subtitleLabel.textContent = '字幕读取暂时失败。';
    }
  };
  setInterval(refreshSubtitle, 2000);

  const seekTo = (value) => {
    const target = Math.max(0, durationSeconds ? Math.min(value, durationSeconds) : value);
    if (!player.classList.contains('hidden')) player.currentTime = target;
    virtualSeconds = target;
    lastSubtitleFetch = -999;
    refreshSubtitle();
    saveProgress(true, 'seeking');
  };

  fileInput?.addEventListener('change', () => {
    const file = fileInput.files?.[0];
    if (!file) return;
    if (objectUrl) URL.revokeObjectURL(objectUrl);
    objectUrl = URL.createObjectURL(file);
    player.src = objectUrl;
    player.classList.remove('hidden');
    document.getElementById('local-source').classList.add('compact-source');
    player.addEventListener('loadedmetadata', () => {
      durationSeconds = Number.isFinite(player.duration) ? player.duration : durationSeconds;
      if (virtualSeconds < durationSeconds) player.currentTime = virtualSeconds;
      saveProgress(true, 'paused');
    }, {once: true});
  });
  player?.addEventListener('play', () => { virtualPlaying = false; toggle.textContent = '播放器控制中'; saveProgress(true, 'playing'); });
  player?.addEventListener('pause', () => saveProgress(true, player.ended ? 'ended' : 'paused'));
  player?.addEventListener('seeked', () => saveProgress(true, 'seeking'));
  player?.addEventListener('ended', () => saveProgress(true, 'ended'));

  toggle?.addEventListener('click', () => {
    if (!player.classList.contains('hidden')) {
      if (player.paused) player.play().catch(() => showToast('浏览器阻止了自动播放，请直接点视频播放键。'));
      else player.pause();
      return;
    }
    virtualPlaying = !virtualPlaying;
    toggle.textContent = virtualPlaying ? '暂停同步' : '继续同步';
    saveProgress(true, virtualPlaying ? 'playing' : 'paused');
  });
  document.getElementById('back-10')?.addEventListener('click', () => seekTo(activeSeconds() - 10));
  document.getElementById('forward-10')?.addEventListener('click', () => seekTo(activeSeconds() + 10));
  document.getElementById('calibrate')?.addEventListener('click', () => {
    const value = Number(document.getElementById('calibrate-seconds').value);
    if (Number.isFinite(value) && value >= 0) seekTo(value);
  });

  const buildEmbedUrl = (sourceType, rawUrl) => {
    if (!rawUrl) return null;
    try {
      const url = new URL(rawUrl);
      if (sourceType === 'youtube') {
        let id = url.hostname.includes('youtu.be') ? url.pathname.slice(1) : url.searchParams.get('v');
        if (!id && url.pathname.includes('/embed/')) id = url.pathname.split('/embed/')[1]?.split('/')[0];
        return id ? `https://www.youtube-nocookie.com/embed/${encodeURIComponent(id)}` : null;
      }
      if (sourceType === 'bilibili') {
        const match = url.pathname.match(/\/(BV[\w]+|av\d+)/i);
        if (!match) return null;
        const key = match[1].toLowerCase().startsWith('av') ? `aid=${match[1].slice(2)}` : `bvid=${match[1]}`;
        return `https://player.bilibili.com/player.html?${key}&high_quality=1`;
      }
      if (sourceType === 'iframe') return rawUrl;
    } catch (_) { return null; }
    return null;
  };
  const embedUrl = buildEmbedUrl(film.source_type, film.source_url);
  if (embedUrl) {
    const iframe = document.createElement('iframe');
    iframe.src = embedUrl;
    iframe.title = `${film.title} 在线播放器`;
    iframe.allow = 'accelerometer; autoplay; encrypted-media; picture-in-picture';
    iframe.allowFullscreen = true;
    iframe.referrerPolicy = 'strict-origin-when-cross-origin';
    iframe.sandbox = 'allow-scripts allow-same-origin allow-forms allow-presentation allow-popups';
    document.getElementById('embed-wrap').appendChild(iframe);
  } else if (film.source_type !== 'local') {
    document.getElementById('embed-wrap').classList.add('not-embedded');
    document.getElementById('embed-wrap').textContent = '此来源未进行 iframe 嵌入，请在原平台播放并使用静音同步。';
  }

  const entryId = (entry) => entry.annotation_id || entry.thought_id || entry.reply_id;
  const renderEntry = (entry) => {
    const id = entryId(entry);
    if (!id || rendered.has(id)) return;
    rendered.add(id);
    const card = document.createElement('article');
    card.className = `trace ${entry.content_type}`;
    card.dataset.entryId = id;
    const top = document.createElement('div');
    top.className = 'trace-top';
    const label = document.createElement('span');
    label.className = 'trace-actor';
    label.textContent = entry.content_type === 'user_annotation' ? '你' : (entry.content_type === 'xiaxia_thought' ? '夏夏 · 想法' : '夏夏 · 回复');
    const time = document.createElement('button');
    time.type = 'button';
    time.className = 'time-jump';
    time.textContent = formatTime(entry.start_seconds);
    time.addEventListener('click', () => seekTo(entry.start_seconds));
    top.append(label, time);
    const content = document.createElement('p');
    content.textContent = entry.content;
    card.append(top, content);
    if (entry.content_type === 'xiaxia_reply' && entry.annotation_id) {
      const parent = document.createElement('small');
      parent.textContent = `回复 annotation ${entry.annotation_id.slice(0, 8)}`;
      card.appendChild(parent);
    }
    timeline.appendChild(card);
  };
  const pollTimeline = async (initial = false) => {
    try {
      const query = timelineCursor ? `?since=${encodeURIComponent(timelineCursor)}` : '';
      const data = await api(`/api/web/films/${film.film_id}/timeline${query}`);
      data.entries.forEach(renderEntry);
      timelineCursor = data.cursor;
      document.getElementById('poll-status').textContent = initial ? '已载入' : '刚刚同步';
      if (!timeline.children.length) {
        const empty = document.createElement('p');
        empty.id = 'empty-timeline';
        empty.className = 'muted';
        empty.textContent = '还没有人留下观影痕迹。';
        timeline.appendChild(empty);
      } else {
        document.getElementById('empty-timeline')?.remove();
      }
    } catch (error) {
      document.getElementById('poll-status').textContent = '同步暂缓';
    }
  };
  pollTimeline(true);
  setInterval(() => pollTimeline(false), 12000);

  document.getElementById('annotation-form')?.addEventListener('submit', async (event) => {
    event.preventDefault();
    const textarea = document.getElementById('annotation-content');
    const content = textarea.value.trim();
    if (!content) return;
    try {
      const data = await api(`/api/web/films/${film.film_id}/annotations`, {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({
          start_seconds: Number(activeSeconds().toFixed(3)),
          cue_id: currentCue && activeSeconds() >= currentCue.start_seconds && activeSeconds() <= currentCue.end_seconds ? currentCue.cue_id : null,
          content,
        }),
      });
      document.getElementById('empty-timeline')?.remove();
      renderEntry(data.annotation);
      textarea.value = '';
      showToast('已经留在这一秒。');
    } catch (error) { showToast(error.message); }
  });

  document.getElementById('subtitle-form')?.addEventListener('submit', async (event) => {
    event.preventDefault();
    const form = event.currentTarget;
    try {
      const response = await fetch(`/api/web/films/${film.film_id}/subtitles`, {
        method: 'POST', headers: {'X-CSRF-Token': csrf}, body: new FormData(form),
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.error?.message || '字幕上传失败');
      film.subtitle_status = 'ready';
      lastSubtitleFetch = -999;
      refreshSubtitle();
      showToast(`字幕已写入，共 ${data.cue_count} 个稳定 cue。`);
    } catch (error) { showToast(error.message); }
  });

  document.getElementById('delete-film')?.addEventListener('click', async () => {
    const confirmed = window.prompt(`删除会级联清理字幕、双方进度和全部观影痕迹。请输入影片标题确认：\n${film.title}`);
    if (confirmed !== film.title) return;
    try {
      await api(`/api/web/films/${film.film_id}`, {
        method: 'DELETE', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({confirm_title: confirmed}),
      });
      window.location.assign('/watch');
    } catch (error) { showToast(error.message); }
  });

  window.addEventListener('pagehide', () => saveProgress(true));
  window.addEventListener('beforeunload', () => saveProgress(true));
  document.addEventListener('visibilitychange', () => { if (document.hidden) saveProgress(true); });
  updateClock();
  refreshSubtitle();
})();
