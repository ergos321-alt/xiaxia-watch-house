(function exposeTimelineMarker(root, factory) {
  const markerModel = factory();
  if (typeof module !== 'undefined' && module.exports) module.exports = markerModel;
  if (root) root.XiaxiaTimelineMarkerModel = markerModel;
})(typeof globalThis !== 'undefined' ? globalThis : this, function buildTimelineMarker() {
  return function timelineMarkerModel(entry, durationSeconds, entryKey) {
    const timestampSeconds = Math.max(0, Number(entry?.start_seconds) || 0);
    const duration = Number(durationSeconds) || 0;
    return {
      entryId: entryKey ? entryKey(entry) : null,
      timestampSeconds,
      positionPercent: duration > 0 ? Math.min(100, timestampSeconds / duration * 100) : null,
    };
  };
});
